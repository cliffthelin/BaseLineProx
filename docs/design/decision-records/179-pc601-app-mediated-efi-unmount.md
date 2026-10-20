# Decision record 179: app-mediated unmount of a mounted partition

Date: 2026-10-09
Status: action implemented in source; physical operation not run.

## Decision

Drive Administration needs a safe app action for unmounting a filesystem
partition when preparing a selected drive for transport or another-machine
testing. The existing logical-volume unmount action is not suitable for an EFI
partition. `unmount_partition` accepts only a direct child of `/mnt`, refuses
the backup and installer-cache mountpoints, asks `findmnt` for the mounted
source, verifies that source's parent and the selected disk serial, then runs
`umount -- <mountpoint>`. It uses the existing per-action HITL flow and
`PkexecRunner`, so the privileged call goes through Ubuntu PolicyKit.

The UI includes the mountpoint in the confirmation details. Partition ownership
is rechecked immediately before unmounting; a missing mount, unrecognized
source, wrong parent, or serial mismatch returns a refusal without unmounting.

## Verification and limits

The focused unit tests passed, including the wrong-drive refusal, missing HITL
authorization, and Drive Administration rendering. These tests use fakes and
do not establish a physical unmount. The running development server was not
reloaded to include this action, and PC601's EFI filesystem remains mounted
read-only at `/mnt/sdb2`. No PC601 disk contents were changed. Restart the
development app, run the action from its signed-in Drive Administration page,
approve its Ubuntu PolicyKit prompt, and verify the mount is gone before
removing the drive. The second-machine boot remains untested.

DR179 does not supersede DR176's UEFI preflight or authorize erasing PC601.
