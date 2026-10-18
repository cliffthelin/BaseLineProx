"""Protect populated drives and keep destructive actions inside each installer lane (DR300).

A drive "has data" if it carries any partition, filesystem, LVM or encrypted volume. A blank drive, or one whose
partition table is empty, has none. A drive whose state cannot be read is treated as HAVING data, because the safe
mistake is refusing.

A drive normally counts as installer-made only if its GPT disk GUID is one the installer generated and registered.
Each installer lane's own drives are runtime data on the persistent admin volume (the development lock: those may be
reinstalled even when they hold old data); no serial is ever stored in the repository. Nothing lists another lane's drives: a drive whose disk GUID is a Baseline host stamp for
its own serial from a DIFFERENT lane is recognised as that lane's (`lane_verdict`) and refused before the empty-disk
or installer-UUID paths. Missing/invalid lane identity enables no development lock. These are source policy, not
caller parameters.

Adopting a drive that predates this rule (`stamp_installer_identity`) is non-destructive and is limited to a drive
that is empty or whose every partition is one of Baseline's own volumes, so stamping cannot be used to launder a
drive that holds someone's data.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import registry

REGISTRY_TYPE = "installer_drives"
# This installer lane's own drives are DATA, never code: the file /etc/baseline/own-drives (one hardware serial per line), which lives on the persistent admin volume, is written on the installed
# system itself (its first boot records the drive it runs from) and is never in the repository. BASELINE_OWN_DRIVES_FILE names another file (a build or test host). Another lane's drive is not
# listed anywhere: it is recognised from the identifier stamped on the drive (identifiers.stamped_lane), which names the lane that installed it.
OWN_DRIVES_PATH = "/etc/baseline/own-drives"
_SERIAL_LINE = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


def _installer_lane_uuid() -> str | None:
    path = Path(__file__).resolve().parent.parent / "INSTALLER_UUID"
    try:
        return str(uuid.UUID(path.read_text(encoding="ascii").strip()))
    except (OSError, UnicodeError, ValueError):
        return None


def own_drives_file() -> Path:
    import os
    return Path(os.environ.get("BASELINE_OWN_DRIVES_FILE") or OWN_DRIVES_PATH)


def own_drive_serials(path=None, lane_uuid=..., *, disposable_only: bool = False) -> frozenset:
    """The serials in the lane's own-drives file: `SERIAL` or `SERIAL disposable` per line (blank lines and # comments ignored). The drives are this lane's allowed targets; the `disposable` ones are the
    development lock (they may be reinstalled over old data), and only the operator marks one so. Without a valid lane identity there are none; an absent or unreadable file means none."""
    if lane_uuid is ...:
        lane_uuid = _installer_lane_uuid()
    if not lane_uuid:
        return frozenset()
    try:
        lines = Path(path or own_drives_file()).read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        return frozenset()
    found = set()
    for line in lines:
        words = line.split("#", 1)[0].split()
        if not words or not _SERIAL_LINE.match(words[0]) or len(words) > 2 or (len(words) == 2 and words[1] != "disposable"):
            continue
        if disposable_only and "disposable" not in words[1:]:
            continue
        found.add(words[0])
    return frozenset(found)


def record_own_drive(serial: str, path=None, *, disposable: bool = False) -> bool:
    """Add one serial to the own-drives file (idempotent; a plain serial only; `disposable` only when the operator says so). Returns whether it was newly added."""
    if not isinstance(serial, str) or not _SERIAL_LINE.match(serial):
        raise ValueError("a drive serial is plain letters, digits and ._- , 8 to 64 characters")
    target = Path(path or own_drives_file())
    if serial in own_drive_serials(target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a") as handle:
        handle.write(serial + (" disposable" if disposable else "") + "\n")
    return True


def lane_verdict(ptuuid, serial) -> str:
    """`ours`, `other` or `none`: whether the drive's disk GUID is a stamp from this installer lane, from another lane, or not a Baseline stamp for this drive at all."""
    import identifiers
    lane = identifiers.stamped_lane(ptuuid, serial) if ptuuid else None
    ours = (_installer_lane_uuid() or "").replace("-", "")[:8]
    if lane is None:
        return "none"
    return "ours" if ours and lane == ours else "other"


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


def is_own_label(label) -> bool:
    """A partition name Baseline itself creates, current or older."""
    return bool(_OWN_LABEL_RE.match(label or ""))


def is_baseline_only(state: DriveState) -> bool:
    """True for a drive that is empty or whose every partition is one of Baseline's own volumes."""
    if not state.known:
        return False
    if not state.has_data:
        return True
    return bool(state.labels) and all(is_own_label(label) for label in state.labels)


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


def _authorize_format(device_path: str, state: DriveState, *, serial: str | None,
                      installer_uuid_registered: bool) -> None:
    """Apply lane identity before blank-disk or registered-GUID allowances."""
    if serial is None:
        raise DataProtectionError(
            f"refused: {device_path} serial could not be read unambiguously; no override")
    if lane_verdict(state.ptuuid, serial) == "other":
        raise DataProtectionError(f"refused: {device_path} carries another installer lane's stamp ({serial}); no override")
    if not state.known:
        raise DataProtectionError(
            f"refused: {device_path} drive state could not be read as one whole disk; no override")
    if serial in own_drive_serials(disposable_only=True):
        return None
    if not state.has_data:
        return None
    if state.ptuuid and installer_uuid_registered:
        return None
    raise DataProtectionError(
        f"refused: {device_path} will not be formatted: it holds data and does not carry a UUID generated by the "
        "Baseline installer. Baseline never formats a drive with data unless the installer created it, and there is no override.")


def require_may_format(device_path: str, *, run=None, serial: str | None = None) -> None:
    """Raises unless whole-disk state and an exact, freshly validated serial authorize this drive.

    Callers that already used ``physical_device_safety.validate_target_device`` pass its serial, avoiding a
    second independent serial lookup that could disagree or be unavailable. Direct callers omit it and must
    provide one unambiguous serial through the read-only lsblk probe.
    """
    state = read_drive_state(device_path, run=run)
    if serial is not None:
        serial = serial.strip() if isinstance(serial, str) else None
        if not serial or any(ch.isspace() for ch in serial):
            serial = None
    else:
        serial_reader = run or _default_run
        try:
            rc, output = serial_reader(["lsblk", "-dn", "-o", "SERIAL", device_path])
        except Exception:  # noqa: BLE001 - inability to identify the target keeps the guard closed
            rc, output = 1, ""
        serials = output.splitlines() if isinstance(output, str) else []
        serial = serials[0].strip() if rc == 0 and len(serials) == 1 else None
    registered = bool(serial and state.ptuuid and is_installer_uuid(state.ptuuid))
    return _authorize_format(device_path, state, serial=serial, installer_uuid_registered=registered)


def stamp_installer_identity(cmd, device_path: str, *, serial: str, read=None) -> StampResult:
    """Give an empty drive, or one that is entirely Baseline's own volumes, a fresh installer-generated disk GUID
    and register it. Changes nothing but the disk identifier."""
    state = read_drive_state(device_path, run=read)
    if not state.known:
        return StampResult(False, f"could not read {device_path}, so it was not stamped")
    if state.ptuuid and is_installer_uuid(state.ptuuid):
        return StampResult(True, f"{device_path} already carries an installer UUID")
    if state.has_data and not is_baseline_only(state):
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
