"""The parent/server backup: the CACHE drive holds every child's persistence data, in git, filed by combination id.

Each child install keeps its data volumes under git (`data_vault`). Here they are pushed into one bare repository per volume role, inside a folder named for the COMBINATION of drives the data belongs
to (the same machine-independent id the twin uses for a pair: a hash of the drives' child UUIDs, so it names no serial and no machine; a lone drive is a combination of one). Inside, each drive has its
own branch (`child/<its child uuid>`), so two paired drives never overwrite one another and any number of children and pairs share the same parent. A push sends only objects the parent does not have,
so an unchanged volume writes nothing. Restoring a volume is a clone of that branch.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from data_vault import DATA_ROLES, VAULT
from write_once import write_if_changed

_CHILD = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


class ParentVaultError(RuntimeError):
    pass


def _child(value: str) -> str:
    value = str(value).lower()
    if not _CHILD.match(value):
        raise ParentVaultError(f"{value!r} is not a child UUID")
    return value


def combination_for(child_ids) -> str:
    """The id of a combination of drives: the twin's pair id for two drives, the same style of hash for one or more. Order does not matter."""
    ids = sorted({_child(c) for c in child_ids})
    if not ids:
        raise ParentVaultError("a combination needs at least one drive")
    return hashlib.sha256(("baseline-twin-pair-v1:" + "+".join(ids)).encode()).hexdigest()[:32]


def repo_path(root, combination: str, role: str) -> Path:
    if role not in DATA_ROLES or not re.fullmatch(r"[a-f0-9]{32}", combination):
        raise ParentVaultError("unknown role or combination id")
    return Path(root) / combination / f"{role}.git"


def _git(runner, *args, timeout=1800):
    done = runner.run(["git", *args], timeout=timeout)
    if done.returncode:
        raise ParentVaultError(f"git {args[0]} failed: {(done.stderr or done.stdout or '').strip()[-300:]}")
    return (done.stdout or "").strip()


def register(root, child_ids) -> str:
    """Record which drives a combination is made of (their child UUIDs only) and return its id."""
    combination = combination_for(child_ids)
    write_if_changed(Path(root) / combination / "combination.json", json.dumps({"drives": sorted({_child(c) for c in child_ids})}, indent=1) + "\n")
    return combination


def push(runner, volume, root, *, child_ids, this_child: str, role: str) -> dict:
    """Send the volume's history to the parent under the combination, on this drive's own branch. Only new objects are written."""
    this_child = _child(this_child)
    if this_child not in {_child(c) for c in child_ids}:
        raise ParentVaultError("the drive is not part of the combination it is being filed under")
    combination = register(root, child_ids)
    bare = repo_path(root, combination, role)
    if not (bare / "HEAD").exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        _git(runner, "init", "-q", "--bare", str(bare))
    source = ["--git-dir", str(Path(volume) / VAULT)]
    _git(runner, *source, "push", "-q", str(bare), f"HEAD:refs/heads/child/{this_child}", "--force", "--tags")
    head = _git(runner, "--git-dir", str(bare), "rev-parse", f"refs/heads/child/{this_child}")
    return {"role": role, "combination": combination, "branch": f"child/{this_child}", "commit": head}


def restore(runner, root, *, combination: str, child: str, role: str, destination) -> str:
    """Clone a drive's latest backed-up volume into `destination` (a folder that does not exist yet)."""
    bare = repo_path(root, combination, role)
    if not (bare / "HEAD").exists():
        raise ParentVaultError("there is no backup of that volume for that combination")
    if Path(destination).exists():
        raise ParentVaultError("the restore destination already exists; nothing is overwritten")
    _git(runner, "clone", "-q", "--branch", f"child/{_child(child)}", str(bare), str(destination))
    return str(destination)


def listing(root) -> list:
    """Every combination on the parent with its drives and which roles are backed up."""
    out = []
    for folder in sorted(Path(root).glob("*/combination.json")):
        try:
            drives = json.loads(folder.read_text())["drives"]
        except (OSError, ValueError, KeyError):
            continue
        out.append({"combination": folder.parent.name, "drives": drives, "roles": sorted(p.stem for p in folder.parent.glob("*.git"))})
    return out
