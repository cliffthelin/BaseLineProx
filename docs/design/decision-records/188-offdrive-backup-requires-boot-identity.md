# DR188: Off-drive backups require boot-drive identity

Date: 2026-10-09  
Status: accepted

## Context

`offdrive_backup.resolve_destination()` compared the destination's physical
serial against the running system's boot serial only when that serial was
available. `_boot_serial()` converts discovery errors into `None`; the missing
identity therefore allowed validation to continue as if no boot-drive match
had been found. That did not establish that the backup target was a separate
device.

## Decision

Destination validation raises `BackupError` when `boot_serial` is absent or
blank. Both the volume and guest backup flows use this same validator. A backup
may proceed only after the caller supplies an observed boot-drive serial, and
existing checks still reject a destination on the running boot drive or on an
enrolled Baseline drive. Boot serial discovery now falls back to the mounted
root's kernel major:minor in sysfs when the `/dev` node is absent, then asks
udev for the parent disk's serial. It does not guess from a model or path.

## Evidence

Regression tests cover unknown boot identity and sysfs discovery when the root
device node is absent. `tests/unit/test_physical_device_safety.py`,
`tests/unit/test_offdrive_backup.py`,
`tests/unit/test_guest_backup.py`, `tests/unit/test_backup_recurring.py`, and
`tests/unit/test_operations_page.py` passed: 134 tests, using synthetic
runners and temporary test destinations. A read-only host probe resolved the
boot serial as `SN211808916391` through the sysfs fallback. No real backup was
attempted and no physical drive was written or verified.

## Remaining work

REAL-005 still tracks complete storage ancestry and broader supported storage
graphs. This record does not claim physical backup verification.
