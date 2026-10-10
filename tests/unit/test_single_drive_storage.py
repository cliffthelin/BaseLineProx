"""Disk-bound offline provisioning: command boundaries are synthetic."""
import json
import pytest
from fake_runner import FakeRunner, FakeProc

SERIAL = "FD01N6557110C271B"
VG_UUID = "vg-unique"
PV_UUID = "pv-unique"


def inspection_runner(*, root_serial=SERIAL, extra_pv=False, foreign_vg=False):
    disks = [{"name": "/dev/sdc", "type": "disk", "serial": SERIAL, "size": 512_110_190_592}]
    ancestor = {"blockdevices": [{"name": "/dev/sdc3", "type": "part", "children": [
        {"name": "/dev/sdc", "type": "disk", "serial": root_serial}]}]}
    pvs = [{"pv_name": "/dev/sdc3", "pv_uuid": PV_UUID, "vg_name": "pve", "vg_uuid": VG_UUID}]
    if extra_pv:pvs.append({"pv_name": "/dev/sde1", "pv_uuid": "foreign-pv", "vg_name": "pve", "vg_uuid": VG_UUID})
    if foreign_vg:pvs.append({"pv_name": "/dev/sde1", "pv_uuid": "foreign-pv", "vg_name": "other", "vg_uuid": "other-vg"})
    return FakeRunner(command_responses=[
        (lambda a: a[:2] == ["lsblk", "-J"], FakeProc(0, json.dumps({"blockdevices": disks}), "")),
        (lambda a: a[0] == "findmnt", FakeProc(0, json.dumps({"filesystems": [
            {"target": "/target", "source": "/dev/mapper/pve-root", "fstype": "ext4", "uuid": "root-uuid"}]}), "")),
        (lambda a: a[:2] == ["lsblk", "-s"], FakeProc(0, json.dumps(ancestor), "")),
        (lambda a: "pvs" in a, FakeProc(0, json.dumps({"report": [{"pv": pvs}]}), "")),
        (lambda a: "lvs" in a, FakeProc(0, json.dumps({"report": [{"lv": [
            {"vg_name": "pve", "vg_uuid": VG_UUID, "lv_name": "root"}]}]}), "")),
    ])


def test_offline_target_root_and_sole_pv_are_bound_to_selected_serial():
    import single_drive_storage as storage
    target = storage.inspect_target(inspection_runner(), expected_serial=SERIAL, root_mount="/target")
    assert target["serial"] == SERIAL
    assert target["path"] == "/dev/sdc"
    assert target["vg_uuid"] == VG_UUID
    assert target["pv_uuid"] == PV_UUID
    assert target["root_mount"] == "/target"


def test_unrelated_volume_group_does_not_join_the_installation():
    import single_drive_storage as storage
    target = storage.inspect_target(inspection_runner(foreign_vg=True), expected_serial=SERIAL, root_mount="/target")
    assert target["vg_uuid"] == VG_UUID


def test_offline_runner_refuses_formatting_a_volume_it_did_not_create(monkeypatch):
    import single_drive_storage as storage
    runner = inspection_runner()
    target = storage.inspect_target(runner, expected_serial=SERIAL, root_mount="/target")
    monkeypatch.setattr(storage.pds, "validate_target_device", lambda *a, **k: {
        "path": target["path"], "serial": SERIAL, "size_bytes": target["size_bytes"]})
    bound = storage.OfflineRunner(runner, target)
    with pytest.raises(storage.StorageError, match="created"):
        bound.run(["mkfs.ext4", "-F", "-L", "USER_ADMIN", "/dev/pve/baseline_user_admin"])
    assert not any(a[0] == "mkfs.ext4" for a in runner.calls)


def test_offline_runner_writes_only_the_target_fstab(monkeypatch):
    import single_drive_storage as storage
    runner = inspection_runner()
    target = storage.inspect_target(runner, expected_serial=SERIAL, root_mount="/target")
    monkeypatch.setattr(storage.pds, "validate_target_device", lambda *a, **k: {
        "path": target["path"], "serial": SERIAL, "size_bytes": target["size_bytes"]})
    bound = storage.OfflineRunner(runner, target)
    bound.append_text("/etc/fstab", "target-entry\n")
    assert runner.files["/target/etc/fstab"] == "target-entry\n"
    assert "/etc/fstab" not in runner.files


