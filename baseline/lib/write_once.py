"""Never rewrite what did not change: a file is written only when its content differs from what is already there.

Every periodic or repeated step (reports, records, settings, markers) writes through here, so an unchanged state costs a read and not a write to the drive.
"""
from __future__ import annotations

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
