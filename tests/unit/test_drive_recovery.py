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
        recovery.create_snapshot(runner, allow_whole_device=True, serial="DRIVE-A", destination=str(tmp_path),
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


# -- write budget: the image may use real free space, never the destination's 3% reserve (2026-10-10) ----------

def _snapshot_setup(tmp_path, monkeypatch, *, free, total):
    import drive_recovery as recovery
    import offdrive_backup as ob
    size = 512_110_190_592
    listing = {"blockdevices": [{"name": "/dev/sdx", "type": "disk", "serial": "DRIVE-A", "size": size,
                                 "mountpoints": [None]}]}
    target = {"path": "/dev/sdx", "serial": "DRIVE-A", "size_bytes": size}
    monkeypatch.setattr(recovery.pds, "validate_target_device", lambda *a, **k: dict(target))
    monkeypatch.setattr(recovery.pds, "get_boot_device_serial", lambda *a, **k: "BOOT")
    monkeypatch.setattr(ob, "resolve_destination",
                        lambda path, **k: ob.Destination(path=str(tmp_path), backup_dir=tmp_path / "b", source="x",
                                                         fstype="ext4", serial="DEST", disks=("sdz",)))
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (free, total))

    class Runner(FakeRunner):
        def run(self, argv, timeout=10):
            if "convert" in argv:
                open(argv[-1], "wb").write(b"qcow2-bytes")          # the image the real convert would write
            return super().run(argv, timeout=timeout)
    runner = Runner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, json.dumps(listing), ""))])
    return recovery, runner


def test_the_recovery_image_is_written_under_a_kernel_cap_of_a_tenth_of_the_drive_within_free_space(tmp_path, monkeypatch):
    """The real numbers from 2026-10-10: 819.5 GB free on a 10 TB destination. Budgeting the raw 512 GB plus
    headroom was the old rule; the budget is free minus 3% of the destination, and never more than a tenth of the drive
    being imaged (operator rule 2026-10-11: a drive that is about 5% used must not be backed up at its full size)."""
    free, total = 819_542_622_208, 10_000_611_147_776
    recovery, runner = _snapshot_setup(tmp_path, monkeypatch, free=free, total=total)
    folder = recovery.create_snapshot(runner, allow_whole_device=True, serial="DRIVE-A", destination=str(tmp_path), allowed_serials={"DRIVE-A"})
    import offdrive_backup as ob
    qemu = [a for a in runner.calls if "qemu-img" in a]
    budget = int(json.loads((folder / "MANIFEST.json").read_text())["size_bytes"] * ob.IMAGE_CAP_FRACTION)
    assert budget < free - int(total * 0.03)
    assert qemu[0][:2] == ["prlimit", f"--fsize={budget}"] and qemu[0][2:4] == ["qemu-img", "convert"]
    assert all(a[0] == "qemu-img" for a in qemu[1:])              # check and compare only read: not capped
    assert json.loads((folder / "MANIFEST.json").read_text())["complete"] is True


def test_a_destination_at_its_reserve_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    import offdrive_backup as ob
    total = 10 * 2**40
    recovery, runner = _snapshot_setup(tmp_path, monkeypatch, free=int(total * 0.03), total=total)
    with pytest.raises(ob.BackupError, match="3%"):
        recovery.create_snapshot(runner, allow_whole_device=True, serial="DRIVE-A", destination=str(tmp_path), allowed_serials={"DRIVE-A"})
    assert not any("qemu-img" in a for a in runner.calls)
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("baseline-recovery-")]


def test_an_image_that_outgrows_its_budget_fails_and_stays_incomplete(tmp_path, monkeypatch):
    free, total = 819_542_622_208, 10_000_611_147_776
    recovery, runner = _snapshot_setup(tmp_path, monkeypatch, free=free, total=total)
    runner.command_responses.insert(0, (lambda a: a[0] == "prlimit", FakeProc(153, "", "File size limit exceeded")))
    with pytest.raises(recovery.RecoveryError, match="write budget"):
        recovery.create_snapshot(runner, allow_whole_device=True, serial="DRIVE-A", destination=str(tmp_path), allowed_serials={"DRIVE-A"})
    folder = next(p for p in tmp_path.iterdir() if p.name.startswith("baseline-recovery-"))
    assert (folder / "INCOMPLETE.json").exists() and not (folder / "MANIFEST.json").exists()
