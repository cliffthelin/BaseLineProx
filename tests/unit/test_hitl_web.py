"""End to end over real sockets: a drive action never runs on request. It needs a person to confirm that exact
request each time (typed phrase + root password), and nothing skips it except a standing approval a person grants.
The 'drive' is a RAM-backed stand-in (ram_drive.py): its contents must survive an unconfirmed request, and change
exactly once after a human confirmation."""
import http.client
import json
import threading

import pytest
from fake_runner import FakeRunner

import hitl
import settings_web as sw
from ram_drive import RamDrive
from test_baseline_web import FakePdsRunner, FakeSudoExecutor, _RealServerCase, _base_deps, _poll_job

SECRET = "test-secret"
ALLOWED_SERIAL = "MD89N41071210AP4E"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _req(case, method, path, body=None, cookie=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=5)
    h = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{case.port}", **(headers or {})}
    h["Cookie"] = f"session={cookie or case.token}"
    conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except ValueError:
        return resp.status, raw


@pytest.fixture
def ram(tmp_path, monkeypatch):
    drive = RamDrive(tmp_path / "ram-cache-drive")
    drive.install_fake_actions(monkeypatch)
    return drive


def _case(min_wait_s=0, clock=None, **over):
    clock = clock or Clock()
    store = hitl.ConfirmationStore(verify_secret=lambda s: s == SECRET, clock=clock, min_wait_s=min_wait_s)
    sessions = sw.SessionStore()
    sessions.create("root", now=clock())
    deps = _base_deps(sessions=sessions, hitl=store, clock=clock, pkexec_executor=FakeSudoExecutor(returncode=0),
                      recovery_verify_fn=lambda s: s == SECRET, **over)
    case = _RealServerCase(deps)
    case.store, case.clock = store, clock
    return case


def _ask(case, action="build_self_installer", params=None, **kw):
    return _req(case, "POST", "/drive-admin/action", {"action_id": action, "params": params or {"device_path": "/dev/sdb"}, **kw})


def _confirm(case, chal, typed=None, secret=SECRET, cookie=None):
    return _req(case, "POST", "/drive-admin/confirm",
                {"challenge_id": chal["id"], "typed": chal["phrase"] if typed is None else typed, "secret": secret}, cookie=cookie)


# --- a request alone never runs anything ---------------------------------------

def test_a_request_only_produces_a_challenge_and_the_ram_drive_is_untouched(ram):
    case = _case()
    try:
        status, body = _ask(case)
        assert status == 200 and body["outcome"] == "confirmation_required"
        assert "job_id" not in body
        assert body["challenge"]["phrase"] == "INSTALL " + ALLOWED_SERIAL[-6:]
        assert ram.installs == 0 and ram.intact()
        assert case.server.deps["pkexec_executor"].calls == []
    finally:
        case.close()


@pytest.mark.parametrize("extra", [
    {"confirm": True}, {"confirmed": True}, {"skip_confirmation": True}, {"force": True}, {"yes": True},
    {"authorization": "approved"}, {"hitl": False}, {"bypass": 1}, {"params": {"device_path": "/dev/sdb", "confirmed": True}},
])
def test_no_flag_in_the_request_body_skips_the_confirmation(ram, extra):
    case = _case()
    try:
        status, body = _ask(case, **extra) if "params" not in extra else _req(
            case, "POST", "/drive-admin/action", {"action_id": "build_self_installer", **extra})
        assert body.get("outcome") in ("confirmation_required", "refused")
        assert body.get("outcome") != "started" and ram.installs == 0 and ram.intact()
    finally:
        case.close()


def test_no_query_string_or_header_skips_the_confirmation(ram):
    case = _case()
    try:
        for path, headers in (("/drive-admin/action?confirm=1&skip=1", None),
                              ("/drive-admin/action", {"X-Confirmed": "1", "X-Authorization": "approved", "Authorization": "Bearer x"})):
            status, body = _req(case, "POST", path, {"action_id": "build_self_installer", "params": {"device_path": "/dev/sdb"}},
                                headers=headers)
            assert body.get("outcome") == "confirmation_required"
        assert ram.installs == 0 and ram.intact()
    finally:
        case.close()


# --- confirming ------------------------------------------------------------------------

def test_a_correct_confirmation_runs_the_stored_request_once_and_changes_the_ram_drive(ram):
    case = _case()
    try:
        _, body = _ask(case)
        status, started = _confirm(case, body["challenge"])
        assert status == 200 and started["outcome"] == "started"
        job = _poll_job(case, started["job_id"])
        assert job["outcome"] == "applied"
        assert ram.installs == 1 and not ram.intact()
    finally:
        case.close()


