"""Identity of an installer and of the drives it installs.

Each installer lane (this one, the parallel effort's) has ONE UUID of its own, pinned in `baseline/INSTALLER_UUID`. It is created the
first time it is needed and never changed afterwards. A lane keeps its own file when source moves between lanes (`.gitattributes`:
`merge=ours`), and a test pins that this lane's value differs from the parallel lane's.

The identity of a drive an installer installed is derived, never generated, and laid out as a readable control structure
(operator layout, 2026-10-11):

    AAAAAAAA - SSSS - EEEE - Vcc - HHHHHHHHHHHH
    |          |      |      |      the first 12 hex digits of sha256(installer UUID : full serial)
    |          |      |      layout marker V=`b1` (Baseline child, layout 1) + `cc`, a check byte over the first three groups
    |          |      the LAST 4 characters of the drive's serial
    |          the FIRST 4 characters of the drive's serial
    the first 8 hex digits of the installer UUID

A UUID is hex only and serials are not (`MD89N41071210AP4E`), so non-hex characters are skipped: the first group is the first four HEX
characters of the serial read from the front, the second the last four hex characters read from the back, kept in their written
order. If a serial has fewer than four hex characters the count is filled with the reserved value `0` (NON_HEX). Those two groups are
therefore a recognisable hint, not the serial; the hash group binds the identity to the exact full serial, so two drives that share
those characters still differ. The check byte lets anyone tell which installer lane minted a UUID without knowing the serial
(`minted_by`).

The same installer and the same drive therefore always give the same UUID, across any number of reinstalls, and it differs between
installers and between drives. It is written to the drive's GPT disk identifier (`sgdisk -U`, which changes nothing else) and
registered in the installer registry (drive_guard.py) against the serial. The registry record outlives any wipe of the drive, and a
reinstall simply stamps the same UUID again, so the identity never changes.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import uuid
from pathlib import Path

import drive_guard

FILE_NAME = "INSTALLER_UUID"        # baseline/INSTALLER_UUID: this lane's pinned installer UUID (each lane keeps its own)
_SERIAL = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")           # at least 8, so the first and last four characters never overlap
LAYOUT = "b1"                                                # marker of this layout (Baseline child, version 1)
_HEX = "0123456789abcdef"
NON_HEX = "0"                                                # reserved filler when a serial has too few hex characters


class IdentityError(RuntimeError):
    pass


def installer_id(directory) -> str:
    """This lane's installer UUID, created on first use in `directory` (the checkout's `baseline/` folder) and never changed afterwards.
    A damaged file is refused: replacing it would silently change the identity of every drive this installer installed."""
    path = Path(directory) / FILE_NAME
    if path.is_file():
        text = path.read_text().strip()
        try:
            if str(uuid.UUID(text)) == text:
                return text
        except ValueError:
            pass
        raise IdentityError(f"{path} does not hold a UUID; it is not replaced, because that would change every drive's identity")
    new = str(uuid.uuid4())
    path.write_text(new + "\n")
    return new


def serial_hex(serial: str, count: int, *, from_end: bool = False) -> str:
    """`count` hex characters of `serial`, skipping every non-hex character: from the front, or the last `count` (kept in written
    order) when `from_end`. Filled with NON_HEX when the serial has too few; the fill goes where the missing characters would be."""
    hexes = [c.lower() for c in serial if c.lower() in _HEX]
    if from_end:
        taken = hexes[-count:]
        return NON_HEX * (count - len(taken)) + "".join(taken)
    taken = hexes[:count]
    return "".join(taken) + NON_HEX * (count - len(taken))


def _check(prefix: str, head: str, tail: str, installer: str) -> str:
    return hashlib.sha256(f"{prefix}{head}{tail}:{installer}".encode()).hexdigest()[:2]


def child_uuid(installer: str, serial: str) -> str:
    if not isinstance(serial, str) or not _SERIAL.match(serial):
        raise IdentityError("a drive's identity needs its plain hardware serial, at least 8 characters")
    installer = str(uuid.UUID(installer))
    prefix = installer.replace("-", "")[:8]
    head, tail = serial_hex(serial, 4), serial_hex(serial, 4, from_end=True)
    body = hashlib.sha256(f"{installer}:{serial}".encode()).hexdigest()[:12]
    return f"{prefix}-{head}-{tail}-{LAYOUT}{_check(prefix, head, tail, installer)}-{body}"


def minted_by(guid: str, installer: str) -> bool:
    """Whether `guid` has this layout and was minted by `installer`'s lane, judged from the UUID alone (no serial needed)."""
    try:
        groups = str(uuid.UUID(guid)).split("-")
        installer = str(uuid.UUID(installer))
    except (ValueError, AttributeError, TypeError):
        return False
    prefix = installer.replace("-", "")[:8]
    return (groups[0] == prefix and groups[3].startswith(LAYOUT)
            and groups[3][2:] == _check(prefix, groups[1], groups[2], installer))


