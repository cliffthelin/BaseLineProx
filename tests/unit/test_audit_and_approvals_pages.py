"""The Audit page (read-only) and the Approvals page (standing approvals and bots' daily authorizations)."""
import json

import pytest

import audit_view
import hitl
import settings_web as sw
from test_baseline_web import _RealServerCase, _base_deps
from test_hitl_web import SECRET, Clock, _req

NOW = 1_800_000_000.0


def test_tail_reads_only_the_last_records_in_newest_first_order(tmp_path):
    path = tmp_path / "a.jsonl"
    lines = [json.dumps({"ts": i, "event": f"e{i}"}) for i in range(10)]
    path.write_text("\n".join(lines) + "\n")
    got = audit_view.read_tail(path, 4)
    assert [r["event"] for r in got] == ["e9", "e8", "e7", "e6"]          # newest first


def test_corrupt_audit_record_is_not_silently_omitted(tmp_path):
    path=tmp_path/'corrupt.jsonl'
    path.write_text('{"event":"recorded"}\n{not json}\n')
    with pytest.raises(audit_view.AuditReadError,match='malformed JSON'):
        audit_view.read_tail(path,10)


def test_a_missing_audit_file_is_an_empty_list(tmp_path):
    assert audit_view.read_tail(tmp_path / "none.jsonl", 10) == []


def test_an_unreadable_audit_file_is_not_reported_as_empty(monkeypatch, tmp_path):
    def denied(*_args, **_kwargs):
        raise PermissionError("audit file permission denied")

    monkeypatch.setattr("builtins.open", denied)
    with pytest.raises(audit_view.AuditReadError, match="audit file permission denied"):
        audit_view.read_tail(tmp_path / "audit.jsonl")


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
    case=_RealServerCase(deps);case.audit_path=log
    return case, store


def test_the_audit_page_shows_recent_events_to_an_admin(tmp_path):
    case, _ = _case(tmp_path)
    try:
        status, body = case.get("/audit")
        assert status == 200 and b"confirmed" in body and b"repair" in body
    finally:
        case.close()


def test_audit_page_reports_corrupt_history_as_unavailable(tmp_path):
    case,_=_case(tmp_path)
    case.audit_path.write_text('{"event":"confirmed"}\n{broken}\n')
    try:
        status,body=case.get('/audit')
        assert status==503
        assert b'malformed JSON' in body and b'No events recorded yet' not in body
    finally:
        case.close()


def test_audit_page_reports_an_unreadable_log_as_unavailable(tmp_path, monkeypatch):
    case, _ = _case(tmp_path)

    def denied(*_args, **_kwargs):
        raise audit_view.AuditReadError("audit file permission denied")

    monkeypatch.setattr(audit_view, "read_tail", denied)
    try:
        status, body = case.get("/audit")
        assert status == 503
        assert b"audit file permission denied" in body
        assert b"No events recorded yet" not in body
    finally:
        case.close()


def test_operations_history_endpoint_reports_an_unreadable_log(tmp_path, monkeypatch):
    case, _ = _case(tmp_path)

    def denied(*_args, **_kwargs):
        raise audit_view.AuditReadError("audit log read failed")

    monkeypatch.setattr(audit_view, "read_tail", denied)
    try:
        status, body = case.get("/operations/history")
        assert status == 503
        assert b"audit log read failed" in body
    finally:
        case.close()


def test_operations_page_labels_unreadable_history(tmp_path, monkeypatch):
    case, _ = _case(tmp_path)

    def denied(*_args, **_kwargs):
        raise audit_view.AuditReadError("audit history cannot be read")

    monkeypatch.setattr(audit_view, "read_tail", denied)
    try:
        status, body = case.get("/operations")
        assert status == 200
        assert b"Run history unavailable: audit history cannot be read" in body
        assert b"No recorded runs" not in body
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
