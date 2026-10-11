"""Identity of an installer and of the drives it installs.

Each installer lane (this one, the parallel effort's) has ONE UUID of its own, pinned in `baseline/INSTALLER_UUID`. It is created the
first time it is needed and never changed afterwards. A lane keeps its own file when source moves between lanes (`.gitattributes`:
`merge=ours`), and a test pins that this lane's value differs from the parallel lane's.

The identity of a drive an installer installed is derived, not generated: uuid5(installer UUID, drive serial). The same installer
and the same drive therefore always give the same UUID, across any number of reinstalls, and it differs between installers and
between drives. It is written to the drive's GPT disk identifier (`sgdisk -U`, which changes nothing else) and registered in the
installer registry (drive_guard.py) against the serial. The registry record outlives any wipe of the drive, and a reinstall simply
stamps the same UUID again, so the identity never changes.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

import drive_guard

FILE_NAME = "INSTALLER_UUID"        # baseline/INSTALLER_UUID: this lane's pinned installer UUID (each lane keeps its own)
_SERIAL = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


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
    if not isinstance(serial, str) or not _SERIAL.match(serial):
        raise IdentityError("a drive's identity needs its plain hardware serial")
    return str(uuid.uuid5(uuid.UUID(installer), serial))


def _real_run(argv):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return proc.returncode, (proc.stdout + proc.stderr)


def probe_disk_guid(device) -> str:
    """The GPT disk GUID read from the device itself (not udev's cache, which lags a table an installer VM just wrote)."""
    proc = subprocess.run(["blkid", "-p", "-o", "value", "-s", "PTUUID", str(device)], capture_output=True, text=True)
    return proc.stdout.strip().lower() if proc.returncode == 0 else ""


def stamp_child_identity(device, serial: str, installer: str, *, run=None, probe=None) -> str:
    """Make `device` carry its stable identity and register it against `serial`. Returns the UUID. Writes nothing when the drive
    already carries it. Only ever called once the installer's VM has exited, so nothing else is writing the partition table."""
    run, probe = run or _real_run, probe or probe_disk_guid
    wanted = child_uuid(installer, serial)
    if (probe(device) or "").lower() != wanted:
        code, output = run(["sgdisk", "-U", wanted, str(device)])
        if code != 0:
            raise IdentityError(f"sgdisk could not set the disk identifier on {device}: {output.strip()[:200]}")
        if (probe(device) or "").lower() != wanted:
            raise IdentityError(f"the disk identifier on {device} did not take; it was not registered")
    drive_guard.register_installer_uuid(wanted, serial=serial)
    return wanted
