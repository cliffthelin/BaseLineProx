"""Oneshot collection cycle for the host-sensor half of the Track A5
dashboard (see sensors_history.py's module docstring for why only this
half needs its own store). Invoked every 30s by
`baseline-sensors-collect.timer` via the thin
`bin/baseline-sensors-collect` entry point, matching this project's
existing timer-invoked entry-point pattern (`baseline-repair-rollback`).

Flattens `diagnostics.py`'s real `collect_sensors`/`collect_nvme`/
`collect_smart` into (source, key, value, unit) samples, records every
numeric one, and prunes anything older than the retention window on
every cycle - keeps the store permanently small without a separate
cleanup job. Never raises on missing hardware/tools; diagnostics.py's
collectors already treat that as a normal, expected outcome, and this
module preserves that discipline all the way through.

Also flattens `drive_installer.collect_volume_usage`'s real per-volume
`df` output (source "volume") - real follow-up work, decision record
71. Reuses this same store rather than a separate one; a volume that
isn't mounted contributes nothing, not an error.

Each source's own real collector only actually runs when that
source's own interval has elapsed (decision record 72 - "a parameter
available to be set as needed as often as needed... it should not
change places that are not of high concern"): `DEFAULT_INTERVALS`
gives every source the same 30s default this module always used, and
`sensors_history.set_interval`/`clear_interval` let an operator
override one specific source - e.g. checking `nvme` every second
during a time of high concern - without touching any other source's
own cadence. The outer systemd timer tick that actually invokes this
module is a separate, honest concern handled by
`sensors_interval_control.py` - you cannot check a source more often
than the outer loop runs at all.
"""
from __future__ import annotations

import time
from pathlib import Path

import diagnostics
import drive_installer
import repair
import sensors_history

DB_PATH = "/var/lib/baseline/sensors_history.db"
DEFAULT_RETENTION_S = 24 * 60 * 60  # 24h at the default 30s cadence

# Every source's plain, un-escalated cadence - unchanged from what
# this module always used. sensors_history.get_interval falls back to
# these when a source has no explicit override.
DEFAULT_INTERVALS = {
    "sensors": 30.0,
    "nvme": 30.0,
    "smart": 30.0,
    "volume": 30.0,
}


def _sensor_samples(result) -> list:
    samples = []
    for chip in result.chips:
        for feature in chip["features"]:
            value = feature["value"]
            if not isinstance(value, (int, float)):
                continue
            key = f"{chip['chip']}/{feature['label']}"
            samples.append(("sensors", key, float(value), feature.get("unit", "")))
    return samples


def _nvme_samples(result) -> list:
    samples = []
    for device in result.devices:
        health = device.get("health") or {}
        temp = health.get("temperature")
        if isinstance(temp, (int, float)):
            samples.append(("nvme", f"{device['path']}/temperature", float(temp), "C"))
        used = health.get("percentage_used")
        if isinstance(used, (int, float)):
            samples.append(("nvme", f"{device['path']}/percentage_used", float(used), "%"))
    return samples


def _smart_samples(result) -> list:
    samples = []
    for device in result.devices:
        temp = device.get("temperature")
        if isinstance(temp, (int, float)):
            samples.append(("smart", f"{device['device']}/temperature", float(temp), "C"))
    return samples


def _volume_samples(usages) -> list:
    samples = []
    for u in usages:
        samples.append(("volume", f"{u.label}/percent_used", u.percent_used, "%"))
        samples.append(("volume", f"{u.label}/used_bytes", float(u.used_bytes), "bytes"))
    return samples


# (source name, real collector call, flatten-to-samples function) -
# one small explicit table rather than four near-identical if-blocks.
_SOURCES = (
    ("sensors", lambda runner: diagnostics.collect_sensors(runner), _sensor_samples),
    ("nvme", lambda runner: diagnostics.collect_nvme(runner), _nvme_samples),
    ("smart", lambda runner: diagnostics.collect_smart(runner), _smart_samples),
    ("volume", lambda runner: drive_installer.collect_volume_usage(runner), _volume_samples),
)


def _source_is_due(conn, source: str, now: float) -> bool:
    interval = sensors_history.get_interval(conn, source, DEFAULT_INTERVALS[source])
    last_attempt = sensors_history.get_last_attempt(conn, source)
    if last_attempt is None:
        return True
    return (now - last_attempt) >= interval


def collect_once(runner: repair.Runner, conn, *, now: float, retention_s: float = DEFAULT_RETENTION_S) -> int:
    """Runs one collection cycle. Only actually queries a source's real
    hardware/tool when that source's own interval has elapsed
    (decision record 72) - a source at its plain default cadence costs
    nothing extra on a tick where it isn't due; an escalated source
    never speeds up any other source's own cadence. Records an attempt
    timestamp regardless of whether that attempt produced any
    recordable samples, so a source with no hardware present is still
    correctly throttled rather than re-queried every single tick.
    Returns the number of samples recorded this cycle."""
    samples = []
    for source, collect_fn, flatten_fn in _SOURCES:
        if not _source_is_due(conn, source, now):
            continue
        sensors_history.record_attempt(conn, source, now)
        samples += flatten_fn(collect_fn(runner))

    for source, key, value, unit in samples:
        sensors_history.record_sample(conn, ts=now, source=source, key=key, value=value, unit=unit)
    sensors_history.prune_older_than(conn, cutoff_ts=now - retention_s)
    return len(samples)


def main() -> int:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sensors_history.open_db(DB_PATH)
    try:
        count = collect_once(repair.RealRunner(), conn, now=time.time())
        print(f"[baseline-sensors-collect] recorded {count} samples")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
