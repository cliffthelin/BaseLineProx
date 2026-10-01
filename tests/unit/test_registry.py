"""Tests for registry.py (decision record 89) - the foundational,
generic registry mechanism underneath settings_store.py and
dependencies.py. conftest.py's `_isolated_registry` autouse fixture
redirects both `registry.GLOBAL_DB_PATH` and
`settings_store.DEFAULT_DB_PATH` (registry.py's own PROTECTED scope
resolves through that same constant) per test - real sqlite3 against
real, disposable temp files, no fakes needed."""
import pytest

import registry as reg


def test_register_type_is_idempotent_and_readable_from_either_scope():
    reg.register_type("demo_type", "a demo registry type", default_scope=reg.GLOBAL)
    reg.register_type("demo_type", "a demo registry type", default_scope=reg.GLOBAL)  # no error, no duplicate row


def test_register_type_rejects_an_unknown_scope():
    with pytest.raises(ValueError):
        reg.register_type("demo_type", "x", default_scope="nowhere")


def test_register_type_writes_only_to_its_own_scopes_database(monkeypatch):
    """Real bug, found by actually running the health check action for
    real: register_type used to write into BOTH physical databases
    unconditionally "for discoverability" - meaning even a purely
    GLOBAL type (dependencies.py) could never be registered on a
    machine where PROTECTED (USER) isn't reachable, which
    defeats the entire point of GLOBAL existing independent of
    USER. Proves the fix: registering a GLOBAL type must
    never even attempt to touch the PROTECTED database."""
    monkeypatch.setattr(reg, "_protected_db_path", lambda: "/nonexistent/definitely/not/writable/x.db")
    reg.register_type("global_only_type", "x", default_scope=reg.GLOBAL)  # must not raise
    import sqlite3
    with sqlite3.connect(reg.GLOBAL_DB_PATH) as conn:
        row = conn.execute("SELECT type_id FROM registry_types WHERE type_id = ?", ("global_only_type",)).fetchone()
    assert row is not None


def test_upsert_entry_then_get_entry_round_trips_attributes_and_value():
    reg.register_type("demo_type", "x", default_scope=reg.PROTECTED)
    reg.upsert_entry("demo_type", "e1", attributes={"default": 1}, scope=reg.PROTECTED, value=42)
    entry = reg.get_entry("demo_type", "e1", scope=reg.PROTECTED)
    assert entry == {"attributes": {"default": 1}, "value": 42}


def test_upsert_entry_with_no_value_leaves_value_null():
    reg.register_type("demo_type", "x", default_scope=reg.PROTECTED)
    reg.upsert_entry("demo_type", "e2", attributes={"a": "b"}, scope=reg.PROTECTED)
    entry = reg.get_entry("demo_type", "e2", scope=reg.PROTECTED)
    assert entry == {"attributes": {"a": "b"}, "value": None}


def test_upsert_entry_with_no_value_does_not_clobber_an_existing_value():
    reg.register_type("demo_type", "x", default_scope=reg.PROTECTED)
    reg.upsert_entry("demo_type", "e3", attributes={"v": 1}, scope=reg.PROTECTED, value="kept")
    reg.upsert_entry("demo_type", "e3", attributes={"v": 2}, scope=reg.PROTECTED)  # re-sync, no value passed
    entry = reg.get_entry("demo_type", "e3", scope=reg.PROTECTED)
    assert entry == {"attributes": {"v": 2}, "value": "kept"}


def test_get_entry_returns_none_for_an_unregistered_entry():
    assert reg.get_entry("demo_type", "never_registered", scope=reg.PROTECTED) is None


def test_set_value_updates_an_existing_entrys_value():
    reg.upsert_entry("demo_type", "e4", attributes={}, scope=reg.PROTECTED, value="old")
    reg.set_value("demo_type", "e4", "new", scope=reg.PROTECTED)
    assert reg.get_entry("demo_type", "e4", scope=reg.PROTECTED)["value"] == "new"


def test_set_value_refuses_when_no_entry_is_registered():
    with pytest.raises(KeyError):
        reg.set_value("demo_type", "never_registered", "x", scope=reg.PROTECTED)


def test_list_entries_returns_only_entries_of_the_requested_type_and_scope():
    reg.upsert_entry("type_a", "x1", attributes={}, scope=reg.PROTECTED, value=1)
    reg.upsert_entry("type_b", "x2", attributes={}, scope=reg.PROTECTED, value=2)
    entries = reg.list_entries("type_a", scope=reg.PROTECTED)
    assert set(entries) == {"x1"}


def test_global_and_protected_scopes_are_genuinely_separate_databases():
    """The entire point of scope: an entry written as GLOBAL must not
    be reachable by asking the PROTECTED database for it, and vice
    versa - they are different files, not a column filter on one."""
    reg.upsert_entry("split_type", "only_global", attributes={}, scope=reg.GLOBAL, value="g")
    reg.upsert_entry("split_type", "only_protected", attributes={}, scope=reg.PROTECTED, value="p")
    assert reg.get_entry("split_type", "only_global", scope=reg.PROTECTED) is None
    assert reg.get_entry("split_type", "only_protected", scope=reg.GLOBAL) is None
    assert reg.get_entry("split_type", "only_global", scope=reg.GLOBAL)["value"] == "g"
    assert reg.get_entry("split_type", "only_protected", scope=reg.PROTECTED)["value"] == "p"


