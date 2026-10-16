"""What the launcher page is built from: tiles, their menus, console paths and the settings of every OS and application (DR259)."""
import pytest

import launcher_state as lst
import layered_settings as ls

VMS = [
    {"name": "ubuntu-desk", "vmid": 101, "running": True, "kind": "overlay", "base": "ubuntu-24.04-base", "memory_mb": 4096, "cpus": 2,
     "iso": None, "recipe": "ubuntu-desktop", "persistence_disk": "u.raw", "persistence_gb": 20, "vnc": None},
    {"name": "debian-13-lab", "vmid": 102, "running": False, "kind": "standalone", "base": None, "memory_mb": 2048, "cpus": 1,
     "iso": None, "recipe": None, "persistence_disk": None, "persistence_gb": None, "vnc": None},
]


@pytest.fixture
def roots(tmp_path):
    made = [tmp_path / n for n in ("admin", "user", "appdata", "session")]
    for p in made:
        p.mkdir()
    return ls.Roots(*map(str, made))


def collect(roots, vms=VMS):
    os_ids = {"ubuntu-desk": "O_V_00001", "debian-13-lab": "O_V_00002"}
    apps = {"vscode": "A_D_00001", "spotify": "A_D_00002", "chrome": "A_D_00003", "chatgpt": "A_D_00004", "claude": "A_D_00005"}
    return lst.collect(vms, node="pc601", roots=roots, os_id_for=lambda vm: os_ids[vm["name"]], app_id_for=lambda key: apps[key])


def test_every_vm_becomes_a_tile_with_its_menu_details_and_console_paths(roots):
    state = collect(roots)
    assert [t["name"] for t in state["tiles"]] == ["ubuntu-desk", "debian-13-lab"]
    running, stopped = state["tiles"]
    assert running["paths"]["window"].startswith("/?console=kvm&novnc=1&vmid=101")
    assert stopped["paths"] == {}                                           # nothing to open until it runs
    assert [i["id"] for i in running["menu"]][:3] == ["open_console", "open_window", "open_fullscreen"]
    assert dict(running["details"])["Identifier"] == "O_V_00001"
    assert state["host"] == "pc601"


def test_settings_of_each_os_and_application_are_included_with_their_source(roots):
    ls.write_layer(roots, "user", {"theme": "dark"})
    ls.write_layer(roots, "os", {"keyboard": "de"}, os_id="O_V_00001")
    ls.write_layer(roots, "app", {"enabled": True}, os_id="O_V_00001", app_id="A_D_00003")
    state = collect(roots)
    first, second = state["tiles"]
    assert first["settings"]["os"]["theme"] == {"value": "dark", "source": "user"}
    assert first["settings"]["os"]["keyboard"]["source"] == "os"
    assert second["settings"]["os"]["theme"]["source"] == "user" and "keyboard" not in second["settings"]["os"]
    assert first["settings"]["apps"]["chrome"]["enabled"] == {"value": True, "source": "app"}
    assert first["settings"]["apps"]["chrome"]["theme"]["value"] == "dark"
    assert "enabled" not in second["settings"]["apps"]["chrome"]
    assert first["settings_error"] == ""


def test_a_settings_problem_is_shown_on_the_tile_and_does_not_hide_the_tiles(roots):
    import os
    with open(os.path.join(roots.user, "x"), "w"):
        pass
    os.makedirs(os.path.join(roots.user, "settings"))
    with open(os.path.join(roots.user, "settings", "shared.json"), "w") as f:
        f.write("{broken")
    state = collect(roots)
    assert len(state["tiles"]) == 2
    assert all("unreadable" in t["settings_error"] and t["settings"] is None for t in state["tiles"])


def test_a_vm_without_an_identifier_is_still_shown_with_settings_disabled(roots):
    def no_id(vm):
        raise OSError("registry unavailable")
    state = lst.collect(VMS, node="pc601", roots=roots, os_id_for=no_id, app_id_for=lambda k: "A_D_00001")
    assert len(state["tiles"]) == 2
    assert all(t["id"] is None and "registry unavailable" in t["settings_error"] for t in state["tiles"])


def test_the_schema_lists_every_setting_with_its_choices(roots):
    schema = collect(roots)["schema"]
    assert schema["os"]["theme"]["choices"] == ["light", "dark", "auto"]
    assert schema["os"]["default_run_mode"]["choices"] == ["console", "window", "fullscreen"]
    assert schema["os"]["display_scale"]["choices"] == [100, 125, 150, 200]
    assert "pattern" in schema["os"]["timezone"] and schema["app"]["enabled"]["type"] == "boolean"


def test_the_five_applications_are_described_once_for_the_page(roots):
    apps = collect(roots)["apps"]
    assert [a["key"] for a in apps] == ["vscode", "spotify", "chrome", "chatgpt", "claude"]
    assert apps[0]["label"] == "VS Code" and apps[3]["label"] == "ChatGPT"


CTS = [{"name": "debian-svc", "vmid": 200, "running": True, "phase": "ready", "template": "debian-12-standard_12.7-1_amd64.tar.zst",
        "os_storage": "session-temp", "data_path": "/mnt/APPDATA_PERSONAL/ct/debian-svc"}]


def collect_with_containers(roots, containers=CTS, **kw):
    os_ids = {"ubuntu-desk": "O_V_00001", "debian-13-lab": "O_V_00002"}
    apps = {k: "A_D_%05d" % i for i, k in enumerate(["vscode", "spotify", "chrome", "chatgpt", "claude"], 1)}
    return lst.collect(VMS, node="pc601", roots=roots, os_id_for=lambda vm: os_ids[vm["name"]], app_id_for=lambda k: apps[k],
                       containers=containers, container_id_for=lambda ct: "O_L_00001", **kw)


def test_containers_follow_the_vms_as_tiles_with_console_paths(roots):
    state = collect_with_containers(roots)
    assert [t["name"] for t in state["tiles"]] == ["ubuntu-desk", "debian-13-lab", "debian-svc"]
    ct = state["tiles"][2]
    assert ct["kind"] == "ct" and ct["id"] == "O_L_00001" and ct["paths"] == {"console": "/?console=lxc&xtermjs=1&vmid=200&vmname=debian-svc&node=pc601&cmd="}
    assert ct["apps"] == [] and ct["settings"]["os"] == {}


def test_a_container_shares_the_users_settings_like_any_other_os(roots):
    ls.write_layer(roots, "user", {"theme": "dark"})
    ct = collect_with_containers(roots)["tiles"][2]
    assert ct["settings"]["os"]["theme"] == {"value": "dark", "source": "user"}


def test_without_containers_nothing_changes(roots):
    assert [t["kind"] for t in collect(roots)["tiles"]] == ["vm", "vm"]


def test_an_unavailable_container_host_is_reported_and_the_vms_stay(roots):
    state = collect_with_containers(roots, containers=None, containers_error="pct is not installed")
    assert len(state["tiles"]) == 2 and any("pct is not installed" in n for n in state["notices"])
    assert collect(roots)["notices"] == []
