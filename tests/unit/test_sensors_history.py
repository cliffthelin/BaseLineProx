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


# --------------------------------------------------------------------------
# Per-source collection intervals (decision record 72) - "a parameter
# available to be set as needed as often as needed... it should not
# change places that are not of high concern": every source gets its
# own independently settable interval, defaulting to whatever the
# caller passes (sensors_collect.py's own DEFAULT_INTERVALS).
# --------------------------------------------------------------------------

def test_get_interval_returns_the_given_default_when_never_set():
    conn = make_db()
    assert sh.get_interval(conn, "nvme", default=30.0) == 30.0


def test_set_interval_then_get_returns_the_override():
    conn = make_db()
    sh.set_interval(conn, "nvme", 1.0)
    assert sh.get_interval(conn, "nvme", default=30.0) == 1.0


def test_set_interval_only_affects_the_named_source():
    conn = make_db()
    sh.set_interval(conn, "nvme", 1.0)
    assert sh.get_interval(conn, "sensors", default=30.0) == 30.0
    assert sh.get_interval(conn, "smart", default=30.0) == 30.0
    assert sh.get_interval(conn, "volume", default=30.0) == 30.0


def test_set_interval_overwrites_a_previous_override_for_the_same_source():
    conn = make_db()
    sh.set_interval(conn, "nvme", 1.0)
    sh.set_interval(conn, "nvme", 5.0)
    assert sh.get_interval(conn, "nvme", default=30.0) == 5.0


def test_clear_interval_reverts_to_the_default():
    conn = make_db()
    sh.set_interval(conn, "nvme", 1.0)
    sh.clear_interval(conn, "nvme")
    assert sh.get_interval(conn, "nvme", default=30.0) == 30.0


def test_clear_interval_is_a_no_op_when_nothing_was_overridden():
    conn = make_db()
    sh.clear_interval(conn, "nvme")  # must not raise
    assert sh.get_interval(conn, "nvme", default=30.0) == 30.0


def test_list_intervals_returns_only_explicit_overrides():
    conn = make_db()
    sh.set_interval(conn, "nvme", 1.0)
    assert sh.list_intervals(conn) == {"nvme": 1.0}


def test_list_intervals_empty_when_nothing_overridden():
    conn = make_db()
    assert sh.list_intervals(conn) == {}


# -- last-attempt tracking (drives per-source due-ness independent of
# whether that attempt actually produced a recordable sample) ---------

def test_get_last_attempt_returns_none_when_never_attempted():
    conn = make_db()
    assert sh.get_last_attempt(conn, "nvme") is None


def test_record_attempt_then_get_returns_the_timestamp():
    conn = make_db()
    sh.record_attempt(conn, "nvme", 1700000000.0)
    assert sh.get_last_attempt(conn, "nvme") == 1700000000.0


def test_record_attempt_overwrites_the_previous_timestamp_for_the_same_source():
    conn = make_db()
    sh.record_attempt(conn, "nvme", 1700000000.0)
    sh.record_attempt(conn, "nvme", 1700000030.0)
    assert sh.get_last_attempt(conn, "nvme") == 1700000030.0


def test_record_attempt_only_affects_the_named_source():
    conn = make_db()
    sh.record_attempt(conn, "nvme", 1700000000.0)
    assert sh.get_last_attempt(conn, "sensors") is None
