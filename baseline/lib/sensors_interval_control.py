"""Real, live control over the *outer* cadence that drives
sensors_collect.py at all (decision record 72).

Per-source gating - does this specific source's real hardware query
actually run this tick - lives entirely in
sensors_history.py/sensors_collect.py's own sqlite tables
(`collection_intervals`/`collection_last_attempt`); that alone answers
"a parameter available to be set as needed as often as needed" for
each source independently. But it cannot answer the one thing that
genuinely isn't scopable per source: you cannot check a source more
often than the outer loop that invokes the collector at all actually
runs. This module's only job is that one honest mechanical fact - the
systemd timer's own tick must be at least as fast as the fastest
currently-configured source, computed fresh every time an override
changes, and reverted exactly to the plain, un-overridden default
(no drop-in file at all, not just a wider number) the moment nothing
needs faster than that - "it should not change places that are not of
high concern" applies to the shipped default's own resource footprint
too, not only to which sources get recorded.

Applied via a systemd drop-in override
(`baseline-sensors-collect.timer.d/override.conf`), never by editing
the shipped `.timer` unit `provision.sh` stages - the standard way to
override a unit's settings at runtime without touching what was
deployed.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def remove(self, path):
            raise NotImplementedError

        def makedirs(self, path):
            raise NotImplementedError


DROPIN_DIR = "/etc/systemd/system/baseline-sensors-collect.timer.d"
DROPIN_PATH = f"{DROPIN_DIR}/override.conf"
TIMER_UNIT = "baseline-sensors-collect.timer"
DEFAULT_TICK_S = 30.0


@dataclass
class ApplyResult:
    applied: bool
    detail: str


def required_tick_seconds(effective_intervals: dict) -> float:
    """The fastest currently-needed cadence across every source - the
    outer loop can never run slower than this or a source configured
    faster than the default would simply never get checked in time."""
    if not effective_intervals:
        return DEFAULT_TICK_S
    return min(min(effective_intervals.values()), DEFAULT_TICK_S)


def dropin_content(tick_s: float) -> str:
    formatted = f"{tick_s:g}"
    return f"[Timer]\nOnUnitActiveSec={formatted}s\n"


def _reload_and_restart(runner: Runner) -> None:
    runner.run(["systemctl", "daemon-reload"], timeout=15)
    runner.run(["systemctl", "restart", TIMER_UNIT], timeout=15)


def apply_timer_tick(runner: Runner, effective_intervals: dict) -> ApplyResult:
    """Idempotent: writes/updates the drop-in only when the required
    tick is faster than the plain default; removes it entirely - a
    real revert, not just a wider number - the moment nothing needs
    faster than the default, so the shipped unit's own cadence is
    exactly what runs again. A true no-op (no drop-in exists, nothing
    needs faster than default) never touches systemctl at all."""
    tick = required_tick_seconds(effective_intervals)
    dropin_exists = runner.path_exists(DROPIN_PATH)

    if tick >= DEFAULT_TICK_S:
        if not dropin_exists:
            return ApplyResult(True, f"already at the plain default ({DEFAULT_TICK_S:g}s) - nothing to do")
        runner.remove(DROPIN_PATH)
        _reload_and_restart(runner)
        return ApplyResult(True, f"reverted to the plain default ({DEFAULT_TICK_S:g}s) - drop-in removed")

    runner.makedirs(DROPIN_DIR)
    runner.write_text_atomic(DROPIN_PATH, dropin_content(tick))
    _reload_and_restart(runner)
    return ApplyResult(True, f"timer tick set to {tick:g}s")
