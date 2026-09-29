# Session handoff - moving to the "Baseline" Claude Project

## 2026-09-28 continuation - roadmap cleanup: v0.1 queue corrected, v0.2 queue started

Asked "where is the roadmap completion" - found `docs/design/v0.1-work-queue.md` stale and self-contradicting: row 29 claimed "v0.1 queue fully closed" while row 17 was still `[ ]` in the same table, and nothing since decision record 82 (everything from records 83-93 this session built) was tracked anywhere.

Fixed:
- Row 17 closed with an honest caveat - `/dev/sdd`'s real, complete install is confirmed by direct inspection (partition table, `pve` VG, two provisioned VMs, live boot to Proxmox's web-UI login), but which of several real-hardware attempts across sessions actually produced it can't be confirmed from disk state alone.
- Row 29's inaccurate "fully closed" claim removed.
- New `docs/design/v0.2-work-queue.md`: backfilled with decision records 83-93 as closed items, plus two new open items - confirming which tool produced `/dev/sdd`'s current install, and a direct suggestion to evaluate a read-only QCOW2 base + copy-on-write overlay layered on Proxmox for zero-risk experimentation/instant rollback (not yet scoped against this project's own already-disposable BASELINE/root design), and v0.1's still-outstanding item 18 (homeassistant-lxc/haos-vm under real QEMU) carried forward.

## 2026-09-28 continuation - QEMU disposable-install smoke test finds a real, would-have-shipped bug

**Read decision record 93 first** (`docs/design/decision-records/93-qemu-smoke-test-for-settings-migration.md`).

Asked to run the QEMU disposable-install smoke test against the settings-to-SQL migration changes. Found a real bug on the first attempt: `self_installer.ANSWER_TEMPLATE` rendered `lvm.maxroot`/`maxvz`/`swapsize` as quoted strings (`"40G"`), but Proxmox's real answer-file schema requires them as plain numbers - a hard TOML parse error (`invalid type: string "40G", expected f64`) that would have failed **every** real self-installer run, on real hardware or under QEMU. No unit test ever caught this because they all mock the assistant binary and never validate the rendered TOML against its real parser.

Fixed: `ANSWER_TEMPLATE` unquoted, `LVM_SIZE_PRESETS` changed from `"20G"`/`"40G"`/`"80G"`-style strings to plain ints. New test actually parses the rendered template with `tomllib` and asserts real numeric types - not a string match, a genuine schema-shaped check.

Re-ran the real QEMU install end-to-end: real pre-install dependency gate → real settings resolved from the real database (`export_bootstrap_snapshot`) → valid answer.toml → real Proxmox install (watched package extraction 60%→99%) → hit the known decision-record-04 reboot-loop trap (caught a throwaway driver-script polling gap that let it reinstall once before recovering) → real post-install boot → **`baseline login:`**, the exact `fqdn` value that came from the real database three steps earlier. Direct, literal, first-hand proof the whole migrated chain works.

Full suite: 1422/1422 (was 1420). Disposable QEMU artifacts (8.3GB disk image, 1.6GB ISO) deleted after verification.

**Separate finding, not yet acted on**: while working, noticed a QEMU process has been running against the real `/dev/sdd` since Sep 26 (`-smbios type=1,product=baseline-real-sdd`, VNC display active) - looks like a leftover, possibly-abandoned real self-installer attempt from an earlier session still holding that physical drive open. Not touched or killed - flagged for the user to check, since it's real hardware and not something to act on unilaterally.

## 2026-09-28 continuation - real /etc/baseline confirms the PROTECTED-scope path end-to-end

**Read decision record 92** (`docs/design/decision-records/92-etc-baseline-production-verification.md`) - closes decision record 91's one open item.

