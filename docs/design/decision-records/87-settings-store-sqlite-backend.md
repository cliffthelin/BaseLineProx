# Decision record: settings_store.py moves from a flat JSON file to SQLite, gains a schema registry

Status: **implemented, unit-tested (1351/1351 full suite, up from 1349).**

## What was asked

"There can be MANY MANY places a user should be reviewing and able to input. This is going to have to record everything an OS has for user preferences, everything every application has for user preferences. This is going to be an incredibly big configuration set that likely will turn into a SQLite database."

Follow-up, resolving the one open question directly: "SQLite is not a requirement if DuckDB or Postgres is a better fit... it just has to be available for sure once proxmox is loaded and preferably prior... possible JSON version should be pulled out of the DB for the earliest configuration requirements and let the rest reside in a DB that can be utilized from a standing proxmox and/or a core linux kernel."

## Engine choice: SQLite, not DuckDB or Postgres

The deciding constraint was availability "once proxmox is loaded and preferably prior... from a core linux kernel":

- **Postgres** needs a running server process, its own init, a listening socket - a nonstarter before any userspace (let alone Proxmox) is up. Disqualified outright by the "prior" requirement.
- **DuckDB** is embedded like SQLite (no server, single file) but is an OLAP engine - built for large columnar scans/aggregations, not the many small, frequent point reads/writes (`get_setting`/`set_setting`) this store actually does. Heavier binary, no real precedent running from a minimal/initramfs-style environment.
- **SQLite** is a library, not a service. It works anywhere Python's stdlib works - a rescue shell, the Proxmox installer's own minimal environment, a bare core-kernel context - with nothing extra to install (`sqlite3` is stdlib; `libsqlite3` ships in virtually every base Debian/Proxmox image). Its WAL mode gives real concurrent-reader/single-writer semantics for "many processes each writing their own settings," which a flat JSON file (read-whole-file, mutate one key, write-whole-file-back) never had.

## What was built

**`settings_store.py`** - real SQLite backend behind the *same* public API (`get_setting`, `set_setting`, `all_effective_settings`, `group_names`, `settings_in_group`) so every existing caller keeps working unchanged in shape, just without a `Runner` argument (sqlite3 is a stdlib embedded call, not an external-process/filesystem boundary this codebase's Runner-injection convention exists to abstract - a real temp-file SQLite database in a test IS the real implementation, not a fake standing in for one).

- One table, `settings(grp, key, value)`, `value` JSON-encoded for type fidelity (ints/strings/bools survive round-trip exactly).
- `register_schema(defs)` - the real answer to "every application has its own preferences": a module registers its own `SettingDef`s once (typically at import time) instead of `SCHEMA` growing forever in this one file. Refuses a duplicate `(group, key)` outright - a real collision is a bug in whichever module registered second.
- `export_bootstrap_snapshot(pairs)` - the "JSON version pulled out of the DB for the earliest configuration requirements" piece: a flat plain-dict snapshot of specific settings, for the one real case that can't open this database live - values baked into a Proxmox unattended-install answer file, which is applied by the Proxmox installer's own environment. `self_installer.py` already does exactly this in-process (resolves settings to plain values before ever writing `answer.toml`) - this function is the same pattern made reusable, not a new consumer invented for it.

**Fixed in the same pass, found while migrating**: `path: str = DEFAULT_DB_PATH` as a keyword default is bound once, at function-definition time - a real, classic Python bug that would have made `DEFAULT_DB_PATH` unpatchable after import (every test needing a temp database would have silently kept hitting the real default path). Caught immediately by the new test suite's own per-test isolation fixture failing with `PermissionError: /etc/baseline`. Fixed by defaulting to `None` and resolving `DEFAULT_DB_PATH` inside each function body instead, so a later override (test isolation, or any real deployment override) is honored.

**Call-site migration**: `admin_elevation.py`, `drive_admin.py` (`apply_volume_mode`, `build_self_installer`), `settings_web.py` (`handle_admin_view`, `handle_admin_edit`) all updated to stop threading a `Runner` through to `settings_store` calls. `handle_admin_view` no longer takes a `runner` parameter at all - it had one only to forward to `settings_store`, which no longer needs it; its former "no Runner configured -> handed off" refusal is gone since there's nothing left for it to guard. `drive_admin.build_self_installer`'s `settings_runner`/`RealRunner` plumbing (decision record 86) is gone too - replaced by a plain `settings_db_path` override, a net simplification.

**Test isolation**: new `tests/unit/conftest.py` autouse fixture (`_isolated_settings_store`) points `settings_store.DEFAULT_DB_PATH` at a per-test `tmp_path` for every test in the suite - not opt-in, so no future test can accidentally hit the real filesystem default by forgetting to override it.

**Known, deliberately-not-addressed loose end**: `admin_elevation.is_elevated`/`require_elevation` still take a now-fully-unused `runner` parameter (it existed only to forward into the old `settings_store.get_setting(runner, ...)` call). Left in place rather than chasing it through ~8 call sites and their tests - genuinely dead, but harmless, and removing it is unrelated churn beyond this record's actual scope.

## Verification performed

- RED confirmed: the stale-default-argument bug was caught live by the new autouse fixture raising `PermissionError` against `/etc/baseline` before the `path: str | None = None` fix landed.
- Full suite: 1351/1351 (1349 before this record).
- **Not verified**: no real deployment has yet read/written this database from an actual pre-Proxmox/rescue/core-kernel environment - the "available prior to Proxmox" requirement is satisfied by construction (sqlite3 has no service dependency), not by an observed real boot-time test.
