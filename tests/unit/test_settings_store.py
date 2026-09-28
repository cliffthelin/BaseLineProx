"""Tests for settings_store.py - the generic, extensible mechanism
behind the "Admin" settings tab and its many groups (decision records
76, 87). Real SQLite storage - the conftest.py `_isolated_settings_store`
autouse fixture points `DEFAULT_DB_PATH` at a per-test tmp_path, so
every test here exercises the real sqlite3 engine against a real,
disposable file - no Runner/fake needed, matching this module's own
"sqlite3 is a stdlib embedded call, not a boundary to fake" design."""
import settings_store as ss


def test_group_names_lists_every_real_group_at_least_once():
    names = ss.group_names()
    assert "sessions" in names
    assert "startup" in names
    assert "volumes" in names
    # no duplicates
    assert len(names) == len(set(names))


def test_volumes_group_covers_every_shared_volume_and_defaults_to_read_write():
    volume_settings = ss.settings_in_group("volumes")
    assert {s.key for s in volume_settings} == {"baseline_mode", "installer_cache_mode", "session_temp_mode"}
    for s in volume_settings:
        assert ss.get_setting("volumes", s.key) == "read-write"


def test_settings_in_group_returns_only_that_groups_definitions():
    session_settings = ss.settings_in_group("sessions")
    assert all(s.group == "sessions" for s in session_settings)
    assert {s.key for s in session_settings} >= {
        "default_session_ttl_hours", "admin_session_ttl_hours", "admin_elevation_ttl_minutes"}


def test_get_setting_returns_the_schema_default_when_never_set():
    assert ss.get_setting("sessions", "default_session_ttl_hours") == 24


def test_get_setting_admin_session_ttl_defaults_to_24_not_1():
    """Direct correction: "24 hours is the default limit not one
    hour" - admin's own base session uses the same 24h default as
    everyone else."""
    assert ss.get_setting("sessions", "admin_session_ttl_hours") == 24


def test_get_setting_admin_elevation_ttl_defaults_to_15_minutes():
    assert ss.get_setting("sessions", "admin_elevation_ttl_minutes") == 15


def test_get_setting_raises_for_an_unknown_setting():
    try:
        ss.get_setting("sessions", "not_a_real_setting")
        assert False, "should have raised"
    except KeyError:
        pass


def test_set_setting_then_get_returns_the_override():
    ss.set_setting("sessions", "default_session_ttl_hours", 8)
    assert ss.get_setting("sessions", "default_session_ttl_hours") == 8


def test_set_setting_persists_across_separate_connections():
    """Real regression coverage for the sqlite migration: each
    get_setting/set_setting call opens its own connection (no shared
    in-memory state) - this proves a value written by one call is
    genuinely durable on disk for a later, independent call to see,
    not just held in a live Python object."""
    ss.set_setting("startup", "auto_start_persona", "work")
    assert ss.get_setting("startup", "auto_start_persona") == "work"
    assert ss.get_setting("startup", "auto_start_persona") == "work"


def test_set_setting_only_affects_the_named_setting():
    ss.set_setting("sessions", "admin_elevation_ttl_minutes", 5)
    assert ss.get_setting("sessions", "default_session_ttl_hours") == 24


def test_set_setting_raises_for_an_unknown_setting_without_writing_anything():
    try:
        ss.set_setting("sessions", "not_a_real_setting", 1)
        assert False, "should have raised"
    except KeyError:
        pass
    assert ss.all_effective_settings() == {
        group: {s.key: s.default for s in ss.settings_in_group(group)} for group in ss.group_names()
    }


def test_all_effective_settings_includes_every_schema_entry_with_defaults():
    effective = ss.all_effective_settings()
    assert effective["sessions"]["default_session_ttl_hours"] == 24
    assert effective["startup"]["auto_start_persona"] == "personal"


def test_all_effective_settings_reflects_a_real_override():
    ss.set_setting("startup", "auto_start_persona", "admin")
    effective = ss.all_effective_settings()
    assert effective["startup"]["auto_start_persona"] == "admin"
    # everything else in the group stays at its default
    assert effective["sessions"]["default_session_ttl_hours"] == 24


def test_store_lives_under_the_user_persistence_redirect_by_default():
    # /etc/baseline is bind-redirected onto USER_PERSISTENCE (persist_bind_mounts.py)
    # - direct instruction: all config must survive a disposable-stage rebuild.
    # Checks the module's own source for the real shipped default, since the
    # autouse fixture in conftest.py deliberately overrides the live
    # `DEFAULT_DB_PATH` attribute for every test's isolation.
    import inspect
    assert 'DEFAULT_DB_PATH = "/etc/baseline/' in inspect.getsource(ss)


def test_self_installer_group_covers_every_pre_populated_field():
    settings = ss.settings_in_group("self_installer")
    assert {s.key for s in settings} == {"lvm_size_preset", "fqdn", "memory_mb"}
    for s in settings:
        assert s.options is not None, f"{s.key} must be selectable, never free text"


def test_set_setting_rejects_a_value_outside_the_defined_options():
    try:
        ss.set_setting("self_installer", "lvm_size_preset", "gigantic")
        assert False, "should have raised"
    except ValueError:
        pass
    assert ss.get_setting("self_installer", "lvm_size_preset") == "medium"


def test_set_setting_accepts_a_value_inside_the_defined_options():
    ss.set_setting("self_installer", "lvm_size_preset", "large")
    assert ss.get_setting("self_installer", "lvm_size_preset") == "large"


def test_set_setting_with_no_options_defined_accepts_any_value():
    ss.set_setting("sessions", "default_session_ttl_hours", 6)
    assert ss.get_setting("sessions", "default_session_ttl_hours") == 6


# -- register_schema (decision record 87: "every application has its
# own preferences" - the real extensibility point, not a growing
# hardcoded tuple) --------------------------------------------------

def test_register_schema_adds_a_new_group_real_apps_can_use():
    ss.register_schema([
        ss.SettingDef("demo_app", "greeting", "hello", options=("hello", "hi"))
    ])
    try:
        assert "demo_app" in ss.group_names()
        assert ss.get_setting("demo_app", "greeting") == "hello"
        ss.set_setting("demo_app", "greeting", "hi")
        assert ss.get_setting("demo_app", "greeting") == "hi"
    finally:
        ss._REGISTRY[:] = [s for s in ss._REGISTRY if s.group != "demo_app"]


def test_register_schema_refuses_a_duplicate_group_and_key():
    try:
        ss.register_schema([ss.SettingDef("sessions", "default_session_ttl_hours", 1)])
        assert False, "should have raised"
    except ValueError:
        pass
    # the real, original built-in definition is untouched
    assert ss.get_setting("sessions", "default_session_ttl_hours") == 24


# -- export_bootstrap_snapshot (the one real case a caller can't reach
# this database live - values baked into a Proxmox answer.toml by
# self_installer.py) --------------------------------------------------

def test_export_bootstrap_snapshot_returns_a_flat_plain_dict():
    ss.set_setting("self_installer", "fqdn", "baseline.home.arpa")
    snapshot = ss.export_bootstrap_snapshot([
        ("self_installer", "fqdn"), ("self_installer", "lvm_size_preset"),
    ])
    assert snapshot == {
        "self_installer.fqdn": "baseline.home.arpa",
        "self_installer.lvm_size_preset": "medium",
    }
