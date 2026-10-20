"""The scripts inbox's gate and its server resolve the same persistence volume (real files, production runner)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline" / "lib"))

import drive_installer as di
import persist_bind_mounts as pbm
import scripts_inbox_gate as sig
import scripts_inbox_web as siw
import storage_policy
from repair import RealRunner


def _independent_drive(root: Path, persona: str):
    labels = {volume[3] for volume in di.baseline_volumes_for()}
    bindings = {label: {"serial": "test-drive", "uuid": f"00000000-0000-0000-0000-{i:012d}"}
                for i, label in enumerate(sorted(labels), start=1)}
    policy = storage_policy.build_policy(serial="test-drive", size_bytes=512 * 1024**3,
                                         required_bytes={label: 0 for label in labels}, bindings=bindings)
    policy_path = root / "SUBSTRATE" / "storage-policy.json"
    storage_policy.save_policy(RealRunner(), str(policy_path), policy)
    marker = root / "independent-drive.json"
    marker.write_text(json.dumps({"serial": "test-drive"}))
    active = root / "active_persona"
    active.write_text(persona)
    return dict(independent_marker_path=str(marker), policy_path=str(policy_path),
                active_persona_marker_path=str(active))


def test_the_server_stores_on_exactly_the_volume_the_gate_checks(tmp_path):
    options = _independent_drive(tmp_path, "admin")
    mount_table = tmp_path / "mounts"
    mount_table.write_text("/dev/x /mnt/USER_ADMIN ext4 rw 0 0\n")
    data_path, inbox_dir = siw.resolve_paths({}, runner=RealRunner(), **options)
    mountpoint = pbm.active_user_mountpoint(RealRunner(), **options)
    assert data_path.startswith(mountpoint + "/") and inbox_dir.startswith(mountpoint + "/")
    assert sig.check(RealRunner(), mount_table_path=str(mount_table), **options) == 0


def test_the_gate_refuses_while_the_active_personas_volume_is_not_mounted(tmp_path):
    options = _independent_drive(tmp_path, "admin")
    mount_table = tmp_path / "mounts"
    mount_table.write_text("/dev/x /mnt/USER_PERSONAL ext4 rw 0 0\n")       # another persona's volume does not count
    assert sig.check(RealRunner(), mount_table_path=str(mount_table), **options) == 1


def test_setting_only_one_explicit_path_is_refused_not_guessed():
    import pytest
    with pytest.raises(ValueError):
        siw.resolve_paths({"BASELINE_SCRIPTS_INBOX_DATA": "/tmp/x/store.db"})
