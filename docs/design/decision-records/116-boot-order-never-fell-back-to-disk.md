# Decision record: the install invocation's own base boot order never fell back to disk, so the auto-installer's own reboot re-entered itself

Status: **real bug found live, the deepest and most subtle in this
whole debugging chain - discovered only after decision records
112-115 let a real install reach genuine completion (99%, "make
system bootable") for the first time. Fixed, covered by regression
tests.**

## What happened

With decision records 112-115 all applied, a real install
(job `c841968111c74aba8537a7116f588871`) finally progressed to real
package configuration and reached 99% - "make system bootable", the
final stage of Proxmox's automated installer. A raw byte read of
`/dev/sdd`'s first sector (bypassing the host kernel's stale
partition-table cache) confirmed a real, fresh GRUB boot-sector
signature being written. This was the deepest real progress in the
entire session.

A follow-up screendump one minute later, expecting a completion
message, instead showed the installer **back at "Preparing installer
mount points and working environment... Starting Proxmox
installation..."** - a fresh boot of the installer environment again -
which then failed the answer-file fetch with the same
`timeout: global` symptom decision record 115 had just fixed for a
*different* cause.

## Root cause

`build_sparse_install_invocation`'s `-boot` argument was
`order=d,once=d`. QEMU's `once=` boot-order override applies **only
to the very first boot of the process's life** (the BIOS/UEFI boot
device selection at process start) - every subsequent boot *within
the same still-running QEMU process* falls back to the **base**
`order=` value. Since the base value here was also `d` (CD-ROM), every
reboot, forever, kept re-selecting the CD-ROM.

Proxmox's automated installer reboots the guest itself after a
successful install (already visible in every prior screendump as
`INFO: Rebooting system after successful installation`) - and that
reboot happens *inside the same QEMU process*, not as a new, separate
launch this codebase could intercept. With the base order stuck at
`d`, that self-triggered reboot re-booted the *installer ISO* again
from scratch, against the now-already-installed disk - and since a
fresh, per-invocation session token is embedded in the answer file
each time `build_and_write_self_installer` runs, a *second*
auto-install attempt inside the same QEMU session (which never calls
that function again) has no valid answer file to find, hence the
fetch timeout.

This exact failure mode was already described in this same function's
own docstring, citing decision record 04: "installer media left first
in boot order can silently re-enter itself against an already-
installed disk." The warning was correct, but the actual fix
(`order=c` as the base) was never applied to this invocation - the
existing separate `build_postinstall_boot_invocation` function already
uses `order=c` correctly, but that function is for a *different*,
later, separately-launched QEMU process; it does nothing for a reboot
that happens automatically inside the *same* installer session before
any of this codebase's own code gets a chance to run again.

## Fix

`build_sparse_install_invocation`'s `-boot` argument changed from
`order=d,once=d` to `order=c,once=d` in both branches (with and
without `target_serial`). The very first boot still uses the CD-ROM
(the one-time override); every boot after that - including the
installer's own internal post-install reboot - now falls back to the
disk, which by that point holds the freshly-installed, bootable
Proxmox system.

## Why no existing test caught this

No existing test ever asserted anything beyond "the CD-ROM is used
for the first boot" - the base/override distinction, and its
consequence for boots after the first, had never been represented
in any test because no test (or prior real run) had ever gotten far
enough for a second boot to occur within the same process. This bug
was structurally unreachable to discover until decision records
112-115 were already in place.

## Files changed

- `baseline/lib/drive_setup_install.py` -
  `build_sparse_install_invocation`'s `-boot` argument corrected in
  both branches; docstring rewritten to explain the real `once=`
  semantics and this specific failure.
- `tests/unit/test_drive_setup_install.py` - the existing boot-order
  test renamed and updated to assert `order=c,once=d`; the SCSI/serial
  branch's own test gained the same assertion (it previously never
  checked boot order at all).

## Verification performed

- Full suite: 1552/1552 (test count unchanged - an existing test was
  corrected rather than a new one added, plus one assertion added to
  an existing test).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Found via a real install reaching genuine completion** for the
  first time in this entire session (99%, confirmed via real raw
  boot-sector bytes read directly from `/dev/sdd`, bypassing the host
  kernel's stale partition-table cache) and then being directly
  observed, via a real screendump, looping back into the installer
  instead of booting the newly-installed system - not from inspection
  or documentation review, even though the documentation had already
  correctly described the failure mode in the abstract.
- A real, self-triggered retry with this fix applied was launched
  after writing this record; end-to-end confirmation (a full install
  cycle reaching a genuine "installation complete" state and then
  correctly booting into the installed system on reboot) is still
  pending at the time this record was written.
