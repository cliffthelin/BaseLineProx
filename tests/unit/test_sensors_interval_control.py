"""Tests for sensors_interval_control.py (decision record 72) - the
one thing that genuinely can't be scoped per-source: the outer
systemd timer tick that invokes sensors_collect at all. You cannot
check a source more often than the outer loop itself runs, so the
timer's own tick must become the minimum of every source's current
interval - and revert exactly to the plain default (no drop-in file
at all) the moment nothing needs faster than that."""
from fake_runner import FakeProc, FakeRunner

import sensors_interval_control as sic


def test_required_tick_seconds_is_the_default_when_no_intervals_given():
    assert sic.required_tick_seconds({}) == sic.DEFAULT_TICK_S


def test_required_tick_seconds_is_the_minimum_across_sources():
    assert sic.required_tick_seconds({"sensors": 30.0, "nvme": 1.0, "smart": 30.0}) == 1.0


def test_required_tick_seconds_stays_at_default_when_nothing_is_faster():
    assert sic.required_tick_seconds({"sensors": 30.0, "nvme": 30.0}) == 30.0


def test_dropin_content_shape():
    assert sic.dropin_content(1.0) == "[Timer]\nOnUnitActiveSec=1s\n"


def test_dropin_content_formats_fractional_seconds_cleanly():
    assert sic.dropin_content(0.5) == "[Timer]\nOnUnitActiveSec=0.5s\n"


def test_apply_timer_tick_writes_a_dropin_when_faster_than_default():
    runner = FakeRunner()
    result = sic.apply_timer_tick(runner, {"nvme": 1.0, "sensors": 30.0})
    assert result.applied is True
    assert runner.files[sic.DROPIN_PATH] == "[Timer]\nOnUnitActiveSec=1s\n"
    assert ["systemctl", "daemon-reload"] in runner.calls
    assert ["systemctl", "restart", "baseline-sensors-collect.timer"] in runner.calls


def test_apply_timer_tick_removes_an_existing_dropin_once_reverted_to_default():
    runner = FakeRunner(files={sic.DROPIN_PATH: "[Timer]\nOnUnitActiveSec=1s\n"})
    result = sic.apply_timer_tick(runner, {"nvme": 30.0, "sensors": 30.0})
    assert result.applied is True
    assert sic.DROPIN_PATH not in runner.files
    assert ["systemctl", "daemon-reload"] in runner.calls
    assert ["systemctl", "restart", "baseline-sensors-collect.timer"] in runner.calls


def test_apply_timer_tick_is_a_true_no_op_when_already_at_default_with_no_dropin():
    runner = FakeRunner()
    result = sic.apply_timer_tick(runner, {"nvme": 30.0, "sensors": 30.0})
    assert result.applied is True
    assert sic.DROPIN_PATH not in runner.files
    # nothing needed to change - never touches systemctl at all
    assert runner.calls == []


def test_apply_timer_tick_updates_an_existing_dropin_to_a_faster_tick():
    runner = FakeRunner(files={sic.DROPIN_PATH: "[Timer]\nOnUnitActiveSec=5s\n"})
    result = sic.apply_timer_tick(runner, {"nvme": 1.0})
    assert result.applied is True
    assert runner.files[sic.DROPIN_PATH] == "[Timer]\nOnUnitActiveSec=1s\n"
