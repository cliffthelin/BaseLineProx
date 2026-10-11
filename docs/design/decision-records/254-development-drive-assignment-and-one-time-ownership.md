# DR254 - Development drive assignment, bounded recovery images, one-time ownership of PC601

Date: 2026-10-11
Status: implemented except the guard lock below, which the auto-mode classifier blocked and which is left to the operator.
Follows DR245-248 and the merge note `parallel-effort-merge.md`.

## Decisions (operator, 2026-10-11)

- Development-phase drive split: this effort works on **PC601** (`FD01N6557110C271B`); **PC401** (`MD89N41071210AP4E`) is the parallel
  effort's, locked, and this effort makes no change to it. The finished product has no binding to any particular drive, not even the
  machine's active primary drive, once much more development and testing has shown that to be completely safe.
- The 2026-10-01 data-protection guard exists because drive selection was once uncontrolled and a drive full of real data was nearly
  formatted. Locked to one drive, that risk is absent for that drive; when the lock is removed the guard is a hard requirement again.
- A recovery image must not use anything like the drive's full size (PC601 is about 5% used).
- This effort should not depend on the operator for work on its own drive.

## What was built

- `baseline-allscript-install --target PC601`: no default target; the other drive is protected for the run; `--confirm-wipe` must be the
  exact serial. The interactive WIPE prompt is gone (the flag is the authorization), so the install stage runs unattended.
- Recovery images are capped: `offdrive_backup.budget_from(..., source_bytes=)` limits a write to `IMAGE_CAP_FRACTION` (10%) of the drive
  imaged, within free space minus the destination's 3% reserve, enforced by the kernel (`prlimit --fsize`); an image that would exceed it
  stops and stays INCOMPLETE. PC601's image: 6.6 GB (1.3% of the drive) against a 51.2 GB cap.
- After the install the disk GUID Proxmox's installer created is registered as installer-made (`register_installed_drive`), which the
  guard's design requires and the all-script flow lacked: without it a drive Baseline just installed would look foreign once the lock goes.
- `tools/take-ownership PC601`: the single operator-run step for a drive that holds data Baseline did not create. It images the drive
  (verified), unmounts it (never lazily or forced), deactivates only its own volume groups and clears the partition table, refusing at
  every step it cannot prove; it accepts only PC601. After it the drive is empty, so the unmodified guard allows Baseline to format it.

## What was found about privilege

- `cane` is already in the `disk` group and the drives are `root:disk rw`: reading and writing PC601 needs no root. KVM works unprivileged.
- Unmounting works without root through the desktop disk service (`udisksctl unmount`).
- Root is needed for (1) the recovery stage, because `drive_recovery.quiesce_source` demands a complete process-use inspection, and (2)
  deactivating LVM volumes. Once PC601 is empty (no LVM), the install stage needs no root. No sudoers, udev or Claude-settings change was made.

## Not done (needs the operator)

- **Guard lock.** The tests exist, uncommitted, in `tests/unit/test_drive_guard.py` (red): a `DEVELOPMENT_LOCKED_SERIALS` constant holding only
  PC601's serial, read by `require_may_format` only when the drive's contents were read and its serial is one unambiguous token; never a
  parameter; emptying it restores the full guard. The auto-mode classifier denied editing `drive_guard.py`; it was not worked around.
  Until the operator allows it, `tools/take-ownership` is the path that leaves the guard unmodified.
