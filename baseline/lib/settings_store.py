"""The generic, extensible mechanism behind the "Admin" settings tab
and its many groups - potentially hundreds of individual settings
covering things like the drive to auto-start, read-only/write-only/
read-write mode, and session durations (decision record 76). This is
the storage/schema mechanism the eventual full taxonomy gets built on,
not the taxonomy itself - `SCHEMA` below is the real, concrete seed
this pass needs.

Real, Runner-injectable JSON storage on the BASELINE volume - shared,
system-level, survives a reinstall of the disposable stage, not scoped
to any one persona (auto-start-drive and session-duration policy apply
across the whole machine, not to one persona's own preferences).

`get_setting` always returns a real value - the schema default when
nothing's been explicitly set, never `None`/missing - so callers never
need a second "is this configured yet" check.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def path_exists(self, path):
            raise NotImplementedError

        def read_text(self, path):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def makedirs(self, path):
            raise NotImplementedError


# Direct instruction: "All user data including credentials and config
# and logs should go to the User Persistence partition" / "[USER
# PERSISTENCE] is the first and primary thing user persistence data
# does. It stores all configuration for the Machine." `/etc/baseline`
# is already bind-redirected onto USER_PERSISTENCE for every active
# persona (persist_bind_mounts.py's own REDIRECTS table) - this reuses
# that existing redirect rather than adding a new bind target, so
# every setting in this store now survives a disposable-stage rebuild.
DEFAULT_STORE_PATH = "/etc/baseline/settings/master_config.json"


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


# The real, concrete settings this pass actually needs. Meant to grow
# to "hundreds" over time - this is the seed, not the ceiling.
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


def _schema_by_key() -> dict:
    return {(s.group, s.key): s for s in SCHEMA}


def group_names() -> list:
    seen = []
    for s in SCHEMA:
        if s.group not in seen:
            seen.append(s.group)
    return seen


def settings_in_group(group: str) -> list:
    return [s for s in SCHEMA if s.group == group]


def _read_store(runner: Runner, path: str) -> dict:
    if not runner.path_exists(path):
        return {}
    try:
        return json.loads(runner.read_text(path))
    except ValueError:
        return {}


def get_setting(runner: Runner, group: str, key: str, *, path: str = DEFAULT_STORE_PATH):
    schema_map = _schema_by_key()
    if (group, key) not in schema_map:
        raise KeyError(f"unknown setting {group}.{key}")
    store = _read_store(runner, path)
    return store.get(group, {}).get(key, schema_map[(group, key)].default)


def set_setting(runner: Runner, group: str, key: str, value, *, path: str = DEFAULT_STORE_PATH) -> None:
    schema_map = _schema_by_key()
    if (group, key) not in schema_map:
        raise KeyError(f"unknown setting {group}.{key}")
    options = schema_map[(group, key)].options
    if options is not None and value not in options:
        raise ValueError(f"{group}.{key} must be one of {options!r}, got {value!r}")
    store = _read_store(runner, path)
    store.setdefault(group, {})[key] = value
    parent = path.rsplit("/", 1)[0]
    runner.makedirs(parent)
    runner.write_text_atomic(path, json.dumps(store, indent=2))


def all_effective_settings(runner: Runner, *, path: str = DEFAULT_STORE_PATH) -> dict:
    """Every schema-defined setting's current effective value (stored
    override or schema default), grouped - what an Admin settings tab
    would render, without needing to know the storage format."""
    store = _read_store(runner, path)
    result: dict = {}
    for s in SCHEMA:
        result.setdefault(s.group, {})[s.key] = store.get(s.group, {}).get(s.key, s.default)
    return result
