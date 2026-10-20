"""An application per machine on Proxmox: the install route follows the Linux type, the seed starts the application on its own, shares never carry a password, and the Ollama container is built right."""
import json

import pytest

import app_catalogue as ac
import app_environment as ae
from test_prebuilt_environment import carried
from test_vm_host import FakeHost

import prebuilt_environment as pe


@pytest.fixture(scope="module")
def cat():
    return ac.load()


def test_the_plan_follows_the_base_and_its_route_and_starts_the_application_on_its_own(cat):
    plan = ae.plan("spotify", "debian", resolved={"url": "https://repository.spotify.com/x.deb", "sha256": "a" * 64}, catalogue=cat)
    assert plan["base"] == "debian-base" and plan["route"] == "deb" and plan["launch"] == "spotify" and plan["headless"] is False
    assert f"echo '{'a' * 64}  /tmp/app.deb' | sha256sum -c -" in plan["script"]
    bazzite = ae.plan("vscode", "bazzite", catalogue=cat)
    assert bazzite["route"] == "flatpak" and bazzite["launch"] == "flatpak run com.visualstudio.code"
    assert ae.plan("ollama", "debian", resolved={"url": "https://x/o.tar.zst", "sha256": "b" * 64}, catalogue=cat)["headless"] is True


def test_an_application_with_no_route_for_that_linux_type_is_refused_with_the_reason(cat):
    only_deb = {**cat, "claude": {**cat["claude"], "routes": {"deb": cat["claude"]["routes"]["deb"]}}}
    with pytest.raises(ae.AppEnvError, match="no route that fits cachyos"):
        ae.plan("claude", "cachyos", catalogue=only_deb)
    web = ae.plan("claude", "cachyos", catalogue=cat)                       # with the website route it is the application's own window
    assert web["route"] == "web" and web["launch"] == "baseline-web-claude"
    with pytest.raises(ae.AppEnvError, match="not in the application catalogue"):
        ae.plan("notepad", "debian", catalogue=cat)
    with pytest.raises(ae.AppEnvError, match="declared or belongs to another side"):
        ae.plan("firefox", "nixos", catalogue=cat)


def test_a_deb_that_has_not_been_resolved_is_not_planned_blind(cat):
    with pytest.raises(ac.CatalogueError, match="must be resolved"):
        ae.plan("claude", "debian", catalogue=cat)


def test_the_seed_runs_the_install_marks_when_it_finished_and_starts_the_application_at_login(cat):
    plan = ae.plan("chatgpt", "ubuntu", resolved={"url": "https://persistent.oaistatic.com/x.deb"}, catalogue=cat)
    extra = ae.seed_extra(plan)
    paths = {f["path"]: f for f in extra["write_files"]}
    assert paths["/var/lib/baseline/install-app.sh"]["permissions"] == "0700" and "Exec=chatgpt" in paths["/etc/xdg/autostart/baseline-app.desktop"]["content"]
    assert "/etc/gdm3/daemon.conf" not in paths                                                            # signing the owner in is the base's seed's job, once
    assert "app-ready.json" in extra["runcmd"][0][2] and '"app": "chatgpt"' in extra["runcmd"][0][2]
    server = ae.seed_extra(ae.plan("ollama", "debian", resolved={"url": "https://x/o.tar.zst", "sha256": "b" * 64}, catalogue=cat))
    assert not any(f["path"].startswith("/etc/xdg/autostart") for f in server["write_files"])               # a server has no desktop to start into


def test_shares_become_mount_rows_and_never_carry_a_password():
    assert ae.mount_entry({"kind": "nfs", "server": "nas.lan", "export": "/volume1/models", "target": "/models"}) == ["nas.lan:/volume1/models", "/models", "nfs", "defaults,_netdev,nofail,x-systemd.automount", "0", "0"]
    smb = ae.mount_entry({"kind": "smb", "server": "nas.lan", "share": "projects", "target": "/srv/projects", "credentials": "/etc/baseline/smb-credentials"})
    assert smb[0] == "//nas.lan/projects" and "credentials=/etc/baseline/smb-credentials" in smb[3] and "password" not in smb[3]
    assert ae.mount_entry({"kind": "virtiofs", "tag": "models", "target": "/models"})[2] == "virtiofs"
    for bad in ({"kind": "smb", "server": "nas.lan", "share": "p", "target": "/x", "password": "x"}, {"kind": "nfs", "server": "a b", "export": "/x", "target": "/m"},
                {"kind": "nfs", "server": "n", "export": "/x", "target": "../etc"}, {"kind": "ftp", "target": "/m"}, {"kind": "virtiofs", "tag": "bad tag", "target": "/m"}):
        with pytest.raises(ae.AppEnvError):
            ae.mount_entry(bad)


