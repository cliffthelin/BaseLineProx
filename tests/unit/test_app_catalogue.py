"""The application catalogue and the install helper: validated entries, each system's own preference, safe non-interactive scripts."""
import copy
import json
import subprocess

import pytest

import app_catalogue as ac


@pytest.fixture(scope="module")
def cat():
    return ac.load()


def test_the_shipped_catalogue_is_valid_and_has_the_browsers_and_the_six_proxmox_apps(cat):
    assert {"firefox", "chromium", "chrome", "brave", "librewolf", "vivaldi", "vscode", "spotify", "claude", "chatgpt", "lm-studio", "ollama"} <= set(cat)
    browsers = [e for e in cat.values() if e["category"] == "browsers"]
    assert len(browsers) == 6 and all("flatpak" in e["routes"] for e in browsers)                  # every browser has a route that fits an immutable system
    images = [e["routes"]["container"]["image"] for e in cat.values() if "container" in e["routes"]]
    assert images and all(i.endswith(":latest") for i in images)                                     # never LinuxServer's deprecated kasm tags


def test_each_system_picks_from_its_own_preference_order(cat):
    assert ac.route_for(cat["firefox"], "debian")[0] == "apt" and ac.route_for(cat["firefox"], "ubuntu")[0] == "flatpak"       # Ubuntu's repository Firefox is a snap
    assert ac.route_for(cat["brave"], "debian")[0] == "flatpak"                                                                 # no repository package: Flatpak
    assert [ac.route_for(cat["firefox"], s)[0] for s in ("cachyos", "omarchy", "bazzite", "nixos", "kasm")] == ["pacman", "pacman", "flatpak", "nix", "proot"]
    route, why = ac.route_for(cat["firefox"], "windows")
    assert route is None and "not a system" in why


def test_a_route_restricted_to_other_systems_is_skipped_and_a_dead_end_is_reported(cat):
    odd = copy.deepcopy(cat["firefox"])
    odd["routes"] = {"apt": {"package": "firefox-esr", "only": ["debian"]}}
    assert ac.route_for(odd, "debian")[0] == "apt"
    route, why = ac.route_for(odd, "bazzite")
    assert route is None and "no route that fits bazzite" in why
    with pytest.raises(ac.CatalogueError, match="no route"):
        ac.install_script(odd, "bazzite")


def test_the_install_scripts_are_noninteractive_fail_fast_and_valid_shell(cat):
    for os_id, app, must in (("debian", "firefox", "apt-get install -y firefox-esr"), ("cachyos", "chromium", "pacman -Syu --noconfirm --needed chromium"),
                             ("bazzite", "brave", "flatpak install -y --system --noninteractive flathub com.brave.Browser"), ("ubuntu", "vivaldi", "apt-get install -y flatpak")):
        script = ac.install_script(cat[app], os_id)
        assert must in script and "set -eu" in script and "DEBIAN_FRONTEND=noninteractive" in script
        assert subprocess.run(["sh", "-n"], input=script, text=True, capture_output=True).returncode == 0
    assert ac.install_script(cat["firefox"], "nixos") is None and ac.install_script(cat["firefox"], "kasm") is None        # declared or belonging to another side: not an install-time command


def test_nixos_gets_attributes_for_its_configuration_not_a_command(cat):
    assert ac.nix_attrs([cat["firefox"], cat["brave"]]) == ["firefox", "brave"]
    import os_build
    assert "firefox brave" in os_build.nix_configuration(packages=("vscode", *ac.nix_attrs([cat["firefox"], cat["brave"]]))).replace("vscode ", "")


@pytest.mark.parametrize("change,why", [
    ({"id": "Bad Id"}, "entry needs"), ({"category": "games"}, "entry needs"), ({"name": ""}, "entry needs"), ({"routes": {}}, "routes are"), ({"routes": {"snap": {"x": 1}}}, "routes are"),
    ({"routes": {"apt": {"package": "x; rm -rf /"}}}, "plain name"), ({"routes": {"flatpak": {"id": "not-an-id"}}}, "plain name"), ({"routes": {"nix": {"attr": "a b"}}}, "plain name"),
    ({"routes": {"container": {"image": "x:latest", "ports": [70000], "config": "/config"}}}, "plain name"), ({"routes": {"container": {"image": "x", "ports": [80], "config": "/config"}}}, "plain name"),
    ({"routes": {"apt": {"package": "firefox", "only": ["windows"]}}}, "known systems"), ({"data": ["../etc"]}, "data paths"),
])
def test_an_entry_with_an_odd_value_is_refused(cat, change, why):
    bad = {**copy.deepcopy(cat["firefox"]), **change}
    with pytest.raises(ac.CatalogueError, match=why):
        ac.validate_entry(bad)


def test_a_catalogue_with_a_duplicate_or_the_wrong_format_is_refused(cat, tmp_path):
    entry = cat["firefox"]
    (tmp_path / "dup.json").write_text(json.dumps({"format": ac.FORMAT, "apps": [entry, entry]}))
    with pytest.raises(ac.CatalogueError, match="twice"):
        ac.load(tmp_path / "dup.json")
    (tmp_path / "wrong.json").write_text(json.dumps({"format": "other", "apps": []}))
    with pytest.raises(ac.CatalogueError, match="format"):
        ac.load(tmp_path / "wrong.json")
    with pytest.raises(ac.CatalogueError, match="cannot be read"):
        ac.load(tmp_path / "absent.json")


def test_an_apt_update_error_is_reported_but_the_install_that_follows_decides(cat):
    script = ac.install_script(cat["firefox"], "debian")
    assert "apt-get update ||" in script and script.index("apt-get update") < script.index("apt-get install -y firefox-esr")
    assert "apt-get update ||" in ac.install_script(cat["vivaldi"], "ubuntu")                          # also before Flatpak is installed


def test_claude_and_chatgpt_reach_every_system_that_has_no_program_for_them_as_their_own_window(cat):
    for system in ("debian", "ubuntu"):
        assert ac.route_for(cat["claude"], system)[0] == "deb"                  # the real program where there is one
    for system in ("cachyos", "omarchy", "bazzite", "nixos"):
        assert ac.route_for(cat["claude"], system)[0] == "web" and ac.route_for(cat["chatgpt"], system)[0] == "web"
    script = ac.install_script(cat["claude"], "bazzite")
    assert "https://claude.ai" in script and "--password-store=basic" in script and "/usr/local/bin/baseline-web-claude" in script and script.startswith("#!/bin/sh\nset -eu")
    import subprocess
    assert subprocess.run(["sh", "-n"], input=script, text=True).returncode == 0


def test_a_web_route_takes_only_a_plain_https_address():
    for bad in ("http://x.com", "https://x.com/a b", "https://x.com/'; rm", "https://localhost", "javascript:x"):
        with pytest.raises(ac.CatalogueError):
            ac.validate_entry({"id": "x", "name": "X", "category": "ai-tools", "routes": {"web": {"url": bad}}})
