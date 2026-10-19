"""Never rewrite what did not change: a file is written only when its content differs from what is already there.

Every periodic or repeated step (reports, records, settings, markers) writes through here, so an unchanged state costs a read and not a write to the drive.
"""
from __future__ import annotations

import filecmp
import os
import shutil
from pathlib import Path


def write_if_changed(path, text: str, *, mode: int | None = None) -> bool:
    """Write `text` to `path` unless it already holds exactly that; returns whether anything was written."""
    target = Path(path)
    try:
        if target.is_file() and not target.is_symlink() and target.read_text() == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    if mode is not None:
        target.chmod(mode)
    return True


def copy_changed(source, destination, ignore=None, *, symlinks=False) -> dict:
    """Make `destination` hold every file of `source`, writing only what differs. A file with the same content is left untouched (not rewritten, same inode and time), a changed file is replaced, a new
    one is added; nothing is deleted (a merge, like the copy it replaces). With `symlinks` a link is kept as a link (and left alone when it already points the same way). Returns {"copied", "unchanged"}.
    This is the only way a tree is copied onto something that already exists: whole-tree copies (`shutil.copytree` into an existing folder) rewrite identical files and are not allowed."""
    source, destination = Path(source), Path(destination)
    counts = {"copied": 0, "unchanged": 0}

    def walk(src, dst):
        dst.mkdir(parents=True, exist_ok=True)
        names = os.listdir(src)
        skip = set(ignore(str(src), names)) if ignore else set()
        for name in names:
            if name in skip:
                continue
            s_path, d_path = src / name, dst / name
            if symlinks and s_path.is_symlink():
                target = os.readlink(s_path)
                if d_path.is_symlink() and os.readlink(d_path) == target:
                    counts["unchanged"] += 1
                else:
                    if d_path.is_symlink() or d_path.is_file():
                        d_path.unlink()
                    os.symlink(target, d_path)
                    counts["copied"] += 1
            elif s_path.is_dir() and not s_path.is_symlink():
                walk(s_path, d_path)
            elif d_path.is_file() and not d_path.is_symlink() and filecmp.cmp(s_path, d_path, shallow=False):
                counts["unchanged"] += 1
            else:
                shutil.copy2(s_path, d_path)
                counts["copied"] += 1
    walk(source, destination)
    return counts
