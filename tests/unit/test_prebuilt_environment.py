"""Ready-made systems as VMs: a base is checked before it is used, the overlay never writes it, the one account comes from a hash, and the retained home is never formatted twice."""
import hashlib
import json

import pytest

import prebuilt_environment as pe
from test_vm_host import FakeHost


def carried(tmp_path, os_id="debian", data=b"base disk bytes", holds=False, sha=None):
    folder = tmp_path / "cache" / "os-bases"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{os_id}-base.qcow2").write_bytes(data)
    (folder / f"{os_id}-base.json").write_text(json.dumps({"base": f"{os_id}-base.qcow2", "sha256": sha or hashlib.sha256(data).hexdigest(), "holds_install_state_or_secrets": holds, "virtualization": {"recipe": "fydeos-virtio-gl-v1"} if os_id == "fydeos" else {}}))
    return folder


def test_a_carried_base_is_checked_then_linked_and_the_carried_file_stays_the_one_copy(tmp_path):
    f = FakeHost(tmp_path / "os")
    folder = carried(tmp_path)
    target = pe.install_base(f.host, "debian", folder)
    assert target.is_symlink() and target.read_bytes() == b"base disk bytes" and target.resolve() == (folder / "debian-base.qcow2").resolve()
    assert pe.install_base(f.host, "debian", folder) == target                                # again: nothing replaced


def test_a_base_that_does_not_match_or_may_hold_secrets_is_never_installed(tmp_path):
    f = FakeHost(tmp_path / "os")
    for kwargs, why in (({"sha": "0" * 64}, "checksum"), ({"holds": True}, "free of install state")):
        folder = carried(tmp_path / kwargs.get("sha", "x")[:3], **kwargs)
        with pytest.raises(pe.PrebuiltError, match=why):
            pe.install_base(f.host, "debian", folder)
    assert not f.host.bases_dir.exists() or not list(f.host.bases_dir.iterdir())
    with pytest.raises(pe.PrebuiltError, match="no ready-made base"):
        pe.base_name("windows")


def test_the_seed_makes_the_owners_account_with_no_password_signs_it_in_and_holds_the_display_manager_for_the_retained_home():
    config = json.loads(pe.cloud_config("debian", owner="cliff", initialize_home=False, hostname="work").split("\n", 1)[1])
    user = config["users"][0]
    assert [u["name"] for u in config["users"]] == ["cliff"] and user["lock_passwd"] is True and "hashed_passwd" not in user and "passwd" not in user      # no password exists
    assert user["sudo"] == ["ALL=(ALL) NOPASSWD:ALL"] and config["disable_root"] is True and user["uid"] == pe.OWNER_UID == 1100      # one uid on every system, clear of the default users
    command = config["bootcmd"][0][2]
    assert "baseline-home" in command and "mount" in command and "mkfs" not in command               # a rebuild never formats retained data
    drop_in = next(w for w in config["write_files"] if w["path"].endswith("baseline-home.conf"))
    assert "gdm3" in drop_in["path"] and "RequiresMountsFor=/home" in drop_in["content"]
    login = next(w for w in config["write_files"] if w["path"] == "/etc/gdm3/daemon.conf")
    assert "AutomaticLogin=cliff" in login["content"]                                                  # the console signs the owner straight in
    ubuntu = json.loads(pe.cloud_config("ubuntu", owner="cliff", initialize_home=False, hostname="work").split("\n", 1)[1])
    assert any(w["path"] == "/etc/gdm3/custom.conf" and "AutomaticLogin=cliff" in w["content"] for w in ubuntu["write_files"])   # Ubuntu's GDM reads custom.conf (found on the rehearsal)
    fresh = json.loads(pe.cloud_config("debian", owner="cliff", initialize_home=True, hostname="work").split("\n", 1)[1])
    assert "mkfs.ext4" in fresh["bootcmd"][0][2] and "cmp -n" in fresh["bootcmd"][0][2] and "blkid" in fresh["bootcmd"][0][2]


def test_a_reserved_or_odd_account_name_is_refused_and_a_system_without_a_display_manager_unit_gets_no_drop_in():
    for bad in ("root", "guest", "admin", "Bad Name", "", "x" * 40):
        with pytest.raises(pe.PrebuiltError):
            pe.cloud_config("debian", owner=bad, initialize_home=True, hostname="x")
    config = json.loads(pe.cloud_config("nixos", owner="cliff", initialize_home=True, hostname="n").split("\n", 1)[1])
    assert not any("service.d" in w["path"] or "daemon.conf" in w["path"] for w in config["write_files"]) and "mounts" not in config      # NixOS keeps /etc and fstab to itself
    kde = json.loads(pe.cloud_config("cachyos", owner="cliff", initialize_home=True, hostname="c").split("\n", 1)[1])
    assert any(w["path"].endswith("baseline-autologin.conf") and "User=cliff" in w["content"] for w in kde["write_files"])


