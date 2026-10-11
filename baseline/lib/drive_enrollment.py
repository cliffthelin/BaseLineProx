"""Drives deliberately added to the ones Baseline may act on (direct instruction 2026-10-03, extending v0.2 row 55).

Row 55 limits every drive action to the SK hynix drives Baseline is set up with (`drive_admin.ALLOWED_TARGET_SERIALS`).
An installer has to work on whatever drives are in front of it, so another drive can be added, but only deliberately:
`drive_admin.enroll_drive` requires the operator to type the serial, the drive itself to report that serial, and a
person to confirm the request like every other drive action. This module only remembers the result.

Enrolling a drive writes nothing to it. It only lets the drive through `drive_admin.resolve_target`; formatting it
is still governed by `drive_guard` (a drive holding data that the installer did not make is never formatted).

Stored in the registry's GLOBAL scope, on BASELINE, beside `drive_guard`'s installer UUIDs. A store that cannot be
read counts as nothing enrolled: the safe mistake is refusing a drive, never admitting one.
"""
from __future__ import annotations

import re

import references
import registry

REGISTRY_TYPE = "enrolled_drives"
_SERIAL_RE = re.compile(r"^[A-Za-z0-9._-]{4,40}$")


class DriveEnrollmentError(ValueError):
    """Enrollment state could not be read; it is not an empty allowlist."""


def check_serial(serial) -> str:
    if not isinstance(serial, str) or not _SERIAL_RE.match(serial) or serial.strip(".") == "":
        raise ValueError(f"not a drive serial: {serial!r}")
    return serial


def enrolled_serials() -> frozenset:
    try:
        return frozenset(registry.list_entries(REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True))
    except Exception as exc:  # noqa: BLE001 - preserve the store failure for every caller
        raise DriveEnrollmentError(f"drive enrollment registry unavailable: {exc}") from exc


def enroll(serial, *, size_bytes: int, model: str, now: float) -> None:
    serial = check_serial(serial)
    registry.register_type(REGISTRY_TYPE, "Drives deliberately added to the ones Baseline may act on "
                           "(drive_enrollment.py)", default_scope=registry.GLOBAL)
    registry.upsert_entry(REGISTRY_TYPE, serial, scope=registry.GLOBAL,
                          attributes={"size_bytes": int(size_bytes), "model": str(model), "enrolled_at": float(now)})
    references.link(REGISTRY_TYPE, serial, kind="hardware")
