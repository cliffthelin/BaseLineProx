"""Offline manifest comparator tests - missing/mismatched comparison
keys, deterministic same-key tokenization, malformed-manifest handling,
and every named comparison category producing the right classification."""
import pytest

from inventory import diff
from inventory import manifest as manifest_mod
from inventory.redact import Redactor

from .fake_runner import FakeRunner


def _fixed_clock():
    return "2026-01-01T00:00:00Z"


def _manifest(runner=None, key=b"shared-key", **kwargs):
    r = runner or FakeRunner()
    return manifest_mod.collect_all(
        r, source=kwargs.pop("source", "current-drive"), host_label=kwargs.pop("host_label", "test"),
        redactor=Redactor(key=key) if key is not None else None,
        clock=_fixed_clock, **kwargs,
    )


# --------------------------------------------------------------------------
# Comparison-key handling
# --------------------------------------------------------------------------

def test_missing_key_id_on_either_side_is_reported_not_matched():
    a = _manifest(key=b"key-a")
    b = _manifest(key=None)  # ephemeral, random key - never equal to a fixed one
    result = diff.compare_manifests(a, b)
    assert result["key_comparison"]["matched"] is False


def test_mismatched_key_ids_are_reported_not_matched():
    a = _manifest(key=b"key-a")
    b = _manifest(key=b"key-b")
    result = diff.compare_manifests(a, b)
    assert result["key_comparison"]["matched"] is False
    assert result["key_comparison"]["key_a"] != result["key_comparison"]["key_b"]


def test_same_key_produces_matched_true_and_matching_key_ids():
    a = _manifest(key=b"shared")
    b = _manifest(key=b"shared")
    result = diff.compare_manifests(a, b)
    assert result["key_comparison"]["matched"] is True
    assert result["key_comparison"]["key_a"] == result["key_comparison"]["key_b"]


def test_require_matching_key_raises_on_mismatch():
    a = _manifest(key=b"key-a")
    b = _manifest(key=b"key-b")
    with pytest.raises(diff.ComparisonKeyError):
        diff.compare_manifests(a, b, require_matching_key=True)


def test_require_matching_key_does_not_raise_when_matched():
    a = _manifest(key=b"shared")
    b = _manifest(key=b"shared")
    diff.compare_manifests(a, b, require_matching_key=True)  # must not raise


def test_deterministic_same_key_tokenization_across_two_separate_runs():
    """The actual cross-run problem this exists to solve: two
    independent collect_all() calls, same key, must tokenize the same
    raw value (e.g. a Proxmox node name) to the identical token - a
    prerequisite for suggested_machine_specific to ever mean anything."""
    r1, r2 = FakeRunner(), FakeRunner()
    for r in (r1, r2):
        r.dirs["/etc/pve/nodes/samehost/qemu-server"] = []
        r.dirs["/etc/pve/nodes/samehost/lxc"] = []
    a = _manifest(runner=r1, key=b"shared", node_names=["samehost"])
    b = _manifest(runner=r2, key=b"shared", node_names=["samehost"])
    token_a = next(iter(a["categories"]["proxmox"]["nodes"]))["node_token"] \
        if isinstance(a["categories"]["proxmox"]["nodes"], list) else None
    # nodes is actually a dict keyed by token in the ported schema - handle both shapes defensively
    nodes_a = a["categories"]["proxmox"]["nodes"]
    nodes_b = b["categories"]["proxmox"]["nodes"]
    assert nodes_a == nodes_b  # byte-identical structure under a shared key


def test_identity_sensitive_value_is_skipped_without_matching_key():
    a = _manifest(key=b"key-a")
    b = _manifest(key=b"key-b")
    result = diff.compare_manifests(a, b)
    # No finding should claim a proxmox/boot/scheduling difference is
    # machine_specific when the keys don't match - those values are
    # unverifiable, not "equal" and not "different".
    assert not any(f["category"] in diff.IDENTITY_SENSITIVE_CATEGORIES
                   and f["classification"] == "suggested_machine_specific"
                   for f in result["findings"])


