# Decision record: a real dependencies table + health-validation layer, in the same primary Baseline database

Status: **implemented, unit-tested (1376/1376 full suite, up from 1374 after decision record 87's 1349, minus a couple lines above where earlier work already landed).**

## What was asked

"Proceed with any SQLite Migrations and code redirects and start up points and check that its running points and check that it have values for the Installer. Make a primary Baseline SQLite if it doesn't already exist, I think it does, in which case we need to build all of this either in that same DB or have a heavily associated DB made and migrate in the configuration. A dependencies table needs to be in place to record not just systems field dependencies but install level and probably other levels as we grow this. Those dependencies should be predefined and validated before install begins and as health validations both at boot and intervals and adhoc calls. Some values will break things loudly some will break things silently. This will also help identify that and be referenced in things like stack traces or determining the system configuration for troubleshooting or just when building know what is in place."

Mid-turn addition: "Credentials and Tokens and such should just have references to their Vault location."

## Which primary database

Confirmed the user's own instinct: a Baseline SQLite database already existed - `sensors_history.db` (`/var/lib/baseline/sensors_history.db`, telemetry samples/collection intervals). Decided **not** to build the dependencies table there: sensor history is a different domain (high-write-volume time series, pruned/rotated) from config/dependency metadata (low-write-volume, rarely changes). Built it into `settings_store.py`'s database instead (`/etc/baseline/settings/master_config.db`, decision record 87) - genuinely the same domain (machine configuration), and its name already signals "primary."

## What was built

**`settings_store.py`** - added `SettingDef.is_secret_ref: bool` and `SECRET_REF_SCHEMES = ("vault://",)`. `set_setting` now refuses any value for an `is_secret_ref` setting that doesn't start with a recognized reference scheme. No actual vault backend exists in this codebase - this is the enforcement point that keeps a future one honest, not an integration with one. Storing a raw credential directly in this database would be exactly a **silent** failure per this same record's own severity model: nothing would crash, the secret would just be sitting in a config file.

**`dependencies.py`** (new module) - two new tables in the same primary database:
- `dependencies` - the real, queryable definitions (id, level, description, severity, phases, check_kind, check_args) - inspectable directly via a plain `sqlite3` CLI even outside Python, per "know what is in place."
- `dependency_check_results` - every check ever run, so the most recent result for any dependency is always available for troubleshooting.

`Dependency.level` is an open string ("system", "install" today; `register_dependencies` lets any future module add its own level, e.g. "persona", "app" - "probably other levels as we grow this," not a fixed enum). `Dependency.severity` is `LOUD` or `SILENT` per direct instruction ("some values will break things loudly some will break things silently") - only a LOUD failure is ever treated as a reason to refuse anything; a SILENT failure is recorded and surfaced (`dump_configuration_snapshot`), never used to block by itself, since blocking on a failure nobody expected to be loud would itself be a surprise.

Four real check kinds cover this pass's seed dependencies without needing a bespoke Python function per id: `binary_on_path`, `path_exists`, `python_module_importable`, `setting_configured` (validates a stored setting still resolves to one of its schema's own `options`). `register_check_kind` lets a future dependency register something more specific (e.g. GPG-chain verification, which already has its own real, tested implementation elsewhere - not duplicated here).

**Wired into all four phases, as asked**:
- `pre_install` - `drive_admin.build_self_installer` runs `dependencies.run_checks(phase=PRE_INSTALL)` before the pipeline starts; any LOUD failure refuses the action outright with the failing dependency's own id and detail in the message.
- `boot` - `persist_bind_mounts.main()` (the real per-boot mount-cascade entry point) runs `dependencies.run_checks(phase=BOOT)` after its own redirects, purely observational - a dependency failure (even LOUD) never changes this function's own return code. Gating boot itself on a health check would trade a working mount cascade for a new way to fail to boot, worse than a degraded-but-running machine a later troubleshooting pass can actually see the failure on.
- `interval` - new `baseline-dependency-check.timer`/`.service` (15-minute interval, `OnBootSec=10m`), mirroring `baseline-backup-recurring`'s existing pattern exactly, calling a new `baseline/bin/baseline-dependency-check` thin entry point.
- `adhoc` - new `drive_admin.run_health_check` action, registered in `ACTIONS` (a fifth action - see "real conflict" below), reusing the exact same `dependencies.run_checks` the other three phases call.

**`dump_configuration_snapshot()`** - the real "referenced in things like stack traces or determining the system configuration for troubleshooting" piece: one call returning every effective setting plus the latest result for every dependency, with currently-failing SILENT dependencies called out by id specifically (by definition, nothing else would have surfaced them).

## Real conflict found and resolved by direct instruction, not silently (same pattern as decision record 86)

Adding `run_health_check` as a fifth top-level action broke `test_describe_actions_lists_exactly_the_four_real_actions`, whose own docstring recorded the prior four-action cap. Flagged directly rather than silently updating the test: given how explicit this session's instruction was about wanting health checks reachable "as... adhoc calls" specifically (not just at boot/interval/pre-install), proceeded and updated the test with a docstring explaining why - matching this project's standing rule that a test only changes for a real, acknowledged design change.

## Real bug found and fixed in passing

`run_checks`'s first implementation opened one sqlite connection, ran every check inside an open write transaction, and committed once at the end. A `setting_configured` check calls back into `settings_store.get_setting`, which opens its **own** fresh connection to the same database file - real `SQLITE_BUSY` lock contention against the outer connection's open transaction, manifesting as a genuine ~10-second hang (Python's `sqlite3.connect` default 5-second busy timeout, hit twice) in this module's own test suite - not a hypothetical, caught immediately by `--durations`. Fixed by splitting `run_checks` into two passes: run every check to completion with no database connection of this function's own open at all, then open one connection purely to persist the already-computed results.

## Verification performed

- RED confirmed for the lock-contention bug (`--durations=10` showing five tests at exactly 10.01s each before the two-pass fix).
- New tests: `tests/unit/test_dependencies.py` (20 tests - seed shape, each check kind pass/fail, phase filtering, a broken check not crashing the run, loud-vs-silent filtering, latest-result-only semantics, snapshot content, duplicate-id/duplicate-check-kind refusal, real on-disk persistence), `test_settings_store.py` (vault-reference enforcement, both directions), `test_drive_admin.py` (pre-install refusal on a real LOUD failure with a genuinely valid drive - proving the *dependency* check is what refused, not the safety gate; `run_health_check` pass/fail), `test_persist_bind_mounts.py` (boot-phase checks run and print but never affect the return code).
- `tools/check_provision_deploys_all_imports.py` and the rest of `boot/provision.sh`'s own self-verification block updated and passing (new module, bin script, service, timer all staged; unit count "eight" -> "nine").
- Full suite: 1376/1376.
- **Not verified**: no real deployment has yet observed `baseline-dependency-check.timer` actually firing on real hardware, nor has anything real yet been stored as an `is_secret_ref` setting (no credential-shaped setting exists in `SCHEMA` yet to exercise it end-to-end beyond the unit tests' own synthetic registrations).
