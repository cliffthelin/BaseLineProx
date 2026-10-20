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


class RecordingHost:
    """Only what the create action calls; records it."""
    def __init__(self):
        self.calls = []

    def create_from_iso(self, name, **kw):
        self.calls.append(("create_from_iso", name, kw))

    def configure_uefi(self, name):
        self.calls.append(("configure_uefi", name))


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


CTS = [{"name": "debian-svc", "vmid": 200, "running": True, "phase": "ready", "template": "debian-12-standard_12.7-1_amd64.tar.zst",
        "os_storage": "session-temp", "data_path": "/mnt/APPDATA_PERSONAL/ct/debian-svc", "base_vmid": 9000}]


class FakeContainers:
    def __init__(self, items=CTS, fail=None):
        self.items, self.fail = items, fail

    def list_containers(self):
        if self.fail:
            raise vh.VmError(self.fail)
        return self.items


def test_containers_appear_as_tiles_with_their_own_identifiers_and_a_console_only(case):
    case.server.deps["container_host"] = FakeContainers()                                   # type: ignore[attr-defined]
    tiles = state(case)["tiles"]
    assert [t["name"] for t in tiles] == ["ubuntu-desk", "debian-13-lab", "debian-svc"]
    ct = tiles[2]
    assert ct["kind"] == "ct" and ct["id"].startswith("O_L_") and list(ct["paths"]) == ["console"]
    assert ct["paths"]["console"].startswith("/?console=lxc&xtermjs=1&vmid=200")
    status, _, page = req(case, "GET", "/launcher")
    assert status == 200 and "debian-svc" in page and "/containers/action" in page


def test_a_container_shares_the_users_settings_and_can_be_given_its_own(case):
    case.server.deps["container_host"] = FakeContainers()                                   # type: ignore[attr-defined]
    ct_id = state(case)["tiles"][2]["id"]
    assert post(case, {"id": ct_id, "layer": "user", "changes": {"theme": "dark"}})[0] == 200
    assert post(case, {"id": ct_id, "layer": "os", "changes": {"keyboard": "de"}})[0] == 200
    ct = state(case)["tiles"][2]
    assert ct["settings"]["os"]["theme"]["source"] == "user" and ct["settings"]["os"]["keyboard"]["source"] == "os"
    assert os.path.exists(os.path.join(case.tmp, "user", "settings", "os", f"{ct_id}.json"))


def test_a_container_listing_problem_is_a_notice_and_the_vms_stay(case):
    case.server.deps["container_host"] = FakeContainers(fail="pct status failed")           # type: ignore[attr-defined]
    s = state(case)
    assert [t["name"] for t in s["tiles"]] == ["ubuntu-desk", "debian-13-lab"]
    assert any("pct status failed" in n for n in s["notices"])
    assert "pct status failed" in req(case, "GET", "/launcher")[2]


def test_a_container_host_that_is_not_there_is_not_an_error(case):
    assert state(case)["notices"] == [] and [t["kind"] for t in state(case)["tiles"]] == ["vm", "vm"]


# --- swap per VM / container (operator 2026-10-16) ----------------------------------------------------------------------------------

class Recorder:
    def __init__(self, rc=0, err=""):
        self.calls, self.rc, self.err = [], rc, err

    def run(self, argv, timeout=10):
        self.calls.append(list(argv))
        return type("P", (), {"returncode": self.rc, "stdout": "", "stderr": self.err})()


def test_swap_is_offered_in_the_os_settings_with_the_agreed_sizes(case):
    swap = state(case)["schema"]["os"]["swap_mb"]
    assert swap["type"] == "choice" and swap["choices"] == [0, 256, 512, 1024, 2048, 4096, 8192, 16384]


def test_a_vms_swap_is_stored_for_the_guest_and_nothing_is_run(case):
    rec = Recorder()
    case.server.deps["container_runner"] = rec                                           # type: ignore[attr-defined]
    vm = state(case)["tiles"][0]
    status, data = post(case, {"id": vm["id"], "layer": "os", "changes": {"swap_mb": 2048}})
    assert status == 200 and data["ok"] is True and data.get("applied") is None
    assert state(case)["tiles"][0]["settings"]["os"]["swap_mb"] == {"value": 2048, "source": "os"}
    assert rec.calls == []                                                               # a VM's swap is inside the guest: stored, not applied here


def test_a_containers_swap_is_applied_by_proxmox_itself_and_then_stored(case):
    rec = Recorder()
    case.server.deps["container_runner"] = rec                                           # type: ignore[attr-defined]
    case.server.deps["container_host"] = FakeContainers()                                # type: ignore[attr-defined]
    ct = state(case)["tiles"][2]
    status, data = post(case, {"id": ct["id"], "layer": "os", "changes": {"swap_mb": 1024}})
    assert status == 200 and rec.calls == [["pct", "set", "200", "--swap", "1024"]] and data["applied"] == "pct set 200 --swap 1024"
    assert state(case)["tiles"][2]["settings"]["os"]["swap_mb"]["value"] == 1024


