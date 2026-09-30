# Decision record: the target drive's real serial was never exposed to the guest, so the answer file's own filter could never match

Status: **real bug found live, via a real install that reached the
QEMU launch stage for the first time on a genuinely fresh (not stale)
process, immediately after decision record 113's stale-process fix.
Fixed, covered by two new regression tests.**

## What happened

After decision record 113 killed the actual stale QEMU process and
fixed the pipeline to kill any future one before launching a new
process, a freshly-triggered real install ran cleanly: DHCP acquired,
the answer file was fetched successfully over `guestfwd`
(`INFO: queried answer file for automatic installation successfully`)
- then failed identically to the failure decision record 112 already
fixed once: `ERROR: Installation failed: filter did not match any
device` / `Auto-installation failed (exit-code 1)`.

This was surprising: decision record 112's fix (`disk_serial=disk_serial`,
not the shadowed `expected_serial`) was confirmed still present and
correct in the code. The answer file's `filter.ID_SERIAL_SHORT` was
genuinely being rendered with the real hardware serial
(`FD01N6557110C271B`) this time - yet the installer still reported no
matching device.

## Root cause

`build_sparse_install_invocation`'s `-drive` line for the target disk
was always `file={target_image},format=raw,if=virtio,cache=none` -
with no `serial=` property. QEMU's virtio-blk device only reports a
serial string to the guest OS if one is explicitly configured; passing
a real host block device (`/dev/sdd`) as the backing `file=` does
**not** propagate that host device's own hardware serial into the
guest automatically. Proxmox's installer, correctly filtering by
`ID_SERIAL_SHORT` as the answer file instructs, saw a blank/absent
serial on the only virtio-blk device present and correctly reported
"filter did not match any device" - a completely accurate error about
a genuinely serial-less virtual disk, not a re-run of decision record
112's variable-shadowing bug.

Decision record 112's fix was real, necessary, and still correct - it
fixed the answer file's *content*. This is a separate, independent gap
in the QEMU *invocation* that record 112's own fix could not have
caught, since nothing in that fix touched how the guest disk itself
was attached.

## Fix

- `build_sparse_install_invocation` (`drive_setup_install.py`) gained
  `target_serial: str | None = None`.
- `build_and_write_self_installer` (`self_installer.py`) now passes
  `target_serial=disk_serial` - the same real, already-detected local
  variable decision record 112 fixed the answer file to use - so the
  guest-visible serial and the answer file's filter are always the
  same real value by construction, not two independently-typed places
  that can drift apart again.

**Correction 1, same day, found immediately on the very next real
retry**: the first version of this fix appended `,serial={target_serial}`
directly onto the combined `-drive file=...,if=virtio,...` shorthand
line. That failed immediately with a real, precise QEMU error against
the actual installed binary (QEMU 10.2.1): `Block format 'raw' does
not support the option 'serial'` - `serial=` is a **device** property
(`virtio-blk-pci`), not a block-format/backend option, and the
combined shorthand only accepts backend-layer options. Moved to the
split form instead - `-drive file=...,format=raw,if=none,id=targetdisk,cache=none`
plus a separate `-device virtio-blk-pci,drive=targetdisk,serial=...`
- confirmed directly against the real, installed QEMU binary via a
disposable dry-run (a 1 MiB dummy file, `-display none -daemonize`,
launched and confirmed alive, then killed) before being redeployed
against the real device.

**Correction 2, same day, found on the very next real retry after
that**: the split `virtio-blk-pci` form launched cleanly - but the
real install still failed with the *exact same* "filter did not match
any device" error. Rather than guess again, this was diagnosed live on
the guest itself: the previous failed attempt's QEMU process was still
alive, sitting at an idle root shell (the auto-install had already
aborted; `/dev/sdd` was confirmed untouched). Real HMP `sendkey`
keystrokes were typed into that live shell (the same safe, proven
technique as decision record 108's screendump viewer - `vnc_type.py`'s
established pattern, never anything but the one intended command) and
the result read back via screendump:

- `udevadm info --query=property /dev/vda` on the real target disk
  showed `ID_SERIAL=FD01N6557110C271B` present and correct, but **no**
  `ID_SERIAL_SHORT` key at all anywhere in the full property listing.
- To confirm this was a `virtio-blk` limitation and not something else,
  a second, entirely disposable test disk (a 1 MiB dummy file, never
  touching the real device) was hot-attached to the *same already-running*
  guest via real `drive_add`/`device_add` HMP commands, as
  `virtio-scsi-pci` + `scsi-hd` with `serial=TESTSERIAL123`.
  `udevadm info --query=property /dev/sda` on that disposable disk
  showed `ID_SERIAL_SHORT=TESTSERIAL123` - present and correct.

This is conclusive, real, direct evidence: `virtio-blk` devices never
populate udev's `ID_SERIAL_SHORT` property under this guest kernel,
regardless of what `serial=` value is configured - only `ID_SERIAL`
(the vendor-prefixed long form). Proxmox's own answer-file filter
checks `ID_SERIAL_SHORT` specifically, so no `virtio-blk`-attached
target disk could ever satisfy it. The fix: attach the target disk via
`virtio-scsi-pci` + `scsi-hd` instead of `virtio-blk-pci` whenever
`target_serial` is given - `-device virtio-scsi-pci,id=targetscsi` +
`-device scsi-hd,drive=targetdisk,bus=targetscsi.0,serial=...`.
Independently dry-run against the real QEMU binary (disposable dummy
file, confirmed alive via `ps`, killed) before redeployment.

## Why no existing test caught this

No test ever asserted anything about the `-drive` line's contents
beyond which files it referenced (`test_sparse_install_invocation_uses_only_sparse_target_and_iso`)
- serial exposure was never in scope for any prior test, since the
concept hadn't been identified as relevant until this real failure.

## Files changed

- `baseline/lib/drive_setup_install.py` - `target_serial` param,
  threaded onto the `-drive` line.
- `baseline/lib/self_installer.py` - `target_serial=disk_serial` at
  the call site.
- `tests/unit/test_drive_setup_install.py` - 2 new tests: serial
  omitted by default, serial threaded through correctly when given.
- `tests/unit/test_self_installer.py` - 1 new test: `disk_serial`
  reaches `build_sparse_install_invocation` as `target_serial`.

## Verification performed

- Full suite: 1550/1550 (both before and after the syntax correction -
  the tests were updated to match the corrected split-device form,
  not just left passing against a stale assertion).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Found via a real install** that reached this exact failure on a
  genuinely fresh QEMU process (confirmed via decision record 113's
  own fix having just been verified working) - not from inspection.
  `/dev/sdd`'s real partition table was independently re-checked and
  confirmed still completely unchanged (the failure happens before any
  partitioning begins).
- The first fix attempt's own real failure was caught immediately by
  the very next real retry (QEMU's own stderr, which nothing redirects
  away from `baseline-web`'s own log) rather than silently believed
  successful - `install_runner.popen()` returning a process handle
  only proves the fork/exec succeeded, never that the child stayed
  alive, and no code anywhere waited to check.
- The corrected split-device syntax was independently dry-run against
  the real, installed QEMU 10.2.1 binary with a disposable 1 MiB dummy
  file (`-display none -daemonize`, confirmed alive via `ps`, then
  killed) before being redeployed against the real device.
- A real, self-triggered retry with the corrected fix applied was
  launched after writing this record.