def test_the_confirm_step_runs_what_was_challenged_not_what_the_confirm_request_says(ram):
    case = _case()
    try:
        _, body = _ask(case, action="mount_volume", params={"device_path": "/dev/sdb", "mountpoint": "/mnt/ram-inspect"})
        chal = body["challenge"]
        status, started = _req(case, "POST", "/drive-admin/confirm",
                               {"challenge_id": chal["id"], "typed": chal["phrase"], "secret": SECRET,
                                "action_id": "build_self_installer", "params": {"device_path": "/dev/sdb"}})
        _poll_job(case, started["job_id"])
        assert ram.mounted == {"/mnt/ram-inspect": "root"} and ram.installs == 0 and ram.intact()
    finally:
        case.close()


def test_a_confirmation_cannot_be_replayed(ram):
    case = _case()
    try:
        _, body = _ask(case)
        _, started = _confirm(case, body["challenge"])
        _poll_job(case, started["job_id"])
        status, again = _confirm(case, body["challenge"])
        assert status == 404 and "job_id" not in again and ram.installs == 1
    finally:
        case.close()


def test_a_wrong_password_or_phrase_starts_nothing(ram):
    case = _case()
    try:
        _, body = _ask(case)
        for kw in ({"secret": "guess"}, {"secret": ""}, {"typed": "INSTALL XXXXXX"}, {"typed": ""}):
            status, out = _confirm(case, body["challenge"], **kw)
            assert status == 403 and "job_id" not in out
        assert ram.installs == 0 and ram.intact()
    finally:
        case.close()


def test_guessing_is_rate_limited_and_a_lock_refuses_even_the_right_password(ram):
    case = _case()
    try:
        _, body = _ask(case)
        statuses = [_confirm(case, body["challenge"], secret=f"guess{i}")[0] for i in range(8)]
        assert 429 in statuses
        status, out = _confirm(case, body["challenge"])
        assert status == 429 and ram.installs == 0 and ram.intact()
    finally:
        case.close()


def test_a_confirmation_that_comes_too_fast_to_have_been_read_is_refused(ram):
    case = _case(min_wait_s=30)
    try:
        _, body = _ask(case)
        status, out = _confirm(case, body["challenge"])
        assert status == 403 and out["reason"] == "too_fast" and ram.intact()
        case.clock.t += 31
        status, out = _confirm(case, body["challenge"])
        assert status == 200 and out["outcome"] == "started"
    finally:
        case.close()


def test_an_expired_challenge_cannot_be_confirmed(ram):
    case = _case()
    try:
        _, body = _ask(case)
        case.clock.t += hitl.DEFAULT_TTL_S + 1
        status, out = _confirm(case, body["challenge"])
        assert status == 404 and ram.installs == 0
    finally:
        case.close()


def test_another_logged_in_session_cannot_confirm_my_challenge(ram):
    case = _case()
    try:
        other = case.server.deps["sessions"].create("root", now=case.clock()).token
        _, body = _ask(case)
        status, out = _confirm(case, body["challenge"], cookie=other)
        assert status == 403 and "job_id" not in out and ram.installs == 0
    finally:
        case.close()


def test_an_unknown_challenge_is_refused(ram):
    case = _case()
    try:
        status, out = _req(case, "POST", "/drive-admin/confirm", {"challenge_id": "nope", "typed": "x", "secret": SECRET})
        assert status == 404
        status, out = _req(case, "POST", "/drive-admin/confirm", {"challenge_id": 123, "typed": "x", "secret": SECRET})
        assert status == 404
    finally:
        case.close()


def test_with_no_confirmation_credential_configured_nobody_can_confirm(ram):
    clock = Clock()
    sessions = sw.SessionStore()
    sessions.create("root", now=clock())
    deps = _base_deps(sessions=sessions, clock=clock, pkexec_executor=FakeSudoExecutor(returncode=0), recovery_verify_fn=None)
    case = _RealServerCase({k: v for k, v in deps.items()})
    case.server.deps.pop("hitl", None)
    from baseline_web import _hitl_store
    case.server.deps["hitl"] = _hitl_store({"clock": clock, "recovery_verify_fn": None})
    try:
        _, body = _ask(case)
        status, out = _confirm(case, body["challenge"], secret="anything")
        assert status == 403 and ram.installs == 0 and ram.intact()
    finally:
        case.close()


def test_a_request_for_a_drive_outside_the_allowlist_never_gets_a_challenge(ram):
    case = _case()
    try:
        status, out = _ask(case, params={"device_path": "/dev/sdz"})
        assert status == 400 and out["outcome"] == "refused" and "challenge" not in out
    finally:
        case.close()


