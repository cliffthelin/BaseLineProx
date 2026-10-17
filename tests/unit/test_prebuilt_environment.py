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


def test_the_seed_makes_one_account_from_a_hash_mounts_the_retained_home_and_holds_the_display_manager_for_it():
    config = json.loads(pe.cloud_config("debian", password_hash="$6$test$hash", initialize_home=False, hostname="work").split("\n", 1)[1])
    assert [u["name"] for u in config["users"]] == ["baseline-admin"] and config["users"][0]["hashed_passwd"] == "$6$test$hash" and config["disable_root"] is True
    command = config["bootcmd"][0][2]
    assert "baseline-home" in command and "mount" in command and "mkfs" not in command               # a rebuild never formats retained data
    drop_in = next(w for w in config["write_files"] if w["path"].endswith("baseline-home.conf"))
    assert "gdm3" in drop_in["path"] and "RequiresMountsFor=/home" in drop_in["content"]
    fresh = json.loads(pe.cloud_config("debian", password_hash="$6$test$hash", initialize_home=True, hostname="work").split("\n", 1)[1])
    assert "mkfs.ext4" in fresh["bootcmd"][0][2] and "cmp -n" in fresh["bootcmd"][0][2] and "blkid" in fresh["bootcmd"][0][2]


def test_a_plain_password_is_refused_and_a_system_without_a_display_manager_unit_gets_no_drop_in():
    with pytest.raises(pe.PrebuiltError):
        pe.cloud_config("debian", password_hash="hunter2", initialize_home=True, hostname="x")
    config = json.loads(pe.cloud_config("nixos", password_hash="$6$test$hash", initialize_home=True, hostname="n").split("\n", 1)[1])
    assert not any("service.d" in w["path"] for w in config["write_files"]) and "mounts" not in config      # NixOS keeps /etc and fstab to itself


def test_creating_a_vm_makes_an_overlay_a_seed_a_retained_disk_and_keeps_the_password_only_as_a_hash(tmp_path):
    f = FakeHost(tmp_path / "os")
    pe.install_base(f.host, "debian", carried(tmp_path))
    got = pe.create(f.host, "work", "debian", password_factory=lambda: b"random-one-time-value", password_hasher=lambda p: "$6$test$hash")
    assert got["username"] == "baseline-admin" and got["password"] == "random-one-time-value"
    profile = f.host.persistence_store / "work" / "profile.json"
    assert b"random-one-time-value" not in profile.read_bytes() and json.loads(profile.read_text())["password_hash"] == "$6$test$hash"
    assert (f.host.vm_dir("work") / "seed.iso").exists() and f.host._spec("work")["uefi"] is True and f.host._spec("work")["base"] == "debian-base"
    assert b"random-one-time-value" not in (f.host.vm_dir("work") / "seed" / "user-data").read_bytes()
    assert (f.host.base_path("debian-base").resolve()).read_bytes() == b"base disk bytes"                  # the base was not written


def test_a_system_whose_own_setup_makes_the_owner_gets_an_overlay_and_no_seed(tmp_path):
    f = FakeHost(tmp_path / "os")
    pe.install_base(f.host, "omarchy", carried(tmp_path, "omarchy"))
    got = pe.create(f.host, "om", "omarchy")
    assert "password" not in got and "first-boot setup" in got["message"]
    assert not (f.host.vm_dir("om") / "seed.iso").exists() and f.host._spec("om")["uefi"] is True


def test_a_base_that_is_not_installed_is_refused_not_guessed(tmp_path):
    f = FakeHost(tmp_path / "os")
    with pytest.raises(pe.PrebuiltError, match="not installed"):
        pe.create(f.host, "work", "debian")
