"""The parent/server backup: the CACHE drive holds every child's persistence data, in git, filed by combination id.

Each child install keeps its data volumes under git (`data_history`). Here they are pushed into one bare repository per volume role, inside a folder named for the COMBINATION of drives the data belongs
to (the same machine-independent id the twin uses for a pair: a hash of the drives' child UUIDs, so it names no serial and no machine; a lone drive is a combination of one). Inside, each drive has its
own branch (`child/<its child uuid>`), so two paired drives never overwrite one another and any number of children and pairs share the same parent. A push sends only objects the parent does not have,
so an unchanged volume writes nothing. Restoring a volume is a clone of that branch.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from data_history import DATA_ROLES, HISTORY
from write_once import write_if_changed

_CHILD = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


class MirrorHistoryError(RuntimeError):
    pass


def _child(value: str) -> str:
    value = str(value).lower()
    if not _CHILD.match(value):
        raise MirrorHistoryError(f"{value!r} is not a child UUID")
    return value


def combination_for(child_ids) -> str:
    """The id of a combination of drives: the twin's pair id for two drives, the same style of hash for one or more. Order does not matter."""
    ids = sorted({_child(c) for c in child_ids})
    if not ids:
        raise MirrorHistoryError("a combination needs at least one drive")
    return hashlib.sha256(("baseline-twin-pair-v1:" + "+".join(ids)).encode()).hexdigest()[:32]


def _folder(root, combination: str) -> Path:
    return Path(root) / "mirror" / combination


def repo_path(root, combination: str, role: str) -> Path:
    if role not in DATA_ROLES or not re.fullmatch(r"[a-f0-9]{32}", combination):
        raise MirrorHistoryError("unknown role or combination id")
    return _folder(root, combination) / "history" / f"{role}.git"


def _git(runner, *args, timeout=1800):
    done = runner.run(["git", *args], timeout=timeout)
    if done.returncode:
        raise MirrorHistoryError(f"git {args[0]} failed: {(done.stderr or done.stdout or '').strip()[-300:]}")
    return (done.stdout or "").strip()


def register(root, child_ids) -> str:
    """Record which drives a combination is made of (their child UUIDs only) and return its id."""
    combination = combination_for(child_ids)
    write_if_changed(_folder(root, combination) / "combination.json", json.dumps({"drives": sorted({_child(c) for c in child_ids})}, indent=1) + "\n")
    return combination


def push(runner, volume, root, *, child_ids, this_child: str, role: str) -> dict:
    """Send the volume's history to the parent under the combination, on this drive's own branch. Only new objects are written."""
    this_child = _child(this_child)
    if this_child not in {_child(c) for c in child_ids}:
        raise MirrorHistoryError("the drive is not part of the combination it is being filed under")
    combination = register(root, child_ids)
    bare = repo_path(root, combination, role)
    if not (bare / "HEAD").exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        _git(runner, "init", "-q", "--bare", str(bare))
    source = ["--git-dir", str(Path(volume) / HISTORY)]
    _git(runner, *source, "push", "-q", str(bare), f"HEAD:refs/heads/child/{this_child}", "--force", "--tags")
    head = _git(runner, "--git-dir", str(bare), "rev-parse", f"refs/heads/child/{this_child}")
    return {"role": role, "combination": combination, "branch": f"child/{this_child}", "commit": head}


def restore(runner, root, *, combination: str, child: str, role: str, destination) -> str:
    """Clone a drive's latest backed-up volume into `destination` (a folder that does not exist yet)."""
    bare = repo_path(root, combination, role)
    if not (bare / "HEAD").exists():
        raise MirrorHistoryError("there is no backup of that volume for that combination")
    if Path(destination).exists():
        raise MirrorHistoryError("the restore destination already exists; nothing is overwritten")
    _git(runner, "clone", "-q", "--branch", f"child/{_child(child)}", str(bare), str(destination))
    return str(destination)


def listing(root) -> list:
    """Every combination on the parent with its drives and which roles are backed up."""
    out = []
    for folder in sorted((Path(root) / "mirror").glob("*/combination.json")):
        try:
            drives = json.loads(folder.read_text())["drives"]
        except (OSError, ValueError, KeyError):
            continue
        out.append({"combination": folder.parent.name, "drives": drives, "roles": sorted(p.stem for p in (folder.parent / "history").glob("*.git"))})
    return out


def migrate_legacy(root) -> list:
    """Move histories filed under the earlier folder name (`<root>/vault/<combination>/...`) into `<root>/mirror/<combination>/history/`, once. Returns what was moved; nothing is copied."""
    old = Path(root) / "vault"
    moved = []
    if not old.is_dir():
        return moved
    for combo in sorted(p for p in old.iterdir() if p.is_dir() and re.fullmatch(r"[a-f0-9]{32}", p.name)):
        target = _folder(root, combo.name)
        (target / "history").mkdir(parents=True, exist_ok=True)
        for item in combo.iterdir():
            dest = target / "combination.json" if item.name == "combination.json" else target / "history" / item.name
            if not dest.exists():
                item.rename(dest)
                moved.append(f"{combo.name}/{item.name}")
        try:
            combo.rmdir()
        except OSError:
            pass
    try:
        old.rmdir()
    except OSError:
        pass
    return moved