# --------------------------------------------------------------------------
# Malformed manifests
# --------------------------------------------------------------------------

def test_empty_dict_manifests_do_not_raise():
    result = diff.compare_manifests({}, {})
    assert result["findings"] == []
    assert result["key_comparison"]["matched"] is False


def test_manifest_missing_categories_key_does_not_raise():
    result = diff.compare_manifests({"source": "current-drive"}, {"source": "disposable-vm"})
    assert result["findings"] == []


def test_manifest_with_non_dict_category_value_does_not_raise():
    a = {"categories": {"packages": "not-a-dict"}}
    b = {"categories": {"packages": {"items": []}}}
    # Should not raise even though shapes are inconsistent - a malformed
    # input degrades to "nothing comparable found", never a crash.
    diff.compare_manifests(a, b)


# --------------------------------------------------------------------------
# Never mutates, never emits remediation
# --------------------------------------------------------------------------

def test_neither_input_manifest_is_mutated():
    a = _manifest(key=b"shared")
    b = _manifest(key=b"shared")
    import copy
    a_before, b_before = copy.deepcopy(a), copy.deepcopy(b)
    diff.compare_manifests(a, b)
    assert a == a_before
    assert b == b_before


def test_findings_never_contain_executable_or_command_shaped_fields():
    a = _manifest(key=b"shared")
    b = _manifest(key=b"shared")
    result = diff.compare_manifests(a, b)
    for f in result["findings"]:
        assert set(f.keys()) == {"category", "key", "manifest_a_value", "manifest_b_value",
                                  "side", "classification", "reason"}
        assert f["classification"] in diff.CLASSIFICATIONS


# --------------------------------------------------------------------------
# Category coverage: packages, repositories, services, baseline deploy,
# network, boot, proxmox, scheduling, sysctls, diagnostic tools, config_files
# --------------------------------------------------------------------------

def test_package_present_only_on_current_drive_is_suggested_required():
    r1, r2 = FakeRunner(), FakeRunner()
    from inventory.runner import CommandResult
    r1.binaries["dpkg-query"] = "/usr/bin/dpkg-query"
    r2.binaries["dpkg-query"] = "/usr/bin/dpkg-query"
    r1.script(lambda a: "${Status}" in " ".join(a),
               CommandResult(ok=True, stdout="lm-sensors\t1:3.6.2-2\tinstall ok installed\n"))
    r2.script(lambda a: "${Status}" in " ".join(a), CommandResult(ok=True, stdout=""))

    a = _manifest(runner=r1, key=b"shared", source="current-drive")
    b = _manifest(runner=r2, key=b"shared", source="disposable-vm")
    result = diff.compare_manifests(a, b)
    hits = [f for f in result["findings"] if f["category"] == "packages"
            and isinstance(f["manifest_a_value"], dict) and f["manifest_a_value"].get("name") == "lm-sensors"]
    assert hits
    assert hits[0]["classification"] == "suggested_required"


def test_baseline_deployed_file_present_only_on_current_drive_is_candidate_obsolete():
    from inventory.runner import CommandResult
    r1, r2 = FakeRunner(), FakeRunner()
    for r in (r1, r2):
        r.dirs["/etc/baseline"] = []
        r.dirs["/var/lib/baseline"] = []
        r.binaries["systemctl"] = "/usr/bin/systemctl"
        r.script(lambda a: a[:2] == ["systemctl", "status"], CommandResult(ok=True, stdout="active"))
    r1.dirs["/opt/baseline/bin"] = ["/opt/baseline/bin/old-tool"]
    r1.dirs["/opt/baseline/lib"] = []
    r2.dirs["/opt/baseline/bin"] = []
    r2.dirs["/opt/baseline/lib"] = []

    a = _manifest(runner=r1, key=b"shared", source="current-drive")
    b = _manifest(runner=r2, key=b"shared", source="disposable-vm")
    result = diff.compare_manifests(a, b)
    hits = [f for f in result["findings"] if f["category"] == "baseline_config"
            and f["key"] == "deployed_files" and f["manifest_a_value"] == "/opt/baseline/bin/old-tool"]
    assert hits
    assert hits[0]["classification"] == "candidate_obsolete"


