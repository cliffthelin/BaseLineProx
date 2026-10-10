"""Storage policy behavior; synthetic identities, no block device writes."""
import json
import pytest
import drive_installer as di
from fake_runner import FakeRunner


def test_complete_measured_policy_roundtrips_with_unique_role_bindings():
    import storage_policy as sp
    required = {v[3]: 0 for v in di.BASELINE_VOLUMES}
    bindings = {v[3]: {"serial": "DRIVE-A", "uuid": f"00000000-0000-4000-8000-{i:012d}"}
                for i, v in enumerate(di.BASELINE_VOLUMES, 1)}
    policy = sp.build_policy(serial="DRIVE-A", size_bytes=512_110_190_592,
                             required_bytes=required, bindings=bindings)
    runner = FakeRunner()
    sp.save_policy(runner, "/policy.json", policy)
    loaded = sp.load_policy(runner, "/policy.json")
    assert loaded == policy
    assert loaded["capacity"]["capacity_basis"] == "measured-workload"
    assert loaded["bindings"]["INSTALLER_CACHE"]["uuid"] != loaded["bindings"]["USER_ADMIN"]["uuid"]
    assert loaded["boot_verified"] is False
    assert json.loads(runner.files["/policy.json"])["serial"] == "DRIVE-A"


def test_measurement_refuses_a_directory_in_place_of_a_mounted_role():
    import storage_policy as sp
    from fake_runner import FakeProc
    runner = FakeRunner(command_responses=[
        (lambda a: a[0] == "findmnt", FakeProc(0, json.dumps({"filesystems": [
            {"target": "/", "uuid": "host-root", "source": "/dev/host", "fstype": "ext4"}]}), "")),
    ])
    with pytest.raises(sp.PolicyError, match="mounted role"):
        sp.measure_role(runner, mountpoint="/mnt/USER_ADMIN", expected_uuid="role-uuid")
    assert not any(a[0] == "du" for a in runner.calls)


def test_firstboot_verification_rejects_a_policy_from_another_installation():
    import storage_policy as sp
    from test_single_drive_storage import inspection_runner, SERIAL
    required = {v[3]: 0 for v in di.BASELINE_VOLUMES}
    bindings = {v[3]: {"serial": "FOREIGN", "uuid": f"00000000-0000-4000-8000-{i:012d}"}
                for i, v in enumerate(di.BASELINE_VOLUMES, 1)}
    policy = sp.build_policy(serial="FOREIGN", size_bytes=512_110_190_592, required_bytes=required, bindings=bindings)
    runner = inspection_runner()
    runner.files[sp.POLICY_PATH] = json.dumps(policy)
    runner.files["/etc/baseline/independent-drive.json"] = json.dumps({"serial": SERIAL,
        "root_uuid": "root-uuid", "pv_uuid": "pv-unique", "vg_uuid": "vg-unique", "policy_path": sp.POLICY_PATH})
    with pytest.raises((sp.PolicyError, RuntimeError), match="serial"):
        sp.verify_runtime(runner)
    assert not runner.writes


def test_legacy_storage_policy_remains_valid_without_claiming_gui_capacity():
    import storage_policy as sp
    required = {v[3]: 0 for v in di.BASELINE_VOLUMES}
    bindings = {v[3]: {'serial': 'DRIVE-A', 'uuid': f'00000000-0000-4000-8000-{i:012d}'}
                for i, v in enumerate(di.BASELINE_VOLUMES, 1)}
    legacy = sp.build_policy(serial='DRIVE-A', size_bytes=512110190592,
        required_bytes=required, bindings=bindings, policy_format='baseline-independent-drive-v1')
    assert sp.validate_policy(legacy) == legacy
    assert legacy['capacity']['volumes_gib']['BASELINE'] < 50
    current = sp.build_policy(serial='DRIVE-A', size_bytes=512110190592,
        required_bytes=required, bindings=bindings)
    assert current['capacity']['volumes_gib']['BASELINE'] >= 50