User ran `sudo mkdir -p /etc/baseline/settings && sudo chown -R "$USER":"$USER" /etc/baseline` themselves (I have no passwordless sudo and won't handle a password). Re-ran `drive_admin.run_health_check(None)` for real: all 4 seed dependencies now pass, including the two PROTECTED-scope ones that previously failed gracefully for lack of this directory. Inspected both real database files directly - confirmed the GLOBAL/PROTECTED split is genuinely happening as designed: dependency definitions/results live in `/mnt/BASELINE/registry/foundation.db` (GLOBAL), the settings they check live in `/etc/baseline/settings/master_config.db` (PROTECTED). Full suite unchanged at 1420/1420 (this was a real-environment verification, not a code change).

The settings-to-SQL migration (decision records 87-92) is now complete, verified end-to-end on real hardware, not just under test isolation.

## 2026-09-28 continuation - completed the settings-to-SQL migration (6-item queue)

**Read decision record 91 first** (`docs/design/decision-records/91-settings-migration-completion.md`).

Asked "what further steps are needed to complete the settings to SQL migration" - answered with a prioritized 6-item list, then told "they all need fixed, just queue them up and resolve them." Did all six:

1. `registry.py` gained real schema versioning (`PRAGMA user_version`, `register_migration`) - scaffolding for a future table change, no migration needed yet since only version 1 has ever shipped.
2. `settings_store.export_bootstrap_snapshot` (built in decision record 87, never called) is now actually used by `drive_admin.build_self_installer`.
3. `netpref.py`'s `network_preference.json` moved onto `settings_store.py` (new `"network"` group) - the first real external use of `register_schema` outside its own seed data. Had zero test coverage before; now has 5 tests.
4. `network.py`'s `interface_aliases.json` moved onto `registry.py` **directly**, not through `settings_store.py` - a dynamic, hardware-dependent key space doesn't fit a fixed schema. Had zero test coverage before; now has 7 tests.
5. `install-config.json` (config_pipeline.py/control_panel_web.py/backup_restore.py) reviewed and deliberately **not** migrated - it's an external tool's export format, read/diffed/backed-up as a file by design; forcing it onto the registry would break the real workflow.
6. `settings_web.py`'s `JsonFileStore` renamed to `LocalAppStore`, rewritten onto SQLite, same public API - deliberately **not** routed through registry.py's GLOBAL/PROTECTED scope, since it's reused by multiple independently-deployed local apps (settings_web's own standalone server, scripts_inbox_web's separate store) each at its own injected path; forcing it onto fixed machine-wide paths would break the "no root, no install required" standalone-evaluation property it exists for.

Also, surfaced while building #6: the Admin tab had zero visibility into dependencies/health-check results - `dump_configuration_snapshot()` existed but nothing in the UI called it. `handle_admin_view`/`render_admin_page` now show every dependency and its latest result, read-only (never triggers a run itself - that's the adhoc action's job).

**One item explicitly not done**: production-equivalent verification (confirming the PROTECTED-scope checks pass, not just fail gracefully, against a real root-owned `/etc/baseline`) - closing this means creating that directory on this real machine, a system-level action outside the repo that needs to be asked for separately, not folded into a broad "resolve everything" instruction.

Full suite: 1420/1420 (was 1414).

## 2026-09-28 continuation - ran run_health_check for real, found and fixed two real GLOBAL/PROTECTED bugs

**Read decision record 90 first** (`docs/design/decision-records/90-health-check-real-run-fixes.md`).

Direct instruction: "Run the health check action for real and fix anything issues found." Ran `drive_admin.run_health_check(None)` for real on this sandbox (non-root, no `/etc/baseline`/`/mnt/BASELINE` yet) - it crashed outright with `PermissionError: /etc/baseline`. Two real bugs, both only visible by actually executing the code:

1. `registry.register_type` wrote into BOTH physical databases unconditionally "for discoverability" - meaning a purely GLOBAL type (dependencies.py) could never even register itself on a machine where PROTECTED isn't reachable, defeating the whole point of GLOBAL existing independent of USER_PERSISTENCE.
2. Both `settings_store._sync_definition` and `dependencies._sync_definition` hardcoded a fixed scope for `register_type` regardless of which entry was actually being synced - so reading the GLOBAL `startup.auto_start_persona` setting still tried to reach PROTECTED just to register the type's description, and would fail exactly when that setting is supposed to survive a broken USER_PERSISTENCE.

Fixed both (register only into the scope actually being used; pass each entry's own `d.scope`, never a hardcoded default). After the fix, the same real run no longer crashes: GLOBAL checks (sqlite3, openssl) pass; PROTECTED checks (self_installer settings) fail gracefully with a clear message on this non-root sandbox lacking `/etc/baseline` - expected, since real Baseline services already run as root. Three new regression tests prove the actual guarantee (GLOBAL never depends on PROTECTED being reachable), not just the absence of a crash on this one machine.

Full suite: 1394/1394 (was 1391).

**Not done:** the PROTECTED-scope checks haven't been verified to actually pass end-to-end in a root/production-equivalent environment - only that they now fail gracefully instead of crashing when `/etc/baseline` doesn't exist. Creating that directory on this real machine would mean touching root-owned system paths outside the repo - not done without asking first.

## 2026-09-28 continuation - one foundational registry (registry.py), not a table per registry type

**Read decision record 89 first** (`docs/design/decision-records/89-foundational-registry.md`).

Direct, corrective instruction: settings_store.py (decision record 87) and dependencies.py (decision record 88) had each grown their own bespoke table - exactly the pattern that doesn't scale to "potentially thousands of registries and hundreds of varying registry types." Built `baseline/lib/registry.py`: three generic tables (`registry_types`, `registry_entries`, `registry_events`) reused by every registry type forever. Migrated both existing modules onto it with their public APIs unchanged in shape.

**Scope is real now, per-entry**: GLOBAL resolves to `/mnt/BASELINE/registry/foundation.db` (the shared, non-persona volume - reachable during recovery even when a specific persona's USER_PERSISTENCE is broken); PROTECTED resolves to the existing USER_PERSISTENCE-redirected database. `startup.auto_start_persona` is now GLOBAL (recovery needs to know which persona to try mounting without asking the very volume that might be broken); `dependencies.Dependency` defaults to GLOBAL entirely (health checks must survive diagnosing a broken USER_PERSISTENCE).

**Concurrency concern addressed directly, with a real test, not just words**: the user pushed back hard on SQLite given the earlier lock-contention bug ("If SQLite can't handle multiple threads of calls its not a long term solution" / "multithreading is a must"). Clarified the earlier bug was this codebase's own mistake (a nested connection opened while another held an uncommitted write transaction), not a SQLite limitation - WAL mode's real guarantee is unlimited concurrent readers, never blocked by each other or a writer. Added `tests/unit/test_registry.py::test_many_concurrent_readers_never_block_or_corrupt_a_read` and `test_concurrent_readers_alongside_a_writer_never_crash_or_corrupt_state`, both firing real concurrent load from a thread pool - proven, not asserted. Also added an explicit `PRAGMA busy_timeout=5000` so a genuine writer-vs-writer collision waits and retries instead of failing instantly.

**Also**: "Don't make caps of the number things pre a v1" - relaxed `drive_admin.ACTIONS`' "exactly N actions" test (already widened twice) to a subset assertion; avoid this pattern going forward for anything expected to keep growing.

**Real near-miss caught before it shipped**: the first draft called `registry.register_type()` at `settings_store.py`'s module *import* time - would have caused real I/O against `/etc/baseline`/`/mnt/BASELINE` before any test's isolation fixture ran (the exact same class of bug as decision record 88's lock contention, just at import time instead of at runtime). Caught in review, fixed by moving registration into the lazy `_sync_definition` path.

Full suite: 1391/1391 (was 1376).

**Not done:** no real deployment has exercised the GLOBAL/PROTECTED split against an actually-broken persona's USER_PERSISTENCE yet - correct by construction and unit-tested for isolation, not yet observed on real, failed hardware.

## 2026-09-28 continuation - real dependencies table + health-validation layer (pre_install/boot/interval/adhoc)

**Read decision record 88 first** (`docs/design/decision-records/88-dependencies-table.md`).

Direct instruction: a dependencies table recording system/install/(future) other-level dependencies, "predefined and validated before install begins and as health validations both at boot and intervals and adhoc calls," with an explicit loud-vs-silent severity distinction, surfaced for troubleshooting. Built `baseline/lib/dependencies.py` - two new tables (`dependencies`, `dependency_check_results`) in the same primary database `settings_store.py` uses (confirmed a Baseline SQLite already existed - `sensors_history.db` - but that's telemetry, a different domain; kept config+dependencies together in `master_config.db`). Wired into all four phases:

- **pre_install**: `drive_admin.build_self_installer` refuses outright on any LOUD dependency failure, before the pipeline starts.
- **boot**: `persist_bind_mounts.main()` runs checks and prints results, purely observational - never blocks boot.
- **interval**: new `baseline-dependency-check.timer`/`.service` (15 min), mirroring `baseline-backup-recurring`'s existing pattern.
- **adhoc**: new `run_health_check` drive-admin action (a fifth action - broke the "exactly four actions" test from decision record 86, same pattern as before: flagged directly, updated the test with a docstring, did not silently change it).

Also, mid-turn: "Credentials and Tokens and such should just have references to their Vault location" - `settings_store.SettingDef` gained `is_secret_ref`, enforced by `set_setting` (must start with `vault://` or similar). No vault backend exists yet; this is the guardrail that keeps a future one honest.

**Real bug found and fixed in passing**: `run_checks`'s first implementation caused genuine `SQLITE_BUSY` lock contention (~10s hangs, caught by `--durations` in its own test suite) - a `setting_configured` check calls back into `settings_store.get_setting`, which opens its own connection to the same file while `run_checks` held an open write transaction on another connection. Fixed by splitting into two passes: compute all results with no connection open, then persist.

Full suite: 1376/1376 (was 1351).

**Not done:** nobody has watched `baseline-dependency-check.timer` fire on real hardware yet; no real credential-shaped setting exists yet to exercise `is_secret_ref` end-to-end beyond synthetic unit tests.

## 2026-09-28 continuation - settings_store.py moved from a flat JSON file to real SQLite

**Read decision record 87 first** (`docs/design/decision-records/87-settings-store-sqlite-backend.md`).

Direct instruction: the configuration surface is going to grow to "everything an OS has for user preferences, everything every application has" - a flat JSON file doesn't scale to that (whole-file read/mutate/rewrite on every single setting change). Considered SQLite/DuckDB/Postgres against the real constraint ("available once proxmox is loaded and preferably prior... from a core linux kernel"): Postgres needs a running server (disqualified), DuckDB is an OLAP engine mismatched to point-lookup config workloads, SQLite is a stdlib-only embedded library with no service dependency - the only one of the three actually available before any userspace is up. Built:

- `settings_store.py` now backed by real SQLite (`/etc/baseline/settings/master_config.db`, same USER_PERSISTENCE redirect as before) behind the *same* `get_setting`/`set_setting`/`all_effective_settings` API - callers didn't need to change shape, just drop the now-unnecessary `Runner` argument.
- `register_schema()` - the real mechanism for "every application has its own preferences" going forward: a module registers its own settings once instead of one file's `SCHEMA` tuple growing forever.
- `export_bootstrap_snapshot()` - a flat-dict export for the one real case that can't open this database live (values baked into a Proxmox answer.toml).
- Found and fixed a real bug in passing: `path: str = DEFAULT_DB_PATH` as a keyword default binds at function-definition time, not call time - would have made the default path unpatchable after import. Caught immediately by the new test isolation fixture raising `PermissionError` against `/etc/baseline` before the fix landed.
- Full suite: 1351/1351 (was 1349).

**Not done:** no real deployment has read/written this database from an actual pre-Proxmox/rescue environment yet - the "available prior to Proxmox" property holds by construction (no service dependency) but hasn't been observed at an actual early boot.

## 2026-09-28 - found and fixed why "build self installer" did nothing for real; made it the default, keyboard-free path

**Read decision record 86 first** (`docs/design/decision-records/86-self-installer-is-the-default-path.md`) - it has full detail; this is the short version.

**The actual bug behind "I typed my sudo password in to the install option and nothing happened":** decision record 85's `drive_admin.build_self_installer()` required `params["expected_serial"]`, `params["proxmox_source_iso"]`, `params["server_host"]`, `params["cert_path"]`, `params["key_path"]` - but `baseline_web.py`'s own JS never had a form field for any of them, only `device_path`. Every real click raised a server-side `KeyError`. This was a real design mistake caught by direct user feedback ("I will never fill in a serial number... everything must be selectable without a keyboard"), not a UI polish issue.

**What changed:**
- `self_installer.py`: `expected_serial`/`proxmox_source_iso`/`server_host`/`cert_path`/`key_path` are all now optional - auto-derived (real hardware serial via udevadm), auto-generated (fresh ephemeral TLS cert via `openssl req`), defaulted (`10.0.2.2`, the QEMU SLIRP gateway - the only address this mechanism can ever need), or auto-located (a fixed, real INSTALLER_CACHE-style search path list), each refusing clearly rather than guessing when it can't.
- `settings_store.py`: new `"self_installer"` group (`lvm_size_preset`/`fqdn`/`memory_mb`, all enum-constrained via a new `SettingDef.options` field, enforced in `set_setting`) - this is the actual "pre-populated data" mechanism the user asked for, reusing the existing Admin-tab schema store rather than a new config file. `DEFAULT_STORE_PATH` moved onto the `/etc/baseline` -> USER_PERSISTENCE redirect that already existed, per direct instruction that nothing outside USER_PERSISTENCE should be expected to survive reboot.
- `settings_web.py`: Admin tab's dropdown rendering generalized off `SettingDef.options` (was hardcoded to just the three volume-mode keys) - the new settings get real `<select>` controls for free.
- `drive_admin.build_self_installer()` now needs nothing but `device_path`. `ACTIONS` reordered so it's listed first; `install`'s description now says plainly it's a human-override-only path (persistence only, no bootloader, no OS) - not removed, just no longer presented as an equal, parallel option.
- Full suite: 1348/1348 (was 1339).

**Not done / left for next session:**
1. No real click-through of the corrected action against physical hardware yet this pass - the fix was found by code inspection (comparing what the JS sends to what the server required), not by re-running the failed attempt. `/dev/sdd` is still the real target (512GB SK Hynix, serial `FD01N6557110C271B`); `/dev/sdb` still has the empty `baseline_persist` LVM VG left over from the earlier "Install" mishap (harmless - drive was empty - but still real, current state).
2. Real hardware needs a Proxmox source ISO at one of `DEFAULT_SOURCE_ISO_SEARCH_PATHS` in `self_installer.py`, or the action will now cleanly refuse ("no Proxmox source ISO found") instead of crashing - check that path exists on the actual box before the next click.
3. QEMU SLIRP's `10.0.2.2` reaching the host-run `EphemeralAnswerServer` is still not empirically verified on this host - reasoned as correct, distinguished from the different, confirmed-broken `guestfwd` mechanism (decision records 15-16), but nobody has watched a real round-trip succeed yet.
4. Work-queue item #18 (run `homeassistant-lxc`/`haos-vm` under real QEMU) still untouched.

## 2026-09-27 late continuation - massive context gap discovered; one uncommitted test fixed; the physical disk-merge is confirmed still untouched

**Read this before touching anything.** This entry is from the same conversation thread as the original "2026-09-27 handoff" entry below (the one that starts the disk-merge investigation) - but a huge amount of work landed on this repo *from elsewhere* (git history, not this thread's own visible context) between that entry and this one: 19 commits, decision records 62-82, the entire persona/recovery-mode/admin-settings arc, and `docs/design/v0.1-work-queue.md` now shows **fully closed**. The "2026-09-27 continuation" entry immediately below this one is that other work's own handoff, written by whoever/whatever did it - it correctly notes the disk-merge thread is separate and not superseded. Confirmed directly: **the physical drives (`sdd`/`sdb`) were never touched by that other work either** - still exactly as the original handoff entry describes (real backups of VM 202/203 sitting on `/run/media/cane/8TB/Projects/Baseline_v01/`, nothing destructive run, plan agreed but not executed).

**Also superseded, no action needed**: the `persist_bind_mounts.py` module this thread was mid-way through hand-writing (the simple 3-path bind-mount version, for "credentials/config/logs should go to USER_PERSISTENCE") - decision records 62-78 already built a far more complete version of the same idea (multi-persona, `drive_installer.py`-integrated, with `switch_active_persona`/recovery mode/admin elevation on top). Don't resurrect the simple draft; read decision record 78 first to see what's actually there now.

**What this pass actually did, concretely:**
- Found real, substantial, **uncommitted** work already sitting in the tree: `baseline/lib/baseline_web.py` (473 lines) + `baseline/lib/drive_admin.py` (305 lines) + their tests (544 lines combined), plus edits to `control_panel_web.py`/`settings_web.py`/`test_settings_web.py`. `baseline_web.py`'s own docstring names it as **decision record 83** - "the merged Baseline web app... one running server exposing every page settings_web.py/control_panel_web.py already had... plus a new Drive Administration tab" per direct instruction ("merge those two together and add a Drive administration tab"). **No decision-record file for 83 exists yet, and none of this is committed.**
- Ran the full suite cold: **1 real failure** - `test_drive_admin_page_reachable_over_a_real_socket` expected the literal string `"Persistence backend"` in the rendered `/drive-admin` page; the page had a `<h2>Mounted volumes</h2>` heading instead. Checked what actually populates that table (`real_volume_state` → `drive_installer.collect_volume_usage`) - it's specifically the Baseline-managed persistence volumes, not a generic "any mounted filesystem" list, so `"Persistence backend"` is the semantically correct heading, not just a string the test wanted. Fixed with a one-line rename in `baseline_web.py`. **Full suite now 1276/1276 passing.**

**Left for the next session, in priority order:**
1. Write the actual decision-record-83 file (`docs/design/decision-records/83-....md`) documenting `baseline_web.py`/`drive_admin.py` properly - it doesn't exist yet despite the code referencing it by number.
2. Decide whether to commit the `baseline_web.py`/`drive_admin.py` work (it's real and tests pass, but nobody has reviewed it in this thread - it appeared already-written).
3. **The disk merge is still the oldest open real-world item**: pick a target drive (still "doesn't matter" per the user), get their explicit go/no-go on the QEMU-against-real-`/dev/sdd` install approach, then actually execute it. Nothing physical has changed since the original entry below.
4. Read decision records 62-83 properly before making further persona/persistence changes - this thread does not have full context on that arc and guessing at its design would be a real mistake.

## 2026-09-27 continuation - v0.1 work queue fully closed; V0.2 ready to start

A later continuation of the same day's session below (the disk-merge
investigation there is separate, unrelated work - still accurate as
its own historical record, not superseded by this note).

**What closed this pass:** `docs/design/v0.1-work-queue.md` items
25-29 - the entire multi-persona/recovery/settings arc decision record
76 started is now fully landed:

- **25** - persona-aware wiring (decision record 78): real
  mount/unmount + `switch_active_persona` in `persist_bind_mounts.py`;
  `scripts_inbox.py`'s `inbox_dir_for`; a stale-session refusal in
  `settings_web.py`; `/api/active-persona` on `control_panel_web.py`.
- **26** - Recovery Mode itself (decision record 81): real automatic
  entry wired into `persist_bind_mounts.main`, a guest-tier
  `/recovery` discovery page with no login anywhere on it, and the
  hard exit condition (refuses to leave without a real read-write
  persona volume) - explicitly not touching the withdrawn USB
  mechanism (decision record 77).
- **27** - automated recurring encrypted backup (decision record 79):
  new `backup_recurring.py` + systemd timer, honestly flagged as not
  yet targeting a genuinely separate physical device (none exists in
  this dev session).
- **28** - the Admin settings tab (decision record 80): a real
  `/admin` page on `settings_web.py`, gated on a real `admin_elevation`
  ticket for edits - the direct instruction itself had already
  answered "web vs TUI" ("essentially a version of the installer Web
  application").
- **29** - the full TDD audit itself (decision record 82) - see that
  record for the actual findings; short version: every module built
  across decision records 62-81 already had real, substantial
  FakeRunner-driven tests going in, so the audit's main output is
  confirmation plus one closed provision.sh staging gap
  (`settings_store.py`/`admin_elevation.py`/`recovery_mode.py`, caught
  by `tools/check_provision_deploys_all_imports.py` during this pass).

**Full suite at close: see decision record 82 for the exact count.**
`docs/design/v0.1-work-queue.md` has no remaining `[ ]` rows.

**V0.2 focus, per the user's own framing:** "Virtual Machines and User
Persistence capturing of data." One real, unresolved architecture
tension flagged directly to the user and **not** resolved by this
pass: `drive_installer.py`'s LVM-based multi-persona model
(`USER_PERSISTENCE_<PERSONA>` volumes inside Proxmox's own VG) does
not match the real, already-deployed `/dev/sdb` layout (plain GPT
partitions on a separate physical drive, no LVM at all) - reconciling
this is likely foundational V0.2 work, not a pre-existing decision to
build on.

## 2026-09-27 handoff - v0.1 queue items #14-16 closed; real install-ISO tooling proven; a live disk-merge is mid-flight, NOT executed

**Ending this session because it's out of tokens, not because the work is done.** The disk-merge work below is genuinely in progress - read the "Right now, unfinished" section before doing anything to either physical drive.

### What shipped this session (pushed to `origin`, tip `23a8ee0`)

Six commits, three decision records (57, 58, 59 were the prior session; this one added **60** and **61**):

1. **`vm_scripts.py`** - pinned + sha256-verified `community-scripts/ProxmoxVE` Helper-Scripts (resolves decision record 35's deferred item). Manifest: `debian-lxc`, `docker-lxc`, `homeassistant-lxc`, `pihole-lxc`, `debian-vm`, `haos-vm`.
2. **`quadlet.py`** - Podman + Quadlet host-service management (Track B4), rootless mode now fully implemented (real `getent passwd` lookup, `runuser -u <user> -- env XDG_RUNTIME_DIR=... systemctl --user`), default corrected to `rootless=False` (no sensible universal default user).
3. **Real QEMU proof, twice** - a disposable install actually reached a genuine, screendump-verified Proxmox login prompt. Found and fixed two real bugs neither module's fake-based tests caught: `repair.RealRunner.write_text_atomic` didn't create missing parent dirs; `systemctl enable` refuses a Quadlet-generated (transient) unit outright (fixed: `write_and_start`, uses `start`/`stop`, never `enable`/`disable`).
4. **Real, important disclosed finding**: `ct/debian.sh` run off-Proxmox doesn't fail closed - it silently took an "update in place" branch and ran real `apt` activity on the host in 8s. `docker-lxc` and `debian-vm` were also run for real afterward and behaved *differently again* (exit 113; exit 127 "pveversion: command not found") - behavior genuinely varies by script/kind, documented plainly in `vm_scripts.py`'s docstring rather than generalized from one data point.
5. **`baseline/bin/baseline-prepare-real-install-iso`** - new operator tool, operationalizes `docs/INSTALL.md` Step 2 for real (`--fetch-from http`, the only accepted mode for real hardware per decision record 02). Found and fixed a real bug (`prepare_iso_defensively` never created its own `--tmp`). Verified for real: hardware match -> 200, mismatch -> 403, replay -> 403.
6. **Hardware-pinning corrected mid-work, per direct instruction** ("hardware is expected to change with install"): the tool's `--target-mac`/`--target-dmi-product` are now optional, not required - `None` means "don't check this fact," relying on the session's other real properties (LAN scope, pinned TLS fingerprint, single-use, TTL) instead. Re-verified for real with a synthetic unknown machine - correctly accepted.
7. **`vm_scripts.py` unified with `pct_provision.py`/`vm_provision.py`** via a VMID-adoption bridge (`run_script_and_adopt`/`start_adopted`/`stop_adopted`/`destroy_adopted`) - creation still runs through the upstream script (unavoidable), everything after creation now goes through Baseline's existing tested primitives. Added `vm_provision.destroy_vm` (a real gap found while wiring this - only the persistence-preserving retire path existed before).
8. `packaging/baseline-drive-setup`'s executables were `777` (contradicting the package's own "read-only, root-owned" description) - fixed to `0755`/`0644`, rebuilt `.deb`, sent to the user.

Full suite: **922/922 passing.** `docs/design/v0.1-work-queue.md` items #14 and #16 closed; #15 partial (2 of 5 remaining scripts real-executed, `homeassistant-lxc`/`haos-vm` still only hash-verified - tracked as new item #18); #17 (real hardware) still blocked, unchanged.

### Right now, unfinished - a live disk-merge investigation, nothing executed yet

User decided to **merge the two physical drives** from `docs/INSTALL.md`'s table (`sdd`, the Proxmox substrate, serial `FD01N6557110C271B`; `sdb`, the persistence backend, serial `MD89N41071210AP4E`) into one - "not the end result and doesn't need to be the journey," both currently connected via USB to the dev machine (this machine, **not** the laptop), neither currently in the laptop.

**Real facts gathered, read-only, both drives left exactly as found (mounted/activated then cleanly unmounted/deactivated afterward):**

- `sdb`: all three partitions (`USER_PERSISTENCE`/`INSTALLER_CACHE`/`SESSION_TEMP`) are **completely empty** - 20K used each, just a fresh `lost+found`. Zero real data at risk on this drive.
- `sdd`'s `pve` LVM (VG size <475.94G, 16G free): `root` LV is 96G allocated but only **6.2G actually used** (7%); thin pool `data` is 352.74G allocated but only **~3.0G actually written** (0.85% data / 0.50% meta), all of it the two real VMs - `vm-202-disk-0` (4.2G alloc, 39.78% used, ~1.67G real) and `vm-203-disk-0` (5.0G alloc, 26.68% used, ~1.33G real), plus two negligible cloudinit disks. **Total real data across both drives: ~9.2GB** - smaller than the user's own "~25-30GB" estimate.

**Recommended plan, given to the user, not yet actioned:**
1. `sudo vzdump 202 203 --dumpdir <path> --mode stop` (or `--mode snapshot`) - back up the only two things worth keeping.
2. Fresh minimal Proxmox install on whichever single drive survives, via `baseline-prepare-real-install-iso` (already proven this session), with `root`/`data` deliberately sized small (~40G/40G instead of 96G/352G) to leave the rest of the drive for `USER_PERSISTENCE`/`INSTALLER_CACHE`/`SESSION_TEMP`.
3. `qmrestore` the two `vzdump` archives onto the fresh install.
4. Verify both VMs boot and match pre-migration state before wiping the now-redundant second drive.

Rejected: shrinking the existing thin pool/root LV in place - real risk combined with a physical-drive consolidation happening at the same time, for no benefit given how little real data exists to preserve.

**Still open, next session should ask the user directly rather than assume:**
- Which physical drive survives (keep `sdd`'s or `sdb`'s physical unit)?
- Proceed with the `vzdump` backup as step 1?

### A real, scoped sudoers entry now exists on this dev machine

`/etc/sudoers.d/claude-disk-inspect` (user-added, not by me): `cane ALL=(root) NOPASSWD: /usr/sbin/vgs, /usr/sbin/lvs, /usr/sbin/vgchange, /usr/sbin/pvs, /usr/bin/mount, /usr/sbin/vzdump`. Confirmed working (`sudo -n vgs` succeeds; `sudo -n true` correctly still fails since `true` isn't in the list - this is a narrow, scoped grant, not a blanket bypass). **Missing `/usr/bin/umount`** - `sudo -n umount` was needed for this session's own cleanup and wasn't in the list, yet succeeded anyway (cause not fully understood - possibly a separate cached ticket from the user's own terminal at the time); don't assume it will always work without a password. If the `vzdump`/reinstall plan above needs more commands (`lvresize`, `lvcreate`, `resize2fs`, `qmrestore`, `pct`/`qm` themselves), they are **not yet in this sudoers file** - ask the user to extend it rather than assuming broader access exists.

### Standing rule this session leaned on hard, worth repeating

Sudo credential caching is per-TTY (`tty_tickets`) - a session authenticated in the user's own terminal does not extend to a separately-launched Claude session even as the same Linux user. Don't assume a "the user just ran sudo" claim means *this* session can too; test with `sudo -n <cmd>` and take the real answer.

## 2026-09-26 status refresh - V0.1 remaining-work audit; starting V0.2

**Requested via chat:** "Note it in unfinished work but I want to
focus remaining 0.1 work and start onto 0.2 the revisions of 0.1 as
needed."

**What changed:** the "Not done" list below was six days stale
relative to this session's own work (Track A1-A5 real-hardware
Proxmox/persistence/kiosk/dashboard, Track B1-B3 GUI investigation,
harness session/write-grant decision records 31-33, and Track A6's
provisioning modules 34-36) and relative to Track A/B's still-earlier
completion in this same conversation. Re-audited item by item, in
place, rather than left to mislead the next session:

- **Done since the original note:** chat-tab multi-turn memory
  (record 31), a scoped/session-only write-access grant (records
  32-33), the real storage migration this project actually needed
  (Track A1/A2's two real NVMe drives), and the static-IP first-boot
  repair path (already solved by `repair.py`'s `reset_interface_to_dhcp`,
  proven live in Track A1 - the old note just predated knowing that).
- **Still genuinely open:** chat-tab streaming, the visible access-
  scope header, the condensed header bar, OSC 52 clipboard copy, the
  80x24 layout floor, additional harness adapters, and - new this
  session - real-hardware verification for `vm_provision.py`/
  `pct_provision.py`/`docker_provision.py` (blocked: no reachable
  Proxmox host, no Docker daemon installed in this dev environment).
- **Flagged as unclear rather than guessed at:** the old "LVM-reclaim
  manual fix" note names nothing specific enough to act on; may
  already be subsumed by Track A1/A2's real LVM work, may not be -
  ask directly before spending effort on it.
- **Confirmed still correctly scoped as V0.2, unchanged:** the phone-
  tether file/script exchange channel - the user's own current
  framing of it matches this doc's original 2026-09-20 scoping
  exactly.

**What this means going forward, per the user's own framing:** finish
what's genuinely still open under V0.1 (the list above) before
starting new V0.2-scoped work, and treat V0.2 as including *revisions
to V0.1 itself* as they're found to be needed - not only new features
layered on top. See the "Not done" section below for the current,
accurate list this applies to.

## 2026-09-24 session handoff - TestPersistence PRD + privacy-scan scope correction

**Repository state**
- Branch `main`, HEAD `71f6ab9` (`fix: widen prohibited-identifier scope; retract premature clean-content claim`), pushed to canonical `origin` (`cliffthelin/BaseLineProx`) - confirmed 0 ahead / 0 behind `origin/main`.
- Working tree: tracked files clean. Untracked and **not part of this session's work**: `backups/`, `sdc2.img`, `docs/design/.~lock.drive-setup-gui-v2-prd.md#` - leftovers from a separate, earlier task thread (a real `/dev/sdc` install plan, see the stale plan file referenced in that thread). Do not delete without investigating first; do not assume they're safe to discard.
- **Never push to `cliff` (`cliffthelin/baseline`).** `origin` (`cliffthelin/BaseLineProx`) is the sole canonical remote - unchanged, longstanding rule, see "Standing rules" below.

**What this session accomplished** (commits `1f10ae2` → `9e83d02` → `71f6ab9`, all on `origin/main`):
1. `1f10ae2` - added `docs/design/testpersistence-prd.md`, a design-only, entirely-synthetic PRD for Baseline's persistence architecture (storage classes, identity model, attachment state machine, access broker, application lifecycle, snapshot/recovery, failure behavior, 20-case acceptance matrix, milestone sequence). Recorded `physical-phase-p0-p1-plan.md`'s identity-scan gate as `pending_operator_verification` (never claimed passed).
2. `9e83d02` - **privacy finding**: the PRD's `Owner:` field carried a real personal name (outside the repo-account-metadata exception). Removed from current content. Also applied 12 architectural corrections to the PRD after independent review (logical-vs-carrier identity split, manifest/ledger authenticity requirement, honest statement that rollback cannot preserve revocation without a non-rollback ledger or monotonic anchor - made a Milestone-2 blocker, scoped clone-detection claims, automatic grant suspension on app disable/uninstall, isolated untrusted-content inspection mount spec, fixed an unknown-device state-machine contradiction, domain-separated test/production manifest authority replacing a mutable boolean, ownership split from application grants, corrected acceptance cases 4 and 20, reserved full-store recovery-ledger capacity).
3. `71f6ab9` - **scope correction**: the `9e83d02` commit's status block wrongly implied current content was clean once one field was fixed. Corrected: the repo-account exception covers GitHub URL/remote references only, not tracked-file personal-identity content. A targeted (non-protected) grep for the already-known identifier found it in two more tracked files - `docs/design/drive-setup-gui-v2-prd.md`'s `Owner:` field (removed) and `packaging/baseline-drive-setup/DEBIAN/control`'s `Maintainer:` field (replaced with a project-generic identity at a reserved `.invalid` domain). `packaging/.../copyright`'s `Copyright:` line was found but **deliberately left unchanged** - flagged as an unresolved policy conflict, not fixed unilaterally (see below).

**Verified state**
- Full pytest suite: **418/418 passing**, last run at HEAD `71f6ab9` (re-run after every edit in this session; not stale).
- Everything this session touched was pure Python schema/doc work with no disk I/O, no LUKS, no QEMU, no privileged operation - unit-tested only, nothing simulation/QEMU-tested and nothing physical-hardware-tested in this session.
- No physical drive was touched, mounted, written to, or installed to. No history rewrite, force-push, `git filter-repo`, ref/tag modification, or destructive operation was performed at any point.

**Current P0/P1 position** (see `docs/design/physical-phase-p0-p1-plan.md`, status block at the top)
- All implementation gaps, security hardening corrections, and coverage-accounting/interactive-scanner work described in that document are complete and previously verified (see that file's own "closed" sections - not re-verified again this session, no new evidence needed).
- The **next dependency-valid step for P0/P1 itself** is unchanged from before this session: the operator runs `python3 tools/interactive_denylist_scan.py` locally (hidden-prompt input, values never seen by Claude) to produce the first real `full_scan` result. Nothing else in P0/P1 is blocked on implementation work right now - it is blocked on that operator action plus the identity-scope questions below.

**Explicit unresolved decisions (operator-only, not implementable by an agent)**
1. **Copyright declaration** (`packaging/baseline-drive-setup/usr/share/doc/baseline-drive-setup/copyright`) - carries a personal-name copyright statement under the MIT license text. Left unchanged. Needs operator direction: keep as intentional individual ownership, or replace with a project-collective form. **Do not change this file** until that direction is given.
2. **Protected full current-content identity scan** - `identity_scan.current_content: pending_full_scan`. The fixes above came from a targeted grep for one already-known term, not the protected scanner, which can find identifiers this session didn't already know to look for. Only a clean `tools/interactive_denylist_scan.py` run (its `current_tracked` scope) can move this to `clean`.
3. **Git-history identity scope** - `identity_scan.git_history: known_findings_scope_unknown`. Not "one value in one commit" - given personal-identity content was found in three separate tracked files, older commits, refs, tags, and commit messages may carry it too, and none of that has been enumerated. A valid rewrite plan requires the operator's protected full scan (`git_history` scope) to run first, plus manual review of anything it can't reach (unreachable objects, other refs/tags, GitHub's own caches). **No rewrite has been proposed in executable form and none should be attempted without that scan plus explicit operator authorization.**
4. **Physical P0/P1 itself** - still entirely unstarted; blocked on the identity-scan gate (items 2-3) for final privacy closeout, not on any remaining implementation.

**Safety boundaries a continuing agent must preserve**
- Authority model stays `propose → validate → authorize → execute → verify → rollback` for anything consequential - do not skip straight to execute on drive/history/privileged operations.
- **A new agent continuing this work is not itself authorization** to run the identity scan's protected values, rewrite history, force-push, touch `/dev/sdX` or any physical drive, or change the copyright file. Those all still require the human operator, present and explicit, regardless of how much session/context has elapsed.
- Never print or reconstruct the personal-identity value that was found and removed - it has intentionally not been repeated anywhere in this document or the commits above.

**Recommended next task for a continuing coding agent**: none of the P0/P1-adjacent work is currently unblocked without one of the four operator decisions above. If further design work is wanted in the meantime, the TestPersistence PRD's own Milestone 2 (`docs/design/testpersistence-prd.md` §16) - pure schema/state-machine unit tests (dataclasses/enums for storage classes, identity model, attachment state machine, grant records; no disk I/O, no LUKS, no QEMU) - is the smallest dependency-valid unit that doesn't require any of the pending operator decisions, since it's synthetic-only and independent of the real identity-scan gate. No other physical-P0/P1-track task is safely startable right now.

---

Written from the CLI session that did tonight's bare-metal bring-up work,
for you to paste into / cross-check against the new Claude Project. I
have no access to that Project (it's a claude.ai web feature, not
reachable from this CLI session), so I can't verify what did or didn't
transfer - this is the definitive account from this side, not a diff.

## READ THIS FIRST - active drive incident, resolved; full backups now exist

Filesystem is healthy (see the "UPDATE" entry further down). After that
recovery, **three complete, checksum-verified backups were made** with
the drive in its now-healthy state (no corruption this round - `tar`
worked normally, 97,210 files each in the two full ones):

| File | Size | Locations | sha256 |
|---|---|---|---|
| `Private_Baseline_files.tar.gz` | 61KB | this CLI machine's `/run/media/cane/CACHE/baseline_repo/backups/`, laptop `/root/backups/`, sent to the user directly | `50d38279b201097ee68dd969f61daa40745c7ea6a39bb2837112d330ad8d5396` |
| `baseline-fullroot-20260920-185140.tar.gz` | 2.40GB | CLI machine's `backups/`, laptop's internal Ubuntu drive `/mnt/baseline-backups/` | `759ee9a9d814e05454d3ad5b9da0f6ba5b0d1f9ed61b94072af53d578493aceb` |
| `baseline-tight-20260920-185838.tar.xz` | 1.91GB | CLI machine's `backups/`, laptop `/root/backups/` | `7e946e28bec0f36e9171c2db5ed51458e0f1a03922692247f408bcc9bcdec5aa` |

`Private_Baseline_files.tar.gz` contains real secrets (OAuth token, SSH
host/root private keys) - same handling rule as everywhere else in this
doc: never public, never GitHub. The two full-root archives exclude
only `/proc /sys /dev /run /tmp /mnt /media /lost+found` and stay on
one filesystem (`--one-file-system`); expect harmless `tar` warnings
for postfix's unix-domain sockets and one "file changed as we read it"
for the live `/var/lib/lxcfs` fuse mount - neither affects integrity
(both archives passed `gzip -t`/`xz -t` plus a full `tar tzf`/`tar tJf`
listing).

The earlier partial/corrupted backups from during the incident
(`partial-verified-20260920-1817.tar.gz`, the failure logs) are still
in `backups/` too - superseded by these for restore purposes, but kept
since they're small and document what the degraded state actually
looked like.


The laptop's boot drive (a 28.7GB USB stick, `/dev/sdb`, holding the
`pve-root` LVM volume that everything runs from) had a real failure
event. **A verified, uncorrupted partial backup now exists** (see
below), but the drive itself is still degraded/read-only and the root
cause (wedged software state vs. genuine media failure) is still
unresolved. Whoever continues this needs to pick up here before
anything else.

**Timeline (2026-09-20):**
- `16:01:40` - kernel logs `usb 2-1.2: USB disconnect, device number 4`
  for the boot drive.
- `16:01:47` - ext4's journal aborts, several `Buffer I/O error`s, the
  root filesystem (`dm-1`, i.e. `pve-root`) remounts itself read-only
  (`errors=remount-ro` kernel safety trigger). Confirmed still
  read-only as of the end of this session (`touch` fails with
  "Read-only file system").
- User confirmed the physical USB connection is seated ("It's plugged
  in"). No new USB disconnect events logged since. Reads continue to
  mostly fail regardless (see below) with a stable connection, which
  points more toward (b) below.
- A full filesystem walk (via Python, since `/usr/bin/tar` itself fails
  to execute with a consistent I/O error) hit **15,372-15,373
  I/O-error failures out of ~18,338 files attempted (~84% failure
  rate)**, spread across essentially every directory - not localized.
  **`/usr/bin/rsync` also failed to execute** with the same I/O error
  pattern as `tar`, while `python3`, `cat`, and plain file reads kept
  working reliably throughout. Two different, unrelated system
  binaries failing to load points toward (b) **genuine, fairly
  extensive media failure** on the drive, more than (a) a simple
  software wedge - not conclusively proven, but the working theory.
- **Three backup attempts; the third succeeded and is verified valid**:
  1. Python `tarfile.add()` directly - corrupted (writes the tar header
     before copying content, so a read failing partway through a file
     desynced everything after it in the stream).
  2. Buffered each file fully into memory first (should have avoided
     the above) - **still corrupted**, breaking after 4247 entries.
     Root cause never fully identified - suspected but unconfirmed:
     `tarfile.gettarinfo()`'s PAX-header prep may use stat-time size
     before the manual `ti.size` override, desyncing PAX-format
     entries specifically. Do not reuse `tarfile` for this host without
     understanding that first.
  3. **Abandoned `tarfile`/any archive-format library entirely.**
     Custom minimal framing (tag byte + length-prefixed path + length-
     prefixed data, written by a remote Python process, parsed by a
     local Python process into individual real files on local disk -
     see `remote_backup3.py`/`local_receive.py` if still present in
     that session's scratchpad, otherwise trivial to rewrite from this
     description) - **worked cleanly**: 2966 files, 417MB, local
     receiver's count matched the remote sender's count exactly, zero
     errors. Repackaged locally (purely local tar of local files, no
     remote I/O involved, so no corruption risk) into
     `partial-verified-20260920-1817.tar.gz`, 139.8MB,
     sha256 `6a03a37ad58e8c6744d6e3e3e069446583044891b0d158c2081e19e82e454d09`
     - **both `gzip -t` and `tar tzf` pass cleanly on this one.**
     Contains the real, critical files: all of `/opt/baseline`
     (including `bin/baseline` itself, which `tar` couldn't read),
     `/etc/systemd/system/baseline.service`, `/etc/baseline/*`
     (**including the live `harness.env` OAuth token and
     `interface_aliases.json`**), and `/etc/ssh/ssh_host_*_key`
     (**including the private host keys**).
  **This archive contains live secrets - never commit it to the public
  BaseLineProx repo or any public location.** It was sent directly to
  the user via chat only. The two earlier *corrupted* archives were
  deleted (not useful, superseded by the working one); the raw failure
  logs from attempt 2 were kept and also sent to the user directly.
- **Still not captured**: ~13,605-15,372 files (the ~84% that fail to
  read at all right now) - most of the base OS, kernel, `/boot`, most
  of `/usr`. This partial backup is enough to reconstruct Baseline's
  own app/config state on a fresh OS install; it is **not** a full
  system image.
- **UPDATE: user rebooted the laptop themselves** (not explicitly
  authorized in chat first - happened directly at the physical
  console). Boot log showed a new, alarming symptom: `WARNING: VG name
  pve is used by VGs 58P3UX-...-2OEmuD and wdSVr9-...-JW1rDy` (two
  volume groups both named "pve") and the `getty.target` ordering-cycle
  skip message from earlier in the session (docs/changelog/boot/001.md)
  reappearing. Also, immediately post-boot, all network interfaces
  showed `carrier_present: FAIL` (no link at all), so SSH was
  unreachable for a few minutes.
- **Once network came back, the picture resolved cleanly - genuinely
  good outcome:**
  - `/` is mounted `rw` again and a live write test succeeded - the
    read-only state is gone.
  - **`tar` and `sha256sum` both load and run normally now** - the
    "binary fails to execute with I/O error" symptom that drove the
    "genuine media failure" theory is **gone**. In hindsight this was
    very likely a software-level wedge from the ext4 journal abort
    (widespread defensive read failures cascading from one bad
    write), not permanent media death - a clean reboot + fsck fixed
    it. The `full_inventory()` "Display" fact investigation two
    reboots earlier turned up the same kind of lesson: be skeptical of
    "the drive is dying" conclusions drawn from software-observable
    symptoms alone without independent hardware evidence (SMART data,
    which was never actually obtained this session - no `nvme-cli`
    installed, no non-interactive `sudo`).
  - The duplicate-VG warning also resolved: `vgs`/`pvs` now show
    exactly one clean `pve` VG on one PV. The PV's device path moved
    from `/dev/sdb3` (throughout this whole session) to **`/dev/sda3`**
    this boot - device-letter reassignment across a reboot is an
    *already-documented* gotcha from earlier in this project (see
    `docs/BAREMETAL_BRINGUP_NOTES.md`). The "duplicate VG" message was
    almost certainly LVM's boot-time scanner catching the same
    physical volume at two different transient device paths before
    udev finished settling names, not a real second installation.
  - `baseline.service` is active and healthy post-reboot;
    `getty.target` itself is genuinely active (not skipped) once boot
    settled, so that regression didn't stick either.
  - **Do not assume device paths are stable** - `/dev/sdX` letters can
    and do change across reboots on this hardware. Anything hardcoding
    `/dev/sdb` specifically (there is nothing in the Baseline app
    itself that does - it resolves interfaces/devices by name/driver,
    not hardcoded paths - but double-check any new scripts) needs to
    tolerate this.
- **Net assessment, revised**: this looks recoverable/transient rather
  than terminal hardware failure, but it demonstrably CAN wedge the
  whole filesystem read-only and take multiple system binaries down
  with it under some trigger condition that was never root-caused
  (what actually caused the original `usb 2-1.2: USB disconnect` at
  16:01:40 is still unknown - cable, power, or a real intermittent
  fault in the drive/enclosure). Don't consider this fully closed -
  keep the backups made tonight, and treat a recurrence as reason to
  actually get real SMART/health data on this drive before trusting it
  further.

**Recommended next steps for whoever picks this up:**
1. Filesystem and service state are healthy as of the end of this
   session - no immediate action required, but this incident is real
   evidence the boot drive needs closer monitoring (real SMART data
   would help - not obtained this session) and that the NVMe-migration
   conversation from earlier (see "Not done" below) is worth prioritizing
   even though nothing is on fire right now.
2. If it recurs, reuse the working custom-framing approach (attempt 3
   in the earlier account of this incident, still above), not
   `tarfile`/`tar`/`rsync` directly - all three were unreliable while
   the filesystem was in its degraded state, for reasons not fully
   understood.
3. Get explicit authorization before rebooting the laptop in the
   future - this time it happened without an explicit go-ahead logged
   in chat.
4. Handle `partial-verified-20260920-1817.tar.gz` as containing live
   secrets (OAuth token, SSH host private keys) - never push it
   anywhere public.

## Do this first (before anything else works)

**SSH access to the laptop needs to be re-established.** The key I've
been using all session lives at a path inside *this* session's own
temporary scratchpad directory - it does not exist anywhere the new
Project can reach. Either:
- Generate a fresh keypair from the new Project's environment and add
  the public half to the laptop's `~/.ssh/authorized_keys` (you'll need
  physical/console access to do that one-time step - `baseline`'s
  Console tab or the Proxmox round-trip feature, see below, both give
  you a shell), or
- Copy an existing private key into wherever the new Project's
  persistent storage is, if one is being kept.

**The laptop's IP changes.** It's DHCP (`vmbr0`), currently
`10.0.0.133`, but it has changed at least twice already this session
(`.181` -> `.133`). Don't hardcode it as fact anywhere; check via
`ip -4 -o addr show` over the console, or your router's DHCP lease
list, before assuming SSH will connect.

## What exists and where

- **Live device**: a Dell Latitude 5290 laptop, Proxmox VE 9.2 bare
  metal, `baseline.service` owns tty1 (real console, not a VM/QEMU
  session at this point in the project).
- **Source of truth repo**: `/run/media/cane/CACHE/baseline_repo` on
  this machine (persistent storage - `/tmp` and drive-letter paths were
  both burned early in the project as unreliable across reboots, see
  `docs/BAREMETAL_BRINGUP_NOTES.md`).
- **GitHub**: <https://github.com/cliffthelin/BaseLineProx> (public),
  `main` branch, tip commit `07eda93` as of this handoff - confirmed to
  contain everything described below.
- **Deployed app path on the laptop**: `/opt/baseline/{bin,lib}`,
  `/etc/baseline/` (preferences/aliases/auth token), `/etc/systemd/
  system/baseline.service`.
- A **second, pre-existing private repo**, `cliffthelin/baseline`,
  unexpectedly received a push from this session too (a `git remote`
  mix-up - see the git-workflow note below). I don't know its history.
  Worth checking directly whether it should be archived/deleted or is
  intentional and predates this session.

## Standing rules the user has set (do not relitigate these)

- **Never use theme/variable colors** ($primary, $surface, etc.) in any
  Textual CSS - always explicit hardcoded hex. This has caused multiple
  illegible-UI bugs already; the bare `TERM=linux` framebuffer console
  renders theme colors unreliably.
- **No fake/decorative buttons or forms.** Every control must do a real
  thing. Where real functionality isn't ready yet (e.g. hardware
  Configuration tab), say so honestly in the UI rather than faking it.
- **Implement real functionality now, don't defer it** - the user has
  explicitly rejected "wait and build it properly later" multiple
  times.
- **No non-ASCII characters anywhere in rendered output** - found and
  removed the app's only Unicode use (arrow glyphs) after multiple
  `TERM=linux` rendering bugs this session; the bare console's font
  can't be assumed to have arbitrary glyphs.
- **Never open a new file descriptor to `/dev/tty1` (or any tty device
  node) from within the running Baseline process.** An earlier attempt
  to do this (for a character-grid query) correlated with real console
  font-table corruption ("garble") that persisted across service
  restarts. Use `os.get_terminal_size()` (reads the process's own
  already-open stdout) instead - see `docs/changelog/hardware/001.md`
  and `boot/001.md` for the full story.
- **Verify before declaring anything done.** The established pattern
  all session: edit locally -> deploy to the laptop -> run a headless
  Textual pilot test (`app.run_test()`) reproducing the actual
  interaction -> restart the service -> confirm stability via
  `systemctl status` (immediate + after a few seconds, to catch crash-
  loops) -> ask the user to visually confirm on the physical screen,
  since no screenshot pipeline exists for this console.
- **Every deployed change gets a change-log entry.** See
  `docs/changelog/INDEX.md` - check it first, it points to category
  files (boot/hardware/network/ui/chat), each an append-only, rotating
  block. Use `docs/changelog/TEMPLATE.md` for the entry format
  (Context/Considered/Requirement/Files changed/Verification/Pointer
  update/Docs update). This is a standing process now, not a one-off.

## What's actually done (verified live, not just written)

- Full vertical-slice PRD V0.1: boot to a Baseline prompt on tty1,
  deterministic hardware status (`inxi`-based), network bring-up
  (wired/Wi-Fi/USB-tether) with per-stage Lifeline diagnostics, a
  read-only Claude Code harness (zero tools, hardware/network JSON as
  its only context).
- A full Textual TUI (Hardware/Network/Chat/Console tabs) replacing the
  original plain Rich console output, with real keyboard navigation
  (Tab/Down/Shift+Tab, all independently verified working), explicit
  hardcoded colors throughout, and crash containment (Textual treats
  any unhandled exception as fatal to the whole app - confirmed in its
  own source - so render callbacks and event handlers are wrapped to
  log-and-continue instead).
- **Hardware tab**: shows every `inxi` fact (not a curated subset),
  grouped, each row opening a modal (Details/Description/
  Troubleshooting/Logs/Configuration - last four are honest
  placeholders).
- **Network tab**: correct Available-vs-Unreachable logic for wired vs.
  wireless links, IP + live traffic on the main row, and a
  `ConnectionModal` per interface with real bridged hardware identity
  (manufacturer/model/connection-type/driver, via `udevadm` - works for
  onboard and USB devices alike), a renameable, persisted alias, a real
  working Enable/Disable, Primary/Fallback as a genuine arrow-navigable
  toggle (not two momentary buttons), and its live position in the
  Lifeline chain when it's the active device.
- **Boot/console robustness**: fixed a `getty.target` systemd ordering
  cycle that could hang boot entirely; fixed `inxi` failing under the
  service's minimal environment; fixed console font-table corruption
  via an `ExecStartPre` `setfont` plus a standalone, re-runnable check
  (`tests/console_font_check.sh`, also wired into `provision.sh`).
- **A real Proxmox<->BaselineOS console round trip**: `(p)` inside
  Baseline switches tty1's physical console to tty2, which starts a
  genuine, unmodified login prompt (systemd-logind auto-starts the
  getty - no unit needed enabling by hand); a `baseline` shell function
  (installed system-wide via `/etc/profile.d/`) switches back to tty1
  without disturbing Baseline's already-running state. **Login stays
  required on the Proxmox side by explicit user decision** - not
  bypassed, don't add auto-login without asking again.
- This change-log system itself (`docs/changelog/`), backfilled with
  tonight's work.

## Not done - open items for the new Project

**Re-audited 2026-09-26** (this section was stale relative to the
Track A/B and harness-session work done since 2026-09-24; edited in
place against current reality rather than left to mislead the next
session - see the 2026-09-26 status-refresh entry near the top of this
file for what changed and why):

1. **Chat tab quality** - partially done. `--session-id <uuid>` +
   `-c/--continue` for real multi-turn memory: **done** (decision
   record 31, `harness.HarnessSession`/`build_ask_argv`). A named,
   auditable, scoped write-access control: **done, but narrower than
   originally proposed** - not a general `--allowedTools`/
   `--disallowedTools` toggle, but an explicit, operator-initiated,
   session-only `WriteGrant` (decision records 32/33; `grant write
   <directory>`/`revoke write` console commands). Genuinely still
   open:
   - `-p --output-format stream-json` for real incremental streaming:
     **done, scope stated precisely** (decision record 41) - the
     answer is available as soon as the assistant event lands rather
     than blocking until the process exits; NOT per-token typing
     (that needs `--include-partial-messages`, deliberately not
     tested this pass to limit real API cost). Not yet verified live
     on a real boot.
   - A visible header item showing the live-granted scope (session
     id/started state, active write grant if any): **done** (decision
     record 37, `harness.describe_session`, Chat tab's `#harness_status`
     line) - not yet verified live on a real boot, no real hardware
     access this session.
   - The condensed one-line header bar: **done, narrowed** (decision
     record 39) - `BaselineOS | <access scope + memory> | c=copy`;
     `tabs` and `datetime` deliberately not duplicated since
     `TabbedContent`'s own tab strip and `Header`'s own clock already
     show them. Not yet verified live on a real boot.
   - Real clipboard "copy" via OSC 52: **done** (decision record 38,
     `clipboard_osc52.build_osc52_copy_sequence`, Chat tab's `c`
     binding) - sends the sequence, does not and cannot confirm a
     terminal actually applied it; still not verified over this
     console/SSH path, no real hardware access this session.
   - Embedding the actual interactive `claude` CLI in a raw PTY widget
     remains explicitly **rejected**, unchanged from the original
     reasoning.
   - See `docs/changelog/chat/001.md` for the full decision record.
2. **Screen-size-appropriate layout** - partially done. The status
   bar (decision record 42) now provably never exceeds an 80-column
   budget for any write-grant scope path length - the one concrete,
   self-inflicted floor risk found in this pass. Other widgets
   (`DataTable`s already use flexible `1fr` heights and Textual's own
   scrolling) weren't individually audited for the same floor - not
   yet verified on a real 80x24 terminal either way.
3. **Storage migration** - **superseded, not open.** This 2026-09-20
   note (a candidate 512GB NVMe, pending a speed test) is the same
   role Track A1/A2 (2026-09-26) filled for real: `/dev/sdd` (Proxmox
   substrate) and `/dev/sdb` (shared LVM-thin persistence backend) are
   both real 512GB NVMe drives, installed, validated
   (`physical_device_safety.py`), and verified live. No further
   speed-test/migration action is needed.
4. **Static-IP first-boot repair** - **done, not open.** The 2026-09-20
   note ("documented but not folded into `provision.sh`") predates the
   actual architectural resolution: Milestone 1's Gates A-F (decision
   records 20-27) deliberately did **not** fix this in `provision.sh`
   at all - `docs/design/decision-records/11-repair-branch-comparison.md`
   found `repair.py`'s `reset_interface_to_dhcp()` already solved this
   fault class as a first-boot discovery+repair action, integrated into
   `firstboot_statemachine.py` and proven live on real hardware in
   Track A1 (2026-09-26). Nothing further is needed here.
5. **"LVM-reclaim manual fix" note** - **unclear, likely stale.** No
   other document in this repo names what specific reclaim step this
   2026-09-20 note referred to. Track A1/A2 (2026-09-26) did extensive
   real LVM work on both drives (deactivating a stale duplicate `pve`
   VG by exact UUID, wiping signatures, building an LVM-thin pool) -
   this note may already be subsumed by that, or may refer to
   something else entirely. Flagged rather than guessed at; ask the
   user directly if this still means something specific before
   spending effort on it.
6. Older, still-open items, carried forward unchanged:
   - Provider "configuration forms" deliberately still not built - by
     design, not an oversight (credential handling stays out of
     Baseline's own hands - see `baseline/lib/harness.py`'s docstring).
   - File-transfer/shared-folder capability for the phone-tether rescue
     channel - **still scoped as v0.2, still not started.** The user's
     own framing in this project's 2026-09-26 conversation ("the tether
     to phone... still needs the file and script exchanges") confirms
     this is still the right v0.2 scoping, not superseded by anything
     built since.
   - **OpenCode is now implemented** (decision record 44) - the second
     real `HarnessAdapter`, normalized through real ACP (Agent Client
     Protocol, an open standard OpenCode's own `opencode acp` speaks
     natively). A real, live round trip was confirmed against the
     actual binary, including a real discrepancy caught between ACP's
     own docs and its actual wire bytes. Has no write-grant support -
     honestly absent, not guessed at, since ACP's own permission
     mechanism hasn't been checked against decision record 32's
     specific shape. Hermes/Pi/DeepSeek/GrokBot remain listed-but-
     unimplemented; the dispatch layer (decision record 43) makes any
     of them a drop-in whenever the user names one and its CLI turns
     out to be checkable the way `claude`/`opencode` both were.
7. **A full audit (2026-09-26, decision record 47) found a real,
   provable contradiction in this session's own record**: commit
   `e82c6e4` claims "Real-hardware-verified... on the live Track A1
   Proxmox install" for Track A3/A5's modules; decision record 45,
   written hours later the same day, says "this session cannot verify
   anything on real Proxmox hardware at all." Neither can be fully
   right. The working plan's Track A1-A5 "STATUS: complete, verified
   on real hardware" claims have no decision record behind any of
   them and are now marked corrected/unconfirmed in place - see
   decision record 47 for the full account. A2's claimed
   `baseline-persist` LVM-thin backend specifically does not exist on
   `/dev/sdb` today (it's plain ext4, decision record 46) - do not
   build anything assuming it does.
9. **See `docs/INSTALL.md` now - the definitive install runbook this
   project didn't have, written 2026-09-26 after an audit found no
   single document (this one included) actually tells anyone how to
   build a working Baseline drive install.** Two real gaps it closed
   with new code rather than narration: `persistence_pool.py` (the
   LVM-thin pool Track A2 built once by hand, never scripted) and a
   documented, code-reuse-based procedure for the real Proxmox install
   (turns out `drive_setup_install.py`'s existing QEMU invocation
   builders already accept a real block device path directly - no new
   code was needed there, just writing down the correct combination
   for the first time). Neither has been run for real yet - see that
   document's own status table, which is meant to be corrected in
   place the first time someone actually runs it, not left to go stale
   the way this section's own prose repeatedly has.
10. **Real-hardware verification is blocked for three provisioning
   modules; the chat harness half is NOT blocked and has now been
   checked for real.** `vm_provision.py`/`pct_provision.py`/
   `docker_provision.py` (decision records 34-36) are still unit-tested
   against fakes only - no `qm`/`pct`/`pvesh`/Docker daemon reachable
   from this dev environment. But this same environment turned out to
   have a real, working `claude` CLI all along - used directly
   (decision record 40) to verify records 31-33's flagged unknowns:
   session continuity (`--session-id`/`-c`) works exactly as designed;
   the write-grant argv had a **real bug** (`Write(...)` isn't a valid
   permission rule - the CLI wants `Edit(...)`, and `--allowedTools`
   alone isn't sufficient without `--permission-mode acceptEdits` too)
   - found and fixed. The scope boundary itself was confirmed to hold
   against a real, adversarially-worded out-of-scope write attempt.

## Where to look for more detail

- `docs/changelog/INDEX.md` - check first, points to everything else.
- `docs/BAREMETAL_BRINGUP_NOTES.md` - accumulated real-hardware gotchas
  (QEMU vs. bare-metal VT-switching, DHCP client quirks, USB tethering,
  the dhclient `-timeout` bug, etc.).
- `docs/adr/0001-bare-metal-network-bootstrap.md` - the two network
  route-selection bugs found early on, written up as an ADR.
- The original PRD context lives in this chat's history, not yet
  extracted into a repo doc - if the new Project needs it and doesn't
  have it, ask for it explicitly rather than assuming it's here.