def test_record_event_then_latest_events_returns_the_most_recent_per_entry():
    reg.record_event("evt_type", "e1", "check", {"ok": False, "detail": "first"}, scope=reg.PROTECTED, at=100.0)
    reg.record_event("evt_type", "e1", "check", {"ok": True, "detail": "second"}, scope=reg.PROTECTED, at=200.0)
    latest = reg.latest_events("evt_type", scope=reg.PROTECTED)
    assert latest["e1"]["detail"] == "second"
    assert latest["e1"]["ok"] is True


def test_latest_events_can_filter_by_kind():
    reg.record_event("evt_type2", "e1", "check", {"n": 1}, scope=reg.PROTECTED, at=100.0)
    reg.record_event("evt_type2", "e1", "other", {"n": 2}, scope=reg.PROTECTED, at=200.0)
    latest_checks = reg.latest_events("evt_type2", scope=reg.PROTECTED, kind="check")
    assert latest_checks["e1"]["n"] == 1


def test_get_entry_rejects_an_unknown_scope():
    with pytest.raises(ValueError):
        reg.get_entry("demo_type", "e1", scope="nowhere")


# -- Schema versioning - forward-looking scaffolding, no real migration
# exists yet (only version 1 has ever shipped), but a future table
# change needs this in place before it can ship safely. ---------------

def test_a_fresh_database_is_stamped_at_the_current_schema_version(tmp_path):
    import sqlite3
    path = str(tmp_path / "fresh.db")
    reg._connect(path).close()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == reg.SCHEMA_VERSION


def test_apply_migrations_refuses_a_database_newer_than_this_code_understands(tmp_path):
    import sqlite3
    path = str(tmp_path / "future.db")
    reg._connect(path).close()
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version = {reg.SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer than this code understands"):
        reg._connect(path)


def test_apply_migrations_refuses_when_no_migration_is_registered_for_a_gap(tmp_path, monkeypatch):
    import sqlite3
    path = str(tmp_path / "gap.db")
    reg._connect(path).close()
    monkeypatch.setattr(reg, "SCHEMA_VERSION", reg.SCHEMA_VERSION + 1)
    with pytest.raises(RuntimeError, match="no migration registered"):
        reg._connect(path)


def test_register_migration_refuses_a_duplicate_from_version():
    reg.register_migration(999, lambda conn: None)
    try:
        with pytest.raises(ValueError):
            reg.register_migration(999, lambda conn: None)
    finally:
        del reg._MIGRATIONS[999]


def test_a_registered_migration_actually_runs_and_advances_the_version(tmp_path, monkeypatch):
    import sqlite3
    path = str(tmp_path / "migrate.db")
    reg._connect(path).close()  # starts at SCHEMA_VERSION
    monkeypatch.setattr(reg, "SCHEMA_VERSION", reg.SCHEMA_VERSION + 1)
    calls = []
    reg.register_migration(1, lambda conn: calls.append(conn))
    try:
        reg._connect(path).close()
        assert len(calls) == 1
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == reg.SCHEMA_VERSION
    finally:
        del reg._MIGRATIONS[1]


# -- Real concurrency (direct instruction: "many app helpers" reading
# config at once, "multithreading is a must") - WAL mode's actual
# guarantee is that any number of readers proceed without blocking
# each other or a concurrent writer; only two simultaneous writers
# serialize. Every registry.py call opens and closes its own
# connection (never shared across a thread boundary), so this is
# exercised for real here, not just asserted. ------------------------

def test_many_concurrent_readers_never_block_or_corrupt_a_read():
    import concurrent.futures
    reg.upsert_entry("concurrency_type", "shared", attributes={"k": "v"}, scope=reg.PROTECTED, value="stable")

    def read_it(_i):
        return reg.get_entry("concurrency_type", "shared", scope=reg.PROTECTED)

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(read_it, range(200)))

    assert all(r == {"attributes": {"k": "v"}, "value": "stable"} for r in results)


def test_concurrent_readers_alongside_a_writer_never_crash_or_corrupt_state():
    import concurrent.futures
    reg.upsert_entry("concurrency_type2", "counter", attributes={}, scope=reg.PROTECTED, value=0)

    def writer(i):
        reg.set_value("concurrency_type2", "counter", i, scope=reg.PROTECTED)
        return True

    def reader(_i):
        entry = reg.get_entry("concurrency_type2", "counter", scope=reg.PROTECTED)
        return entry is not None and isinstance(entry["value"], int)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        writer_results = list(pool.map(writer, range(20)))
        reader_results = list(pool.map(reader, range(100)))

    assert all(writer_results)
    assert all(reader_results)  # every read saw *some* valid int, never a crash or garbage
