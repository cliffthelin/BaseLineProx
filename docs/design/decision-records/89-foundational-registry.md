# Decision record: one foundational registry (`registry.py`), not a bespoke table per registry type

Status: **implemented, unit-tested (1391/1391 full suite, up from 1376).**

## What was asked

"To be clear the registry, the details about whats registering, which register type, and so on should be foundational Baseline table concepts that are not new tables everytime we need a register. SO plan it dynamicly to address potentially thousands of registries and hundred of varying registry types and consider user scope for these. Some may be allowed as a global foundation for recovery while the rest are protected with the user peristence."

This is a direct, corrective critique of decision records 87 and 88: `settings_store.py` got its own `settings` table, then `dependencies.py` got its own `dependencies` + `dependency_check_results` tables - exactly the pattern the user is now stopping before a third registry type would have added a fourth/fifth table.

Also, mid-turn: "If SQLLite can't handle multiple threads of calls its not a long term solution" and "When I need to load a whole OS and every configuration and every application configuration and feed many into app helpers multithreading is a must." Addressed directly, not deferred: the earlier ~10s hang (decision record 88) was a real bug in this codebase's own connection handling (a nested call opening a second connection to the same file while the outer one held an uncommitted write transaction), not evidence that SQLite can't do concurrency. WAL mode's actual guarantee - unlimited concurrent readers, never blocked by each other or a writer; only two simultaneous writers serialize - fits a "many app helpers reading their own config" workload exactly. Proven with a real test, not just asserted: `test_registry.py`'s `test_many_concurrent_readers_never_block_or_corrupt_a_read` and `test_concurrent_readers_alongside_a_writer_never_crash_or_corrupt_state` fire real concurrent reads/writes from a thread pool against the same on-disk database.

Also, separately: "Don't make caps of the number things pre a V1 that is generally a bad idea" - the `drive_admin.ACTIONS` "exactly N actions" test had already needed widening twice (decision records 85, 86, 88); relaxed to a subset assertion (`expected <= set(ACTIONS)`) instead of an exact-set one, and this pattern is now avoided going forward.

## What was built

**`registry.py`** (new module) - three tables, reused by every registry type forever:

- `registry_types` - what kinds of registry exist (`type_id`, `description`, `default_scope`).
- `registry_entries` - every entry of every type, one row each (`type_id`, `entry_id`, `attributes` JSON, `value` JSON, `scope`). `attributes` holds whatever static shape a type needs - a setting's default/options/description, a dependency's severity/phases/check_kind/check_args, or anything a future type needs - a flexible JSON blob instead of a bespoke column set (and therefore a bespoke table) per type.
- `registry_events` - an append-only log any registry type can use for history (a dependency's check results, a setting's future change history) - one shared table, not one per type.

**Scope and the two-physical-database split** (direct instruction: "some may be allowed as a global foundation for recovery while the rest are protected"):

- `GLOBAL` scope resolves to `/mnt/BASELINE/registry/foundation.db` - the shared, non-persona LVM volume (`drive_installer.SHARED_VOLUMES`), present regardless of which persona is active or whether a specific persona's own `USER_PERSISTENCE_<PERSONA>` volume is broken.
- `PROTECTED` scope resolves to the existing USER_PERSISTENCE-redirected database (`settings_store.DEFAULT_DB_PATH`, decision record 87).
- Scope is a per-*entry* decision, not only a per-type default - `settings_store.SettingDef` and `dependencies.Dependency` each gained a `scope` field. Concrete real example: `startup.auto_start_persona` is now `GLOBAL` - asking "which persona's volume should I even try mounting" from inside that same volume is circular, so recovery needs this readable independent of any one persona's persistence. `dependencies.Dependency` defaults to `GLOBAL` entirely - a dependency's whole purpose is diagnosing machine health, including USER_PERSISTENCE itself, so its definitions and results being trapped inside the volume being diagnosed would be unreachable exactly when needed most.

**`settings_store.py` and `dependencies.py` migrated onto this foundation**, public API unchanged in shape (existing callers needed zero changes beyond dropping the now-removed `path=` override parameter - isolation for tests comes from the autouse fixture redirecting `registry.GLOBAL_DB_PATH`/`settings_store.DEFAULT_DB_PATH`, not a per-call override). Each module's own domain logic (settings' `options`/`is_secret_ref` enforcement, dependencies' severity/phases/check-kind vocabulary) stays exactly where it was - only the storage underneath moved.

**Real bug avoided by design review, not discovered at runtime**: the first draft of this migration had `settings_store.py` call `registry.register_type(...)` at module *import* time. Caught before it ran: real database I/O during import would execute before any test's isolation fixture has had a chance to redirect the default paths - the same class of bug decision record 88 already found once (there, a held-open connection; here, it would have been a `PermissionError` against `/etc/baseline` on the very first `import settings_store` of the whole test session, before any fixture runs). Fixed by moving `register_type`/`upsert_entry` calls into `_sync_definition`, which only runs at real access time (`get_setting`/`set_setting`/`run_checks`), after fixtures have already patched the paths.

## Real conflict found and resolved by direct instruction, not silently

`drive_admin.py`'s `settings_db_path`/`run_health_check`'s equivalent override parameters were removed entirely (no replacement) since `registry.py`'s scope-based routing plus the autouse test fixture make a per-call path override unnecessary - the one place that needed to simulate a stale/corrupted value (a test) now writes directly into the already-isolated default database via `registry.upsert_entry`, not a separate custom file. Confirmed no real caller outside tests ever used the override.

## Verification performed

- New `tests/unit/test_registry.py` (17 tests): type registration idempotency and validation, entry round-trip (with/without a value, re-sync not clobbering an existing value), scope isolation (proving GLOBAL and PROTECTED are genuinely separate files, not a column filter), event recording and latest-per-entry retrieval (with and without a kind filter), and the two real concurrency tests described above.
- `settings_store.py`'s and `dependencies.py`'s own existing test suites pass unchanged in shape (23 and 20 tests respectively) - proof the migration preserved their public contracts.
- `tools/check_provision_deploys_all_imports.py` caught `registry.py` missing from `boot/provision.sh`'s copy list on the first run after the migration - fixed immediately.
- Full suite: 1391/1391 (1376 before this record).
- **Not verified**: no real deployment has yet exercised the GLOBAL/PROTECTED split during an actual recovery-mode scenario (a persona's USER_PERSISTENCE genuinely broken while `/mnt/BASELINE` remains reachable) - the routing is correct by construction and unit-tested for isolation, but not yet observed against real, failed hardware.
