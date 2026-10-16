"""The launcher's model: what a tile is, what its right-click menu offers, and the console addresses for the three run modes (DR259).

Pure functions. The console addresses are Proxmox's own console pages; that they open a real console is not provable without a Proxmox."""
import pytest

import launcher_model as lm

VM = {"name": "ubuntu-desk", "vmid": 101, "running": True, "kind": "overlay", "base": "ubuntu-24.04-base", "memory_mb": 4096, "cpus": 2,
      "iso": None, "recipe": "ubuntu-desktop", "persistence_disk": "u.raw", "persistence_gb": 20, "vnc": None}


def tile(**over):
    return lm.build_tile({**VM, **over}, os_id="O_V_00001", node="pc601")


# --- the tile ---------------------------------------------------------------------------------------------------------------------

def test_a_tile_carries_the_constant_id_the_name_and_the_state():
    t = tile()
    assert t["id"] == "O_V_00001" and t["name"] == "ubuntu-desk" and t["state"] == "running" and t["kind"] == "vm"
    assert tile(running=False)["state"] == "stopped"


@pytest.mark.parametrize("vm,family,release", [
    ({"recipe": "ubuntu-desktop"}, "ubuntu", "24.04"), ({"recipe": "ubuntu-server"}, "ubuntu", "24.04"),
    ({"recipe": None, "name": "debian-13-x"}, "debian", "13"), ({"recipe": None, "name": "box", "iso": "ubuntu-24.04.2-live.iso"}, "ubuntu", "24.04"),
    ({"recipe": None, "name": "cachyos-lab"}, "arch", ""), ({"recipe": None, "name": "mystery", "base": None}, "unknown", ""),
])
def test_the_os_family_comes_from_the_recipe_the_name_or_the_installer_image(vm, family, release):
    t = tile(**vm)
    assert (t["os"]["family"], t["os"]["release"]) == (family, release)


def test_the_icon_is_a_letter_and_a_stable_hue_for_the_family():
    a, b = tile(), tile(name="other")
    assert a["icon"]["letter"] == "U" and a["icon"]["hue"] == b["icon"]["hue"]
    assert tile(recipe=None, name="debian-13")["icon"]["hue"] != a["icon"]["hue"]


def test_the_five_applications_are_listed_for_the_tile_with_honest_availability_and_no_install_claim():
    apps = tile()["apps"]
    assert [a["key"] for a in apps] == ["vscode", "spotify", "chrome", "chatgpt", "claude"]
    assert {a["support"] for a in apps} == {"native"}                      # Ubuntu is a platform the bundles support
    assert all(a["installed"] is None for a in apps)                        # nothing reports installation yet: not claimed
    assert {a["support"] for a in tile(recipe=None, name="cachyos-lab")["apps"]} == {"helper"}


# --- run modes and console addresses ----------------------------------------------------------------------------------------------

def test_the_three_run_modes_for_a_vm_are_console_window_and_fullscreen():
    modes = {m["id"]: m for m in tile()["modes"]}
    assert list(modes) == ["console", "window", "fullscreen"]
    assert all(m["enabled"] for m in modes.values())


def test_the_console_mode_says_when_the_vm_has_no_serial_port():
    modes = {m["id"]: m for m in tile(serial=False)["modes"]}
    assert modes["console"]["enabled"] is False and "serial" in modes["console"]["hint"].lower()
    assert modes["window"]["enabled"] and modes["fullscreen"]["enabled"]


def test_a_stopped_vm_offers_no_open_modes_until_it_runs():
    assert not any(m["enabled"] for m in tile(running=False)["modes"])
    assert all("start" in m["hint"].lower() for m in tile(running=False)["modes"])


def test_console_paths_use_proxmoxs_own_console_pages():
    assert lm.console_path("vm", 101, "ubuntu-desk", "pc601", "console") == \
        "/?console=kvm&xtermjs=1&vmid=101&vmname=ubuntu-desk&node=pc601&cmd="
    for mode in ("window", "fullscreen"):
        assert lm.console_path("vm", 101, "ubuntu-desk", "pc601", mode) == \
            "/?console=kvm&novnc=1&vmid=101&vmname=ubuntu-desk&node=pc601&resize=off&cmd="
    assert lm.console_path("ct", 200, "svc", "pc601", "console") == "/?console=lxc&xtermjs=1&vmid=200&vmname=svc&node=pc601&cmd="


@pytest.mark.parametrize("args", [
    ("vm", "101; reboot", "n", "node", "window"), ("vm", 101, "a b", "node", "window"), ("vm", 101, "a&x=1", "node", "window"),
    ("vm", 101, "n", "no de", "window"), ("vm", 101, "n", "node", "rdp"), ("vm", 0, "n", "node", "window"), ("vm", True, "n", "node", "window"),
    ("vm", 101, "", "node", "window"), ("lxc", 101, "n", "node", "window"), ("ct", 200, "svc", "node", "window"),
])
def test_nothing_unexpected_reaches_a_console_address(args):
    with pytest.raises(ValueError):
        lm.console_path(*args)


