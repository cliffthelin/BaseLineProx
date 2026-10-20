"""Where this host's lane data lives (the drives it may act on), the same for every tool.

`baseline-allscript-install` sets `BASELINE_OWN_DRIVES_FILE` for itself; a tool started on its own (through sudo, a service, a one-off command)
did not, and was refused with "not one of this installer lane's drives" (operator, 2026-10-19). Every entry point calls `apply_defaults`
first. Nothing is overridden when the operator has set a location.
"""
from __future__ import annotations

import os
from pathlib import Path

BUILD_DRIVES_FILE = "/var/lib/baseline/build/drives.json"  # generic fallback; mounted CACHE discovery is preferred on build hosts


def _cache_mounts():
    """Mounted volumes named CACHE, independent of the desktop login's mount path."""
    candidates = [Path("/mnt/CACHE"), *Path("/run/media").glob("*/CACHE")]
    return tuple(path for path in candidates if path.is_mount())


def build_drives_file(environ=None) -> Path:
    env = os.environ if environ is None else environ
    if env.get("BASELINE_DRIVES_FILE"):
        return Path(env["BASELINE_DRIVES_FILE"])
    # Keep explicit test/embedding overrides stable; production uses the
    # mounted volume rather than an operator-specific absolute pathname.
    if BUILD_DRIVES_FILE != "/var/lib/baseline/build/drives.json":
        return Path(BUILD_DRIVES_FILE)
    for cache in _cache_mounts():
        folder = cache / "baseline-build"
        if folder.is_dir():
            return folder / "drives.json"
    return Path(BUILD_DRIVES_FILE)


def apply_defaults(environ) -> None:
    """Only on a build host: when the operator set a location, or the build volume's lane files exist. An installed system has neither, and keeps
    its own `/etc/baseline/own-drives` (drive_guard's default)."""
    drives = str(build_drives_file(environ))
    own = Path(drives).with_name("own-drives")
    if "BASELINE_DRIVES_FILE" in environ or own.exists():
        environ.setdefault("BASELINE_DRIVES_FILE", drives)
        environ.setdefault("BASELINE_OWN_DRIVES_FILE", str(own))
