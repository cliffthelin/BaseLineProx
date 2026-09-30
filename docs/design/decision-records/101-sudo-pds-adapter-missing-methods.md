# Decision record: `_SudoPdsAdapter` was missing 3 of 4 real methods `validate_target_device` needs - crashed the connection, explaining "nothing happened"

Status: **real crash found via the actual server log, fixed, and
covered by 3 new tests that would have caught this before it ever
shipped. Not yet re-verified against a real `build_self_installer`
run (needs the user's own password again).**

## What happened

User: "logged in fine but nothing happened when I authorized and ran."
The real server log showed the actual cause - an unhandled
`AttributeError: '_SudoPdsAdapter' object has no attribute 'realpath'`,
raised inside `physical_device_safety.validate_target_device` during a
real `build_self_installer` request. `BaseHTTPRequestHandler` doesn't
send a clean response when a handler raises - the connection just
breaks. The browser's `fetch()` in `driveAdminModalConfirm` never got
a parseable JSON response, so its `.then` never ran: no redirect, no
banner, the modal just sat there - exactly "nothing happened."

## Root cause

`_SudoPdsAdapter` (built earlier this session, decision record 84-
adjacent, for `rebuild_persistence_lvm`'s own real
`pds.wipe_signatures` call) only ever implemented `run()`. But
`physical_device_safety.validate_target_device` - which
`build_self_installer` reaches through `self_installer.
build_and_write_self_installer` - also calls `lstat`, `realpath`, and
`read_size_file` on its `pds_runner`. Those three were never actually
exercised against this adapter until this real request: `install`/
`create_volumes_on_existing_vg` (both removed in decision record 99)
went through `rebuild_persistence_lvm`, which only calls `wipe_signatures`
(needs `run()` alone) - `build_self_installer` is a different, newer
call path that needed the adapter's *full* interface, and nothing
caught the gap because no test ever constructed a real
`_SudoPdsAdapter` and called anything but `run()` on it.

## Fix

None of `lstat`/`realpath`/`read_size_file` need real privilege -
they're the same plain filesystem/sysfs reads
`physical_device_safety.Runner`'s own default (non-sudo)
implementation already does. `_SudoPdsAdapter` now holds a plain
`pds.Runner()` instance and delegates all three to it, rather than
reimplementing (and potentially re-breaking) them a second time.

## Files changed

- `baseline/lib/drive_admin.py` - `_SudoPdsAdapter` gained `lstat`/
  `realpath`/`read_size_file`, delegating to a plain `pds.Runner()`.
- `tests/unit/test_drive_admin.py` - 3 new tests: proves `lstat`/
  `realpath` work for real against a real temp file, proves the
  delegation target is a real `pds.Runner`, and proves `run()` still
  goes through real sudo - closing the exact coverage gap that let
  this ship.

## Verification performed

- Full suite: 1504/1504 (was 1501 before this record's 3 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Not yet re-verified against a real `build_self_installer` run** -
  that needs the user to retry with their own real password again,
  now that the crash is fixed.
