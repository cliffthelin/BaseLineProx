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


def test_existing_ubuntu_base_without_verification_receipt_is_not_trusted(tmp_path):
    f=FakeHost(tmp_path/'os')
    target=f.host.base_path(ue.BASE_NAME);target.parent.mkdir(parents=True)
    target.write_bytes(b'unknown image')
    with pytest.raises(ue.UbuntuError,match='receipt'):
        ue.acquire_base(f.host,cache_dir=tmp_path/'cache')


def test_base_receipt_detects_changed_image_before_reuse(tmp_path):
    import hashlib
    f=FakeHost(tmp_path/'os')
    source=tmp_path/'source.img';source.write_bytes(b'vanilla')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    def convert(argv):
        assert argv[:2]==['qemu-img','convert']
        Path(argv[-1]).write_bytes(b'converted test image')
        return 0,'',''
    f.host.run=convert
    target=ue.install_base(f.host,source=source,expected_sha256=digest)
    assert ue.verify_base(f.host,target,expected_source_sha256=digest)==target
    target.chmod(0o600);target.write_bytes(b'changed')
    with pytest.raises(ue.UbuntuError,match='digest'):
        ue.verify_base(f.host,target,expected_source_sha256=digest)


def test_vm_base_preparation_uses_identified_vanilla_source_acquisition(tmp_path,monkeypatch):
    import hashlib,installer_sources
    f=FakeHost(tmp_path/'os');source=tmp_path/'pinned.img';source.write_bytes(b'vanilla')
    digest=hashlib.sha256(source.read_bytes()).hexdigest();monkeypatch.setattr(ue,'IMAGE_SHA256',digest)
    observed=[]
    def acquire(runner,root):
        observed.append(root)
        return {'path':str(source),'sha256':digest}
    monkeypatch.setattr(installer_sources,'acquire_ubuntu',acquire)
    def convert(argv):
        assert argv[:2]==['qemu-img','convert']
        Path(argv[-1]).write_bytes(b'converted fixture')
        return 0,'',''
    f.host.run=convert
    ue.acquire_base(f.host,cache_dir=tmp_path/'cache/images')
    assert observed==[tmp_path/'cache']
