# Decision record: persist_bind_mounts.py and drive_installer.py disagreed on the real USER_PERSISTENCE mountpoint

Status: **implemented and tested (1003/1003 suite passing). Not run
against real hardware.**

## What was found

While tracing where the scripts-inbox CRUD server (decision record 70)
should default its inbox directory, checked which real path
`persist_bind_mounts.py` actually expects `USER_PERSISTENCE` to be
mounted at, to keep the new module consistent with it -
`MOUNT_POINT = "/mnt/user-persistence"` (lowercase, hyphenated).
`drive_installer.py`'s own `BASELINE_VOLUMES` (decision records 46-49,
68) mounts the same ext4-labeled volume at `/mnt/USER_PERSISTENCE`
(uppercase, matching the label's own casing).

These are two different paths on a case-sensitive filesystem, written
by two different sessions' work that never cross-checked each other.
`ensure_persistence_mounted()` mounts by `LABEL=USER_PERSISTENCE`, so
it does not care which physical LV it finds - meaning if both
`persist_bind_mounts.ensure_persistence_mounted()` and
`drive_installer.ensure_volume()` ever ran against the same real
machine, the same physical, labeled ext4 filesystem would end up
mounted read-write at two different paths simultaneously. That is not
a cosmetic mismatch - double-mounting the same block device read-write
at two separate mountpoints risks writes made through one mount not
being visible or durable through the other until an unmount, a real
corruption/lost-write class, not just a broken path reference.

## The fix

`persist_bind_mounts.MOUNT_POINT` changed to `/mnt/USER_PERSISTENCE`,
matching `drive_installer.py`'s own real, already-established
convention (chosen as the side to fix since it already has real
LVM-creation logic and decision-record backing behind its casing,
versus fixing the reverse and touching the ext4 LABEL convention
itself). Every hardcoded lowercase path in
`tests/unit/test_persist_bind_mounts.py` updated to match - a
mechanical, repo-wide `grep` confirmed no other file referenced the
old lowercase path.

## What this does not do

- Not run against real hardware - this was found and fixed by reading
  both modules' source directly, not by observing an actual double
  mount.
- Does not add an automated cross-module consistency check for this
  specific class of "two modules independently name the same real
  resource differently" bug - found this one by deliberately tracing
  a dependency before building on top of it, not by a general tool.

## Verification performed

- `tests/unit/test_persist_bind_mounts.py`: 22/22 passing after the
  path update.
- Full suite: 1003/1003 passing, no regressions.
