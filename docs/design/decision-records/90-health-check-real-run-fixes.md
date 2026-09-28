# Decision record: running `run_health_check` for real found two real GLOBAL/PROTECTED scope bugs

Status: **implemented, unit-tested (1394/1394 full suite, up from 1391).**

## What was asked

"Run the health check action for real and fix anything issues found."

## What running it for real actually found

`PYTHONPATH=baseline/lib python3 -c "import drive_admin as da; da.run_health_check(None)"` on this development sandbox (a plain, non-root user, no `/etc/baseline` or `/mnt/BASELINE` yet - i.e. NOT a deployed, root-run Baseline machine) crashed outright:

```
PermissionError: [Errno 13] Permission denied: '/etc/baseline'
```

Two real bugs, both in the same shape, both only visible by actually executing the code rather than reading it or running it against fakes:

1. **`registry.register_type` wrote into BOTH physical databases unconditionally**, "for discoverability," regardless of whether a type's entries ever used the other scope at all. `dependencies.py` registers its type as GLOBAL-only - but every call to sync a dependency's definition still tried to also write into the PROTECTED (USER_PERSISTENCE-redirected) database just to register the type's *description* there too. On a machine where PROTECTED doesn't exist or isn't writable (this sandbox; also, genuinely, any machine mid-recovery with a broken USER_PERSISTENCE), that call raised - meaning a purely GLOBAL type could never even be registered, defeating the entire point of GLOBAL existing independent of USER_PERSISTENCE.

2. **`settings_store._sync_definition` and `dependencies._sync_definition` each hardcoded a fixed scope** (`PROTECTED` and `GLOBAL` respectively) as `register_type`'s target, regardless of the specific entry actually being synced. Reading the GLOBAL setting `startup.auto_start_persona` still called `register_type(..., default_scope=PROTECTED)` - meaning even a read of a setting explicitly designed to survive a broken USER_PERSISTENCE (decision record 89's own stated reason for that setting being GLOBAL) would fail if PROTECTED wasn't reachable, which is precisely the scenario it exists to survive.

## What was fixed

- `registry.register_type` now writes only into `default_scope`'s own database - never both. `registry_types` is pure description metadata; nothing joins against it or enforces anything from it, so there was never a correctness reason to touch the other database.
- Both `_sync_definition` functions now pass the entry's own `scope` (`d.scope`) to `register_type`, not a hardcoded constant - so registering/reading any entry only ever touches the one database that entry actually needs.

## Verification performed

- RED confirmed live, not synthetically: the exact crash above, from a real, unmodified run against real default paths on this sandbox.
- After the fix, the same real run no longer crashes - `system.sqlite3_importable` and `system.openssl_on_path` (both GLOBAL) report OK; `install.self_installer_lvm_preset_valid`/`fqdn_valid` (both PROTECTED, since they read `self_installer.*` settings) report a clean, graceful failure with a clear detail message (`PermissionError` caught and recorded, never crashing the run) rather than an unhandled exception - **expected and correct** on this non-root sandbox lacking `/etc/baseline`, not a remaining bug: a real deployed Baseline machine's own services (`baseline.service`, `baseline-web.service`) already run as root, so this specific permission gap does not exist there.
- Three new regression tests proving the actual guarantee, not just the absence of a crash on this one sandbox: `test_registry.py::test_register_type_writes_only_to_its_own_scopes_database`, `test_settings_store.py::test_get_setting_for_a_global_setting_never_requires_protected_to_be_reachable`, `test_dependencies.py::test_run_checks_for_global_dependencies_never_requires_protected_to_be_reachable` - each monkeypatches PROTECTED to an unreachable path and proves the corresponding GLOBAL operation still succeeds.
- Full suite: 1394/1394 (1391 before this record).
- **Not verified**: no root-run/production-equivalent environment has been used to confirm the PROTECTED-scope checks (`install.self_installer_lvm_preset_valid`/`fqdn_valid`) actually pass end-to-end once `/etc/baseline` exists and is writable - only that they now fail *gracefully* rather than crashing when it doesn't. Setting up `/etc/baseline` on this real machine to complete that verification would mean creating root-owned system paths outside this repository - not done without asking first.
