# Decision record: the Admin settings tab - a real web surface over settings_store.py

Status: **implemented and tested (1194/1194 suite passing, up from
1176 after decision record 79). Not run against real hardware.**

## What this closes

Work-queue item 28: "Settings-tab web/TUI surface exposing
`settings_store.py` (Admin sub-tab + groups; auto-start-drive;
per-volume read-only/write-only/read-write mode) - 'essentially a
version of the installer web application used for install and
update.'" Its stated blocker was "deciding web vs TUI vs both, and on
the full settings taxonomy beyond the seed schema already built."

## The web-vs-TUI decision was already made

The direct instruction that created this item said so explicitly:
"Make this a setting on Baseline in a settings tab and sub tab of
Admin... **Essentially a version of the installer Web application**
used for install and update." `settings_web.py` already *is* that
installer web application (PRD SS5.16) - building the Admin tab as a
new page on it, rather than inventing a parallel TUI surface or a
third framework, follows the instruction's own words directly. The TUI
(`bin/baseline`) stays free to grow its own Admin view later if wanted
- nothing here forecloses that - but it was never the piece asked for
by name.

## What was built

**`settings_store.py`**: extended `SCHEMA` with the `volumes` group -
`baseline_mode`/`installer_cache_mode`/`session_temp_mode`, one per
`drive_installer.SHARED_VOLUMES` label, defaulting to `"read-write"` -
the real "per-volume read-only/write-only/read-write mode" setting
item 28 named. **Storage only** - wiring an effective value here into
`drive_installer.py`'s actual mount behavior is a separate, deferred
integration step, matching `FileBackedSectionApplier`'s own existing
"saved here, real application is a follow-up integration" precedent
for the older `KNOWN_SECTIONS` surface. `startup.auto_start_persona`
(the "drive to auto start on startup" item 28 also named) already
existed from decision record 76 - this pass gave it a real page to
live on, not new storage.

**`settings_web.py`**: three new route handlers -
`handle_admin_view` (session-gated, reads
`settings_store.all_effective_settings`), `handle_admin_elevate`
(session-gated, calls `admin_elevation.attempt_elevation` with an
injected verifier), `handle_admin_edit` (session-gated, additionally
requires a real, currently-live `admin_elevation` ticket via
`admin_elevation.require_elevation` before calling
`settings_store.set_setting` - never on session alone). Deliberately
separate from the pre-existing `handle_settings_view`/`_edit`'s flat
`KNOWN_SECTIONS` model (network/firewall/tether/...) - different
store, different data, not two doors onto the same one.

Gating edits behind a real elevation ticket (not just a valid login)
follows directly from decision record 76's own design: these settings
are cross-persona-consequential (auto-start-persona, session TTLs
affecting every persona, per-volume mode), matching admin's own
"essentially sudo or root" model. Viewing is allowed on a valid
session alone, matching every other settings page on this surface.

New real routes: `GET /admin` (renders every group/setting, an
elevation-passphrase form when not yet elevated), `POST
/admin/elevate`, `POST /admin/settings/<group>/<key>`. New real default
implementations: `FileBackedElevationVerifier` (a separate
`elevation_password_hash` field in the same `JsonFileStore`, seeded to
a DEV-ONLY `"baseline-admin"` passphrase - deliberately different from
the login password `"baseline"`, per decision record 76's own "a
SEPARATE, additional passphrase" requirement). `build_real_server`
now accepts and wires a real `runner` (shared with the persona
provider from decision record 78) and the real elevation verifier;
`SettingsWebServer.deps` gained `runner`/`elevation_store`/
`elevation_verify_fn`, all optional and safely handed-off (never
crashing) when absent, so every pre-existing call site is unaffected.

## A real gap the checker caught while wiring this in

`tools/check_provision_deploys_all_imports.py` failed immediately
after `settings_web.py` gained real `import settings_store`/`import
admin_elevation` calls: **neither module had ever been staged in
`provision.sh` at all**, since decision record 76 built them without a
staged caller yet. Fixed by staging both alongside `settings_web.py`
itself. The exact same class of gap this same checker caught for
`stream_json.py` earlier this session - the checker is doing its job.

## What this does not do

Does not wire `volumes.*_mode` into `drive_installer.py`'s real mount
behavior - storage only, explicitly deferred (see above). Does not
build a TUI Admin view - the instruction named the web surface
specifically; the TUI stays open for later if wanted. Does not add
per-field type/choice validation to `settings_store.set_setting` (e.g.
refusing a `volumes.baseline_mode` value outside the three named
strings) - the existing mechanism validates only that the `(group,
key)` pair is known, unchanged from decision record 76; tighter
per-field validation is a bounded, real future improvement, not built
here. Does not run against real hardware.

## Verification performed

- `settings_store.py`: 2 new tests (the `volumes` group's three keys
  exist and default to `"read-write"`; `group_names()` includes
  `"volumes"`) - all 12 pre-existing tests pass unchanged.
- `settings_web.py`: 17 new tests - `handle_admin_view`/
  `handle_admin_elevate`/`handle_admin_edit`'s session/hand-off/refusal/
  success paths (11), `FileBackedElevationVerifier`'s real
  sha512crypt round trip and its refusal when unconfigured (2),
  `build_real_server`'s real wiring of `runner`/`elevation_verify_fn`/
  `elevation_store` (3), `render_admin_page`'s real smoke test for both
  the elevated and not-yet-elevated cases (2) - all 31 pre-existing
  tests pass unchanged.
- `tools/check_provision_deploys_all_imports.py`: found and fixed a
  real, pre-existing gap (see above); zero gaps after the fix.
- `bash -n boot/provision.sh`: valid syntax.
- Full suite: 1194/1194 passing, no regressions.
