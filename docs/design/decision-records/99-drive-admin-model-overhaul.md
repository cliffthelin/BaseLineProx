# Decision record: Drive Administration model overhaul - self-installer only, real per-drive Baseline detection/repair, Hardware moved to its own tab

Status: **implemented and fully unit-tested (1497/1497 full suite),
verified live in the browser (including a real CSS bug found and
fixed). "Update selected"'s actual version-checking logic is an
honest, explicit placeholder - no real "newer version available"
source exists for any cached artifact yet.**

## What this resolves

Direct instruction, 2026-09-29, correcting the prior session's own
Drive Administration design on several fronts at once.

## "The only installer is a self installer"

Removed the `install` (human-override, bare persistence) and
`create_volumes_on_existing_vg` actions entirely - `build_self_installer`
is now the only installer action. `install_drive`/`create_baseline_volumes`
remain as real internal functions (still used by the new `repair`
action below), just no longer exposed as their own top-level actions.

## Real, per-drive Baseline detection + grouping + missing-volume listing

New `drive_admin.find_vg_for_device`/`detect_baseline_drive`: for each
real candidate drive, finds its own real LVM volume group (via `pvs`,
matched by prefix since a PV is usually a partition of the disk) and
runs `drive_installer.detect_existing_baseline_install` against it.
`is_baseline_drive` is true the moment *any* real Baseline volume is
found there (a genuinely partial install is still "a Baseline drive").
`list_candidate_drives` now sorts Baseline drives to the top; the web
page draws a "Baseline Installed" group heading above them, a green
"Baseline drive" pill on each card, and lists any real missing volumes
directly on the card.

## Repair - now real, not a v0.2 stub

`repair_scan_and_fix` is per-drive (`requires_device=True`): finds the
selected drive's real VG, and if incomplete, calls
`drive_installer.ensure_baseline_volumes` - which only ever creates
what's actually missing, never reformats or touches an existing
volume. Each missing volume `detect_baseline_drive` finds is the same
real, individually-listed validation failure shown on the drive card
itself - one real mechanism behind both.

## "Update selected" - real structure, honest placeholder for the check itself

New `check_cache_updates(runner) -> list`: returns a real empty list -
deliberately not a fabricated "checked, nothing available" per item.
No real update source is wired up for any cached artifact yet: the
curated Helper-Scripts in `vm_scripts.SCRIPT_MANIFEST` are deliberately
manually-pinned and reviewed (never auto-checked, by design - see
decision record 57), and the cached Proxmox source ISO / any distro
ISO has no version-tracking built at all yet. `update_selected` itself
refuses plainly ("update-checking is not implemented yet...") rather
than claim a check that never ran. The real, structural parts direct
instruction asked for ARE built: the action only shows when a Baseline
drive is selected (client-side, toggled off `driveList`'s own
`is_baseline_drive`, itself server-rendered as `hidden` by default so
a JS failure fails safe-closed, not open), and the volume table has a
real per-row checkbox plus a header "select all" checkbox.

**Real, previously-existing capability now orphaned - flagged, not
silently dropped**: `apply_volume_mode`/`switch_persona` (real, tested
functions - mount-mode enforcement, persona switching) were the old
`update_selected`'s actual behavior. They have no web-UI entry point
at all now that `update_selected` means something else. Not rebuilt
this pass since the direct instruction didn't ask for it back - flagged
here so it isn't mistaken for dead code by accident later.

## Hardware moved to its own tab

New `/hardware` nav tab (`real_hardware_state`/`render_hardware_page`):
shows `dependencies.run_checks(ADHOC)` results plus real
`diagnostics.collect_sensors`/`collect_nvme`/`collect_smart` output
directly on page load - no button, no action, matching direct
instruction ("Health check should just show... it reports on
hardware"). `run_health_check` is no longer a Drive Administration
`ActionSpec` entry. Verified live: real CPU/RAM/NVMe temperatures from
this actual machine's sensors, a real per-device SMART listing, and an
honest "Not available" for `nvme-cli` (not installed on this machine).

## Real bug found and fixed while verifying live

`.action-card { display: flex }` overrode the native `[hidden]`
attribute's own default `display: none` - equal CSS specificity
(class selector vs. attribute selector), author style wins over the
UA stylesheet regardless. The `update_selected` card had `hidden=true`
set correctly in the DOM but was still visually showing
(`offsetParent !== null` when checked live). Fixed with an explicit
`.action-card[hidden] { display: none; }` rule; a new regression test
(`test_render_drive_admin_page_css_actually_hides_a_hidden_action_card`)
asserts the rule's own presence in the rendered page, and the fix was
independently confirmed live via `getComputedStyle` before and after.

## Files changed

- `baseline/lib/drive_admin.py` - `install`/`create_volumes_on_existing_vg`
  actions removed; `find_vg_for_device`, `detect_baseline_drive`,
  `check_cache_updates` added; `repair_scan_and_fix`/`update_selected`
  rewritten for the new real semantics; `list_candidate_drives` sorts
  Baseline drives first and attaches `is_baseline_drive`/`vg_name`/
  `missing_baseline_volumes` per drive; dead `UPDATABLE_VOLUME_LABELS`
  constant removed.
- `baseline/lib/baseline_web.py` - drive cards grouped/pilled/annotated;
  volume table gained a "select all" checkbox; `update_selected`
  action card hidden by default, revealed by JS only for a selected
  Baseline drive; new `real_hardware_state`/`render_hardware_page`;
  new `/hardware` route and nav tab; the `.action-card[hidden]` CSS fix.
- Tests: `test_drive_admin.py` (new tests for `find_vg_for_device`/
  `detect_baseline_drive`/`repair_scan_and_fix`/`check_cache_updates`/
  `update_selected`; obsolete `create_volumes_on_existing_vg`/old
  `update_selected` tests removed), `test_baseline_web.py` (new tests
  for grouping, the pill, missing-volume display, the hidden-card CSS
  bug, and the new Hardware tab).

## Verification performed

- Full suite: 1497/1497 (was 1485 before this record's own changes).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- Live browser verification: real drive list (13 real drives, none
  currently a Baseline drive - correctly no "Baseline Installed" group
  shown); `update_selected` card confirmed genuinely hidden via
  `getComputedStyle`/`offsetParent`, then confirmed it reveals when a
  simulated Baseline-drive selection is made; `/hardware` tab shows
  real live sensor/SMART data and real dependency-check results with
  no action/button.

## Not done, flagged honestly

- No real "is a newer version available" check exists for any cached
  artifact - `update_selected` cannot actually apply anything yet.
- The 7 downloaded distro ISOs (`~/.ubuntu26-usb/`) still have not been
  copied into any real INSTALLER_CACHE - pending the `/dev/sdd`
  wipe-and-rebuild this record's own work was done in service of.
- `apply_volume_mode`/`switch_persona` have no web-UI entry point.
