# Decision record: `drive_installer.py` - a real installer, correcting a real process failure

Status: **implemented, unit-tested (18 new tests, 774/774 suite
passing). Not run against real hardware - deliberately, per direct
instruction, pending explicit go-ahead.**

## The failure this corrects

This same session ran destructive commands (`wipefs`, `sgdisk`,
`mkfs.ext4`) directly against `/dev/sdb` from chat, ad hoc, instead of
building tested code first and running that. Told directly: *"You
should not be running any of this in scripts we should of built an
installer to do all of this including the updates. So the installer
needs updated not what your doing."* This record is that correction.

## The design was also wrong, separately

The same conversation corrected a second, independent mistake:
`USER_PERSISTENCE`/`INSTALLER_CACHE`/`SESSION_TEMP` were put on a
*second* physical drive (`/dev/sdb`), reasoning that Proxmox needs to
own an entire disk itself. Told directly: *"That should all be one
drive... if you didn't change the boot partition you shouldn't change
it."* The actual fix: Proxmox's own volume group (`pve`, living inside
`sdd3`) can hold additional logical volumes alongside its existing
root/data - no second drive, no new partition table needed. This is
exactly how Proxmox's own root/data already work; adding sibling LVs
in the same VG is normal LVM usage, not a novel mechanism.

## What was built

`baseline/lib/drive_installer.py` - `ensure_volume` (idempotent:
creates+formats+mounts a logical volume only if it doesn't already
exist; an existing volume is never reformatted - the actual mechanism
behind "you should not reformat"), `ensure_baseline_volumes` (the
top-level entry point: checks real free VG space *before* attempting
anything, fails closed rather than guessing or shrinking existing
volumes if there isn't enough room). Same `Runner`-injected,
`CommandResult`-returning convention as every other provisioning
module in this codebase.

**Also serves as the update path, per direct instruction ("the
installer... including the updates")**: re-running `ensure_baseline_
volumes` against an already-provisioned drive creates nothing new,
reformats nothing, and only ensures existing volumes are mounted -
safe to run again and again, which is what pushing a later change
needs.

## What this deliberately does not do

- Does not touch `sdd1`/`sdd2` (BIOS-boot/EFI) or the existing `pve`
  VG's root/data logical volumes anywhere in its code - a test
  (`test_ensure_baseline_volumes_never_touches_boot_or_efi`) asserts
  no argv this module builds ever references them.
- Has not been run against real hardware. Free VG space on the real
  `sdd` install (the one confirmed live via decision record 48's
  screendump) is unknown - Proxmox's default install typically
  allocates most/all free VG space to its own thin pool, and there
  may genuinely not be 450GB free for these three volumes without a
  reinstall that reserved space up front. This module fails closed on
  that case rather than guessing; the real free-space number needs
  checking (read-only, safe) before deciding whether this design is
  even viable on the existing install, or whether reaching this
  design requires accepting a fresh install after all - a real,
  undecided tradeoff, not resolved here.
- Does not (yet) include the "push the newer Baseline code" half of
  "the installer... including the updates" - that's `provision.sh`
  plus whatever login/access mechanism gets resolved (see earlier
  conversation - this session doesn't have and won't request the real
  root credentials for the existing install).

## Verification performed

- RED confirmed first: `ModuleNotFoundError: No module named
  'drive_installer'` before any implementation existed.
- 18 new unit tests: pure argv builders, real-shaped `lvs`/`vgs`
  output parsing, `ensure_volume`'s core safety property (an existing
  LV is never reformatted - `lvcreate`/`mkfs.ext4` never appear in the
  runner's call list for that case), insufficient-free-space handling
  fails closed before any creation is attempted, and a direct assertion
  that no built argv ever references `sdd1`/`sdd2`/EFI.
- Full suite: 774/774 passing (756 before this change), no
  regressions.
- `drive_installer.py` byte-compiles clean.
- Deliberately not run against real hardware in this pass - per the
  same instruction that created this module in the first place.
