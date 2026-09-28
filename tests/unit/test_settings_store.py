"""Tests for settings_store.py - the generic, extensible mechanism
behind the "Admin" settings tab and its many groups (decision record
76). Real, Runner-injectable JSON storage on BASELINE (shared,
system-level, survives a reinstall). This is the storage/schema
mechanism the eventual hundreds-of-settings taxonomy gets built on -
the schema below is the real, concrete seed this pass needs, not the
ceiling."""
from fake_runner import FakeRunner

import settings_store as ss


def test_group_names_lists_every_real_group_at_least_once():
    names = ss.group_names()
    assert "sessions" in names
    assert "startup" in names
    assert "volumes" in names
    # no duplicates
    assert len(names) == len(set(names))


def test_volumes_group_covers_every_shared_volume_and_defaults_to_read_write():
    runner = FakeRunner()
    volume_settings = ss.settings_in_group("volumes")
    assert {s.key for s in volume_settings} == {"baseline_mode", "installer_cache_mode", "session_temp_mode"}
    for s in volume_settings:
        assert ss.get_setting(runner, "volumes", s.key) == "read-write"


def test_settings_in_group_returns_only_that_groups_definitions():
    session_settings = ss.settings_in_group("sessions")
    assert all(s.group == "sessions" for s in session_settings)
    assert {s.key for s in session_settings} >= {
        "default_session_ttl_hours", "admin_session_ttl_hours", "admin_elevation_ttl_minutes"}


def test_get_setting_returns_the_schema_default_when_never_set():
    runner = FakeRunner()
    assert ss.get_setting(runner, "sessions", "default_session_ttl_hours") == 24


def test_get_setting_admin_session_ttl_defaults_to_24_not_1():
    """Direct correction: "24 hours is the default limit not one
    hour" - admin's own base session uses the same 24h default as
    everyone else."""
    runner = FakeRunner()
    assert ss.get_setting(runner, "sessions", "admin_session_ttl_hours") == 24


def test_get_setting_admin_elevation_ttl_defaults_to_15_minutes():
    runner = FakeRunner()
    assert ss.get_setting(runner, "sessions", "admin_elevation_ttl_minutes") == 15


def test_get_setting_raises_for_an_unknown_setting():
    runner = FakeRunner()
    try:
        ss.get_setting(runner, "sessions", "not_a_real_setting")
        assert False, "should have raised"
    except KeyError:
        pass


def test_set_setting_then_get_returns_the_override():
    runner = FakeRunner()
    ss.set_setting(runner, "sessions", "default_session_ttl_hours", 8)
    assert ss.get_setting(runner, "sessions", "default_session_ttl_hours") == 8


def test_set_setting_persists_across_separate_get_calls_on_the_same_store():
    runner = FakeRunner()
    ss.set_setting(runner, "startup", "auto_start_persona", "work")
    assert ss.get_setting(runner, "startup", "auto_start_persona") == "work"
    # a second, independent read call still sees it - not held only in memory
    assert ss.get_setting(runner, "startup", "auto_start_persona") == "work"


def test_set_setting_only_affects_the_named_setting():
    runner = FakeRunner()
    ss.set_setting(runner, "sessions", "admin_elevation_ttl_minutes", 5)
    assert ss.get_setting(runner, "sessions", "default_session_ttl_hours") == 24


def test_set_setting_raises_for_an_unknown_setting_without_writing_anything():
    runner = FakeRunner()
    try:
        ss.set_setting(runner, "sessions", "not_a_real_setting", 1)
        assert False, "should have raised"
    except KeyError:
        pass
    assert runner.files == {}


def test_all_effective_settings_includes_every_schema_entry_with_defaults():
    runner = FakeRunner()
    effective = ss.all_effective_settings(runner)
    assert effective["sessions"]["default_session_ttl_hours"] == 24
    assert effective["startup"]["auto_start_persona"] == "personal"


def test_all_effective_settings_reflects_a_real_override():
    runner = FakeRunner()
    ss.set_setting(runner, "startup", "auto_start_persona", "admin")
    effective = ss.all_effective_settings(runner)
    assert effective["startup"]["auto_start_persona"] == "admin"
    # everything else in the group stays at its default
    assert effective["sessions"]["default_session_ttl_hours"] == 24


def test_store_lives_under_the_user_persistence_redirect_by_default():
    # /etc/baseline is bind-redirected onto USER_PERSISTENCE (persist_bind_mounts.py)
    # - direct instruction: all config must survive a disposable-stage rebuild.
    assert ss.DEFAULT_STORE_PATH.startswith("/etc/baseline/")


def test_self_installer_group_covers_every_pre_populated_field():
    settings = ss.settings_in_group("self_installer")
    assert {s.key for s in settings} == {"lvm_size_preset", "fqdn", "memory_mb"}
    for s in settings:
        assert s.options is not None, f"{s.key} must be selectable, never free text"


def test_set_setting_rejects_a_value_outside_the_defined_options():
    runner = FakeRunner()
    try:
        ss.set_setting(runner, "self_installer", "lvm_size_preset", "gigantic")
        assert False, "should have raised"
    except ValueError:
        pass
    assert ss.get_setting(runner, "self_installer", "lvm_size_preset") == "medium"


def test_set_setting_accepts_a_value_inside_the_defined_options():
    runner = FakeRunner()
    ss.set_setting(runner, "self_installer", "lvm_size_preset", "large")
    assert ss.get_setting(runner, "self_installer", "lvm_size_preset") == "large"


def test_set_setting_with_no_options_defined_accepts_any_value():
    runner = FakeRunner()
    ss.set_setting(runner, "sessions", "default_session_ttl_hours", 6)
    assert ss.get_setting(runner, "sessions", "default_session_ttl_hours") == 6