def test_when_proxmox_refuses_the_containers_swap_nothing_is_stored(case):
    case.server.deps["container_runner"] = Recorder(rc=255, err="unable to set swap: not enough memory")   # type: ignore[attr-defined]
    case.server.deps["container_host"] = FakeContainers()                                # type: ignore[attr-defined]
    ct = state(case)["tiles"][2]
    status, data = post(case, {"id": ct["id"], "layer": "os", "changes": {"swap_mb": 16384}})
    assert status == 502 and "not enough memory" in data["error"]
    assert "swap_mb" not in state(case)["tiles"][2]["settings"]["os"]


def test_the_shared_swap_setting_is_not_pushed_into_containers(case):
    rec = Recorder()
    case.server.deps["container_runner"] = rec                                           # type: ignore[attr-defined]
    case.server.deps["container_host"] = FakeContainers()                                # type: ignore[attr-defined]
    ct = state(case)["tiles"][2]
    assert post(case, {"id": ct["id"], "layer": "user", "changes": {"swap_mb": 512}})[0] == 200
    assert rec.calls == []                       # "all my OSes" is a default for new ones, not a change to every running container


# ---- the supported-OS list: operating systems that are asked for and not built yet ---------------------------------------------

LISTING = {"os": [
    {"id": "debian", "name": "Debian 13", "iso": "debian-13.7.0-amd64-DVD-1.iso", "apps": ["vscode", "chrome"]},
    {"id": "qubes", "name": "Qubes OS 4.3", "iso": "Qubes-R4.3.2-x86_64.iso"},
    {"id": "kasm-workspaces", "name": "Kasm", "kind": "kasm"}]}


def test_the_launcher_offers_listed_operating_systems_that_are_not_built_yet(case):
    listing = case.tmp / "supported-os.json"
    listing.write_text(json.dumps(LISTING))
    isos = case.tmp / "isos"
    isos.mkdir()
    case.server.deps["os_list_path"] = str(listing)        # type: ignore[attr-defined]
    case.server.deps["vm_iso_dir"] = str(isos)             # type: ignore[attr-defined]  # not this machine's real cache
    state = req(case, "GET", "/launcher/state")[2]
    available = json.loads(state)["available"]
    assert [a["id"] for a in available] == ["qubes"]       # debian-13-lab is built; Kasm is the workspaces component, not a guest OS
    assert available[0]["name"] == "Qubes OS 4.3" and available[0]["image"] == "missing" and len(available[0]["apps"]) == 5
    assert "blocked" in available[0]                       # Qubes is never offered as a plain VM, and its image is missing here as well
    page = req(case, "GET", "/launcher")[2]
    assert "Available to create" in page and "drawAvailable" in page
    (isos / "Qubes-R4.3.2-x86_64.iso").write_bytes(b"x")
    assert json.loads(req(case, "GET", "/launcher/state")[2])["available"][0]["image"] == "carried"


def test_without_a_list_or_with_a_bad_one_the_tiles_are_unaffected(case):
    case.server.deps["os_list_path"] = str(case.tmp / "none.json")        # type: ignore[attr-defined]
    state = json.loads(req(case, "GET", "/launcher/state")[2])
    assert state["available"] == [] and [t["name"] for t in state["tiles"]] == ["ubuntu-desk", "debian-13-lab"]
    bad = case.tmp / "bad.json"
    bad.write_text("not json")
    case.server.deps["os_list_path"] = str(bad)            # type: ignore[attr-defined]
    state = json.loads(req(case, "GET", "/launcher/state")[2])
    assert state["available"] == [] and any("supported-OS list could not be used" in n for n in state["notices"]) and len(state["tiles"]) == 2


def test_a_carried_listed_system_comes_with_a_plan_the_create_action_accepts(case):
    listing = case.tmp / "supported-os.json"
    listing.write_text(json.dumps({"os": [{"id": "debian", "name": "Debian 13", "iso": "debian-13.7.0-amd64-DVD-1.iso"}, {"id": "bazzite", "name": "Bazzite", "iso": "bazzite-stable-amd64.iso"}]}))
    isos = case.tmp / "isos2"
    isos.mkdir()
    (isos / "bazzite-stable-amd64.iso").write_bytes(b"x")
    case.server.deps.update(os_list_path=str(listing), vm_iso_dir=str(isos), host_memory_mb=lambda: 65536)      # type: ignore[attr-defined]
    available = json.loads(req(case, "GET", "/launcher/state")[2])["available"]
    plan = available[0]["plan"]
    assert [a["id"] for a in available] == ["bazzite"] and plan["firmware"] == "uefi" and plan["name"] == "bazzite"
    import vm_page
    assert set(plan) == {"name", "iso", "disk_gb", "memory_mb", "cpus", "firmware"}                 # exactly the create_iso parameters
    host = RecordingHost()                                                       # the plan, handed to the real create action, creates the VM with UEFI
    vm_page.perform(host, "create_iso", dict(plan), iso_dir=str(isos))
    assert host.calls == [("create_from_iso", "bazzite", {"iso": str(isos / "bazzite-stable-amd64.iso"), "disk_gb": 80, "memory_mb": 8192, "cpus": 4}),
                          ("configure_uefi", "bazzite")]
