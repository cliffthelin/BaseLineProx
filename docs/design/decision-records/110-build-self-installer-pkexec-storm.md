# Decision record: `build_self_installer`'s own device validation was spawning a real pkexec dialog per plain read

Status: **real bug found live (a genuinely blocking authentication
dialog on the operator's screen, for a read that never needed
privilege), fixed, and covered by a new regression test.**

## What happened

A real, self-triggered `build_self_installer` retry (with decision
record 109's corrected `patch`-mode xorriso fix already applied) hung
indefinitely at "Validating /dev/sdd is a real, safe, non-boot
target..." - no progress for 40+ real seconds. Investigated directly
rather than assuming another slow-I/O false alarm: `ps --ppid
<baseline-web-pid>` found a real, live child process -
`pkexec udevadm info --query=property --name=/dev/sdd` - genuinely
running and blocked, waiting for an authentication dialog nobody was
watching. Killing it let the job continue exactly one step, to the
*next* plain read (`pkexec findmnt / -no SOURCE`), which spawned its
own separate blocking dialog in turn.

## Root cause

`build_self_installer`'s own docstring already stated the real fact:
none of its five real stages need root on this machine - `udevadm`/
`lsblk`/`findmnt` device queries are unprivileged reads (`cane` is in
the `disk` group), and the final QEMU step only needs group-level
access to the device node. Its `pds_runner` selection logic, though,
still defaulted to `runner.as_pds_runner()` "for consistency" whenever
available. That was correct for `SudoRunner` (decision record 84) -
its own adapter (`_SudoPdsAdapter`) already delegates `lstat`/
`realpath`/`read_size_file` to a plain, unprivileged `pds.Runner()`
internally, and even its `run()` method only mattered for the rare
case those reads needed a real command. It was silently **wrong** for
`PkexecRunner` (decision record 103): `_PkexecPdsAdapter.run()` wraps
*every* call - including a plain `udevadm info` - in a real `pkexec`
invocation. Since `physical_device_safety.validate_target_device`
calls `runner.run()` repeatedly (once for the target's own serial,
then again inside `get_boot_device_serial`'s own `findmnt`/`lsblk`/
`udevadm` chain), every one of those calls became its own separate,
genuinely blocking real authentication prompt - with nothing on
screen explaining why checking a drive's serial number needed a
password at all.

## Fix

`build_self_installer`'s `pds_runner` now always defaults to a plain
`pds.Runner()` directly - never derived from whatever `runner` it was
given. This action's own validation reads never had a real reason to
authenticate in the first place, regardless of which kind of runner
authorized the broader action.

## Files changed

- `baseline/lib/drive_admin.py` - `build_self_installer`'s `pds_runner`
  selection simplified to `pds_runner or pds.Runner()`, dropping the
  `runner.as_pds_runner()` fallback; docstring rewritten with the real
  story.
- `tests/unit/test_drive_admin.py` - new test proves a real
  `PkexecRunner` passed to `build_self_installer` results in a plain
  `pds.Runner()` being used for validation, and that zero `pkexec`
  calls are ever made for the action's own setup.

## Verification performed

- Full suite: 1541/1541 (was 1540 before this record's 1 new test).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Live, real diagnosis**: found the actual stuck `pkexec udevadm`
  child process via `ps --ppid`, confirmed killing it let the job
  advance exactly one step before hitting the *next* unnecessary
  dialog - conclusively proving the "one dialog per plain read"
  pattern before writing any fix. Server restarted on the fix; the
  operator's next real retry should reach QEMU launch without any
  spurious authentication prompts along the way.
