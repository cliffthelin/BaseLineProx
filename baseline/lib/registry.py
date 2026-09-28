"""The foundational registry mechanism every registry-shaped subsystem
in Baseline builds on (decision record 89, direct instruction): "the
registry... should be foundational Baseline table concepts that are
not new tables every time we need a register... plan it dynamically to
address potentially thousands of registries and hundreds of varying
registry types." `settings_store.py` and `dependencies.py` were each
about to grow their own bespoke table the moment a third registry-
shaped need showed up - this file is what stops that pattern: three
generic tables, reused by every registry type forever, never a fourth
table just because a new type of thing needs registering.

Three tables, in either physical database (see "Scope" below):

- `registry_types` - what kinds of registry exist at all (id,
  description, default_scope). Metadata about a *type*, not its
  entries.
- `registry_entries` - every entry of every type, one row each
  (type_id, entry_id, attributes JSON, value JSON, scope). `attributes`
  holds whatever static shape that type needs (a setting's default/
  options/description, a dependency's severity/phases/check_kind/
  check_args, or anything a future type needs) - a flexible JSON blob
  is the only way to avoid a bespoke column set, and therefore a
  bespoke table, per type. `value` is the current *stored* value for a
  stateful type (a setting's override); left `None` for a definition-
  only type (a dependency has nothing to "set", only to check).
- `registry_events` - an append-only log any registry type can use for
  history (a dependency's check results, a setting's change history,
  or anything a future type needs) - one shared table, not one per
  type, distinguished by `type_id`/`entry_id`/`kind`.

**Scope, and why there are two physical databases, not one** (direct
instruction: "Some may be allowed as a global foundation for recovery
while the rest are protected with the user persistence"):

- `GLOBAL` entries live in a database on the shared, non-persona
  `/mnt/BASELINE` volume (`drive_installer.SHARED_VOLUMES` - a real,
  separate LVM volume from any one persona's own
  `USER_PERSISTENCE_<PERSONA>` volume, present regardless of which
  persona is active or whether a persona's own volume is broken).
  Reachable during recovery precisely because it does not depend on
  the thing recovery mode exists to work around.
- `PROTECTED` entries live in the existing USER_PERSISTENCE-redirected
  database (`settings_store.DEFAULT_DB_PATH`, decision record 87) -
  gone or inaccessible exactly when that persona's persistence is
  broken, which is correct for anything that should NOT be trusted or
  available during recovery.

A registry type declares a *default* scope, but an individual entry
may override it - "some may be... global... while the rest are
protected" reads as a real, per-entry decision (e.g.
`startup.auto_start_persona` must be GLOBAL: recovery needs to know
which persona to even attempt mounting, and asking that question from
inside the very volume that might be the thing that's broken is
circular), not only a per-type default.

No `Runner` injection - same reasoning as `settings_store.py`/
`dependencies.py`: sqlite3 is a stdlib embedded call, not an external-
process/filesystem boundary this codebase's Runner convention exists
to abstract.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing

GLOBAL = "global"
PROTECTED = "protected"
SCOPES = (GLOBAL, PROTECTED)

# The shared, non-persona volume - not gated on any one persona's own
# USER_PERSISTENCE_<PERSONA> being mounted or healthy.
GLOBAL_DB_PATH = "/mnt/BASELINE/registry/foundation.db"

# The USER_PERSISTENCE-redirected database settings_store.py already
# established (decision record 87). Imported lazily inside functions,
# not at module level, to avoid a real import cycle - settings_store.py
# itself is built on this module.


def _protected_db_path() -> str:
    import settings_store
    return settings_store.DEFAULT_DB_PATH


def _path_for_scope(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r} - must be one of {SCOPES}")
    return GLOBAL_DB_PATH if scope == GLOBAL else _protected_db_path()


def _connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    # A real writer-vs-writer collision (two processes/timers landing on
    # the same file within the same instant) should wait briefly and
    # retry, not fail outright the moment it happens - WAL mode already
    # lets any number of readers proceed concurrently with a writer
    # without blocking at all; this PRAGMA only governs the rarer
    # writer-vs-writer case.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS registry_types ("
        "type_id TEXT PRIMARY KEY, description TEXT NOT NULL, default_scope TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS registry_entries ("
        "type_id TEXT NOT NULL, entry_id TEXT NOT NULL, attributes TEXT NOT NULL, "
        "value TEXT, scope TEXT NOT NULL, PRIMARY KEY (type_id, entry_id))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS registry_events ("
        "row_id INTEGER PRIMARY KEY AUTOINCREMENT, type_id TEXT NOT NULL, entry_id TEXT NOT NULL, "
        "kind TEXT NOT NULL, at REAL NOT NULL, data TEXT NOT NULL)"
    )
    return conn


def register_type(type_id: str, description: str, *, default_scope: str = PROTECTED) -> None:
    """Idempotent - safe to call every time a module registering
    entries of this type is imported, matching `settings_store.py`/
    `dependencies.py`'s own "seed at import, real state in the
    database" precedent.

    Writes only into `default_scope`'s own database - **not** both.
    `registry_types` is pure description metadata (nothing else joins
    against it; there is no foreign key from `registry_entries`), so
    there is no correctness reason to touch the other database at all.
    Found as a real bug by actually running a health check for real
    (not a fake): `dependencies.py` registers its type as GLOBAL-only,
    but this function used to write into the PROTECTED database too
    "for discoverability" - meaning a purely GLOBAL type could never
    even be registered on a machine where PROTECTED (the USER_PERSISTENCE-
    redirected path) doesn't exist or isn't writable, which defeats the
    entire point of GLOBAL entries being usable independent of
    USER_PERSISTENCE - precisely the scenario recovery mode exists
    for. A caller that later stores entries of this type under the
    *other* scope as well just won't have this type's description
    pre-registered there - entries work regardless, since nothing
    reads `registry_types` to validate an entry write."""
    if default_scope not in SCOPES:
        raise ValueError(f"unknown default_scope {default_scope!r} - must be one of {SCOPES}")
    path = _path_for_scope(default_scope)
    with closing(_connect(path)) as conn:
        conn.execute(
            "INSERT INTO registry_types (type_id, description, default_scope) VALUES (?, ?, ?) "
            "ON CONFLICT(type_id) DO UPDATE SET description=excluded.description, "
            "default_scope=excluded.default_scope",
            (type_id, description, default_scope),
        )
        conn.commit()


def upsert_entry(type_id: str, entry_id: str, *, attributes: dict, scope: str, value=None) -> None:
    """Writes (or updates) one entry's definition, and its current
    value if given. Passing `value=None` leaves an existing stored
    value untouched (a definition re-sync must never clobber a real
    override) - use `set_value` to explicitly clear or change a value."""
    path = _path_for_scope(scope)
    with closing(_connect(path)) as conn:
        if value is None:
            conn.execute(
                "INSERT INTO registry_entries (type_id, entry_id, attributes, value, scope) "
                "VALUES (?, ?, ?, NULL, ?) ON CONFLICT(type_id, entry_id) DO UPDATE SET "
                "attributes=excluded.attributes, scope=excluded.scope",
                (type_id, entry_id, json.dumps(attributes), scope),
            )
        else:
            conn.execute(
                "INSERT INTO registry_entries (type_id, entry_id, attributes, value, scope) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(type_id, entry_id) DO UPDATE SET "
                "attributes=excluded.attributes, value=excluded.value, scope=excluded.scope",
                (type_id, entry_id, json.dumps(attributes), json.dumps(value), scope),
            )
        conn.commit()


def set_value(type_id: str, entry_id: str, value, *, scope: str) -> None:
    """Updates only an entry's stored value - the real "set_setting"-
    shaped operation. Refuses if the entry's definition doesn't exist
    yet (a value with no definition is meaningless - nothing would
    ever know its schema, options, or default)."""
    path = _path_for_scope(scope)
    with closing(_connect(path)) as conn:
        cur = conn.execute(
            "UPDATE registry_entries SET value = ? WHERE type_id = ? AND entry_id = ?",
            (json.dumps(value), type_id, entry_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"no registered entry {type_id}.{entry_id} to set a value on")
        conn.commit()


def get_entry(type_id: str, entry_id: str, *, scope: str) -> dict | None:
    path = _path_for_scope(scope)
    with closing(_connect(path)) as conn:
        row = conn.execute(
            "SELECT attributes, value FROM registry_entries WHERE type_id = ? AND entry_id = ?",
            (type_id, entry_id),
        ).fetchone()
    if row is None:
        return None
    return {"attributes": json.loads(row[0]), "value": json.loads(row[1]) if row[1] is not None else None}


def list_entries(type_id: str, *, scope: str) -> dict:
    """Every entry of `type_id` currently stored at `scope` - a caller
    juggling entries split across both scopes calls this once per
    scope and merges, rather than this function guessing which
    database to prefer."""
    path = _path_for_scope(scope)
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            "SELECT entry_id, attributes, value FROM registry_entries WHERE type_id = ?", (type_id,)
        ).fetchall()
    return {
        r[0]: {"attributes": json.loads(r[1]), "value": json.loads(r[2]) if r[2] is not None else None}
        for r in rows
    }


def record_event(type_id: str, entry_id: str, kind: str, data: dict, *, scope: str, at: float | None = None) -> None:
    path = _path_for_scope(scope)
    at = at if at is not None else time.time()
    with closing(_connect(path)) as conn:
        conn.execute(
            "INSERT INTO registry_events (type_id, entry_id, kind, at, data) VALUES (?, ?, ?, ?, ?)",
            (type_id, entry_id, kind, at, json.dumps(data)),
        )
        conn.commit()


def latest_events(type_id: str, *, scope: str, kind: str | None = None) -> dict:
    """One entry per `entry_id` - its most recent event of `kind`
    (or, if `kind` is omitted, its most recent event of any kind).
    What a troubleshooting dump actually wants: not a whole history,
    just "what's true right now.\""""
    path = _path_for_scope(scope)
    with closing(_connect(path)) as conn:
        if kind is None:
            rows = conn.execute(
                "SELECT entry_id, kind, at, data FROM registry_events WHERE type_id = ? AND "
                "(entry_id, at) IN (SELECT entry_id, MAX(at) FROM registry_events WHERE type_id = ? GROUP BY entry_id)",
                (type_id, type_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT entry_id, kind, at, data FROM registry_events WHERE type_id = ? AND kind = ? AND "
                "(entry_id, at) IN (SELECT entry_id, MAX(at) FROM registry_events "
                "WHERE type_id = ? AND kind = ? GROUP BY entry_id)",
                (type_id, kind, type_id, kind),
            ).fetchall()
    return {r[0]: {"kind": r[1], "at": r[2], **json.loads(r[3])} for r in rows}
