# Decision record: each settings group is its own registry type - `settings_store.py` stops being a registrar

Status: **implemented, unit-tested (1454/1454 full suite, up from 1452), verified for real against both live registry databases.**

## What was asked

"also settigns_store is toobroad and the file should weigh in on what level it has settings and is this not another registrar needed and typ needed" - a direct architectural critique, mid-way through building `gpu_admin.py` (decision record 94): `dependencies.py` gets its own real registry type (`"dependencies"`), `gpu_admin.py` gets its own (`"gpu_devices"`), but `settings_store.py` had been centralizing *every* domain - sessions, startup, volumes, self_installer, network - under one shared `TYPE_ID = "settings"`, distinguished only by an internal `group` string invisible at the `registry.py` level.

## What changed

`settings_store.py`'s registry `type_id` for any given setting is now that setting's own `group` - not a shared constant. `_sync_definition` calls `registry.register_type(d.group, ...)`/`registry.upsert_entry(d.group, d.key, ...)` instead of a fixed `"settings"` type_id; `get_setting`/`set_setting` follow the same change; `all_effective_settings()` now loops per `(group, scope)` pair instead of per scope alone, since scope is still resolved per-`SettingDef` and a group could in principle mix scopes (none currently does, but the loop handles it correctly either way rather than assuming otherwise).

`settings_store.py` itself is no longer *a* registrar - it's shared validation machinery (`SettingDef`, `register_schema`, `options` enum enforcement, `is_secret_ref` vault-reference enforcement, real defaults) that any domain module reuses. The registry-level identity of a settings domain is now its own group name, directly answering "what level does this have settings at" by construction - `registry_types` now shows `"sessions"`, `"self_installer"`, `"network"`, `"startup"`, `"volumes"` each as their own real row, the same way `"dependencies"`/`"gpu_devices"` already did, rather than one opaque `"settings"` type requiring a reader to parse a composite `entry_id` to find the real domain boundary.

## What did NOT need to change

Every external caller (`dependencies.py`, `gpu_admin.py`'s own use of settings for nothing directly, `drive_admin.py`, `settings_web.py`, `netpref.py`, `network.py`) calls `get_setting`/`set_setting`/`all_effective_settings`/`register_schema` - none of that public API's shape changed. 24 of `settings_store.py`'s own existing tests passed unchanged; only one test helper elsewhere (`test_drive_admin.py`'s `_corrupt_lvm_size_preset_directly`, which pokes a stale value directly into the registry to simulate corruption) needed updating, since it had hardcoded the old shared `type_id="settings"` + composite `entry_id="self_installer.lvm_size_preset"` shape directly.

## Verification performed

- Two new tests proving the actual property this refactor was for, not just that nothing broke: `test_each_settings_group_is_its_own_real_registry_type_not_one_shared_settings_type` (asserts `"sessions"`/`"self_installer"` each appear as distinct rows in the real `registry_types` table, and the old `"settings"` type_id does not) and `test_a_groups_entries_land_under_that_groups_own_type_id_in_the_real_db`.
- Real, non-test verification against both live databases: `network`, `self_installer`, and `startup` (GLOBAL, alongside `dependencies`/`gpu_devices`) each now show up as their own real `registry_types` row - confirmed by direct `sqlite3` inspection of `/etc/baseline/settings/master_config.db` and `/mnt/BASELINE/registry/foundation.db`, not just asserted from the code.
- Full suite: 1454/1454 (1452 before this record).
- **Known, harmless residue**: the real PROTECTED database still carries a leftover `"settings"` `registry_types` row from real runs made before this refactor landed - nothing reads it, and a fresh deployment starting from this code would never create it; left in place rather than manually scrubbed, since cleaning up historical dev-sandbox data isn't this record's job.
