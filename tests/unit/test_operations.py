"""operations.py: what the web app can run (ad hoc, in the background, or on a schedule) and the scheduler."""
import json

import pytest

import operations as ops
import web_gate as wg
import web_origin_helper as woh
from settings_web import SessionStore

NOW = woh.NOW


@pytest.fixture(autouse=True)
def _reset():
    wg.configure(None)
    yield
    wg.configure(None)


def test_unknown_operation_and_bad_params_are_refused():
    with pytest.raises(ValueError):
        ops.validate("nope", {})
    with pytest.raises(ValueError):
        ops.validate("backup_offdrive", {"dry_run": "yes"})
    with pytest.raises(ValueError):
        ops.validate("backup_offdrive", {"surprise": True})
    assert ops.validate("backup_offdrive", {}) == {"dry_run": False, "force": False}
    assert ops.validate("backup_offdrive", {"dry_run": True}) == {"dry_run": True, "force": False}


def test_execute_runs_the_backup_with_the_origin(monkeypatch):
    gate = woh.configured_gate()
    seen = {}
    monkeypatch.setattr(ops.offdrive_backup, "main", lambda **kw: seen.update(kw) or 0)
    params = ops.validate("backup_offdrive", {"dry_run": True})
    origin = woh.origin_for("backup_offdrive", params, gate=gate)
    lines = []
    assert ops.execute("backup_offdrive", params, origin, print_fn=lines.append) == 0
    assert seen["dry_run"] is True and seen["origin"] is origin


def test_execute_without_a_valid_origin_runs_nothing(monkeypatch):
    woh.configured_gate()
    monkeypatch.setattr(ops.offdrive_backup, "main", lambda **kw: pytest.fail("ran without permission"))
    with pytest.raises(wg.NotFromWebApp):
        ops.execute("backup_offdrive", ops.validate("backup_offdrive", {}), None, print_fn=print)


def test_a_manual_backup_is_forced_past_the_minimum_interval_only_when_asked(monkeypatch):
    gate = woh.configured_gate()
    seen = {}
    monkeypatch.setattr(ops.offdrive_backup, "main", lambda **kw: seen.update(kw) or 0)
    params = ops.validate("backup_offdrive", {"force": True})
    ops.execute("backup_offdrive", params, woh.origin_for("backup_offdrive", params, gate=gate), print_fn=print)
    assert seen["force"] is True


# -- scheduler ----------------------------------------------------------------

def make(tmp_path, clock):
    gate = wg.WebGate(b"s" * 32, clock=lambda: clock["t"])
    wg.configure(gate)
    sessions = SessionStore()
    token = sessions.create("root", NOW).token
    ran = []
    store = ops.ScheduleStore(tmp_path / "schedules.json")
    sched = ops.Scheduler(gate, store, lambda op, params, origin: ran.append((op, params, origin.kind)),
                          clock=lambda: clock["t"])
    return gate, sessions, token, store, sched, ran


def test_a_schedule_runs_when_due_then_waits(tmp_path):
    clock = {"t": NOW}
    gate, sessions, token, store, sched, ran = make(tmp_path, clock)
    sched.set(sessions, token, "backup_offdrive", {}, every_hours=24)
    sched.tick()
    assert ran == [("backup_offdrive", {"dry_run": False, "force": False}, "schedule")]
    clock["t"] += 3600
    sched.tick()
    assert len(ran) == 1
    clock["t"] += 24 * 3600
    sched.tick()
    assert len(ran) == 2


def test_a_schedule_survives_a_restart_and_keeps_its_last_run(tmp_path):
    clock = {"t": NOW}
    gate, sessions, token, store, sched, ran = make(tmp_path, clock)
    sched.set(sessions, token, "backup_offdrive", {}, every_hours=24)
    sched.tick()
    sched2 = ops.Scheduler(gate, ops.ScheduleStore(tmp_path / "schedules.json"),
                           lambda op, params, origin: ran.append(op), clock=lambda: clock["t"])
    sched2.tick()
    assert len(ran) == 1


def test_editing_the_schedule_file_makes_the_scheduler_ignore_it(tmp_path):
    clock = {"t": NOW}
    gate, sessions, token, store, sched, ran = make(tmp_path, clock)
    sched.set(sessions, token, "backup_offdrive", {}, every_hours=24)
    path = tmp_path / "schedules.json"
    data = json.loads(path.read_text())
    data["schedules"][0]["every_hours"] = 0.01
    path.write_text(json.dumps(data))
    clock["t"] += 100
    sched.tick()
    assert ran == []


def test_a_forged_schedule_with_no_signature_is_ignored(tmp_path):
    clock = {"t": NOW}
    gate, sessions, token, store, sched, ran = make(tmp_path, clock)
    (tmp_path / "schedules.json").write_text(json.dumps(
        {"schedules": [{"op": "backup_offdrive", "params": {}, "every_hours": 1, "created": 0, "sig": "x"}], "last_run": {}}))
    sched.tick()
    assert ran == []


def test_setting_a_schedule_needs_a_login_and_a_schedulable_operation(tmp_path):
    clock = {"t": NOW}
    gate, sessions, token, store, sched, ran = make(tmp_path, clock)
    with pytest.raises(wg.NotFromWebApp):
        sched.set(sessions, "no-login", "backup_offdrive", {}, every_hours=24)
    with pytest.raises(ValueError):
        sched.set(sessions, token, "backup_list", {}, every_hours=24)
    with pytest.raises(ValueError):
        sched.set(sessions, token, "backup_offdrive", {}, every_hours=0)


def test_a_failing_run_does_not_stop_the_scheduler_or_repeat_in_a_storm(tmp_path):
    clock = {"t": NOW}
    gate, sessions, token, store, sched, ran = make(tmp_path, clock)

    def boom(op, params, origin):
        ran.append(op)
        raise RuntimeError("x")
    sched.run = boom
    sched.set(sessions, token, "backup_offdrive", {}, every_hours=24)
    sched.tick()
    sched.tick()
    assert len(ran) == 1


def test_remove_and_list(tmp_path):
    clock = {"t": NOW}
    gate, sessions, token, store, sched, ran = make(tmp_path, clock)
    sched.set(sessions, token, "backup_offdrive", {}, every_hours=24)
    assert [s["op"] for s in sched.listing()] == ["backup_offdrive"]
    sched.remove(sessions, token, "backup_offdrive")
    assert sched.listing() == []
