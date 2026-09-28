# Decision record: self-installer is the default, keyboard-free path; "Install" is a demoted human-override

Status: **implemented, unit-tested (1348/1348 full suite, up from 1339).**

## What was asked

Direct feedback, in sequence, on the same web-app session:

1. "Shouldn't the self installer do all of that and just finish the install from the pre-populated data added to the User Persistence? In general there should not be a version that is not a self installed. The non-self install should only be for human override."
2. "I will never fill in a serial number you are not allowed a user to do so. Everything you asked me to do must be selectable without a keyboard."
3. "You should make the user data file that preconfigures these items from selectable options in the Web App. This is the first and primary thing user persistence does. It stores all configuration for the Machine."
4. "Nothing configuration wise not in user persistence is required to survive reboot after system is in place."

## The real bug this also explains

"I typed my sudo password in to the install option and nothing happened." Investigating: the web app's own JS (`baseline_web.py`'s `driveAdminModalConfirm` handler) only ever sends `device_path` for `build_self_installer` - there was never a form field anywhere in this app for `expected_serial`, `proxmox_source_iso`, `server_host`, `cert_path`, or `key_path`. But `drive_admin.build_self_installer()` (decision record 85) required all five via `params["..."]` - a bare `KeyError`, server-side, on every real click. Telling the user to "fill in" those fields in an earlier turn was itself wrong: the UI was never capable of collecting them. This was not a UI glitch, it was a real, load-bearing design mistake - the action's own required inputs did not match what its own front end could ever send.

## What was built

**`self_installer.py`** - `expected_serial`, `proxmox_source_iso`, `server_host`, `cert_path`, `key_path` are now all optional:
- `expected_serial` defaults to `None` (matches `physical_device_safety.validate_target_device`'s own existing "unrestricted" default) - the *safety gate* needs no serial. Separately, the real hardware serial of whichever drive was clicked is now always read via `pds.get_device_serial` for the answer-file's own disk-targeting field (`filter.ID_SERIAL_SHORT`) - refuses clearly (`"reports no hardware serial"`) rather than embedding `None` into an answer file if a device genuinely can't report one.
- `cert_path`/`key_path` default to `None` -> a fresh self-signed 1-day TLS cert is generated on the fly (`_generate_ephemeral_cert`, real `openssl req -x509`) into the workspace. No human ever runs openssl or pastes a path.
- `server_host` defaults to `DEFAULT_SERVER_HOST = "10.0.2.2"` - the QEMU SLIRP host-proxy gateway, the only address this mechanism could ever actually need, since the installer is always QEMU-launched.
- `proxmox_source_iso` defaults to `None` -> auto-located via `_locate_proxmox_source_iso` against `DEFAULT_SOURCE_ISO_SEARCH_PATHS` (real, conventional INSTALLER_CACHE-style paths); refuses clearly, listing the paths it checked, if none is found - never silently guesses.
- New `LVM_SIZE_PRESETS` dict (`small`/`medium`/`large`) - the same three options `settings_store.py`'s new schema entry exposes as a dropdown.

**`settings_store.py`** - the actual "pre-populated data" mechanism (point 3 above), reusing the existing schema/group storage built for the Admin tab (decision record 80) rather than inventing a parallel config file:
- `SettingDef` gained an `options: tuple | None` field. `set_setting` now refuses any value not in a setting's own `options` when defined - the enforcement point for "everything must be selectable, never typed," not just a UI nicety.
- New `"self_installer"` group: `lvm_size_preset` (small/medium/large), `fqdn` (3 real presets), `memory_mb` (4 real presets) - every one enum-constrained.
- `DEFAULT_STORE_PATH` moved from `/mnt/BASELINE/settings/master_config.json` to `/etc/baseline/settings/master_config.json` - point 4 above ("nothing configuration-wise not in User Persistence is required to survive reboot"): `/etc/baseline` is already bind-redirected onto USER_PERSISTENCE for the active persona (`persist_bind_mounts.py`'s existing table), so this reuses that redirect rather than adding a new bind target. Every Admin-tab setting (sessions, startup, volumes, and now self_installer) is durable across a disposable-stage rebuild as of this record, not just the new group.

**`settings_web.py`** - `render_admin_page` no longer hardcodes which keys get a dropdown (`volume_mode_keys`/`volume_mode_options`); it now looks up `options` from `settings_store.SCHEMA` generically for every group/key, so the new `self_installer` settings get real `<select>` controls with zero new rendering code, and any future enum-constrained setting gets one automatically just by declaring `options=`.

**`drive_admin.build_self_installer()`** - now needs nothing from a caller but `device_path`. Reads `lvm_size_preset`/`fqdn`/`memory_mb` from `settings_store.get_setting` (a plain unauthenticated `RealRunner` read - these are non-secret presets, not credentials) and passes everything else through as `None`, letting `self_installer.py`'s own defaults/auto-derivation resolve it. Every value remains overridable via `params` for a genuine programmatic/advanced caller - the web UI simply never renders a text field for any of them.

**`ACTIONS` ordering and framing** - `build_self_installer` is now listed first (point 1: "should not be a version that is not a self installed"); `install`'s description now opens with `"HUMAN OVERRIDE ONLY - not the normal path (use Build Self Installer instead)"` and clarifies it produces persistence only, no bootloader, no OS. Not removed - a human who genuinely wants bare persistence with no OS still can - but no longer presented as a parallel, equally-weighted first-class option.

## Verification performed

- RED confirmed for the new refusal paths (missing serial, missing source ISO) before the corresponding auto-derivation/auto-locate code existed.
- New tests: `test_self_installer.py` (no-hardware-serial refusal, self-generated-cert-doesn't-crash, no-source-ISO-found refusal, `DEFAULT_SERVER_HOST` value), `test_settings_store.py` (`self_installer` group shape, `options` enforcement both ways, unconstrained settings still accept anything, store path assertion updated), `test_drive_admin.py` (`build_self_installer` reaches the real safety gate cleanly with only `device_path` - the actual "I typed my password and nothing happened" case, now proven not to `KeyError`).
- Full suite: 1348/1348 (1339 before this record).
- **Not verified**: no real click-through of the corrected `build_self_installer` action against physical hardware yet in this pass - the KeyError this record fixes was found by code inspection of what the JS actually sends versus what the server required, not by re-running the failed click.
