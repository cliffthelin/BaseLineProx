"""Explicit real-qemu-img check over new temporary regular files; no devices."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline" / "lib"))


def test_actual_qcow2_snapshot_integrity_and_tamper_detection(tmp_path):
    import drive_recovery as recovery
    from repair import RealRunner
    runner = RealRunner()
    image = tmp_path / "drive.qcow2"
    assert runner.run(["qemu-img", "create", "-f", "qcow2", str(image), "16M"]).returncode == 0
    manifest = {"format": "baseline-drive-recovery-v1", "serial": "DRIVE-A", "image": "drive.qcow2",
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "complete": True,
                "source_compared": True, "size_bytes": 16 * 1024**2, "image_bytes": image.stat().st_size}
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))
    assert recovery.verify_snapshot(runner, tmp_path, expected_serial="DRIVE-A") == manifest
    with open(image, "ab") as stream:stream.write(b"tampered")
    with pytest.raises(recovery.RecoveryError, match="integrity"):
        recovery.verify_snapshot(runner, tmp_path, expected_serial="DRIVE-A")
