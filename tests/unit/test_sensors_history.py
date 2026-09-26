"""Unit tests for sensors_history.py (Track A5) - the small sqlite-backed
store for host hardware-sensor samples (the half of the dashboard with no
existing history source to reuse, unlike per-VM stats which reuse
Proxmox's own RRD data - see proxmox_vm_metrics.py). Tested against a
real in-memory sqlite3 connection, matching this module's own simplicity
- no Runner/fake needed for a pure stdlib sqlite3 boundary."""
import sqlite3

import sensors_history as sh


def make_db():
    return sh.open_db(":memory:")


def test_open_db_creates_schema():
    conn = make_db()
    # should not raise - table exists and is queryable
    conn.execute("SELECT ts, source, key, value, unit FROM samples LIMIT 0")


def test_record_and_query_single_sample():
    conn = make_db()
    sh.record_sample(conn, ts=1700000000.0, source="sensors", key="coretemp/Package id 0", value=45.0, unit="C")
    rows = sh.query_history(conn, source="sensors", key="coretemp/Package id 0", since_ts=0)
    assert rows == [(1700000000.0, 45.0)]


def test_query_history_filters_by_source_and_key():
    conn = make_db()
    sh.record_sample(conn, ts=1.0, source="sensors", key="a", value=1.0, unit="C")
    sh.record_sample(conn, ts=2.0, source="sensors", key="b", value=2.0, unit="C")
    sh.record_sample(conn, ts=3.0, source="nvme", key="a", value=3.0, unit="C")
    rows = sh.query_history(conn, source="sensors", key="a", since_ts=0)
    assert rows == [(1.0, 1.0)]


def test_query_history_filters_by_since_ts():
    conn = make_db()
    sh.record_sample(conn, ts=100.0, source="sensors", key="a", value=1.0, unit="C")
    sh.record_sample(conn, ts=200.0, source="sensors", key="a", value=2.0, unit="C")
    rows = sh.query_history(conn, source="sensors", key="a", since_ts=150.0)
    assert rows == [(200.0, 2.0)]


def test_query_history_empty_for_unknown_key():
    conn = make_db()
    rows = sh.query_history(conn, source="sensors", key="nonexistent", since_ts=0)
    assert rows == []


def test_query_history_returns_in_chronological_order():
    conn = make_db()
    sh.record_sample(conn, ts=300.0, source="sensors", key="a", value=3.0, unit="C")
    sh.record_sample(conn, ts=100.0, source="sensors", key="a", value=1.0, unit="C")
    sh.record_sample(conn, ts=200.0, source="sensors", key="a", value=2.0, unit="C")
    rows = sh.query_history(conn, source="sensors", key="a", since_ts=0)
    assert rows == [(100.0, 1.0), (200.0, 2.0), (300.0, 3.0)]


def test_prune_older_than_removes_only_old_samples():
    conn = make_db()
    sh.record_sample(conn, ts=100.0, source="sensors", key="a", value=1.0, unit="C")
    sh.record_sample(conn, ts=200.0, source="sensors", key="a", value=2.0, unit="C")
    sh.prune_older_than(conn, cutoff_ts=150.0)
    rows = sh.query_history(conn, source="sensors", key="a", since_ts=0)
    assert rows == [(200.0, 2.0)]


def test_prune_older_than_keeps_everything_when_cutoff_is_earliest():
    conn = make_db()
    sh.record_sample(conn, ts=100.0, source="sensors", key="a", value=1.0, unit="C")
    sh.prune_older_than(conn, cutoff_ts=0.0)
    rows = sh.query_history(conn, source="sensors", key="a", since_ts=0)
    assert len(rows) == 1


def test_open_db_is_idempotent_on_existing_schema():
    conn = sh.open_db(":memory:")
    # calling schema init logic twice on the same connection must not raise
    sh._ensure_schema(conn)
    conn.execute("SELECT 1 FROM samples LIMIT 0")
