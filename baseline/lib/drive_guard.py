"""No formatting a drive that holds data unless the Baseline installer made it (operator instruction 2026-10-01).

A drive "has data" if it carries any partition, filesystem, LVM or encrypted volume. A blank drive, or one whose
partition table is empty, has none. A drive whose state cannot be read is treated as HAVING data, because the safe
mistake is refusing.

A drive counts as installer-made only if its GPT disk GUID is one the installer generated and registered. The
installer stamps a fresh GUID (`sgdisk -U`, which changes nothing but the disk identifier) and records it in the
registry; the check compares the drive's current GUID to the registry. A drive that holds data and does not carry
such a GUID can NEVER be formatted by Baseline. There is no override: `require_may_format` has no parameter that
relaxes it, and neither a human confirmation (hitl.py) nor a standing approval can skip it, because a refused
request never even reaches a confirmation.

Adopting a drive that predates this rule (`stamp_installer_identity`) is non-destructive and is limited to a drive
that is empty or whose every partition is one of Baseline's own volumes, so stamping cannot be used to launder a
drive that holds someone's data.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass, field

import registry

REGISTRY_TYPE = "installer_drives"
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Partition names Baseline itself creates, including the older names that real drives still carry.
_OWN_LABEL_RE = re.compile(r"^(BASELINE|INSTALLER_CACHE|SESSION_TEMP|SUBSTRATE(_PERSISTENCE)?|USER(_[A-Z0-9_]+)?|"
                           r"APPDATA_[A-Z0-9_]+)$")


class DataProtectionError(Exception):
    """A drive holds data and was not created by the Baseline installer."""


@dataclass(frozen=True)
class DriveState:
    known: bool
    has_data: bool
    ptuuid: str | None = None
    labels: tuple = field(default_factory=tuple)      # partition labels, for deciding whether a drive is Baseline's own
    fstypes: tuple = field(default_factory=tuple)     # partition filesystem types (an LVM2_member means Proxmox or similar)


@dataclass(frozen=True)
class StampResult:
    ok: bool
    detail: str


def _default_run(argv):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout


def normalize_guid(value) -> str:
    if not isinstance(value, str):
        raise ValueError("a GUID must be text")
    guid = value.strip().lower()
    if not _GUID_RE.match(guid):
        raise ValueError(f"not a plain GUID: {value!r}")
    return guid


def new_installer_uuid() -> str:
    return str(uuid.uuid4())


def read_drive_state(device_path: str, *, run=None) -> DriveState:
    """Read-only (`lsblk`). `run(argv) -> (returncode, stdout)`."""
    run = run or _default_run
    try:
        rc, out = run(["lsblk", "-nr", "-o", "NAME,TYPE,FSTYPE,PTUUID,LABEL", device_path])
    except Exception:  # noqa: BLE001 - any failure to look means "unknown", which protects the drive
        return DriveState(known=False, has_data=True)
    if rc != 0 or not isinstance(out, str):
        return DriveState(known=False, has_data=True)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        fields = line.split(" ")
        if len(fields) < 2:
            return DriveState(known=False, has_data=True)
        fields += [""] * (5 - len(fields))
        rows.append(fields[:5])
    disks = [r for r in rows if r[1] == "disk"]
    if len(disks) != 1:
        return DriveState(known=False, has_data=True)
    disk, others = disks[0], [r for r in rows if r[1] != "disk"]
    ptuuid = disk[3].strip() or None
    has_data = bool(disk[2].strip()) or bool(others)
    labels = tuple(r[4].strip() for r in others if r[1] == "part")
    fstypes = tuple(r[2].strip() for r in others if r[1] == "part")
    return DriveState(known=True, has_data=has_data, ptuuid=ptuuid, labels=labels, fstypes=fstypes)


def is_baseline_only(state: DriveState) -> bool:
    """True for a drive that is empty or whose every partition is one of Baseline's own volumes."""
    if not state.known:
        return False
    if not state.has_data:
        return True
    return bool(state.labels) and all(_OWN_LABEL_RE.match(label or "") for label in state.labels)


def require_baseline_drive(device_path: str, *, run=None) -> None:
    """The Baseline drive layout may only be written to a drive that is empty or already Baseline's own: never the
    Proxmox install drive or anything holding someone else's data, whatever its disk identifier says."""
    state = read_drive_state(device_path, run=run)
    if not is_baseline_only(state):
        raise DataProtectionError(
            f"{device_path} is not the Baseline drive: it holds partitions that are not Baseline's own volumes, "
            "or it could not be read, so the Baseline layout will not be written to it")


def _ensure_type() -> None:
    registry.register_type(REGISTRY_TYPE, "Disk GUIDs the Baseline installer generated (drive_guard.py)",
                           default_scope=registry.GLOBAL)


def register_installer_uuid(guid, *, serial: str) -> None:
    guid = normalize_guid(guid)
    _ensure_type()
    registry.upsert_entry(REGISTRY_TYPE, guid, attributes={"serial": str(serial)}, scope=registry.GLOBAL,
                          value={"by": "installer"})


def is_installer_uuid(guid) -> bool:
    try:
        guid = normalize_guid(guid)
    except ValueError:
        return False
    return guid in registry.list_entries(REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True)


def require_may_format(device_path: str, *, run=None) -> None:
    """Raises DataProtectionError unless the drive is empty or carries an installer-generated UUID. Takes no
    option that relaxes it."""
    state = read_drive_state(device_path, run=run)
    if not state.has_data:
        return None
    if state.known and state.ptuuid and is_installer_uuid(state.ptuuid):
        return None
    why = ("its contents could not be read, so it is treated as holding data" if not state.known
           else "it holds data and does not carry a UUID generated by the Baseline installer")
    raise DataProtectionError(
        f"refused: {device_path} will not be formatted: {why}. Baseline never formats a drive with data unless "
        "the installer created it, and there is no override.")


def stamp_installer_identity(cmd, device_path: str, *, serial: str, read=None) -> StampResult:
    """Give an empty drive, or one that is entirely Baseline's own volumes, a fresh installer-generated disk GUID
    and register it. Changes nothing but the disk identifier."""
    state = read_drive_state(device_path, run=read)
    if not state.known:
        return StampResult(False, f"could not read {device_path}, so it was not stamped")
    if state.ptuuid and is_installer_uuid(state.ptuuid):
        return StampResult(True, f"{device_path} already carries an installer UUID")
    if state.has_data and not (state.labels and all(_OWN_LABEL_RE.match(label or "") for label in state.labels)):
        return StampResult(False, f"{device_path} holds data that is not Baseline's own volumes, so the installer cannot adopt it")
    guid = new_installer_uuid()
    result = cmd.run(["sgdisk", "-U", guid, device_path], timeout=60)
    if result.returncode != 0:
        return StampResult(False, f"could not set the disk identifier: {(result.stderr or '').strip()[:200]}")
    after = read_drive_state(device_path, run=read)
    if not after.known or not after.ptuuid or after.ptuuid.lower() != guid:
        return StampResult(False, f"{device_path} did not take the new identifier, so nothing was registered")
    register_installer_uuid(guid, serial=serial)
    return StampResult(True, f"{device_path} now carries installer UUID {guid}")
