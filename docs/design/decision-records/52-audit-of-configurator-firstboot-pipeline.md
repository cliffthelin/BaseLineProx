# Decision record: audit of the configurator->firstboot config pipeline (decision record 51)

Status: **three real defects found and fixed, with tests added first
for each. 804/804 suite passing.** Not run against real hardware -
same standing constraint as everything else this session.

## What was asked

Direct instruction, immediately after decision record 51 landed:
*"Audit this concept and how it implemented."* Read as: re-verify the
just-completed work against the actual code and tests, not against my
own description of it - the same discipline this session's earlier
"full walkthrough inventory" already established, applied to work from
the same session rather than assuming recency makes it correct.

## Method

Re-read `config_pipeline.py`, `config_apply.py`'s two new functions,
`firstboot_statemachine.py`'s wiring, and the configurator's export
logic directly - cross-checked field-id naming with a real diff
between the HTML's `F("proxmox"/"drivers", ...)` ids and
`config_pipeline.py`'s own key constants (exact match, no drift), and
scanned every `type:"select"` field in the configurator for a missing
`options` array (a real, silent, one-and-done bug class - a select
with no options renders as an empty, unusable dropdown, and nothing
in HTML review catches it visually until it's opened).

## Findings

1. **Non-interactive apt-get missing.** `apply_cpu_microcode()` and
   `apply_wifi_firmware()` ran bare `apt-get install -y <pkg>`, unlike
   every other apt-get call in this codebase
   (`install_diagnostic_tools()`'s `env DEBIAN_FRONTEND=noninteractive
   apt-get install -y ...`). On real hardware this is a real risk of
   an unattended firstboot run hanging on a debconf prompt (microcode
   packages and firmware packages both can trigger one). **Fixed**:
   both functions now use the same `env DEBIAN_FRONTEND=noninteractive`
   prefix.

2. **`ethtool_interface` silently discarded.** The configurator has a
   real field for which interface ethtool settings apply to, but
   `apply_stored_config()` never read `proxmox["ethtool_interface"]` -
   it always used whatever `network_interface` the caller passed
   (resolved from the firstboot journal or a hardcoded default). The
   operator's own selection in the form was never actually consulted.
   **Fixed**: the config's own `ethtool_interface` now wins whenever
   it's set; `network_interface` is only the fallback for a config
   that omits it - `test_apply_stored_config_uses_the_configs_own_ethtool_interface_over_the_fallback`
   and its sibling fallback test lock this in.

3. **Two `<select>` fields with no options - one of them also never
   consumed.** `ethtool_interface` and `smartmontools_device` were
   both `type:"select"` with no `options` array anywhere in their
   definition - a select with zero options renders as an empty,
   unusable dropdown; this is exactly the kind of bug a config review
   form should never itself have. Separately, `smartmontools_device`
   turned out to be entirely disconnected from the real apply path:
   `config_apply.build_smartd_conf()` always emits one `DEVICESCAN`
   line covering every device - it never reads a per-device path at
   all, so this field did nothing even before the options bug.
   **Fixed**: both converted to plain text fields with real defaults
   (`eno1` for the interface, matching this session's own real NIC
   detection; `"all devices (DEVICESCAN)"` for the device field, with
   an honest description and `coded: false` since nothing consumes it).

## What was NOT found to be broken (checked, not assumed)

- Field-id naming between the HTML and `config_pipeline.py`'s
  `_SMARTD_KEYS`/`_ETHTOOL_KEYS`/`drivers.get(...)` calls: verified by
  direct extraction and diff, exact match, no drift.
- Subsystem independence (`smartd`/`ethtool`/`cpu_microcode`/
  `wifi_firmware` each skip or fail without affecting the others):
  already covered by decision record 51's own tests; re-verified by
  re-reading `run_subsystem()`'s implementation directly.
- The never-touches-the-ISO invariant: re-confirmed by re-reading
  `config_pipeline.py`'s and `config_apply.py`'s full argv/path
  surface - nothing takes or constructs an ISO path anywhere in either
  module.
- `apt-get`'s lack of a lock-retry/wait mechanism is a real,
  pre-existing limitation shared by every apt-get caller in this
  codebase (including the original five-tool installer) - not a
  regression introduced by decision record 51, and out of scope for
  this audit to fix on its own.

## Verification performed

- RED confirmed for the two `ethtool_interface` tests before the fix
  (`test_apply_stored_config_uses_the_configs_own_ethtool_interface_over_the_fallback`
  failed with the operator's interface silently dropped, as expected).
- Every existing test asserting the old bare-`apt-get` argv shape was
  a real behavioral assertion, not incidental - each was updated
  deliberately, not loosened, to assert the corrected noninteractive
  argv.
- Full suite: 804/804 passing (802 before this audit's two new tests),
  no regressions.
