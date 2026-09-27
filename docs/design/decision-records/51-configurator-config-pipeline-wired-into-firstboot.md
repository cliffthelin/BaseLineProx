# Decision record: the configurator's saved values are now genuinely read back and applied at firstboot

Status: **implemented, unit-tested (10 new tests, 802/802 suite
passing). Not run against real hardware** - same standing constraint
as every other provisioning module this session.

## What was asked

Direct instruction, after decision record 50 built real apply
functions but left them disconnected from the configurator: *"Work on
wiring all of this in. So that its utilized during install / setup
and automated."* Followed immediately by a hard constraint, given
mid-turn: *"Note it should not ever change the ISO."*

## What "wiring it in" means here, and what it deliberately does not mean

The configurator artifact's saved values live in the Artifact
platform's own `db` store (cloud-hosted, per-artifact) - a real
install/setup process running on the target machine has no route to
that store at firstboot time, and building one was never asked for and
would be a real trust/security decision on its own. The actual bridge
built instead is an **export**: the configurator now has an "Export
install-config.json" button (the `downloads` capability) that writes
out everything reviewable in the form as one JSON file, field-for-field
matching `config_apply.py`'s/`config_pipeline.py`'s real keys - no
translation layer. The operator places that file at
`/etc/baseline/install-config.json` on the already-installed disk
before first boot; `firstboot_statemachine.py` reads it and applies it
for real, automatically, with no further action needed.

**The ISO constraint, honored by construction, not just by promise**:
nothing in this change touches `drive_setup_acquire.py` or any other
ISO-build code path at all. `config_pipeline.py` never takes an ISO
path as an argument, never runs before or during install, and only
ever reads a file from the already-installed system's own disk, post
install, at firstboot - the exact same real/vanilla-ISO boundary this
project's `testpersistence-prd.md` already established for its own
reasons (§9a - "the ISO/base-image build has no knowledge of any
person, application configuration, or customization whatsoever").
`test_apply_stored_config_never_touches_anything_iso_shaped` in
`tests/unit/test_config_pipeline.py` asserts this directly against
every path/argv the pipeline touches, rather than leaving it as an
unchecked claim.

## What was built

- **`config_apply.py`**: two new real apply functions,
  `apply_cpu_microcode()` (`apt-get install -y amd64-microcode`) and
  `apply_wifi_firmware()` (`apt-get install -y firmware-mediatek` by
  default, package overridable) - the first two Drivers & Hardware tab
  toggles to get a real apply function, matching this project's
  per-tool research discipline (these are the two packages this
  session's own real `lspci -k`/`dpkg -l` detection found this
  machine's AMD CPU and MediaTek Wi-Fi chip actually need).
- **New `config_pipeline.py`**: `load_config(runner, path)` - `None`
  when no config was ever exported, never an error; `apply_stored_config(runner,
  config, network_interface=...)` - dispatches to `apply_smartd_config`/
  `apply_ethtool_config`/`apply_cpu_microcode`/`apply_wifi_firmware`
  independently per subsystem (one subsystem's absence or failure never
  skips a different one), returning `{"applied": [...], "skipped": [...],
  "failed": [...]}` by subsystem name.
- **`firstboot_statemachine.py`**: new `apply_configurator_settings()`,
  called at both real completion points - the fresh commit (right after
  `packages_verified` -> `committed`) and the `already_completed` fast
  path (so a config exported and copied over *after* the first commit
  still gets applied on a later boot, without redoing network
  repair/package install). Best-effort and explicitly non-gating by
  design: wrapped so a missing or malformed config file can never block
  or fail the real authorization gate above it - `_resolve_network_interface()`
  falls back to this project's own real, detected default NIC (`eno1`)
  when no `network_repaired` evidence exists yet in the journal.
- **Configurator artifact**: new "Export install-config.json" header
  button (`downloads` capability, with a copy-to-clipboard modal
  fallback when that capability is unavailable in a given view);
  `buildExportConfig()` walks every tab's live field values (including
  driver records and any AI-identified/custom field, filed into its
  real tab per the prior correction) into one JSON document. The two
  newly-wired driver toggles (`cpu_microcode`, `nic_wifi_firmware`) are
  now honestly marked `coded: true` with a codeRef naming the real
  apply path, instead of the previous `coded: false`.

## What this deliberately does not do

- Does not touch the ISO, ever, in any way - see above.
- Does not auto-create any VM - `vm_provision.py`'s functions stay
  unconnected; spinning up a guest unattended during firstboot was
  judged too consequential to wire without an explicit, separate ask.
- Does not apply GPU driver mode, `iperf3`, Proxmox Core
  (`datacenter.cfg`), or any AI-identified/custom field - none of those
  have a real apply function anywhere yet, and this change adds none;
  they remain honestly `coded: false` in the configurator.
- Does not build any live network path from the real machine back to
  the Artifact's own `db` store - the bridge is the exported file,
  placed by the operator, deliberately no more automatic than that.

## Verification performed

- RED confirmed first: `ModuleNotFoundError: No module named
  'config_pipeline'` before any implementation existed.
- 10 new unit tests: `test_config_pipeline.py` (6 - load/apply/skip/
  partial-failure-isolation/the explicit never-touches-ISO assertion)
  and `test_config_apply.py` additions (4 - the two new apply
  functions' success/failure/default-package-name paths) plus 4 new
  cases in `test_firstboot_statemachine.py` (a committed run applies an
  exported config; an already-completed run applies one exported
  afterward; a missing config file is skipped without error; a
  malformed config file never blocks or fails commit).
- Full suite: 802/802 passing (798 before the firstboot-wiring tests),
  no regressions.
- Not run against real hardware - no real `apt-get`/`ethtool`/
  `smartd.conf` write has ever actually happened via this code path.