def test_the_confirm_route_needs_a_login_and_a_same_origin_post(ram):
    case = _case()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=5)
        conn.request("POST", "/drive-admin/confirm", body=b"{}", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status in (303, 401)
        conn.close()
        status, _ = _req(case, "POST", "/drive-admin/confirm", {"challenge_id": "x"}, headers={"Origin": "http://evil.example"})
        assert status == 403
    finally:
        case.close()


# --- standing approvals: the only exception -------------------------------------------

def _grant(case, action="mount_volume", minutes=10, max_uses=2, secret=SECRET, typed=None):
    typed = typed if typed is not None else f"I AUTHORIZE {hitl.VERBS[action]} {ALLOWED_SERIAL[-6:]} FOR {minutes} MINUTES"
    return _req(case, "POST", "/drive-admin/approvals", {"action_id": action, "device_path": "/dev/sdb", "minutes": minutes,
                                                          "max_uses": max_uses, "typed": typed, "secret": secret})


def test_a_standing_approval_needs_the_password_and_the_sentence(ram):
    case = _case()
    try:
        assert _grant(case, secret="guess")[0] == 403
        assert _grant(case, typed="please")[0] == 403
        status, out = _grant(case)
        assert status == 200 and out["grant"]["uses_left"] == 2
    finally:
        case.close()


def test_with_an_approval_the_matching_action_runs_without_a_challenge_until_it_is_used_up(ram):
    case = _case()
    try:
        _grant(case, max_uses=2)
        for _ in range(2):
            status, body = _ask(case, action="mount_volume", params={"device_path": "/dev/sdb", "mountpoint": "/mnt/ram-inspect"})
            assert body["outcome"] == "started"
            _poll_job(case, body["job_id"])
        assert ram.mounted == {"/mnt/ram-inspect": "root"}
        _, third = _ask(case, action="mount_volume", params={"device_path": "/dev/sdb", "mountpoint": "/mnt/ram-inspect"})
        assert third["outcome"] == "confirmation_required"
    finally:
        case.close()


def test_an_approval_covers_only_its_own_action_and_drive(ram):
    case = _case()
    try:
        _grant(case, action="mount_volume")
        _, other_action = _ask(case, action="unmount_volume", params={"device_path": "/dev/sdb"})
        assert other_action["outcome"] == "confirmation_required"
    finally:
        case.close()


def test_installing_over_a_drive_can_never_be_pre_approved_and_is_confirmed_every_time(ram):
    case = _case()
    try:
        status, out = _grant(case, action="build_self_installer")
        assert status == 403 and "every time" in out["detail"]
        for _ in range(2):
            _, body = _ask(case)
            assert body["outcome"] == "confirmation_required"
        assert ram.installs == 0 and ram.intact()
    finally:
        case.close()


def test_an_approval_belongs_to_the_session_that_made_it(ram):
    case = _case()
    try:
        _grant(case)
        other = case.server.deps["sessions"].create("root", now=case.clock()).token
        status, body = _req(case, "POST", "/drive-admin/action",
                            {"action_id": "mount_volume", "params": {"device_path": "/dev/sdb"}}, cookie=other)
        assert body["outcome"] == "confirmation_required"
    finally:
        case.close()


def test_an_approval_can_be_listed_and_revoked(ram):
    case = _case()
    try:
        _, out = _grant(case)
        _, listing = _req(case, "GET", "/drive-admin/approvals")
        assert [g["id"] for g in listing["grants"]] == [out["grant"]["id"]]
        _req(case, "POST", "/drive-admin/approvals/revoke", {"id": out["grant"]["id"]})
        _, body = _ask(case, action="mount_volume", params={"device_path": "/dev/sdb"})
        assert body["outcome"] == "confirmation_required"
    finally:
        case.close()


def test_an_approval_expires(ram):
    case = _case()
    try:
        _grant(case, minutes=5)
        case.clock.t += 5 * 60 + 1
        _, body = _ask(case, action="mount_volume", params={"device_path": "/dev/sdb"})
        assert body["outcome"] == "confirmation_required"
    finally:
        case.close()


# --- audit -------------------------------------------------------------------------------

def test_every_step_lands_in_an_append_only_audit_log_without_the_secret(ram, tmp_path):
    audit = tmp_path / "audit" / "hitl.jsonl"
    clock = Clock()
    store = hitl.ConfirmationStore(verify_secret=lambda s: s == SECRET, clock=clock, min_wait_s=0, audit=hitl.AuditFile(audit))
    case = _case(clock=clock)
    case.server.deps["hitl"] = store
    try:
        _, body = _ask(case)
        _confirm(case, body["challenge"], secret="a-wrong-secret-value")
        _, started = _confirm(case, body["challenge"])
        _poll_job(case, started["job_id"])
        text = audit.read_text()
        events = [json.loads(l)["event"] for l in text.splitlines()]
        assert events == ["challenge", "confirm_failed", "confirmed", "authorization_used"]
        assert "a-wrong-secret-value" not in text and SECRET not in text
    finally:
        case.close()


# --- the page ----------------------------------------------------------------------------

def test_the_page_script_asks_a_person_to_confirm_and_shows_the_summary_safely():
    case = _case()
    try:
        status, page = case.get("/drive-admin")
        text = page.decode()
        assert "askForConfirmation" in text and "/drive-admin/confirm" in text
        assert "summary.textContent" in text and "secret.type = \"password\"" in text
    finally:
        case.close()
