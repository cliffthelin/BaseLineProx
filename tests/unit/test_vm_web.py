"""The VM library inside the web app: /vms page, /vms/status, /vms/action - behind login, admin only."""
import json

import pytest

import settings_web as sw
import vm_page as vp
from test_baseline_web import _RealServerCase, _base_deps
from test_vm_host import FakeHost

NOW = 1_800_000_000.0


def _case(tmp_path, role="admin"):
    f = FakeHost(tmp_path / "store")
    iso_dir = tmp_path / "isos"
    iso_dir.mkdir()
    (iso_dir / "ubuntu.iso").write_bytes(b"x")
    sessions = sw.SessionStore()
    sessions.create("someone", NOW, role=role)
    events = []
    deps = _base_deps(sessions=sessions, vm_host=f.host, vm_iso_dir=iso_dir, vm_config_path=tmp_path / "vm.json",
                      audit=events.append)
    return _RealServerCase(deps), f, events


def test_the_page_renders_for_an_admin_with_the_isos_offered(tmp_path):
    case, f, _ = _case(tmp_path)
    try:
        status, body = case.get("/vms")
        assert status == 200 and b"Virtual machines" in body and b"ubuntu.iso" in body
    finally:
        case.close()


def test_the_nav_has_a_virtual_machines_tab(tmp_path):
    case, f, _ = _case(tmp_path)
    try:
        assert b'href="/vms"' in case.get("/vms")[1]
    finally:
        case.close()


def test_creating_starting_and_stopping_through_the_action_route(tmp_path):
    case, f, events = _case(tmp_path)
    try:
        s, r = case.post_json("/vms/action", {"action": "create_iso", "name": "dev", "iso": "ubuntu.iso",
                                              "disk_gb": "10", "memory_mb": "2048", "cpus": "2"})
        assert s == 200 and r["ok"], r
        s, r = case.post_json("/vms/action", {"action": "start", "name": "dev", "display": "vnc"})
        assert r["ok"] and f.host.status("dev")["running"]
        s, r = case.post_json("/vms/action", {"action": "force_stop", "name": "dev"})
        assert r["ok"] and not f.host.status("dev")["running"]
        assert [e["action"] for e in events if e.get("event") == "vm_action"] == ["create_iso", "start", "force_stop"]
    finally:
        case.close()


def test_status_route_matches_what_the_page_embeds(tmp_path):
    case, f, _ = _case(tmp_path)
    try:
        case.post_json("/vms/action", {"action": "create_iso", "name": "dev", "iso": "ubuntu.iso",
                                       "disk_gb": "10", "memory_mb": "2048", "cpus": "2"})
        _, page = case.get("/vms")
        status, raw = case.get("/vms/status")
        compact = json.dumps(json.loads(raw), separators=(",", ":"))
        assert status == 200 and json.dumps(compact).encode() in page
    finally:
        case.close()


def test_changing_the_store_location_is_saved_and_validated(tmp_path):
    case, f, _ = _case(tmp_path)
    try:
        s, r = case.post_json("/vms/action", {"action": "set_store", "store": "/etc"})
        assert not r["ok"]
        s, r = case.post_json("/vms/action", {"action": "set_store", "store": str(tmp_path / "newstore")})
        assert r["ok"] and vp.load_store(tmp_path / "vm.json", default="x") == str(tmp_path / "newstore")
    finally:
        case.close()


@pytest.mark.parametrize("role", ["operator", "bot:repair"])
@pytest.mark.parametrize("path", ["/vms", "/vms/status"])
def test_limited_logins_cannot_reach_the_vm_pages(tmp_path, role, path):
    case, f, _ = _case(tmp_path, role=role)
    try:
        assert case.get(path)[0] == 403
        assert case.post_json("/vms/action", {"action": "start", "name": "x"})[0] == 403
    finally:
        case.close()


def test_installed_proxmox_uses_its_lifecycle_adapter(tmp_path, monkeypatch):
    import baseline_web as bw
    import proxmox_vm_host as pv
    import shutil
    monkeypatch.setattr(shutil, "which", lambda tool: "/usr/sbin/" + tool if tool in ("qm", "pvesh") else None)
    host = bw._vm_host_for({"vm_config_path": tmp_path / "vm.json"})
    assert isinstance(host, pv.ProxmoxVmHost)