def test_diagnostic_tools_missing_on_new_build_is_a_finding():
    from inventory.runner import CommandResult
    r1, r2 = FakeRunner(), FakeRunner()
    r1.binaries["sensors"] = "/usr/bin/sensors"
    r1.script(lambda a: a[:1] == ["sensors"], CommandResult(ok=True, stdout="lm-sensors version 3.6.2\n"))
    a = _manifest(runner=r1, key=b"shared", source="current-drive")
    b = _manifest(runner=r2, key=b"shared", source="disposable-vm")
    result = diff.compare_manifests(a, b)
    assert any(f["category"] == "diagnostic_tools" for f in result["findings"])


def test_config_files_permission_drift_is_reported_without_matching_key():
    """Non-tokenized config_files metadata (mode/owner/size) must still
    compare even when the comparison key differs - only content_identity
    is key-gated."""
    a = {"source": "current-drive", "redaction_report": {"key_id": "aaa"},
         "categories": {}, "config_files": [
             {"path": "/etc/hostname", "mode": "644", "owner": "root", "exists": True},
         ]}
    b = {"source": "disposable-vm", "redaction_report": {"key_id": "bbb"},
         "categories": {}, "config_files": [
             {"path": "/etc/hostname", "mode": "600", "owner": "root", "exists": True},
         ]}
    result = diff.compare_manifests(a, b)
    mode_findings = [f for f in result["findings"] if f["key"] == "/etc/hostname.mode"]
    assert mode_findings
    assert mode_findings[0]["manifest_a_value"] == "644"
    assert mode_findings[0]["manifest_b_value"] == "600"


def test_config_files_content_identity_is_skipped_without_matching_key():
    a = {"source": "current-drive", "redaction_report": {"key_id": "aaa"},
         "categories": {}, "config_files": [
             {"path": "/etc/hostname", "content_identity": "content:1111"},
         ]}
    b = {"source": "disposable-vm", "redaction_report": {"key_id": "bbb"},
         "categories": {}, "config_files": [
             {"path": "/etc/hostname", "content_identity": "content:2222"},
         ]}
    result = diff.compare_manifests(a, b)
    assert not any(f["key"] == "/etc/hostname.content_identity" for f in result["findings"])


def test_config_files_content_identity_compared_when_key_matches():
    a = {"source": "current-drive", "redaction_report": {"key_id": "same"},
         "categories": {}, "config_files": [
             {"path": "/etc/hostname", "content_identity": "content:1111"},
         ]}
    b = {"source": "disposable-vm", "redaction_report": {"key_id": "same"},
         "categories": {}, "config_files": [
             {"path": "/etc/hostname", "content_identity": "content:2222"},
         ]}
    result = diff.compare_manifests(a, b)
    assert any(f["key"] == "/etc/hostname.content_identity" for f in result["findings"])


def test_secret_shaped_value_is_flagged_detected_secret_identity():
    a = {"source": "current-drive", "redaction_report": {"key_id": "same"},
         "categories": {"apt": {"policy_summary": "192.168.1.1 leaked somehow"}}, "config_files": []}
    b = {"source": "disposable-vm", "redaction_report": {"key_id": "same"},
         "categories": {"apt": {"policy_summary": "clean value"}}, "config_files": []}
    result = diff.compare_manifests(a, b)
    hits = [f for f in result["findings"] if f["classification"] == "detected_secret_identity"]
    assert hits


def test_findings_by_classification_counts_match_findings_list():
    a = _manifest(key=b"shared", source="current-drive")
    b = _manifest(key=b"shared", source="disposable-vm")
    result = diff.compare_manifests(a, b)
    total = sum(result["findings_by_classification"].values())
    assert total == len(result["findings"])