def test_the_owners_name_is_the_signed_in_proxmox_user_kept_once_so_it_persists(tmp_path):
    f = FakeHost(tmp_path / "os")
    assert pe.owner_account(f.host, "Cliff", users=[]) == "cliff"
    assert pe.owner_account(f.host, "someone-else", users=[]) == "cliff"                               # kept: the same user in every VM until more users are made
    assert json.loads((f.host.persistence_store / "owner.json").read_text()) == {"username": "cliff"}


def test_the_realm_is_taken_off_the_proxmox_user_id():
    assert pe.owner_name("cliff@pam") == "cliff" and pe.owner_name("Cliff@pve") == "cliff"


def test_root_is_not_the_persons_account_but_the_one_other_proxmox_user_is(tmp_path):
    assert pe.owner_name("root@pam", ["root@pam", "cliff@pam"]) == "cliff"
    assert pe.owner_name("root@pam", ["root@pam"]) is None                                            # nothing is guessed
    assert pe.owner_name("root@pam", ["root@pam", "a@pam", "b@pam"]) is None                          # two people: not chosen for them


def test_a_root_sign_in_is_the_person_who_installed_it(tmp_path):
    import operator_identity as oi
    oi.record(tmp_path / "admin", "cane")
    f = FakeHost(tmp_path / "os")
    assert pe.owner_account(f.host, "root@pam", users=["root@pam"], operator_file=tmp_path / "admin" / oi.FILE) == "cane"
    assert pe.owner_name("root@pam", [], "cane") == "cane" and pe.owner_name("alex@pam", [], "cane") == "alex"


def test_there_is_no_generic_account_when_the_name_cannot_be_worked_out(tmp_path):
    g = FakeHost(tmp_path / "os2")
    with pytest.raises(pe.OwnerUnknown):
        pe.owner_account(g.host, "root@pam", users=["root@pam"], operator_file=tmp_path / "none.json")
    assert not (g.host.persistence_store / "owner.json").exists()
    assert pe.set_owner(g.host, "Cliff") == "cliff" and pe.owner_account(g.host, "root@pam", users=[]) == "cliff"
    for bad in ("owner", "guest", "root", "Bad Name", ""):
        with pytest.raises(pe.PrebuiltError):
            pe.set_owner(g.host, bad)


def test_a_generic_name_recorded_by_an_earlier_version_is_not_kept(tmp_path):
    f = FakeHost(tmp_path / "os")
    f.host.persistence_store.mkdir(parents=True, exist_ok=True)
    (f.host.persistence_store / "owner.json").write_text(json.dumps({"username": "owner"}))
    assert pe.owner_account(f.host, "cliff@pam", users=[]) == "cliff"


def test_creating_a_vm_makes_an_overlay_a_seed_and_a_retained_disk_and_no_password_exists_anywhere(tmp_path):
    f = FakeHost(tmp_path / "os")
    pe.install_base(f.host, "debian", carried(tmp_path))
    got = pe.create(f.host, "work", "debian", owner="cliff")
    assert got["owner"] == "cliff" and "password" not in got and "no separate login" in got["message"]
    profile = (f.host.persistence_store / "work" / "profile.json").read_text()
    assert json.loads(profile)["owner"] == "cliff" and "password" not in profile
    assert (f.host.vm_dir("work") / "seed.iso").exists() and f.host._spec("work")["uefi"] is True and f.host._spec("work")["base"] == "debian-base"
    assert "passwd" not in (f.host.vm_dir("work") / "seed" / "user-data").read_text().replace("lock_passwd", "")
    assert (f.host.base_path("debian-base").resolve()).read_bytes() == b"base disk bytes"                  # the base was not written


def test_a_system_whose_own_setup_makes_the_owner_gets_an_overlay_and_no_seed(tmp_path):
    f = FakeHost(tmp_path / "os")
    pe.install_base(f.host, "fydeos", carried(tmp_path, "fydeos"))
    got = pe.create(f.host, "om", "fydeos", owner="cliff")
    assert "password" not in got and "first-boot setup" in got["message"]
    assert not (f.host.vm_dir("om") / "seed.iso").exists() and f.host._spec("om")["uefi"] is True


def test_omarchy_and_bazzite_are_seeded_through_the_seed_runner_with_no_password_anywhere():
    omarchy = _seed("omarchy")
    assert omarchy["users"] == []                                                                  # Omarchy's own first-boot script makes the account, fed from the seed
    assert ["/usr/bin/python3", "/etc/baseline-seed/omarchy_owner.py", "cliff", "work"] in omarchy["runcmd"]
    assert omarchy["bootcmd"][0][0] == "/bin/sh"
    bazzite = _seed("bazzite")
    assert bazzite["users"][0]["name"] == "cliff" and bazzite["users"][0]["lock_passwd"] is True
    assert any(w["path"] == "/etc/sddm.conf.d/baseline-autologin.conf" for w in bazzite["write_files"])
    for config in (omarchy, bazzite):
        assert "passwd:" not in json.dumps(config) and "chpasswd" not in json.dumps(config)


