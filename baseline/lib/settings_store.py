"""The generic, extensible mechanism behind the "Admin" settings tab
and its many groups - potentially hundreds, eventually thousands, of
individual settings covering every OS-level preference and every
application's own preferences (decision record 87, direct instruction:
"this is going to have to record everything an OS has for user
preferences, everything every application has for user preferences...
likely turn into a SQLite database"). `SCHEMA` below is the real,
concrete built-in seed; `register_schema` is how an application adds
its own settings later without this file growing forever.

**Storage engine: SQLite, not Postgres or DuckDB** - the deciding
requirement was "available once proxmox is loaded and preferable
prior... utilized from a standing proxmox and/or a core linux kernel."
Postgres needs a running server process and is a nonstarter before
Proxmox (or any userspace) is up. DuckDB is embedded like SQLite but is
an OLAP engine built for large columnar scans, not the many small,
frequent point reads/writes (`get_setting`/`set_setting`) this store
actually does. SQLite is a library, not a service - it works from a
rescue shell or the installer's own minimal environment with nothing
but the Python stdlib, and its WAL mode gives real concurrent-reader/
single-writer semantics for the "many processes each writing their own
settings" case a flat JSON file never had.

`get_setting` always returns a real value - the schema default when
nothing's been explicitly set, never `None`/missing - so callers never
need a second "is this configured yet" check. No `Runner` injection
here (unlike most of this codebase) - sqlite3 is a stdlib embedded
library call, not an external process/network boundary, so a real
temp-file or in-memory database in a test IS the real implementation,
not a fake standing in for one.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass

# Direct instruction: "All user data including credentials and config
# and logs should go to the User Persistence partition" / "[USER
# PERSISTENCE] is the first and primary thing user persistence data
# does. It stores all configuration for the Machine." `/etc/baseline`
# is already bind-redirected onto USER_PERSISTENCE for every active
# persona (persist_bind_mounts.py's own REDIRECTS table) - this reuses
# that existing redirect rather than adding a new bind target, so
# every setting in this store survives a disposable-stage rebuild.
DEFAULT_DB_PATH = "/etc/baseline/settings/master_config.db"


@dataclass(frozen=True)
class SettingDef:
    group: str
    key: str
    default: object
    description: str = ""
    # Fixed, enumerated choices for this setting - when set, this is
    # the ONLY way a value here may be entered anywhere in the web app
    # (a <select>, never free text): "everything you asked me to do
    # must be selectable without a keyboard." `set_setting` refuses any
    # value not in this set.
    options: tuple | None = None
    # Direct instruction: "Credentials and Tokens and such should just
    # have references to their Vault location." When True, this
    # setting's value is never the actual secret - only a reference
    # string into wherever secrets are actually kept (a vault path,
    # e.g. "vault://secret/data/proxmox/api-token"), enforced by
    # `set_setting` below. This database has no special protection
    # against being read by anything that can read the file - storing
    # a raw credential in it directly would be a silent, not loud,
    # failure (nothing crashes; the secret is just sitting in a config
    # file) - exactly the class of problem this flag exists to catch
    # before it happens, not after.
    is_secret_ref: bool = False


# Reference-string schemes `set_setting` accepts for an `is_secret_ref`
# setting. No actual vault backend exists in this codebase yet - this
# is the enforcement point that keeps a future one honest, not an
# integration with one.
SECRET_REF_SCHEMES = ("vault://",)


# The real, concrete built-in settings this pass needs. Meant to grow
# to "everything an OS and every application has" over time via
# `register_schema`, not by this tuple growing forever - this is the
# seed, not the ceiling.
SCHEMA = (
    SettingDef("sessions", "default_session_ttl_hours", 24,
               "Max session length before reauthorization is required (non-admin personas)."),
    SettingDef("sessions", "admin_session_ttl_hours", 24,
               "Max session length for the admin persona's own login - same default as everyone "
               "else, per direct correction (\"24 hours is the default limit not one hour\")."),
    SettingDef("sessions", "admin_elevation_ttl_minutes", 15,
               "How long admin's cross-persona passphrase stays cached before it must be "
               "re-entered - sudo-like, deliberately much shorter than the base session."),
    SettingDef("startup", "auto_start_persona", "personal",
               "Which persona's USER_PERSISTENCE volume mounts automatically on boot."),
    # Per-volume mode for the three shared volumes (never persona-scoped
    # - matches drive_installer.SHARED_VOLUMES exactly). Real, storable,
    # editable values ("read-write", "read-only", or "write-only", per
    # direct instruction); wiring an effective value here into
    # drive_installer.py's actual mount behavior is a separate, deferred
    # integration step, matching FileBackedSectionApplier's own
    # "saved here, real application is a follow-up" precedent - this is
    # the settings-tab storage half, not the enforcement half.
    SettingDef("volumes", "baseline_mode", "read-write",
               "Mount mode for the shared BASELINE volume: read-write, read-only, or write-only."),
    SettingDef("volumes", "installer_cache_mode", "read-write",
               "Mount mode for the shared INSTALLER_CACHE volume: read-write, read-only, or write-only."),
    SettingDef("volumes", "session_temp_mode", "read-write",
               "Mount mode for the shared SESSION_TEMP volume: read-write, read-only, or write-only."),
    # Pre-populated self-installer configuration (decision record 86):
    # "the self installer[should] just finish the install from the
    # pre-populated data added to the User Persistence." Every value
    # here is a preset chosen from the Admin tab's dropdowns ahead of
    # time - build_self_installer then needs no input from an operator
    # beyond which drive to click.
    SettingDef("self_installer", "lvm_size_preset", "medium",
               "Disk-space split for a self-installed machine (root/container-storage/swap sizing).",
               options=("small", "medium", "large")),
    SettingDef("self_installer", "fqdn", "baseline.local",
               "Hostname the self-installed machine answers to.",
               options=("baseline.local", "baseline.home.arpa", "baseline.lan")),
    SettingDef("self_installer", "memory_mb", 3072,
               "RAM given to the automated-install process itself while it installs.",
               options=(2048, 3072, 4096, 8192)),
)

# The live, growable registry every lookup actually reads from -
# `SCHEMA` is just its initial contents. Kept separate from `SCHEMA`
# itself so `SCHEMA` stays a stable, inspectable "what ships built-in"
# constant even after other modules register more at import time.
_REGISTRY: list[SettingDef] = list(SCHEMA)


def register_schema(defs) -> None:
    """The real extensibility point for "every application has its own
    preferences" - a module registers its own settings once (typically
    at import time) instead of this file growing forever. Refuses a
    duplicate (group, key) outright rather than silently letting one
    app's registration shadow another's - a real collision is a real
    bug in whichever module registered second, not something to paper
    over."""
    existing = {(s.group, s.key) for s in _REGISTRY}
    for d in defs:
        if (d.group, d.key) in existing:
            raise ValueError(f"setting {d.group}.{d.key} is already registered")
        _REGISTRY.append(d)
        existing.add((d.group, d.key))


def _schema_by_key() -> dict:
    return {(s.group, s.key): s for s in _REGISTRY}


def group_names() -> list:
    seen = []
    for s in _REGISTRY:
        if s.group not in seen:
            seen.append(s.group)
    return seen


def settings_in_group(group: str) -> list:
    return [s for s in _REGISTRY if s.group == group]


def _connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "grp TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
        "PRIMARY KEY (grp, key))"
    )
    return conn


def get_setting(group: str, key: str, *, path: str | None = None):
    # `path` resolves DEFAULT_DB_PATH at CALL time, not def time - a
    # default argument value is bound once, when this function object
    # is created at import, so binding it directly here would freeze
    # in the very first DEFAULT_DB_PATH this module ever saw and never
    # see a later override again (real bug, caught by the test suite's
    # own per-test DB isolation needing to redirect this path).
    path = path if path is not None else DEFAULT_DB_PATH
    schema_map = _schema_by_key()
    if (group, key) not in schema_map:
        raise KeyError(f"unknown setting {group}.{key}")
    with closing(_connect(path)) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE grp = ? AND key = ?", (group, key)
        ).fetchone()
    if row is None:
        return schema_map[(group, key)].default
    return json.loads(row[0])


def set_setting(group: str, key: str, value, *, path: str | None = None) -> None:
    path = path if path is not None else DEFAULT_DB_PATH
    schema_map = _schema_by_key()
    if (group, key) not in schema_map:
        raise KeyError(f"unknown setting {group}.{key}")
    definition = schema_map[(group, key)]
    options = definition.options
    if options is not None and value not in options:
        raise ValueError(f"{group}.{key} must be one of {options!r}, got {value!r}")
    if definition.is_secret_ref:
        if not isinstance(value, str) or not value.startswith(SECRET_REF_SCHEMES):
            raise ValueError(
                f"{group}.{key} holds a vault reference, not a raw value - must start with "
                f"one of {SECRET_REF_SCHEMES!r}, got {value!r}")
    with closing(_connect(path)) as conn:
        conn.execute(
            "INSERT INTO settings (grp, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(grp, key) DO UPDATE SET value = excluded.value",
            (group, key, json.dumps(value)),
        )
        conn.commit()


def all_effective_settings(*, path: str | None = None) -> dict:
    """Every schema-defined setting's current effective value (stored
    override or schema default), grouped - what an Admin settings tab
    would render, without needing to know the storage format."""
    path = path if path is not None else DEFAULT_DB_PATH
    with closing(_connect(path)) as conn:
        stored = {(r[0], r[1]): json.loads(r[2]) for r in conn.execute("SELECT grp, key, value FROM settings")}
    result: dict = {}
    for s in _REGISTRY:
        result.setdefault(s.group, {})[s.key] = stored.get((s.group, s.key), s.default)
    return result


def export_bootstrap_snapshot(pairs, *, path: str | None = None) -> dict:
    """Pulls a flat, plain-dict snapshot of specific (group, key) pairs
    out of the database - for the rare real consumer that cannot open
    this database live (namely: values baked into the Proxmox
    unattended-install answer file, which is applied by the Proxmox
    installer's own environment, not this one - see
    `self_installer.py`, which resolves its settings this way before
    ever writing an answer.toml). Not a general-purpose export - a
    caller that CAN reach this database directly should just call
    `get_setting` instead of taking a snapshot."""
    return {f"{group}.{key}": get_setting(group, key, path=path) for group, key in pairs}
