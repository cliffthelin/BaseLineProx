"""Small local history store for real host hardware-sensor samples
(temps/fans/voltages from lm-sensors, NVMe health, SMART) - the half of
the Track A5 sensors + per-VM dashboard with no existing source to reuse.
Per-VM historical stats deliberately do NOT go through this module - see
proxmox_vm_metrics.py's `vm_rrd_history`, which reuses Proxmox's own
already-retained RRD data instead of duplicating it here.

Pure stdlib `sqlite3`, WAL mode. Intentionally not Runner-injected like
the subprocess-shelling collectors in this project (repair.py, diagnostics.py) -
there is nothing to fake here that a real `:memory:` connection doesn't
already give tests directly, so tests use one.

Default retention: the caller decides the cutoff (see
`prune_older_than`); `baseline-sensors-collect` prunes to a 24h window
on every 30s collection cycle, keeping the table permanently small
(~2,880 samples per key).
"""
from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_samples_source_key_ts ON samples (source, key, ts);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def open_db(path: str) -> sqlite3.Connection:
    """Opens (creating if needed) the sensor-history database at `path`.
    Pass ":memory:" for tests. WAL mode is skipped for ":memory:" (sqlite
    doesn't support it there) and applied otherwise for safe concurrent
    read access while the collector writes."""
    conn = sqlite3.connect(path)
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def record_sample(conn: sqlite3.Connection, *, ts: float, source: str, key: str, value: float, unit: str = "") -> None:
    conn.execute(
        "INSERT INTO samples (ts, source, key, value, unit) VALUES (?, ?, ?, ?, ?)",
        (ts, source, key, value, unit),
    )
    conn.commit()


def query_history(conn: sqlite3.Connection, *, source: str, key: str, since_ts: float) -> list:
    """Returns [(ts, value), ...] for `source`/`key` at or after
    `since_ts`, oldest first. Empty list for an unknown key - not an
    error."""
    rows = conn.execute(
        "SELECT ts, value FROM samples WHERE source = ? AND key = ? AND ts >= ? ORDER BY ts ASC",
        (source, key, since_ts),
    ).fetchall()
    return [(ts, value) for ts, value in rows]


def prune_older_than(conn: sqlite3.Connection, *, cutoff_ts: float) -> None:
    conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff_ts,))
    conn.commit()
