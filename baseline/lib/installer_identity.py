"""Identity of an installer and of the drives it installs.

Each installer lane (this one, the parallel effort's) has ONE UUID of its own, pinned in `baseline/INSTALLER_UUID`. It is created the
first time it is needed and never changed afterwards. A lane keeps its own file when source moves between lanes (`.gitattributes`:
`merge=ours`), and a test pins that this lane's value differs from the parallel lane's.

The identity of a drive an installer installed is derived, never generated, by `identifiers.host_id` (DR255: the first 8 hex digits of
this lane's UUID, the first and last four hex characters of the drive's serial, a layout/kind/check header and a hash of the full
installer UUID and serial). The same installer and the same drive always give the same identifier, across any number of reinstalls; it
differs between lanes and between drives. First boot sets it as the drive's GPT disk identifier (`sfdisk --disk-id`, which changes
nothing else) before it records anything; the host then verifies it, registers it in the installer registry (drive_guard.py) and in the
hierarchical registry (identifiers.py), and retires the older identities registered for that serial. The registry records outlive any
wipe of the drive, and a reinstall simply sets the same identifier again, so it never changes.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

import drive_guard
import identifiers

FILE_NAME = "INSTALLER_UUID"        # baseline/INSTALLER_UUID: this lane's pinned installer UUID (each lane keeps its own)
_SERIAL = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")           # at least 8, so the first and last four characters never overlap


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


def child_uuid(installer: str, serial: str) -> str:
    """The identifier of the install `installer` makes on the drive with `serial` (identifiers.host_id)."""
    try:
        return identifiers.host_id(installer, serial)
    except identifiers.IdentifierError as exc:
        raise IdentityError(str(exc)) from None


def minted_by(guid: str, installer: str) -> bool:
    """Whether `guid` is a valid host, substrate or VM identifier minted by `installer`'s lane, judged from the UUID alone."""
    try:
        return identifiers.parse(guid).lane == str(uuid.UUID(installer)).replace("-", "")[:8]
    except (identifiers.IdentifierError, ValueError):
        return False


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


def legacy_entries(serial: str) -> list:
    """Registered identities for `serial` that do not have the DR255 layout: random ones an installer's own disk got, and those of the
    earlier layouts. Identifiers with the layout (any lane's) are never listed."""
    import registry
    entries = registry.list_entries(drive_guard.REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True)
    found = []
    for guid, entry in entries.items():
        attributes = entry.get("attributes", entry) if isinstance(entry, dict) else {}
        if attributes.get("serial") == serial and not identifiers.is_valid(guid):
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
    identifiers.register_host(wanted, serial=serial)
    retire_legacy_entries(serial, wanted)
    return wanted
