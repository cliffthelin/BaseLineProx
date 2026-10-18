"""Every data volume is under git from the build, and a rebuild backs it up first.

A rebuild updates the code layer and may add configuration, user data or app data; it never formats a drive and never discards data. So each data volume (the user's and the applications'
files) keeps its own version history in a git directory kept beside the files (`.baseline-vault`, never inside the user's folders, never file-synced to the twin: each drive keeps its own
history). `snapshot` records the current state as a commit (and a tag when asked); `bundle` writes a self-contained copy of the whole history, which lands on a volume the twin carries.

What is left out of the history is what must never be versioned as files: live databases and journals, running VMs' disk images, sockets, pid and lock files, and any single file over
`MAX_FILE_BYTES` (they are listed in the snapshot's report, never silently dropped). Everything else is committed as it is.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import twin_sync
from write_once import write_if_changed

VAULT = ".baseline-vault"
MAX_FILE_BYTES = 64 * 1024 * 1024
DATA_ROLES = ("USER_ADMIN", "USER_PERSONAL", "APPDATA_ADMIN", "APPDATA_PERSONAL")
_NEVER_TRACKED = twin_sync._NEVER + (twin_sync.STATE_DIR + "/", VAULT + "/", "lost+found/")


class VaultError(RuntimeError):
    pass


def _git(runner, volume, *args, timeout=600):
    argv = ["git", "--git-dir", str(Path(volume) / VAULT), "--work-tree", str(volume), "-c", "user.name=Baseline", "-c", "user.email=baseline@localhost",
            "-c", "core.quotepath=off", "-c", "gc.auto=0", *args]
    done = runner.run(argv, timeout=timeout)
    if done.returncode:
        raise VaultError(f"git {args[0]} failed on {volume}: {(done.stderr or done.stdout or '').strip()[-300:]}")
    return (done.stdout or "").strip()


def tracked_roots(role: str):
    """The folders of a volume that are versioned: all of it, or for USER_ADMIN only the user's own folders (the rest is the host's identity and live state)."""
    include = (twin_sync._RULES.get(role) or {}).get("include")
    return tuple(include) if include else (".",)


def oversize(volume, roots) -> list:
    big = []
    for root in roots:
        base = Path(volume) / root
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (VAULT, twin_sync.STATE_DIR, "lost+found")]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    if path.is_file() and not path.is_symlink() and path.stat().st_size > MAX_FILE_BYTES:
                        big.append(str(path.relative_to(volume)))
                except OSError:
                    continue
    return sorted(big)


def ensure(runner, volume, role: str) -> dict:
    """Put the volume under git if it is not already; the same call at build time and at every rebuild."""
    volume = Path(volume)
    if not volume.is_dir():
        raise VaultError(f"{volume} is not a folder")
    created = not (volume / VAULT / "HEAD").exists()
    if created:
        _git(runner, volume, "init", "-q")
    return {"volume": str(volume), "role": role, "created": created}


def snapshot(runner, volume, role: str, *, message: str, tag: str | None = None) -> dict:
    """Commit the volume's current state. Returns the commit, whether anything changed, and the files left out for being too large."""
    info = ensure(runner, volume, role)
    roots = tuple(r for r in tracked_roots(role) if r == "." or (Path(volume) / r).is_dir())      # a folder that does not exist yet has nothing to record
    big = oversize(volume, roots)
    write_if_changed(Path(volume) / VAULT / "info" / "exclude", "\n".join([*_NEVER_TRACKED, *("/" + b for b in big)]) + "\n")
    if roots:
        _git(runner, volume, "add", "-A", "--", *roots)
    dirty = bool(roots) and bool(_git(runner, volume, "status", "--porcelain", "--", *roots))
    has_head = runner.run(["git", "--git-dir", str(Path(volume) / VAULT), "rev-parse", "-q", "--verify", "HEAD"], timeout=30).returncode == 0
    if dirty or not has_head:
        _git(runner, volume, "commit", "-q", "--allow-empty", "-m", message)
    commit = _git(runner, volume, "rev-parse", "HEAD")
    if tag:
        _git(runner, volume, "tag", "-f", tag, commit)
    return dict(info, commit=commit, changed=dirty, left_out_too_large=big)


def bundle(runner, volume, destination, *, name: str, commit: str | None = None) -> str:
    """A self-contained copy of the volume's whole history, as one file. When `commit` is given the file is named for it: a history that has not moved since its last bundle is not written again."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (f"{name}-{commit[:12]}.bundle" if commit else f"{name}.bundle")
    if commit and target.exists():
        return str(target)
    _git(runner, volume, "bundle", "create", str(target), "--all")
    return str(target)


def backup_all(runner, volumes: dict, destination, *, message: str, tag: str) -> list:
    """Snapshot and bundle every data volume found ({role: mount path}); a volume that is missing is reported, never skipped silently."""
    report = []
    for role in DATA_ROLES:
        path = volumes.get(role)
        if path is None or not Path(path).is_dir():
            report.append({"role": role, "skipped": "not mounted"})
            continue
        snap = snapshot(runner, path, role, message=message, tag=tag)
        snap["bundle"] = bundle(runner, path, destination, name=role, commit=snap["commit"])
        report.append(snap)
    return report
