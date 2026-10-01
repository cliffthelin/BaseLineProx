"""web_gate: an operation runs only when the web application asked for it. The proof is signed with a key that
only the web service holds, so a script, another process, or a hand-built object cannot produce it."""
import pytest

import web_gate as wg
from settings_web import SessionStore

KEY = b"k" * 32
NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _reset():
    wg.configure(None)
    yield
    wg.configure(None)


def logged_in():
    sessions = SessionStore()
    return sessions, sessions.create("root", NOW).token


def gate():
    g = wg.WebGate(KEY, clock=lambda: NOW)
    wg.configure(g)
    return g


def test_nothing_runs_when_no_web_app_is_configured():
    with pytest.raises(wg.NotFromWebApp):
        wg.require(None, "backup_offdrive", {})


def test_a_session_that_is_not_logged_in_cannot_mint():
    g = gate()
    with pytest.raises(wg.NotFromWebApp):
        g.origin_for_session(SessionStore(), "no-such-token", "backup_offdrive", {}, NOW)


def test_a_logged_in_session_mints_an_origin_valid_for_exactly_that_request():
    g = gate()
    sessions, token = logged_in()
    origin = g.origin_for_session(sessions, token, "backup_offdrive", {"dry_run": True}, NOW)
    wg.require(origin, "backup_offdrive", {"dry_run": True})
    with pytest.raises(wg.NotFromWebApp):
        wg.require(origin, "backup_offdrive", {"dry_run": False})
    with pytest.raises(wg.NotFromWebApp):
        wg.require(origin, "backup_verify", {"dry_run": True})


def test_an_origin_expires():
    clock = {"t": NOW}
    g = wg.WebGate(KEY, clock=lambda: clock["t"])
    wg.configure(g)
    sessions, token = logged_in()
    origin = g.origin_for_session(sessions, token, "op", {}, NOW)
    clock["t"] += wg.ORIGIN_TTL_S + 1
    with pytest.raises(wg.NotFromWebApp):
        wg.require(origin, "op", {})


def test_an_origin_signed_with_a_different_key_is_refused():
    other = wg.WebGate(b"z" * 32, clock=lambda: NOW)
    sessions, token = logged_in()
    forged = other.origin_for_session(sessions, token, "op", {}, NOW)
    gate()
    with pytest.raises(wg.NotFromWebApp):
        wg.require(forged, "op", {})


@pytest.mark.parametrize("fake", [None, "web", {"kind": "session"}, object()])
def test_things_that_are_not_origins_are_refused(fake):
    gate()
    with pytest.raises(wg.NotFromWebApp):
        wg.require(fake, "op", {})


def test_an_origin_cannot_be_built_by_hand():
    gate()
    with pytest.raises(wg.NotFromWebApp):
        wg.require(wg.WebOrigin("session", "op", wg.digest("op", {}), NOW + 60, "00" * 32), "op", {})


def test_a_signed_schedule_yields_origins_and_an_edited_schedule_does_not():
    g = gate()
    sessions, token = logged_in()
    record = g.sign_schedule(sessions, token, {"op": "backup_offdrive", "params": {}, "every_hours": 24}, NOW)
    origin = g.origin_for_schedule(record, NOW)
    wg.require(origin, "backup_offdrive", {})
    edited = dict(record, every_hours=1)
    with pytest.raises(wg.NotFromWebApp):
        g.origin_for_schedule(edited, NOW)
    swapped = dict(record, op="repair")
    with pytest.raises(wg.NotFromWebApp):
        g.origin_for_schedule(swapped, NOW)


def test_a_schedule_cannot_be_signed_without_a_login():
    g = gate()
    with pytest.raises(wg.NotFromWebApp):
        g.sign_schedule(SessionStore(), "nope", {"op": "backup_offdrive", "params": {}, "every_hours": 24}, NOW)


def test_confirmed_operations_cannot_be_scheduled():
    g = gate()
    sessions, token = logged_in()
    with pytest.raises(ValueError):
        g.sign_schedule(sessions, token, {"op": "build_self_installer", "params": {}, "every_hours": 24}, NOW)


def test_key_file_is_created_root_only_and_reused(tmp_path):
    path = tmp_path / "web-signing.key"
    k1 = wg.load_or_create_key(path)
    assert len(k1) == 32 and oct(path.stat().st_mode & 0o777) == "0o600"
    assert wg.load_or_create_key(path) == k1


def test_a_key_file_with_loose_permissions_is_refused(tmp_path):
    path = tmp_path / "web-signing.key"
    path.write_bytes(b"k" * 32)
    path.chmod(0o644)
    with pytest.raises(wg.GateError):
        wg.load_or_create_key(path)


def test_requests_and_refusals_are_audited():
    log = []
    g = wg.WebGate(KEY, clock=lambda: NOW, audit=log.append)
    wg.configure(g)
    sessions, token = logged_in()
    origin = g.origin_for_session(sessions, token, "op", {}, NOW)
    with pytest.raises(wg.NotFromWebApp):
        wg.require(origin, "other", {})
    assert [r["event"] for r in log] == ["operation_requested", "operation_refused"]