def _real_run(argv):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return proc.returncode, (proc.stdout + proc.stderr)


def probe_disk_guid(device) -> str:
    """The GPT disk GUID read from the device itself (not udev's cache, which lags a table an installer VM just wrote)."""
    proc = subprocess.run(["blkid", "-p", "-o", "value", "-s", "PTUUID", str(device)], capture_output=True, text=True)
    return proc.stdout.strip().lower() if proc.returncode == 0 else ""


def ensure_disk_guid(device, wanted: str, *, run=None, probe=None) -> str:
    """Make `device` carry `wanted` as its GPT disk identifier (`sfdisk --disk-id`: part of util-linux, so present on the installed
    system as well as on the host; it changes nothing else) and read it back. Writes nothing when it already carries it."""
    run, probe = run or _real_run, probe or probe_disk_guid
    if (probe(device) or "").lower() != wanted:
        code, output = run(["sfdisk", "--disk-id", str(device), wanted])
        if code != 0:
            raise IdentityError(f"sfdisk could not set the disk identifier on {device}: {output.strip()[:200]}")
        if (probe(device) or "").lower() != wanted:
            raise IdentityError(f"the disk identifier on {device} did not take")
    return wanted


def is_layout_uuid(guid: str) -> bool:
    """Whether `guid` has this layout (the marker in its fourth group): minted by some lane's installer, not random or older."""
    try:
        return str(uuid.UUID(guid)).split("-")[3].startswith(LAYOUT)
    except (ValueError, AttributeError, TypeError, IndexError):
        return False


def legacy_entries(serial: str) -> list:
    """Registered identities for `serial` that do not have this layout: random ones an installer's own disk got, and the
    first-version uuid5 ones. Identities with the layout (any lane's) are never listed."""
    import registry
    entries = registry.list_entries(drive_guard.REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True)
    found = []
    for guid, entry in entries.items():
        attributes = entry.get("attributes", entry) if isinstance(entry, dict) else {}
        if attributes.get("serial") == serial and not is_layout_uuid(guid):
            found.append(guid)
    return sorted(found)


def retire_legacy_entries(serial: str, replaced_by: str) -> list:
    """Replace the older registered identities of `serial` by the deterministic one (recorded as an event on it)."""
    import registry
    retired = legacy_entries(serial)
    if retired:
        registry.record_event(drive_guard.REGISTRY_TYPE, replaced_by, "migrated", {"retired": retired}, scope=registry.GLOBAL)
        for guid in retired:
            registry.delete_entry(drive_guard.REGISTRY_TYPE, guid, scope=registry.GLOBAL)
    return retired


def stamp_child_identity(device, serial: str, installer: str, *, run=None, probe=None) -> str:
    """Make `device` carry its stable identity, register it against `serial`, and retire the older identities registered for that
    serial. Returns the UUID. Writes nothing to the drive when it already carries it (first boot normally set it already). Only called
    once the installer's VM has exited, so nothing else is writing the partition table."""
    wanted = child_uuid(installer, serial)
    ensure_disk_guid(device, wanted, run=run, probe=probe)
    drive_guard.register_installer_uuid(wanted, serial=serial)
    retire_legacy_entries(serial, wanted)
    return wanted
