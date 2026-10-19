"""Where this host's lane data lives (the drives it may act on), the same for every tool.

`baseline-allscript-install` sets `BASELINE_OWN_DRIVES_FILE` for itself; a tool started on its own (through sudo, a service, a one-off command)
did not, and was refused with "not one of this installer lane's drives" (operator, 2026-10-19). Every entry point calls `apply_defaults`
first. Nothing is overridden when the operator has set a location.
"""
from __future__ import annotations

from pathlib import Path

BUILD_DRIVES_FILE = "/run/media/cane/CACHE/baseline-build/drives.json"       # the build volume (everything of Baseline's lives on CACHE)


def apply_defaults(environ) -> None:
    """Only on a build host: when the operator set a location, or the build volume's lane files exist. An installed system has neither, and keeps
    its own `/etc/baseline/own-drives` (drive_guard's default)."""
    drives = environ.get("BASELINE_DRIVES_FILE") or BUILD_DRIVES_FILE
    own = Path(drives).with_name("own-drives")
    if "BASELINE_DRIVES_FILE" in environ or own.exists():
        environ.setdefault("BASELINE_DRIVES_FILE", drives)
        environ.setdefault("BASELINE_OWN_DRIVES_FILE", str(own))
