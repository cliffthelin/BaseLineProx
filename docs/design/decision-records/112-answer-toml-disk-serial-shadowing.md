# Decision record: the answer file's disk-serial filter used the wrong variable - baked in the literal string "None"

Status: **real bug found live, immediately after decision record
111's network fix let a real install finally reach this stage for the
first time. Fixed, covered by a new regression test that closes the
exact gap that let it ship.**

## What happened

With decision record 111's `guestfwd` fix applied, a real install
attempt finally got past the answer-file fetch (`INFO: queried answer
file for automatic installation successfully`) and began real
installation steps - then failed: `ERROR: Installation failed: filter
did not match any device` / `Auto-installation failed (exit-code 1)`.

## Root cause

`build_and_write_self_installer` computes the real, actual device
serial early (`disk_serial = pds.get_device_serial(pds_runner,
device_path)`, confirmed correct - `progress(f"Target confirmed:
{device_path} (serial {disk_serial})")` already showed the real value,
`FD01N6557110C271B`, in the progress console). But the answer file
template rendering used `ANSWER_TEMPLATE.format(..., disk_serial=
expected_serial, ...)` - `expected_serial` is a *different*, optional
parameter (the human-override escape hatch decision record 86
explicitly said should never be typed by an operator), `None` in every
real web-driven run. The answer file's own `filter.ID_SERIAL_SHORT`
field got the literal Python string `"None"` baked in - Proxmox's own
installer correctly refused to match any real device against that.

A simple variable-name collision: two different things named
similarly enough (`disk_serial` the real local variable, vs.
`expected_serial` the parameter) at the call site, with the wrong one
used.

## Why no existing test caught this

Every test in `test_self_installer.py`'s `_ready_kwargs` fixture
passed `expected_serial=REAL_SERIAL` - the *same* value the fake
device would also report as its own real serial. `disk_serial ==
expected_serial` in every single test, by construction, completely
masking the bug. The new regression test deliberately passes
`expected_serial=None` - the actual real production default - to
prove the fix.

## Fix

`ANSWER_TEMPLATE.format(..., disk_serial=disk_serial, ...)` - the
real, already-detected local variable, not the parameter.

## Files changed

- `baseline/lib/self_installer.py` - one-line fix + explanatory
  comment at the call site.
- `tests/unit/test_self_installer.py` - new test proves the rendered
  answer file's `filter.ID_SERIAL_SHORT` contains the real detected
  serial and never the literal string `"None"`, using
  `expected_serial=None` (the real production default) specifically
  because every existing test's fixture choice had masked this.

## Verification performed

- Full suite: 1545/1545 (was 1544 before this record's 1 new test).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Found via a real install attempt** reaching further than any prior
  attempt this session (thanks to decision record 111's network fix) -
  not discovered by inspection or a pre-existing test. A real,
  self-triggered retry with both fixes applied was launched after
  writing this record.
