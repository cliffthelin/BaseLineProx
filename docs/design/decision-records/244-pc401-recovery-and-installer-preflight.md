> Imported 2026-10-11 from the parallel (Codex) effort, where this record is DR244. Numbered DR244 here so it does not collide with this branch's DR245-248. Other DR numbers inside the text refer to that effort's numbering.

# DR244 (parallel effort DR244): PC401 recovery and installer preflight

Date: 2026-10-10

## Decision

Continue PC401 work by serial `<PC401 drive serial>`, leaving PC601
`<PC601 drive serial>` untouched. Keep the operator-facing installer test on
loopback port 8101 so it does not collide with another service or test target.
Do not claim PC401 ready for native comparison until its authenticated
application review, PolicyKit-authorized update, and independent boot/network
checks succeed.

## Evidence

- Current production `lsblk` inventory identifies PC401 at `/dev/sdc` in this
  observation and PC601 separately at `/dev/sdb`. Device paths are transient;
  future actions must re-resolve the serial.
- The production `installed_drive_update.discover_path()` resolved the enrolled
  PC401 serial to `/dev/sdc`; `discover_recovery()` selected its backup snapshot
  under `/mnt/10TB/backup`.
- The snapshot's 7,975,665,664-byte image SHA-256 matched its manifest:
  `2d3b319931691b1423bafe2c5f8ca091eb5dca96a96fde0ae013c86bd0a4919a`.
  `qemu-img info` confirmed a self-contained 512,110,190,592-byte qcow2 and
  `qemu-img check` reported no errors. The manifest does not claim boot
  verification.
- Current visible `lsblk` reports no PC401 mounts, `/proc/*/mountinfo` contains
  no visible entry naming its VG, and `fuser` reported no users for the checked
  target volumes. This is not a complete privileged LVM/use-state inspection:
  `/dev/mapper/control` is inaccessible to the unprivileged process.
- The current-source web app is running on `127.0.0.1:8101`. The Installer Plan
  route redirects unauthenticated requests to login. Its guarded update action
  still requires an authenticated review and native PolicyKit authorization;
  neither has been completed in this increment.
- No physical disk was written. PC401 has not been updated, booted natively, or
  compared with PC601 in this increment. No fake runner or fake process was
  used.

## Consequences and remaining work

The recovery image is currently integrity-checked and available for the
application's guarded update flow. The physical target is not ready for a
comparison test yet. Complete the authenticated Installer Plan preparation and
review, accept the exact serial-bound action in the application, complete its
native PolicyKit prompt, then verify installation and boot with a distinct
network test allocation. Continue under v0.2 queue rows 72 and 78 and the
independent-drive checklist. This record does not close either item.
