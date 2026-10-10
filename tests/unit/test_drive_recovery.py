import json
import pytest
import hashlib
from fake_runner import FakeRunner, FakeProc


def test_recovery_snapshot_refuses_any_mounted_descendant_before_writing(tmp_path):
    import drive_recovery as recovery
    listing = {"blockdevices": [{"name": "/dev/sdc", "type": "disk", "serial": "DRIVE-A",
        "size": 512_110_190_592, "mountpoints": [None], "children": [
            {"name": "/dev/sdc1", "type": "part", "mountpoints": ["/data"]}]}]}
    runner = FakeRunner(command_responses=[
        (lambda a: a[0] == "lsblk", FakeProc(0, json.dumps(listing), "")),
    ])
    with pytest.raises(recovery.RecoveryError, match="mounted"):
        recovery.create_snapshot(runner, serial="DRIVE-A", destination=str(tmp_path),
                                 allowed_serials={"DRIVE-A"})
    assert not list(tmp_path.iterdir())
    assert not any(a[0] == "qemu-img" for a in runner.calls)


def test_recovery_verification_refuses_a_valid_image_of_the_wrong_disk_size(tmp_path):
    import drive_recovery as recovery
    image = tmp_path / "drive.qcow2"
    image.write_bytes(b"synthetic image")
    manifest = {"format": "baseline-drive-recovery-v1", "serial": "DRIVE-A", "image": "drive.qcow2",
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "complete": True,
                "source_compared": True, "size_bytes": 512_110_190_592, "image_bytes": image.stat().st_size}
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["qemu-img", "info"], FakeProc(0, json.dumps({"virtual-size": 4096, "format": "qcow2"}), "")),
    ])
    with pytest.raises(recovery.RecoveryError, match="size"):
        recovery.verify_snapshot(runner, tmp_path, expected_serial="DRIVE-A")


def test_recovery_verification_accepts_a_valid_manifest_with_a_stale_incomplete_marker(tmp_path):
    import drive_recovery as recovery
    image = tmp_path / "drive.qcow2"
    image.write_bytes(b"valid image bytes")
    manifest = {"format": "baseline-drive-recovery-v1", "serial": "DRIVE-A", "image": "drive.qcow2",
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "complete": True,
                "source_compared": True, "size_bytes": 4096, "image_bytes": image.stat().st_size}
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))
    (tmp_path / "INCOMPLETE.json").write_text(json.dumps({"complete": False}))
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["qemu-img", "info"], FakeProc(0, json.dumps({"virtual-size": 4096, "format": "qcow2"}), "")),
        (lambda a: a[:2] == ["qemu-img", "check"], FakeProc(0, "", "")),
    ])
    assert recovery.verify_snapshot(runner, tmp_path, expected_serial="DRIVE-A") == manifest


def test_publishing_complete_snapshot_removes_incomplete_marker(tmp_path):
    import drive_recovery as recovery
    (tmp_path / "INCOMPLETE.json").write_text(json.dumps({"complete": False}))
    recovery._publish_complete_manifest(tmp_path, {"complete": True})
    assert json.loads((tmp_path / "MANIFEST.json").read_text()) == {"complete": True}
    assert not (tmp_path / "INCOMPLETE.json").exists()


def test_quiescence_refuses_active_file_users_without_unmounting(monkeypatch):
    import drive_recovery as recovery
    monkeypatch.setattr(recovery.pds, "validate_target_device", lambda *a, **k: {"path": "/dev/sdc", "serial": "DRIVE-A", "size_bytes": 512_110_190_592})
    listing = {"blockdevices": [{"name": "/dev/sdc", "type": "disk", "serial": "DRIVE-A",
        "size": 512_110_190_592, "mountpoints": [None], "children": [
            {"name": "/dev/sdc1", "type": "part", "mountpoints": ["/data"]}]}]}
    runner = FakeRunner(command_responses=[
        (lambda a: a[0] == "id", FakeProc(0, "0\n", "")),
        (lambda a: a[0] == "lsblk", FakeProc(0, json.dumps(listing), "")),
        (lambda a: a[0] == "fuser", FakeProc(0, "123\n", "")),
    ])
    with pytest.raises(recovery.RecoveryError, match="active"):
        recovery.quiesce_source(runner, serial="DRIVE-A", allowed_serials={"DRIVE-A"})
    assert not any(a[0] == "umount" for a in runner.calls)
