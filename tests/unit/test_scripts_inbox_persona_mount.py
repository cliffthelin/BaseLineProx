"""Regression checks for the scripts inbox's active persistence volume.

These tests use the production filesystem runner against isolated files under
pytest's temporary directory. They do not simulate subprocesses or mount
state with a fake runner.
"""
from pathlib import Path
import sys

LIB = Path(__file__).resolve().parents[2] / "baseline" / "lib"
sys.path.insert(0, str(LIB))

import drive_installer as di
import persist_bind_mounts as pbm
import scripts_inbox as si
import scripts_inbox_gate as sig
import scripts_inbox_web as siw
from repair import RealRunner
import storage_policy


def _write_independent_policy(root: Path, *, active_persona="admin"):
    runner = RealRunner()
    labels = {volume[3] for volume in di.baseline_volumes_for()}
    bindings = {
        label: {"serial": "test-drive", "uuid": f"00000000-0000-0000-0000-{index:012d}"}
        for index, label in enumerate(sorted(labels), start=1)
    }
    required = {label: 0 for label in labels}
    policy = storage_policy.build_policy(
        serial="test-drive", size_bytes=512 * 1024**3,
        required_bytes=required, bindings=bindings,
    )
    policy_path = root / "SUBSTRATE" / "storage-policy.json"
    storage_policy.save_policy(runner, str(policy_path), policy)
    marker = root / "etc" / "independent-drive.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"serial":"test-drive"}')
    active = root / "BASELINE" / "state" / "active_persona"
    active.parent.mkdir(parents=True)
    active.write_text(active_persona)
    return runner, marker, policy_path, active


def test_active_user_mountpoint_uses_enrolled_persona_and_its_gate_path(tmp_path):
    runner, marker, policy, active = _write_independent_policy(tmp_path)
    mount_table = tmp_path / "mounts"
    mount_table.write_text("/dev/test-user /mnt/USER_ADMIN ext4 rw,relatime 0 0\n")

    assert pbm.active_user_mountpoint(
        runner, independent_marker_path=str(marker), policy_path=str(policy),
        active_persona_marker_path=str(active),
    ) == "/mnt/USER_ADMIN"
    assert si.persistent_paths_for_active_user(
        runner, independent_marker_path=str(marker), policy_path=str(policy),
        active_persona_marker_path=str(active),
    ) == (
        "/mnt/USER_ADMIN/scripts-inbox-auth/store.json",
        "/mnt/USER_ADMIN/scripts_inbox",
    )
    assert sig.check(
        runner, independent_marker_path=str(marker), policy_path=str(policy),
        active_persona_marker_path=str(active), mount_table_path=str(mount_table),
    ) == 0


def test_active_user_mountpoint_refuses_unenrolled_persona(tmp_path):
    runner, marker, policy, active = _write_independent_policy(
        tmp_path, active_persona="guest"
    )
    try:
        pbm.active_user_mountpoint(
            runner, independent_marker_path=str(marker), policy_path=str(policy),
            active_persona_marker_path=str(active),
        )
    except RuntimeError as exc:
        assert "not enrolled" in str(exc)
    else:
        raise AssertionError("unvalidated active persona must fail closed")


def test_legacy_installation_resolves_legacy_user_mountpoint(tmp_path):
    runner = RealRunner()
    assert pbm.active_user_mountpoint(
        runner, independent_marker_path=str(tmp_path / "missing-marker"),
        policy_path=str(tmp_path / "missing-policy"),
        active_persona_marker_path=str(tmp_path / "missing-active-persona"),
    ) == "/mnt/USER"


def test_service_paths_default_to_the_active_persistence_volume(tmp_path):
    runner, marker, policy, active = _write_independent_policy(tmp_path)
    data_path, inbox_dir = siw.resolve_paths(
        {}, runner=runner, independent_marker_path=str(marker),
        policy_path=str(policy), active_persona_marker_path=str(active),
    )
    assert data_path == "/mnt/USER_ADMIN/scripts-inbox-auth/store.json"
    assert inbox_dir == "/mnt/USER_ADMIN/scripts_inbox"


def test_explicit_service_paths_remain_available_for_local_development():
    paths = siw.resolve_paths({
        "BASELINE_SCRIPTS_INBOX_DATA": "/tmp/inbox/store.db",
        "BASELINE_SCRIPTS_INBOX_DIR": "/tmp/inbox/scripts",
    })
    assert paths == ("/tmp/inbox/store.db", "/tmp/inbox/scripts")
