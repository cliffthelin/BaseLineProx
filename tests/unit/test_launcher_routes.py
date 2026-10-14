"""The launcher through the real HTTP server with a real session (DR259). Only the VM host is a fake (a real Proxmox is not here); the
settings are written to real files in a temp directory standing in for the volumes."""
import json
import os

import pytest

import layered_settings as ls
import vm_host as vh
from test_baseline_web import _RealServerCase, _base_deps
from test_new_web_routes import req

VMS = [
    {"name": "ubuntu-desk", "vmid": 101, "running": True, "kind": "overlay", "base": "ubuntu-24.04-base", "memory_mb": 4096, "cpus": 2,
     "iso": None, "recipe": "ubuntu-desktop", "persistence_disk": "u.raw", "persistence_gb": 20, "vnc": None},
    {"name": "debian-13-lab", "vmid": 102, "running": False, "kind": "standalone", "base": None, "memory_mb": 2048, "cpus": 1,
     "iso": None, "recipe": None, "persistence_disk": None, "persistence_gb": None, "vnc": None},
]


class FakeHost:
    def __init__(self, vms=VMS, fail=None):
        self._vms, self._fail = vms, fail

    def list_vms(self):
        if self._fail:
            raise vh.VmError(self._fail)
        return self._vms

    def list_bases(self):
        return []


@pytest.fixture
def case(tmp_path):
    made = [tmp_path / n for n in ("admin", "user", "appdata", "session")]
    for p in made:
        p.mkdir()
    c = _RealServerCase(_base_deps(vm_host=FakeHost(), launcher_roots=ls.Roots(*map(str, made))))
    c.tmp = tmp_path
    yield c
    c.close()


def state(case):
    status, _, body = req(case, "GET", "/launcher/state")
    assert status == 200
    return json.loads(body)


def post(case, fields):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=10)
    conn.request("POST", "/launcher/settings", body=json.dumps(fields).encode(), headers={
        "Content-Type": "application/json", "Cookie": f"session={case.token}", "Origin": f"http://127.0.0.1:{case.port}"})
    r = conn.getresponse()
    data = json.loads(r.read() or b"{}")
    conn.close()
    return r.status, data


def test_the_launcher_needs_a_session_and_shows_every_vm_as_a_tile(case):
    assert req(case, "GET", "/launcher", cookie=False)[0] == 303
    status, _, page = req(case, "GET", "/launcher")
    assert status == 200 and "ubuntu-desk" in page and "debian-13-lab" in page
    assert 'role="menu"' in page and "contextmenu" in page and "Fullscreen" in page
    assert req(case, "GET", "/launcher/state", cookie=False)[0] == 303


def test_the_state_carries_console_paths_for_the_running_vm_only(case):
    s = state(case)
    running, stopped = s["tiles"]
    assert set(running["paths"]) == {"console", "window", "fullscreen"} and stopped["paths"] == {}
    assert running["id"].startswith("O_V_") and running["id"] != stopped["id"]
    assert state(case)["tiles"][0]["id"] == running["id"]                  # the identifier is stable across requests


def test_the_page_is_reachable_from_the_navigation_and_home(case):
    assert 'href="/launcher"' in req(case, "GET", "/hardware")[2]
    assert 'href="/launcher"' in req(case, "GET", "/home")[2]


def test_an_unavailable_vm_host_shows_a_reason_and_no_tiles_instead_of_failing(tmp_path):
    c = _RealServerCase(_base_deps(vm_host=FakeHost(fail="the store is not mounted")))
    try:
        status, _, page = req(c, "GET", "/launcher")
        assert status == 200 and "the store is not mounted" in page
        status, _, body = req(c, "GET", "/launcher/state")
        assert status == 503 and "the store is not mounted" in body
    finally:
        c.close()


def test_a_shared_setting_is_saved_on_the_users_volume_and_reaches_every_os(case):
    tid = state(case)["tiles"][0]["id"]
    status, data = post(case, {"id": tid, "layer": "user", "changes": {"theme": "dark"}})
    assert status == 200 and data["ok"] is True
    assert json.load(open(os.path.join(case.tmp, "user", "settings", "shared.json"))) == {"theme": "dark"}
    for tile in state(case)["tiles"]:
        assert tile["settings"]["os"]["theme"] == {"value": "dark", "source": "user"}


def test_an_os_difference_and_an_app_setting_land_on_their_own_volumes(case):
    tid = state(case)["tiles"][0]["id"]
    assert post(case, {"id": tid, "layer": "os", "changes": {"keyboard": "de"}})[0] == 200
    assert post(case, {"id": tid, "layer": "app", "app": "chrome", "changes": {"enabled": True}})[0] == 200
    assert os.path.exists(os.path.join(case.tmp, "user", "settings", "os", f"{tid}.json"))
    app_id = next(a["id"] for a in state(case)["apps"] if a["key"] == "chrome")
    assert json.load(open(os.path.join(case.tmp, "appdata", app_id, "os", f"{tid}.json"))) == {"enabled": True}
    assert not os.path.exists(os.path.join(case.tmp, "admin", "settings"))          # nothing reaches USER_ADMIN from a guest-facing page
    assert list((case.tmp / "session").iterdir()) == []


@pytest.mark.parametrize("fields", [
    {"layer": "admin", "changes": {"theme": "dark"}},                         # the admin layer is not writable from here
    {"layer": "session", "changes": {"theme": "dark"}},
    {"layer": "user", "changes": {"theme": "neon"}},
    {"layer": "user", "changes": {"hostname": "x"}},
    {"layer": "user", "changes": {}},
    {"layer": "user", "changes": "theme=dark"},
    {"layer": "app", "app": "../../etc", "changes": {"enabled": True}},
    {"layer": "app", "app": "firefox", "changes": {"enabled": True}},
    {"layer": "app", "changes": {"enabled": True}},
    {"layer": "os", "changes": {"theme": "dark"}, "id": "O_V_99999"},         # an OS that is not on this machine
    {"layer": "os", "changes": {"theme": "dark"}, "id": "../O_V_00001"},
    {"layer": "os", "changes": {"theme": "dark"}, "id": None},
])
def test_a_bad_settings_request_is_refused_and_writes_nothing(case, fields):
    tid = state(case)["tiles"][0]["id"]
    body = {"id": tid, **fields}
    status, data = post(case, body)
    assert status == 400 and data["error"]
    assert list(case.tmp.glob("*/settings")) == [] and list(case.tmp.glob("appdata/*")) == []


def test_settings_need_a_session(case):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=10)
    conn.request("POST", "/launcher/settings", body=b"{}", headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{case.port}"})
    assert conn.getresponse().status in (303, 401)
