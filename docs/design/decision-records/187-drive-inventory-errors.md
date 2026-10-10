# DR187: Drive and LVM inventory failures stay visible

Date: 2026-10-09

## Context

Drive enumeration returned `[]` when `lsblk` failed. The partition summary
turned its failed `lsblk` call into `unknown` fields, and `find_vg_for_device`
returned `None` on failed `pvs`, making permission/tool failures look like a
disk with no volume group. Baseline LVM enumeration failures could likewise be
rendered as a disk without a Baseline installation.

## Decision

Drive and LVM observations raise `DriveInventoryError` on command failures,
missing stdout, malformed key/value rows, or unknown boot-drive identity.
Drive Administration renders inventory errors separately from a successful
empty candidate list. Baseline repair, mount, and unmount actions return an
explicit failed result when the VG query fails; no operation proceeds on
assumed-empty inventory.

## Verification and limits

317 focused drive-administration, enrollment, and web tests passed with
synthetic runners. A read-only development-host call to list candidate drives
failed closed because it could not establish the boot-drive serial. This is
not a verified physical drive inventory. No physical drive was modified.

## Follow-up

Drive enrollment and physical ancestry still require live target verification.
Other audit tasks remain open in `docs/design/runtime-reality-tasks.md`.