def test_a_base_that_is_not_installed_is_refused_not_guessed(tmp_path):
    f = FakeHost(tmp_path / "os")
    with pytest.raises(pe.PrebuiltError, match="not installed"):
        pe.create(f.host, "work", "debian", owner="cliff")


def test_a_disk_smaller_than_the_systems_own_is_refused_before_anything_is_created(tmp_path):
    """Found on the rehearsal: asking for 8 GB over a 32 GB base failed inside qemu-img after the VM was already registered."""
    f = FakeHost(tmp_path / "os")
    pe.install_base(f.host, "debian", carried(tmp_path))
    original = f.run.__call__
    def run(argv):
        if argv[:2] == ["qemu-img", "info"]:
            f.run.calls.append(list(argv))
            return 0, json.dumps({"virtual-size": 32 * 2**30}), ""
        return original(argv)
    f.host.run = run
    with pytest.raises(pe.PrebuiltError, match="at least 32 GB"):
        pe.create(f.host, "work", "debian", owner="cliff", disk_gb=8)
    assert not f.host.vm_dir("work").exists()                                                     # nothing was made
    assert pe.create(f.host, "work", "debian", owner="cliff", disk_gb=40)["owner"] == "cliff"


def _seed(os_id, initialize_home=True):
    return json.loads(pe.cloud_config(os_id, owner="cliff", initialize_home=initialize_home, hostname="work").split("\n", 1)[1])


@pytest.mark.parametrize("os_id", ["debian", "ubuntu", "nixos", "cachyos"])
def test_the_home_script_is_plain_sh_that_finds_its_tools_on_every_system(os_id):
    """Found on the rehearsal: NixOS has no `bash` on cloud-init's PATH (exit 127, no home, no sign-in)."""
    command = _seed(os_id)["bootcmd"][0]
    assert command[0] == "/bin/sh" and command[1] == "-c"
    script = command[2]
    assert "/run/current-system/sw/bin" in script and "/run/wrappers/bin" in script and "/usr/sbin" in script       # NixOS and the usual places
    for bashism in ("[[", "<<<", "function ", "$'", "==", "local ", "declare "):                                 # plain POSIX sh only (also checked by running it on each system)
        assert bashism not in script


def test_a_home_that_is_already_a_mountpoint_on_the_systems_own_disk_is_mounted_over_not_skipped():
    """Found on the rehearsal: CachyOS keeps /home as a btrfs subvolume, so 'mount unless /home is a mountpoint' left the retained disk unmounted."""
    script = _seed("cachyos")["bootcmd"][0][2]
    assert "mountpoint -q /home" not in script
    assert "--target /home" in script and "tail -n 1" in script                                                  # compares the topmost mount's source with the retained disk
    assert "mount -t ext4" in script


def test_each_system_signs_the_owner_in_through_the_login_manager_it_actually_has():
    cachyos = _seed("cachyos")
    paths = {w["path"]: w["content"] for w in cachyos["write_files"]}
    assert "User=cliff" in paths["/etc/plasmalogin.conf.d/baseline-autologin.conf"] and "Session=plasma" in paths["/etc/plasmalogin.conf.d/baseline-autologin.conf"]
    assert "User=cliff" in paths["/etc/sddm.conf.d/baseline-autologin.conf"] and "Session=plasma.desktop" in paths["/etc/sddm.conf.d/baseline-autologin.conf"]   # SDDM signs in only when told which session
    assert "/etc/systemd/system/plasmalogin.service.d/baseline-home.conf" in paths
    nixos = _seed("nixos")
    rewrite = [c for c in nixos["bootcmd"][1:] if "/etc/gdm/custom.conf" in c[2]]
    assert rewrite and "rm -f /etc/gdm/custom.conf" in rewrite[0][2] and "AutomaticLogin=cliff" in rewrite[0][2]      # NixOS links the file into the store; a real file replaces the link
    assert any("display-manager" in " ".join(c) for c in nixos["runcmd"])                                         # a greeter already up is restarted so the sign-in applies
    for os_id in ("debian", "ubuntu"):
        assert not any("display-manager" in " ".join(c) for c in _seed(os_id)["runcmd"])


def test_the_retained_home_gets_its_selinux_label_on_systems_that_have_one():
    """Found on the rehearsal: a freshly formatted disk's root has no label, and Bazzite's login manager could not enter the owner's home on it."""
    for os_id in ("bazzite", "debian", "nixos"):
        script = _seed(os_id)["bootcmd"][0][2]
        assert 'command -v restorecon' in script and 'restorecon -F "$(readlink -f /home)"' in script
        assert script.index("restorecon") < script.index("touch /run/baseline-home-ready")                 # labelled before anything may sign in