def test_creating_the_vm_adds_the_application_to_the_bases_seed_for_the_signed_in_user_and_no_password_exists(tmp_path):
    f = FakeHost(tmp_path / "os")
    pe.install_base(f.host, "debian", carried(tmp_path))
    got = ae.create_vm(f.host, "spotify-vm", "spotify", "debian", owner="cliff", resolved={"url": "https://repository.spotify.com/x.deb", "sha256": "a" * 64},
                       shares=[{"kind": "virtiofs", "tag": "music", "target": "/mnt/music"}])
    assert got["owner"] == "cliff" and "password" not in got
    user_data = (f.host.vm_dir("spotify-vm") / "seed" / "user-data").read_text()
    config = json.loads(user_data.split("\n", 1)[1])
    assert any(w["path"].endswith("install-app.sh") for w in config["write_files"]) and ["music", "/mnt/music", "virtiofs", "defaults,nofail", "0", "0"] in config["mounts"]
    assert config["users"][0]["name"] == "cliff" and config["users"][0]["lock_passwd"] is True and "passwd" not in config["users"][0]
    assert any(w["path"] == "/etc/gdm3/daemon.conf" and "AutomaticLogin=cliff" in w["content"] for w in config["write_files"])


def test_extra_seed_content_is_limited_to_the_kinds_the_seed_understands():
    with pytest.raises(pe.PrebuiltError):
        pe.cloud_config("debian", owner="cliff", initialize_home=True, hostname="x", extra={"users": []})


def test_the_virtiofs_command_lines_map_a_folder_under_mnt_to_the_vm():
    mapping, device = ae.virtiofs_argv("pve1", 101, 0, "models", "/mnt/APPDATA_PERSONAL/models")
    assert mapping == ["pvesh", "create", "/cluster/mapping/dir", "--id", "models", "--map", "node=pve1,path=/mnt/APPDATA_PERSONAL/models"] and device == ["qm", "set", "101", "--virtiofs0", "models,cache=auto"]
    for bad in (("pve1", 101, 0, "models", "/etc"), ("pve1", 101, 0, "bad tag", "/mnt/x"), ("pve1", 101, 12, "m", "/mnt/x"), ("pve1", 101, 0, "m", "/mnt/../etc")):
        with pytest.raises(ae.AppEnvError):
            ae.virtiofs_argv(*bad)


def test_the_ollama_container_has_its_models_on_a_constant_volume_the_firewall_on_and_one_rule():
    got = ae.ollama_container(120, template="local:vztmpl/debian-13-standard_13.0-1_amd64.tar.zst", models_host_path="/mnt/APPDATA_PERSONAL/ollama", allow_from="192.168.1.0/24")
    create = got["create"]
    assert create[:4] == ["pct", "create", "120", "local:vztmpl/debian-13-standard_13.0-1_amd64.tar.zst"] and "--unprivileged" in create and create[create.index("--unprivileged") + 1] == "1"
    assert "firewall=1" in create[create.index("--net0") + 1] and create[create.index("--mp0") + 1] == "/mnt/APPDATA_PERSONAL/ollama,mp=/models" and create[create.index("--onboot") + 1] == "1"
    assert "IN ACCEPT -p tcp -dport 11434 -source 192.168.1.0/24" in got["firewall"] and "policy_in: DROP" in got["firewall"]
    for bad in ({"models_host_path": "/etc/shadow"}, {"allow_from": "everyone"}, {"port": 0}):
        with pytest.raises(ae.AppEnvError):
            ae.ollama_container(120, **{"template": "t", "models_host_path": "/mnt/x", "allow_from": "10.0.0.0/8", **bad})


def test_nixos_gets_no_file_in_its_read_only_etc_xdg_and_a_path_for_its_first_boot(cat):
    plan_ = ae.plan("claude", "nixos", catalogue=cat)
    extra = ae.seed_extra(plan_, tag="claude")
    assert not any(f["path"].startswith("/etc/xdg") for f in extra["write_files"])
    assert "/run/current-system/sw/bin" in extra["runcmd"][0][2]
    other = ae.seed_extra(ae.plan("claude", "cachyos", catalogue=cat), tag="claude")
    assert any(f["path"].startswith("/etc/xdg/autostart") for f in other["write_files"])
