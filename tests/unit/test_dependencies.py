"""Tests for dependencies.py (decision record 88) - the dependency-
tracking and health-validation layer living in the same primary
Baseline database settings_store.py uses. conftest.py's
`_isolated_settings_store` autouse fixture redirects
`settings_store.DEFAULT_DB_PATH` per test, and `dependencies.py`
resolves its own default path from that same constant, so every test
here is isolated to a real, disposable temp database - no fakes needed
for sqlite3 itself."""
import settings_store
import dependencies as dep


def _reset_registry():
    dep._REGISTRY[:] = list(dep.SEED_DEPENDENCIES)


def setup_function(_fn):
    _reset_registry()


def teardown_function(_fn):
    _reset_registry()


def test_seed_dependencies_cover_both_a_system_and_an_install_level():
    levels = {d.level for d in dep.all_dependencies()}
    assert "system" in levels
    assert "install" in levels


def test_seed_dependencies_include_at_least_one_loud_and_one_silent():
    severities = {d.severity for d in dep.all_dependencies()}
    assert dep.LOUD in severities
    assert dep.SILENT in severities


def test_check_binary_on_path_passes_for_a_real_binary():
    ok, detail = dep._check_binary_on_path({"name": "python3"})
    assert ok is True
    assert "python3" in detail


def test_check_binary_on_path_fails_for_a_fake_binary():
    ok, detail = dep._check_binary_on_path({"name": "definitely-not-a-real-binary-xyz"})
    assert ok is False


def test_check_python_module_importable_passes_for_sqlite3():
    ok, detail = dep._check_python_module_importable({"module": "sqlite3"})
    assert ok is True


def test_check_python_module_importable_fails_for_a_fake_module():
    ok, detail = dep._check_python_module_importable({"module": "not_a_real_module_xyz"})
    assert ok is False


def test_check_setting_configured_passes_for_a_valid_default():
    ok, detail = dep._check_setting_configured({"group": "self_installer", "key": "lvm_size_preset"})
    assert ok is True
    assert "medium" in detail


def test_check_setting_configured_fails_for_an_unknown_setting():
    ok, detail = dep._check_setting_configured({"group": "self_installer", "key": "not_real"})
    assert ok is False


def test_run_checks_records_every_matching_dependency_for_the_phase():
    results = dep.run_checks(phase=dep.PRE_INSTALL)
    ids = {r.id for r in results}
    assert "install.self_installer_lvm_preset_valid" in ids
    assert "system.sqlite3_importable" in ids


def test_run_checks_only_returns_dependencies_registered_for_that_phase():
    dep.register_dependencies([
        dep.Dependency("test.boot_only", "system", "only runs at boot", dep.LOUD, (dep.BOOT,),
                        "python_module_importable", {"module": "sqlite3"})
    ])
    pre_install_ids = {r.id for r in dep.run_checks(phase=dep.PRE_INSTALL)}
    boot_ids = {r.id for r in dep.run_checks(phase=dep.BOOT)}
    assert "test.boot_only" not in pre_install_ids
    assert "test.boot_only" in boot_ids


def test_run_checks_rejects_an_unknown_phase():
    try:
        dep.run_checks(phase="not_a_real_phase")
        assert False, "should have raised"
    except ValueError:
        pass


def test_run_checks_restricted_to_one_level():
    results = dep.run_checks(phase=dep.PRE_INSTALL, level="install")
    assert all(r.level == "install" for r in results)
    assert len(results) >= 2


def test_a_broken_check_records_as_a_failure_without_crashing_the_run():
    dep.register_dependencies([
        dep.Dependency("test.broken", "system", "deliberately broken check", dep.LOUD, (dep.ADHOC,),
                        "setting_configured", {"group": "nonexistent", "key": "missing"})
    ])
    results = dep.run_checks(phase=dep.ADHOC)
    broken = next(r for r in results if r.id == "test.broken")
    assert broken.ok is False


