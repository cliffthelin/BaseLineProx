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
"""
from __future__ import annotations

import time
from pathlib import Path

import diagnostics
import repair
import sensors_history

DB_PATH = "/var/lib/baseline/sensors_history.db"
DEFAULT_RETENTION_S = 24 * 60 * 60  # 24h at the timer's 30s cadence


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


def collect_once(runner: repair.Runner, conn, *, now: float, retention_s: float = DEFAULT_RETENTION_S) -> int:
    """Runs one collection cycle. Returns the number of samples
    recorded."""
    samples = []
    samples += _sensor_samples(diagnostics.collect_sensors(runner))
    samples += _nvme_samples(diagnostics.collect_nvme(runner))
    samples += _smart_samples(diagnostics.collect_smart(runner))
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
