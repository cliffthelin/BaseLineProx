import os
import stat

from inventory import schema, validate


def _minimal_manifest(categories=None):
    return {
        "schema_version": schema.SCHEMA_VERSION,
        "generated_at": "2026-01-01T00:00:00Z",
        "source": "current-drive",
        "host_label": "",
        "categories": categories or {},
        "config_files": [],
        "redaction_report": {"fields_redacted": 0},
    }


def test_clean_manifest_passes():
    report = validate.validate_manifest(_minimal_manifest())
    assert report["passed"] is True
    for check, issues in report["issues"].items():
        if check == "output_permissions":
            continue  # no output_path given in this test
        assert issues == [], f"{check}: {issues}"


def test_missing_schema_version_fails():
    m = _minimal_manifest()
    del m["schema_version"]
    report = validate.validate_manifest(m)
    assert report["passed"] is False
    assert report["issues"]["schema_validity"]


def test_wrong_schema_version_fails():
    m = _minimal_manifest()
    m["schema_version"] = 999
    report = validate.validate_manifest(m)
    assert report["passed"] is False


def test_output_permissions_checked_against_real_file(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    os.chmod(path, 0o644)
    report = validate.validate_manifest(_minimal_manifest(), output_path=str(path))
    assert report["passed"] is False
    assert "0o600" in report["issues"]["output_permissions"][0] or "644" in report["issues"]["output_permissions"][0]

    os.chmod(path, 0o600)
    report = validate.validate_manifest(_minimal_manifest(), output_path=str(path))
    assert report["issues"]["output_permissions"] == []


def test_forbidden_field_name_survives_normalization_is_caught():
    m = _minimal_manifest({"proxmox": {"storage_cfg": {"fields": {"password": "should-not-be-a-key"}}}})
    report = validate.validate_manifest(m)
    assert report["passed"] is False
    assert any("password" in issue for issue in report["issues"]["forbidden_field_names"])


def test_expected_token_field_names_are_not_flagged():
    m = _minimal_manifest({"proxmox": {"nodes": {"vmid_token": "vmid:abc123def456"}}})
    report = validate.validate_manifest(m)
    assert report["issues"]["forbidden_field_names"] == []


def test_raw_ip_in_value_is_caught():
    m = _minimal_manifest({"network": {"leaked": "10.0.0.5"}})
    report = validate.validate_manifest(m)
    assert report["passed"] is False
    assert any("raw_ipv4" in issue for issue in report["issues"]["secret_value_patterns"])


def test_raw_mac_in_value_is_caught():
    m = _minimal_manifest({"network": {"leaked": "AA:BB:CC:DD:EE:FF"}})
    report = validate.validate_manifest(m)
    assert any("raw_mac" in issue for issue in report["issues"]["secret_value_patterns"])


def test_raw_uuid_in_value_is_caught():
    m = _minimal_manifest({"storage": {"leaked": "11111111-2222-3333-4444-555555555555"}})
    report = validate.validate_manifest(m)
    assert any("raw_uuid" in issue for issue in report["issues"]["secret_value_patterns"])


def test_embedded_url_credential_is_caught():
    m = _minimal_manifest({"apt": {"leaked": "https://user:hunter2@example.com/repo"}})
    report = validate.validate_manifest(m)
    assert any("embedded_url_credential" in issue for issue in report["issues"]["secret_value_patterns"])


def test_private_key_marker_is_caught():
    m = _minimal_manifest({"leaked": "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n"})
    report = validate.validate_manifest(m)
    assert any("private_key_marker" in issue for issue in report["issues"]["secret_value_patterns"])


def test_ssh_key_material_is_caught():
    m = _minimal_manifest({"leaked": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII"})
    report = validate.validate_manifest(m)
    assert any("ssh_key_material" in issue for issue in report["issues"]["secret_value_patterns"])


def test_proxmox_subscription_key_shape_is_caught():
    m = _minimal_manifest({"leaked": "pve2c-0123456789"})
    report = validate.validate_manifest(m)
    assert any("proxmox_subscription_key" in issue for issue in report["issues"]["secret_value_patterns"])


def test_large_text_value_is_flagged_but_not_hard_failure():
    m = _minimal_manifest({"apt": {"policy_summary": "x" * 5000}})
    report = validate.validate_manifest(m)
    assert report["passed"] is True
    assert report["issues"]["large_text_values_for_manual_review"]


def test_degraded_categories_are_collected_for_human_review():
    m = _minimal_manifest({
        "proxmox": {"storage_cfg": {"available": False, "reason": "not found"}},
        "packages": {"_collection_notes": [{"command": "dpkg-query", "status": "timed_out", "reason": "x"}]},
    })
    report = validate.validate_manifest(m)
    assert any("storage_cfg.available" in c for c in report["degraded_categories_reported"])
    assert any("packages._collection_notes" in c for c in report["degraded_categories_reported"])


def test_validator_never_writes_anything(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    os.chmod(path, 0o600)
    before = path.read_bytes()
    before_mtime = os.stat(path).st_mtime_ns
    validate.validate_manifest(_minimal_manifest(), output_path=str(path))
    assert path.read_bytes() == before
    assert os.stat(path).st_mtime_ns == before_mtime
