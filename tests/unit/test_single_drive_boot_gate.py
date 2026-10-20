from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_independent_drive_services_require_real_storage_verification():
    unit = (REPO / "boot" / "baseline-storage-verify.service").read_text()
    assert "ConditionPathExists=/etc/baseline/independent-drive.json" in unit
    assert "ExecStart=/usr/bin/python3 /opt/baseline/bin/baseline-single-drive-storage verify" in unit
    assert "RequiresMountsFor=/mnt/BASELINE /mnt/INSTALLER_CACHE /mnt/SESSION_TEMP /mnt/SUBSTRATE /mnt/USER_ADMIN /mnt/USER_PERSONAL /mnt/APPDATA_ADMIN /mnt/APPDATA_PERSONAL" in unit
    provision = (REPO / "boot" / "provision.sh").read_text()
    assert 'cp "$SRC/boot/baseline-storage-verify.service" /etc/systemd/system/baseline-storage-verify.service' in provision
    assert "Requires=baseline-storage-verify.service" in provision
