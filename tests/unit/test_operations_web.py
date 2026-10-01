"""Over real sockets: the Operations page and routes, the signed-origin requirement, the limited operator role."""
import json

import pytest

import operations as ops
import settings_web as sw
import web_gate as wg
from test_baseline_web import _RealServerCase, _base_deps, _poll_job
from test_hitl_web import _req

NOW = 1_800_000_000.0


class Clock:
    def __call__(self):
        return NOW


def _case(tmp_path, role="admin", gate=True, monkeypatch=None, **over):
    clock = Clock()
    sessions = sw.SessionStore()
    sessions.create("someone", NOW, role=role)
    deps = _base_deps(sessions=sessions, clock=clock, **over)
    if gate:
        g = wg.WebGate(b"w" * 32, clock=clock)
        wg.configure(g)
        deps["web_gate"] = g
        deps["scheduler"] = ops.Scheduler(g, ops.ScheduleStore(tmp_path / "s.json"),
                                          lambda op, params, origin: None, clock=clock)
    return _RealServerCase(deps)


@pytest.fixture(autouse=True)
def _reset():
    wg.configure(None)
    yield
    wg.configure(None)


@pytest.fixture
def fake_backup(monkeypatch):
    calls = []

    def main(**kw):
        calls.append(kw)
        kw["print_fn"]("[ok] fake backup")
        return 0
    monkeypatch.setattr(ops.offdrive_backup, "main", main)
    return calls


def test_the_page_lists_operations_and_is_in_the_nav(tmp_path):
    case = _case(tmp_path)
    try:
        status, body = case.get("/operations")
        assert status == 200 and b"backup offdrive" in body and b"Run now" in body
        assert b'href="/operations"' in body
    finally:
        case.close()


def test_run_now_starts_a_background_job_with_a_signed_origin(tmp_path, fake_backup):
    case = _case(tmp_path)
    try:
        status, body = _req(case, "POST", "/operations/run", {"op": "backup_offdrive", "params": {"dry_run": True}})
        assert status == 200 and body["outcome"] == "started"
        job = _poll_job(case, body["job_id"])
        assert job["outcome"] == "applied" and "[ok] fake backup" in job["lines"]
        assert fake_backup[0]["dry_run"] is True and isinstance(fake_backup[0]["origin"], wg.WebOrigin)
    finally:
        case.close()


@pytest.mark.parametrize("body", [{"op": "nope"}, {"op": "backup_offdrive", "params": {"x": 1}},
                                  {"op": "backup_offdrive", "params": {"dry_run": "yes"}}, {"op": ""}])
def test_bad_operation_requests_are_refused(tmp_path, fake_backup, body):
    case = _case(tmp_path)
    try:
        status, resp = _req(case, "POST", "/operations/run", body)
        assert status == 400 and fake_backup == []
    finally:
        case.close()


def test_a_request_with_no_login_runs_nothing(tmp_path, fake_backup):
    case = _case(tmp_path)
    try:
        status, _ = _req(case, "POST", "/operations/run", {"op": "backup_offdrive"}, cookie="not-a-session")
        assert status in (401, 403) and fake_backup == []
    finally:
        case.close()


def test_without_a_gate_the_server_refuses(tmp_path, fake_backup):
    case = _case(tmp_path, gate=False)
    try:
        status, _ = _req(case, "POST", "/operations/run", {"op": "backup_offdrive"})
        assert status == 503 and fake_backup == []
    finally:
        case.close()


def test_schedule_set_list_and_remove_over_the_web(tmp_path):
    case = _case(tmp_path)
    try:
        status, body = _req(case, "POST", "/operations/schedule", {"op": "backup_offdrive", "every_hours": 24})
        assert status == 200 and body["outcome"] == "applied"
        assert b"Scheduled every 24" in case.get("/operations")[1]
        _req(case, "POST", "/operations/schedule/remove", {"op": "backup_offdrive"})
        assert b"Not scheduled" in case.get("/operations")[1]
        status, _ = _req(case, "POST", "/operations/schedule", {"op": "backup_list", "every_hours": 24})
        assert status == 400
        status, _ = _req(case, "POST", "/operations/schedule", {"op": "backup_offdrive", "every_hours": 0})
        assert status == 400
    finally:
        case.close()


# -- the limited operator role ----------------------------------------------------

def test_an_operator_can_run_and_schedule_operations(tmp_path, fake_backup):
    case = _case(tmp_path, role="operator")
    try:
        assert case.get("/operations")[0] == 200
        status, body = _req(case, "POST", "/operations/run", {"op": "backup_offdrive"})
        assert status == 200
        assert _req(case, "POST", "/operations/schedule", {"op": "backup_offdrive", "every_hours": 12})[0] == 200
    finally:
        case.close()


@pytest.mark.parametrize("path", ["/settings", "/admin", "/recovery", "/drive-admin", "/hardware", "/installer-cache",
                                  "/master-config", "/app-isolation", "/drive-admin/approvals", "/api/detect"])
def test_an_operator_cannot_open_anything_else(tmp_path, path):
    case = _case(tmp_path, role="operator")
    try:
        assert case.get(path)[0] == 403
    finally:
        case.close()


@pytest.mark.parametrize("path,body", [
    ("/drive-admin/action", {"action_id": "repair", "params": {"device_path": "/dev/sdb"}}),
    ("/drive-admin/confirm", {"challenge_id": "x", "typed": "x", "secret": "x"}),
    ("/drive-admin/approvals", {"action_id": "repair"}),
    ("/admin/elevate", {"passphrase": "x"}), ("/recovery/unlock", {"passphrase": "x"}),
    ("/api/backup", {"dest": "/tmp/x.tar.gz", "targets": []}),
    ("/setup/machine-passphrase", {"passphrase": "x"}),
])
def test_an_operator_cannot_act_outside_operations(tmp_path, path, body):
    case = _case(tmp_path, role="operator")
    try:
        assert _req(case, "POST", path, body)[0] == 403
    finally:
        case.close()


def test_the_operator_role_comes_from_the_configured_machine_accounts(tmp_path):
    import http.client

    class Verifier:
        def verify(self, user, password):
            return password == "pw"
    clock = Clock()
    deps = _base_deps(sessions=sw.SessionStore(), clock=clock, verifier=Verifier(),
                      operator_users=lambda: "claude, other", operator_session_hours=lambda: 3)
    deps["sessions"].create("seed", NOW)
    case = _RealServerCase(deps)
    try:
        def login(user):
            conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=5)
            conn.request("POST", "/login", body=json.dumps({"username": user, "password": "pw"}).encode(),
                         headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{case.port}"})
            resp = conn.getresponse()
            resp.read()
            return resp.status, resp.getheader("Location"), resp.getheader("Set-Cookie")
        status, location, cookie = login("claude")
        assert location == "/operations"
        token = cookie.split("session=")[1].split(";")[0]
        assert deps["sessions"].sessions[token].role == "operator"
        assert deps["sessions"].sessions[token].ttl_s == 3 * 3600
        status, location, cookie = login("cane")
        assert location == "/settings"
        token = cookie.split("session=")[1].split(";")[0]
        assert deps["sessions"].sessions[token].role == "admin"
        assert deps["sessions"].sessions[token].ttl_s == 1800.0
    finally:
        case.close()
