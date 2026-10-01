# 05 · SESSION_TEMP

**Status: MVP completed** · [index](README.md)

Ephemeral session data and quarantine for anything not yet triaged. Mounted at
`/mnt/SESSION_TEMP`, 5-50 GB, `defaults,nosuid,nodev,noexec`. Never anything
meant to run, and nothing here is expected to survive.

## What lives here

- Recovery-mode working state: `recovery_mode.record_entry` and
  `record_exit` write a small JSON file here. It goes on this volume and not
  under a persona, because the persona volume may be exactly what is broken.
- Quarantine for content not yet triaged.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Volume defined and mounted `noexec` | MVP completed | unit tests | `drive_installer.MOUNT_OPTIONS` |
| Recovery-mode state file | MVP completed | unit tests | `recovery_mode.py`, DR 81 |
| Recovery exit requires a read-write persona volume | MVP completed | unit tests | `recovery_mode.can_exit` |
