"""Setting up USER_ADMIN on each install (DR257, operator 2026-10-17: "the host needs to set up the User Admin on each install").

USER_ADMIN holds everything personal that belongs to this host: its configuration, credentials, browser use and installation details. It is never published
and never carried from the machine that built the installer: every install creates its own, and this module is the one place that says what it contains.

`setup` is safe to run again. It will not write unless USER_ADMIN is genuinely a separate mounted volume (a write to an unmounted `/mnt/USER_ADMIN` would land on the
root volume, which is the publishable one), it refuses a volume that already belongs to a different install, and it never follows a link. What it makes:

    config/            host configuration the operator chose (the supported-OS list)
    settings/          the layered settings' admin layer
    vault/             the credential vault, mode 0700
    chromium/kiosk/    the kiosk browser's profile
    .baseline-user-admin.json   which install this volume belongs to, and when it was set up
"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

ROOT = Path("/mnt/USER_ADMIN")
MANIFEST = ".baseline-user-admin.json"
FORMAT = "baseline.user-admin/v1"
FOLDERS = (("config", 0o755), ("settings", 0o755), ("vault", 0o700), ("chromium", 0o755), ("chromium/kiosk", 0o755))


class UserAdminError(RuntimeError):
    pass


def _plain_folder(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def read_manifest(root: Path = ROOT):
    try:
        data = json.loads((Path(root) / MANIFEST).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_ready(root: Path = ROOT, is_mount=os.path.ismount) -> bool:
    """True only when USER_ADMIN is a mounted volume this module has set up: what anything that writes there should check first."""
    manifest = read_manifest(root)
    return bool(is_mount(str(root)) and manifest and manifest.get("format") == FORMAT)


def setup(root: Path = ROOT, *, host_id: str = "", is_mount=os.path.ismount, now=None) -> dict:
    root = Path(root)
    if not is_mount(str(root)):
        raise UserAdminError(f"{root} is not a mounted volume; nothing is written to it (it would land on the root volume)")
    if not _plain_folder(root):
        raise UserAdminError(f"{root} is not a plain folder")
    existing = read_manifest(root)
    if existing is not None and existing.get("format") != FORMAT:
        raise UserAdminError("this volume carries a record this version does not understand; refusing to adopt it")
    if existing and existing.get("host_id") and host_id and existing["host_id"] != host_id:
        raise UserAdminError("this USER_ADMIN belongs to a different install; it is not adopted by this one")
    made, kept = [], []
    for relative, mode in FOLDERS:
        path = root / relative
        if path.is_symlink() or (path.exists() and not _plain_folder(path)):
            raise UserAdminError(f"{path} is a link or not a folder; refusing to use it")
        if path.exists():
            kept.append(relative)
        else:
            path.mkdir(parents=True)
            made.append(relative)
        path.chmod(mode)                      # a folder that exists with looser permissions is tightened, never left open
    record = dict(existing or {})
    record.update({"format": FORMAT, "role": "USER_ADMIN", "folders": [f for f, _ in FOLDERS],
                   "notice": "private to this install; never publish it, and it is not carried from the machine that built the installer"})
    record.setdefault("created", (now or (lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z")))())
    if host_id:
        record["host_id"] = host_id
    target = root / MANIFEST
    tmp = root / (MANIFEST + ".part")
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, target)
    return {"created": made, "kept": kept, "host_id": record.get("host_id", ""), "adopted_existing": existing is not None}
