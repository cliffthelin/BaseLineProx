"""How much has been written to a drive, so a run can say what it cost it and a rebuild can be held to a budget.

The kernel counts the sectors written to each block device since it was attached (/sys/block/<name>/stat, field 7, always in 512-byte units). A run reads it before and after; the difference is what that
run (and anything else writing to the drive meanwhile) wrote. Reads cost a drive nothing, so only writes are counted.
"""
from __future__ import annotations

from pathlib import Path

SECTOR = 512
GIB = 1024 ** 3


def written_bytes(device_name: str, *, sys_block="/sys/block") -> int | None:
    """Bytes written to the device since the kernel attached it, or None when it cannot be read (name like `sdl`, not a path)."""
    try:
        fields = (Path(sys_block) / device_name / "stat").read_text().split()
        return int(fields[6]) * SECTOR
    except (OSError, ValueError, IndexError):
        return None


def spent(before: int | None, after: int | None) -> int | None:
    return None if before is None or after is None else max(after - before, 0)


def describe(nbytes: int | None) -> str:
    return "unknown" if nbytes is None else f"{nbytes / GIB:.1f} GiB"
