"""Ubuntu recipe: a clean OS plus an independently retained home disk."""
import json
from pathlib import Path

import pytest

import ubuntu_environment as ue
from test_vm_host import FakeHost


def test_ubuntu_seed_mounts_retained_home_before_creating_the_one_admin_account():
    config = json.loads(ue.cloud_config(password_hash="$6$test$hash", desktop=True,
                                        homepage="https://baseline.invalid:8006", initialize_home=False).split("\n", 1)[1])
    assert [u["name"] for u in config["users"]] == ["baseline-admin"]
    assert config["users"][0]["hashed_passwd"] == "$6$test$hash"
    assert config["disable_root"] is True
    assert "ubuntu-desktop-minimal" in config["packages"]
    assert "firefox" in config["packages"]
    command = config["bootcmd"][0][2]
    assert "baseline-home" in command and "mount" in command
    assert "mkfs" not in command  # a rebuild never formats retained data
    assert any(m[1] == "/home" for m in config["mounts"])
    policy = next(f for f in config["write_files"] if f["path"].endswith("policies.json"))
    assert json.loads(policy["content"])["policies"]["Homepage"]["URL"] == "https://baseline.invalid:8006"


def test_seed_for_a_fresh_disk_refuses_a_nonblank_or_wrong_filesystem():
    config = json.loads(ue.cloud_config(password_hash="$6$test$hash", initialize_home=True).split("\n", 1)[1])
    command = config["bootcmd"][0][2]
    assert "mkfs.ext4" in command and "cmp" in command and "blkid" in command
    assert "wipefs" not in command


def test_boot_recipe_keeps_password_out_of_files_and_preserves_seed_on_rebuild(tmp_path):
    f = FakeHost(tmp_path / "os")
    f.host.bases_dir.mkdir(parents=True)
    (f.host.bases_dir / "ubuntu-noble.qcow2").write_bytes(b"clean OS")
    result = ue.create(f.host, "work", base="ubuntu-noble", desktop=True,
                       password_factory=lambda: b"random-one-time-value",
                       password_hasher=lambda p: "$6$test$hash")
    assert result["username"] == "baseline-admin" and result["password"] == "random-one-time-value"
    profile = f.host.persistence_store / "work" / "profile.json"
    assert b"random-one-time-value" not in profile.read_bytes()
    assert json.loads(profile.read_text())["password_hash"] == "$6$test$hash"
    assert (f.host.vm_dir("work") / "seed.iso").exists()
    assert f.host._spec("work")["uefi"] is True
    argv = f.host.qemu_argv("work")
    assert any("if=pflash" in a and "readonly=on" in a for a in argv)
    data = f.host.persistence_store / "work" / "home.qcow2"
    data.write_bytes(b"documents")
    ue.rebuild(f.host, "work")
    assert data.read_bytes() == b"documents"
    assert b"mkfs" not in (f.host.vm_dir("work") / "seed" / "user-data").read_bytes()
    assert any("seed.iso" in a for a in f.host.qemu_argv("work"))


def test_image_digest_mismatch_never_installs_a_base(tmp_path):
    f = FakeHost(tmp_path / "os")
    source = tmp_path / "upstream.img"
    source.write_bytes(b"wrong bytes")
    with pytest.raises(ue.UbuntuError, match="digest"):
        ue.install_base(f.host, source=source, expected_sha256="a" * 64)
    assert not f.host.bases_dir.exists()


def test_server_recipe_does_not_install_a_desktop():
    config = json.loads(ue.cloud_config(password_hash="$6$test$hash", desktop=False).split("\n", 1)[1])
    assert "ubuntu-desktop-minimal" not in config["packages"]
    assert "qemu-guest-agent" in config["packages"]
    assert "default" not in config["users"]


def test_home_failure_cannot_start_the_desktop_or_write_a_ready_marker():
    config = json.loads(ue.cloud_config(password_hash="$6$test$hash").split("\n", 1)[1])
    guard = next(f for f in config["write_files"] if "gdm3.service.d" in f["path"])
    assert "ConditionPathExists=/run/baseline-home-ready" in guard["content"]
    final_command = config["runcmd"][-1]
    assert final_command[:2] == ["bash", "-ec"]
    assert "baseline-home-ready" in final_command[2]
    assert "is-active" in final_command[2] and "gdm3" in final_command[2]
    assert final_command[2].endswith("touch /var/lib/baseline-environment-ready")


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://example.com\nInjected", "https://example.com/path"])
def test_homepage_must_be_a_plain_proxmox_endpoint(url):
    with pytest.raises(ue.UbuntuError):
        ue.cloud_config(password_hash="$6$test$hash", homepage=url)