def test_a_container_offers_only_the_console():
    t = lm.build_tile({"name": "svc", "vmid": 200, "running": True}, os_id="O_L_00001", node="pc601", kind="ct")
    assert [m["id"] for m in t["modes"] if m["enabled"]] == ["console"]
    assert {m["id"]: m for m in t["modes"]}["window"]["hint"]


# --- the right-click menu ---------------------------------------------------------------------------------------------------------

def menu(t):
    return {i["id"]: i for i in lm.menu_for(t)}


def test_the_menu_has_open_the_power_action_and_the_four_panels():
    m = menu(tile())
    assert list(m) == ["open_console", "open_window", "open_fullscreen", "shutdown", "force_stop", "details", "vm_settings",
                       "os_settings", "applications"]
    assert menu(tile(running=False)).keys() >= {"start"} and "shutdown" not in menu(tile(running=False))


def test_vm_settings_can_only_be_changed_while_the_vm_is_stopped_and_say_why():
    assert menu(tile())["vm_settings"]["enabled"] is False and menu(tile())["vm_settings"]["hint"]
    assert menu(tile(running=False))["vm_settings"]["enabled"] is True


def test_a_container_menu_shows_the_graphical_modes_disabled_not_missing():
    t = lm.build_tile({"name": "svc", "vmid": 200, "running": True}, os_id="O_L_00001", node="pc601", kind="ct")
    assert "open_window" in menu(t) and menu(t)["open_window"]["enabled"] is False


# --- panels -----------------------------------------------------------------------------------------------------------------------

def test_details_list_the_facts_with_their_source():
    d = dict(lm.details(tile()))
    assert d["Identifier"] == "O_V_00001" and d["Proxmox ID"] == "101" and d["Memory"] == "4096 MB" and d["CPUs"] == "2"
    assert "ubuntu-24.04-base" in d["Disk"] and "20 GB" in d["Retained user disk"]


@pytest.mark.parametrize("memory,cpus,ok", [(512, 1, True), (4096, 128, True), (255, 2, False), (4096, 0, False), (4096, 129, False),
                                            ("4096", 2, False), (True, 2, False), (4096, None, False)])
def test_vm_settings_are_validated_like_the_existing_configure_action(memory, cpus, ok):
    if ok:
        assert lm.validate_vm_settings(memory, cpus) == {"memory_mb": int(memory), "cpus": int(cpus)}
    else:
        with pytest.raises(ValueError):
            lm.validate_vm_settings(memory, cpus)


# --- containers (LXC) as tiles ----------------------------------------------------------------------------------------------------

CT = {"name": "debian-svc", "vmid": 200, "running": True, "phase": "ready", "template": "debian-12-standard_12.7-1_amd64.tar.zst",
      "os_storage": "session-temp", "data_path": "/mnt/APPDATA_PERSONAL/ct/debian-svc"}


def ct_tile(**over):
    return lm.build_tile({**CT, **over}, os_id="O_L_00001", node="pc601", kind="ct")


@pytest.mark.parametrize("over,state", [({}, "running"), ({"running": False}, "stopped"), ({"running": None}, "unknown"),
                                        ({"running": False, "phase": "preparing"}, "preparing")])
def test_a_container_tile_says_what_is_known_about_it(over, state):
    assert ct_tile(**over)["state"] == state


def test_the_os_of_a_container_comes_from_its_template():
    t = ct_tile()
    assert (t["os"]["family"], t["os"]["release"]) == ("debian", "12") or t["os"]["family"] == "debian"
    assert ct_tile(template="ubuntu-24.04-standard_24.04-2_amd64.tar.zst")["os"]["family"] == "ubuntu"
    assert ct_tile(template=None)["os"]["family"] == "linux"


def test_a_container_can_only_be_opened_as_a_console_and_only_while_running():
    assert [m["id"] for m in ct_tile()["modes"] if m["enabled"]] == ["console"]
    assert not any(m["enabled"] for m in ct_tile(running=False)["modes"])
    unknown = ct_tile(running=None)
    assert not any(m["enabled"] for m in unknown["modes"]) and all("status" in m["hint"].lower() for m in unknown["modes"])


def test_a_container_menu_has_start_stop_details_and_os_settings_but_no_force_stop_vm_settings_or_applications():
    m = {i["id"]: i for i in lm.menu_for(ct_tile())}
    assert m["shutdown"]["enabled"] and "force_stop" not in m
    assert m["details"]["enabled"] and m["os_settings"]["enabled"]
    assert m["vm_settings"]["enabled"] is False and m["applications"]["enabled"] is False
    assert {i["id"]: i for i in lm.menu_for(ct_tile(running=False))}["start"]["enabled"]


def test_a_container_that_is_still_being_prepared_or_unknown_offers_no_power_actions():
    for over in ({"phase": "preparing", "running": False}, {"running": None}):
        ids = [i["id"] for i in lm.menu_for(ct_tile(**over))]
        assert "start" not in ids and "shutdown" not in ids, over
        assert "details" in ids


def test_container_details_list_its_facts():
    d = dict(lm.details(ct_tile()))
    assert d["Identifier"] == "O_L_00001" and d["Proxmox ID"] == "200" and d["Template"].startswith("debian-12")
    assert d["Storage"] == "session-temp" and d["Data folder"].startswith("/mnt/APPDATA_PERSONAL")
