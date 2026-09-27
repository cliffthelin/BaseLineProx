# Decision record: audit of the Drivers & Hardware and Virtual Machines tabs

Status: **one real defect found and fixed (with tests added first);
the VM tab audited clean.** 807/807 suite passing. Not run against
real hardware.

## What was asked

Direct instruction: *"Audit the drivers and VM tabs too. Remember that
it doesn't have to use these values and other hardware can be changed
when installed on the target system that may not be the same
system."* - a specific lens for this audit: the configurator reviews
*this* machine's real, detected hardware, but the actual install
target is not guaranteed to be the same physical machine. Anything
that auto-applies a value baked in from this machine's own detection,
with no way to override it for different target hardware, is a real
defect under that lens - not a stylistic nitpick.

## Finding: driver packages were hardwired to this machine's own hardware

`apply_cpu_microcode()` and `apply_wifi_firmware()` (added in decision
record 51) hardcoded `amd64-microcode` and `firmware-mediatek`
respectively - this session's own real, detected CPU vendor and Wi-Fi
chip. `apply_cpu_microcode()` took no package argument *at all*;
`apply_wifi_firmware()` accepted one but `config_pipeline.py` never
passed anything through, so it was unreachable in practice. Both were
marked `coded: true` in the configurator - which, under this audit's
lens, overclaimed correctness: they were only ever correct for a
target identical to this machine, with no path to say otherwise.

This is exactly the class of bug the instruction warned about: a
config reviewed on one machine, exported, and applied automatically at
firstboot on a *different* target would have silently installed the
wrong microcode/firmware package there, with the toggle honestly
reporting "wired" the whole time.

**Fixed**: `apply_cpu_microcode()` now takes a `package` argument
(previously none existed to take). `config_pipeline.apply_stored_config()`
reads two new config keys - `drivers.cpu_microcode_package` and
`drivers.wifi_firmware_package` - and only falls back to this
machine's own detected packages when they're omitted from the exported
config. Two new configurator fields (`cpu_microcode_package`,
`wifi_firmware_package`) expose this directly, each described as "this
machine's own reference default - the target machine may not be this
one." `test_apply_stored_config_uses_a_driver_package_override_for_different_target_hardware`
and its omitted-value sibling lock in both directions.

## The Virtual Machines tab: audited, found not to have this problem

Re-read every field in the VM tab directly rather than trusting memory.
Every single one - `vm_debian_include`, `vm_ubuntu_include`, memory/
cores/disk-size fields, `vm_network_bridge`, `vm_storage_backend`, the
free-text catalog field - is honestly `coded: false`; nothing in
`config_pipeline.py` or anywhere else reads this tab's saved values at
all. Because nothing here auto-applies anything, the "target hardware
may differ" risk this audit was looking for cannot occur in this tab
today - there is no automated action to be wrong. `vm_network_bridge`/
`vm_storage_backend`'s defaults (`vmbr0`/`local-lvm`) are also
independently fine on this point: they are Proxmox's own generic
default names, not values specific to this session's own machine, so
even if this tab is wired up later, its current defaults do not carry
the same this-machine-only assumption the driver toggles did.

## What else was checked in the Drivers tab and found NOT broken

- `gpu_driver_mode` already defaults to `"auto"` with real,
  non-hardware-specific option labels ("let the target machine's own
  install detect and choose") - it already follows the pattern the
  driver-package fix now also follows, and has no apply function at
  all (`coded: false`), so it carries no risk either way.
- `manual_override`, `driver_cache_root`, `driver_unused_subfolder`,
  and every `*_detected` readonly field: all correctly `coded: false`
  or purely informational; none are read by any apply function.
- Re-ran the full-file select-with-no-options scan from decision record
  52's audit against the current file: zero remaining issues.

## Verification performed

- RED confirmed first: `apply_cpu_microcode(runner, package=...)`
  raised `TypeError: unexpected keyword argument 'package'` before the
  fix; the config-pipeline override test asserted the intel-microcode/
  firmware-realtek argv and failed against the old hardcoded behavior.
- 3 new tests: `test_apply_cpu_microcode_accepts_a_different_package_name`,
  `test_apply_stored_config_uses_a_driver_package_override_for_different_target_hardware`,
  `test_apply_stored_config_falls_back_to_this_machines_own_packages_when_omitted`.
- Full suite: 807/807 passing (804 before this audit), no regressions.
