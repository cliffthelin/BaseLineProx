import importlib.machinery
import importlib.util
import json
from pathlib import Path

import rebuild_authority as ra

BIN = Path(__file__).resolve().parents[2] / "baseline/bin"


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(BIN / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_service_routes_request_then_approve(tmp_path):
    svc = load("baseline-rebuild-service")
    auth = ra.Authority(tmp_path, {"ONE": "S1"})
    req = svc.handle(auth, {"op": "request", "target": "ONE"})
    assert svc.handle(auth, {"op": "approve", "id": req["id"], "code": "wrong"})["ok"] is False
    assert svc.handle(auth, {"op": "approve", "id": req["id"], "code": req["code"]})["ok"] is True
    assert svc.handle(auth, {"op": "nope"})["ok"] is False


def test_drain_inbox_answers_and_removes_the_message(tmp_path, monkeypatch):
    svc = load("baseline-rebuild-service")
    monkeypatch.setattr(svc, "INBOX", tmp_path / "in")
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.json").write_text(json.dumps({"op": "status"}))
    svc.drain_inbox(ra.Authority(tmp_path / "st", {}))
    assert json.loads((tmp_path / "in" / "a.out").read_text())["ok"] is True
    assert not (tmp_path / "in" / "a.json").exists()


def test_client_refuses_cleanly_when_service_is_absent(monkeypatch):
    cli = load("baseline-rebuild")
    monkeypatch.setattr(cli, "INBOX", Path("/nonexistent-baseline-inbox"))
    try:
        cli.call({"op": "status"})
    except SystemExit as exc:
        assert "sudo" in str(exc)
