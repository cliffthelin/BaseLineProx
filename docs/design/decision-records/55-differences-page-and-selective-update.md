# Decision record: DIFFERENCES page, auto-detection, and a selective Update action

Status: **implemented. Backend (drive_installer.detect_existing_baseline_install,
config_diff.py, update_pipeline.py, baseline-diff, baseline-update) is
real, unit-tested (835/835 suite passing), and smoke-tested end to end
against this real dev machine's own ethtool/dpkg-query/lvs. The two
configurator-side pieces (the Update modal, the DIFFERENCES artifact)
are real, working browser code, not yet connected to a live target -
same standing bridge-via-export pattern as every other configurator
feature this session.** Not run against real target hardware.

## What was asked

Direct instruction: *"The installer need the actions to install or
update an existing drive and the ability to auto detect that drive and
then check for each of the install points and configurations and able
to highlight the changes that should show on a single page named
DIFFERENCES. The update action should have its own page or modal and
should also allow applying only code updates and or DRIVERS and or
Applications AND or OS installs AND or only update configs note
configs should be select-able as update or not update in any
combination."*

## Auto-detection

`drive_installer.detect_existing_baseline_install()` reuses
`ensure_volume()`'s own `lvs` parsing rather than inventing a second
detection mechanism that could drift out of sync with it - it checks
whether all three `BASELINE_VOLUMES` already exist on the target VG.
A partial state (some but not all volumes present) is reported
honestly rather than rounded up or blocked - `ensure_baseline_volumes()`
already creates whatever's missing regardless of this function's own
answer.

## Checking every install point/configuration - config_diff.py

Scoped to what actually has a real apply function today
(`config_apply.py`'s four subsystems - smartd, ethtool, and the two
driver packages), not invented for settings nothing can apply yet.
Real read-back, not guessed: the `smartd.conf` parser is an exact
reverse of `build_smartd_conf()`'s own fixed format (a real,
deterministic round-trip since that function is the only code that
ever writes the file); the `ethtool` parser matches the real, standard
output shape of `ethtool`/`ethtool -k`/`ethtool -a` - verified against
this dev machine's own real NIC during smoke-testing, not just a
synthetic fixture. `diff_config()` is a pure current-vs-desired
comparison; `compute_full_diff()` assembles one section per real
subsystem into the report `baseline-diff` prints.

## The Update action - update_pipeline.py, real category selection

`apply_selective_update()` takes `categories` with any combination of
`code`, `drivers`, `applications`, `os` (booleans) and `configs`
(`True`/`False`/a list of specific field names). Checked against the
actual codebase before wiring anything: `code` (updating Baseline's
own software), `applications` (the five diagnostic tools + kiosk,
confirmed by decision record 53's own audit to be installed
unconditionally, never selectively), and `os` (VM creation via
`vm_provision.py`) have NO real apply mechanism anywhere in this
project yet. Selecting one of those three is real - recorded in the
summary's `not_available` list - applying it is not, and this module
says so rather than silently doing nothing.

**"Configs... selectable as update or not update in any combination"**
required real thought, not just a boolean per field: `smartd.conf` is
a whole-file rewrite, so simply omitting an unselected field from the
dict handed to `build_smartd_conf()` would reset it to absent/off, not
leave it alone. The fix: an unselected field is read back from the
target's own CURRENT state via `config_diff.py` and merged in before
the real apply function runs, so a partial selection genuinely
preserves everything not chosen - proven directly by
`test_configs_partial_selection_preserves_unselected_fields_from_the_targets_current_state`.

## The two real CLI bridges

`baseline-diff --config install-config.json` runs the auto-detection
and the full diff report against the live system it's invoked on,
printing one JSON document. `baseline-update --config ... --selection
update-selection.json` applies exactly what `apply_selective_update()`
resolves. Both were smoke-tested for real on this dev machine (not
just against fakes): `baseline-diff` correctly read this machine's
real 1000Mb/s ethtool speed and its already-installed amd64-microcode
package, and handled a real `lvs` permission-denied error (non-root)
gracefully instead of crashing; `baseline-update` correctly reported
`not_available`/`skipped` for an all-off selection with zero real
commands attempted.

## The DIFFERENCES page and the Update modal

**DIFFERENCES** is its own new artifact
(`baseline-differences.html`) - a single page, as asked. It takes the
pasted JSON `baseline-diff` produces (there is no live bridge from a
browser artifact to a real target, so the operator runs the real
command and pastes its output, the same export/paste bridge this
session's other configurator features already use) and renders
install-detection status plus every subsystem's fields, changed ones
highlighted, unchanged ones shown too so the report is honestly
complete rather than only listing differences.

**The Update action** got its own modal inside the existing
configurator (the "page or modal" instruction's other option) rather
than a separate page, since it's an action tightly coupled to the
configurator's own field definitions - its config-field checklist is
generated directly from the same `FIELDS` array the rest of the tool
uses, so it can never drift out of sync with what the configurator
actually tracks. Five category toggles (Code/Drivers/Applications/OS
disabled with "not available" shown plainly; Configs real), and when
Configs is on, every real smartd_/ethtool_ field gets its own
checkbox - true "any combination," with Select all/Select none
shortcuts. Exports `update-selection.json` via the same `downloads`
capability pattern as `install-config.json`, for `baseline-update` to
consume.

## Verification performed

- RED confirmed first for every new function across all three modules
  (`detect_existing_baseline_install`, every `config_diff.py`
  function, `apply_selective_update`) before any implementation
  existed.
- 23 new backend tests, all passing on first real implementation
  attempt for `config_diff.py` and `update_pipeline.py` (the smartd
  round-trip and ethtool parser format were both derived from this
  project's own real, controlled output format / real documented tool
  output, not guessed).
- Both new CLI scripts smoke-tested by direct invocation against this
  real dev machine - not just FakeRunner tests - confirming the real
  `ethtool`/`dpkg-query`/`lvs` parsing actually works against real
  command output, and that a real permission error is handled
  gracefully.
- Full suite: 835/835 passing (812 before this change), no
  regressions.
- Configurator/DIFFERENCES HTML changes verified by direct JS syntax
  check (`node --check`) and the standing select-with-no-options scan
  before each publish.
