"""The Audit page (read-only) and the Approvals page (standing approvals and bots' daily authorizations)."""
import json

import pytest

import audit_view
import hitl
import settings_web as sw
from test_baseline_web import _RealServerCase, _base_deps
from test_hitl_web import SECRET, Clock, _req

NOW = 1_800_000_000.0


def test_tail_reads_only_the_last_records_and_skips_garbage(tmp_path):
    path = tmp_path / "a.jsonl"
    lines = [json.dumps({"ts": i, "event": f"e{i}"}) for i in range(10)]
    lines.insert(3, "{not json")
    path.write_text("\n".join(lines) + "\n")
    got = audit_view.read_tail(path, 4)
    assert [r["event"] for r in got] == ["e9", "e8", "e7", "e6"]          # newest first


def test_a_missing_audit_file_is_an_empty_list(tmp_path):
    assert audit_view.read_tail(tmp_path / "none.jsonl", 10) == []


def test_the_view_never_shows_secret_looking_fields(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps({"ts": 1, "event": "x", "secret": "hunter2", "password": "p", "token": "t", "ok": 1}) + "\n")
    shown = audit_view.read_tail(path, 5)[0]
    assert "hunter2" not in json.dumps(shown) and shown["ok"] == 1 and "password" not in shown and "token" not in shown


def _case(tmp_path, role="admin", **over):
    clock = Clock()
    sessions = sw.SessionStore()
    sessions.create("someone", NOW, role=role)
    store = hitl.ConfirmationStore(verify_secret=lambda s: s == SECRET, clock=clock, min_wait_s=0)
    log = tmp_path / "audit.jsonl"
    log.write_text(json.dumps({"ts": NOW, "event": "confirmed", "action": "repair"}) + "\n")
    deps = _base_deps(sessions=sessions, clock=clock, hitl=store, audit_log_path=log, **over)
    return _RealServerCase(deps), store


def test_the_audit_page_shows_recent_events_to_an_admin(tmp_path):
    case, _ = _case(tmp_path)
    try:
        status, body = case.get("/audit")
        assert status == 200 and b"confirmed" in body and b"repair" in body
    finally:
        case.close()


@pytest.mark.parametrize("role", ["operator", "bot:repair", "bot:backup_offdrive"])
@pytest.mark.parametrize("path", ["/audit", "/approvals"])
def test_limited_logins_cannot_open_audit_or_approvals(tmp_path, role, path):
    case, _ = _case(tmp_path, role=role)
    try:
        assert case.get(path)[0] == 403
    finally:
        case.close()


def test_the_approvals_page_lists_daily_authorizations_and_an_admin_can_revoke_one(tmp_path):
    case, store = _case(tmp_path)
    try:
        chal = store.challenge("s", "repair", {"device_path": "/dev/sdb"}, "MD89N41071210AP4E", "x")
        store.confirm("s", chal["id"], chal["phrase"], SECRET, daily_for="botrepair")
        status, body = case.get("/approvals")
        assert status == 200 and b"botrepair" in body and b"repair" in body
        (entry,) = store.list_all_daily()
        assert _req(case, "POST", "/approvals/daily/revoke", {"id": entry["id"]})[0] == 200
        assert store.list_all_daily() == []
        assert _req(case, "POST", "/approvals/daily/revoke", {"id": entry["id"]})[0] == 404
    finally:
        case.close()


def test_a_bot_cannot_revoke_or_list_approvals(tmp_path):
    case, store = _case(tmp_path, role="bot:repair")
    try:
        assert _req(case, "POST", "/approvals/daily/revoke", {"id": "x"})[0] == 403
    finally:
        case.close()
