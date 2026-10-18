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
    (folder / f"{os_id}-base.json").write_text(json.dumps({"base": f"{os_id}-base.qcow2", "sha256": sha or hashlib.sha256(data).hexdigest(), "holds_install_state_or_secrets": holds}))
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
    assert pe.owner_account(f.host, "Cliff") == "cliff"
    assert pe.owner_account(f.host, "someone-else") == "cliff"                                         # kept: the same user in every VM until more users are made
    assert json.loads((f.host.persistence_store / "owner.json").read_text()) == {"username": "cliff"}
    g = FakeHost(tmp_path / "os2")
    assert pe.owner_account(g.host, "root") == "owner"                                                 # root cannot be the VM's account: a plain name is used and kept
    assert pe.owner_account(g.host, "cliff") == "owner"


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
    pe.install_base(f.host, "omarchy", carried(tmp_path, "omarchy"))
    got = pe.create(f.host, "om", "omarchy", owner="cliff")
    assert "password" not in got and "first-boot setup" in got["message"]
    assert not (f.host.vm_dir("om") / "seed.iso").exists() and f.host._spec("om")["uefi"] is True


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