@pytest.mark.parametrize("kwargs", [{"root_serial": "FOREIGN"}, {"extra_pv": True}])
def test_wrong_root_or_multi_pv_volume_group_is_refused(kwargs):
    import single_drive_storage as storage
    runner = inspection_runner(**kwargs)
    with pytest.raises(storage.StorageError):
        storage.inspect_target(runner, expected_serial=SERIAL, root_mount="/target")
    assert not runner.writes


def test_provisioning_requires_measurements_before_any_disk_mutation():
    import single_drive_storage as storage
    runner = inspection_runner()
    with pytest.raises(storage.StorageError, match="measure"):
        storage.provision_target(runner, expected_serial=SERIAL, root_mount="/target", required_bytes=None)
    assert not runner.writes
    assert not any(a[0] in {"lvcreate", "mkfs.ext4", "mount"} for a in runner.calls)


def test_measured_offline_provisioning_persists_uuid_routes_only_on_target(tmp_path, monkeypatch):
    import hashlib
    import drive_installer as di
    import storage_policy as sp
    import single_drive_storage as storage
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    image = recovery / "drive.qcow2"
    image.write_bytes(b"unit boundary image")
    (recovery / "MANIFEST.json").write_text(json.dumps({"format": "baseline-drive-recovery-v1",
        "serial": SERIAL, "size_bytes": 512_110_190_592, "image": image.name,
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "image_bytes": image.stat().st_size,
        "complete": True, "source_compared": True}))
    runner = inspection_runner()
    runner.command_responses.insert(0, (lambda a: "lv_name,lv_size,lv_attr" in a,
        FakeProc(0, json.dumps({"report": [{"lv": [
            {"lv_name": "root", "lv_size": str(32 * 1024**3), "lv_attr": "-wi"},
            {"lv_name": "swap", "lv_size": str(4 * 1024**3), "lv_attr": "-wi"},
            {"lv_name": "data", "lv_size": str(64 * 1024**3), "lv_attr": "twi"}]}]}), "")))
    runner.command_responses.insert(0, (lambda a: "lv_name,lv_size" in a, FakeProc(0, "root 34359738368\n", "")))
    runner.command_responses.insert(0, (lambda a: "vg_name,lv_name" in a, FakeProc(0, "pve root\n", "")))
    runner.command_responses.insert(0, (lambda a: "vgs" in a, FakeProc(0, str(400 * 1024**3), "")))
    runner.command_responses.insert(0, (lambda a: a[:2] == ["qemu-img", "info"],
        FakeProc(0, json.dumps({"format": "qcow2", "virtual-size": 512_110_190_592}), "")))
    for i, (name, _, _, label, mountpoint) in enumerate(di.BASELINE_VOLUMES, 1):
        identity = f"00000000-0000-4000-8000-{i:012d}"
        runner.command_responses.insert(0, (lambda a, name=name: a[0] == "blkid" and a[-1] == "/dev/pve/" + name,
            FakeProc(0, identity + "\n", "")))
        runner.command_responses.insert(0, (lambda a, mountpoint=mountpoint: a[0] == "findmnt" and "/target" + mountpoint in a,
            FakeProc(0, identity + "\n", "")))
    monkeypatch.setattr(storage.pds, "validate_target_device", lambda *a, **k: {
        "path": "/dev/sdc", "serial": SERIAL, "size_bytes": 512_110_190_592})
    result = storage.provision_target(runner, expected_serial=SERIAL, root_mount="/target",
        required_bytes={v[3]: 0 for v in di.BASELINE_VOLUMES}, recovery_folder=recovery)
    assert result["state"] == "provisioned" and result["boot_verified"] is False
    assert set(result["created_roles"]) == {v[3] for v in di.BASELINE_VOLUMES}
    assert len(result["policy"]["bindings"]) == 8
    assert "/etc/fstab" not in runner.files
    assert runner.files["/target/etc/fstab"].count("UUID=") == 8
    assert sp.load_policy(runner, "/target" + sp.POLICY_PATH) == result["policy"]