def test_loud_failures_filters_out_silent_ones():
    results = [
        dep.CheckResult("a", False, "loud broke", dep.LOUD, "system"),
        dep.CheckResult("b", False, "silent broke", dep.SILENT, "system"),
        dep.CheckResult("c", True, "fine", dep.LOUD, "system"),
    ]
    assert [r.id for r in dep.loud_failures(results)] == ["a"]


def test_latest_check_results_reflects_the_most_recent_run_only():
    settings_store.set_setting("self_installer", "lvm_size_preset", "small")
    dep.run_checks(phase=dep.ADHOC)
    settings_store.set_setting("self_installer", "lvm_size_preset", "medium")
    dep.run_checks(phase=dep.ADHOC)
    latest = dep.latest_check_results()
    assert "medium" in latest["install.self_installer_lvm_preset_valid"]["detail"]


def test_dump_configuration_snapshot_calls_out_a_currently_failing_silent_dependency():
    dep.register_dependencies([
        dep.Dependency("test.silent_break", "install", "silently wrong", dep.SILENT, (dep.ADHOC,),
                        "setting_configured", {"group": "nonexistent", "key": "missing"})
    ])
    dep.run_checks(phase=dep.ADHOC)
    snapshot = dep.dump_configuration_snapshot()
    assert "test.silent_break" in snapshot["silent_failures"]
    assert "test.silent_break" not in snapshot["loud_failures"]
    assert "settings" in snapshot


def test_dump_configuration_snapshot_includes_effective_settings():
    dep.run_checks(phase=dep.ADHOC)
    snapshot = dep.dump_configuration_snapshot()
    assert snapshot["settings"]["self_installer"]["lvm_size_preset"] == "medium"


def test_run_checks_for_global_dependencies_never_requires_protected_to_be_reachable(monkeypatch):
    """Real bug, found by actually running the health check action for
    real on a non-root sandbox missing /etc/baseline entirely: syncing
    a dependency's definition used to hardcode GLOBAL as
    register_type's target regardless - which happened to work for
    every current seed dependency (all GLOBAL) but was fixed to use
    each entry's own scope instead, matching settings_store.py's
    identical fix. This proves system-level (GLOBAL) checks - the ones
    a boot-time or recovery health check most needs - keep working
    even when PROTECTED (USER_PERSISTENCE) is completely unreachable."""
    import settings_store
    monkeypatch.setattr(settings_store, "DEFAULT_DB_PATH", "/nonexistent/definitely/not/writable/x.db")
    results = dep.run_checks(phase=dep.BOOT)  # only system.* deps run at BOOT, both GLOBAL
    assert all(r.ok for r in results)


def test_register_dependencies_refuses_a_duplicate_id():
    try:
        dep.register_dependencies([
            dep.Dependency("system.sqlite3_importable", "system", "dup", dep.LOUD, (dep.ADHOC,),
                            "python_module_importable", {"module": "sqlite3"})
        ])
        assert False, "should have raised"
    except ValueError:
        pass


def test_register_check_kind_refuses_to_shadow_a_builtin():
    try:
        dep.register_check_kind("binary_on_path", lambda args: (True, ""))
        assert False, "should have raised"
    except ValueError:
        pass


def test_sync_definitions_persists_the_registry_into_the_shared_registry_entries_table():
    """Decision record 89: dependencies.py has no table of its own
    anymore - definitions live in registry.py's generic
    `registry_entries`, type "dependencies". system.* dependencies
    default to GLOBAL scope, so they land in registry.GLOBAL_DB_PATH
    (the autouse fixture's isolated tmp file)."""
    import sqlite3
    import registry
    dep.sync_definitions()
    with sqlite3.connect(registry.GLOBAL_DB_PATH) as conn:
        ids = {row[0] for row in conn.execute(
            "SELECT entry_id FROM registry_entries WHERE type_id = 'dependencies'")}
    assert "system.sqlite3_importable" in ids
    assert "install.self_installer_lvm_preset_valid" in ids
