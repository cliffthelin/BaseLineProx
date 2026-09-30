"""Tests for measured_boot.py (hardened-appliance-prd.md, R4.2 / A3.1-A3.3).
Pure: no TPM, no disk, no registry. The runner is injected."""
import hashlib

import measured_boot as mb


class FakeRunner:
    def __init__(self, returncode=0, stderr=""):
        self.calls = []
        self.returncode = returncode
        self.stderr = stderr

    def run(self, argv):
        self.calls.append(list(argv))
        return self.returncode, "", self.stderr


def test_digest_is_stable_across_calls():
    entries = {"a": 1, "b": [1, 2]}
    assert mb.layer_digest("device_layer", entries) == mb.layer_digest("device_layer", entries)


def test_digest_ignores_key_order_and_whitespace_in_source():
    one = mb.layer_digest("device_layer", {"a": 1, "b": {"x": 1, "y": 2}})
    two = mb.layer_digest("device_layer", {"b": {"y": 2, "x": 1}, "a": 1})
    assert one == two


def test_digest_changes_on_single_value_change():
    base = mb.layer_digest("device_layer", {"a": "value"})
    assert mb.layer_digest("device_layer", {"a": "valuf"}) != base


def test_digest_is_domain_separated_by_layer_name():
    entries = {"a": 1}
    assert mb.layer_digest("device_layer", entries) != mb.layer_digest("application_layer", entries)


def test_digest_is_sha256_hex():
    d = mb.layer_digest("device_layer", {})
    assert len(d) == 64
    int(d, 16)


def test_expected_pcr_after_extend_matches_tpm_arithmetic():
    old = bytes(32)
    digest = mb.layer_digest("device_layer", {"a": 1})
    want = hashlib.sha256(old + bytes.fromhex(digest)).hexdigest()
    assert mb.expected_pcr_after_extend(old.hex(), digest) == want


def test_extend_pcr_calls_tpm2_pcrextend_with_sha256_bank():
    runner = FakeRunner()
    digest = mb.layer_digest("device_layer", {"a": 1})
    mb.extend_pcr(runner, 15, digest)
    assert runner.calls == [["tpm2_pcrextend", f"15:sha256={digest}"]]


def test_extend_pcr_refuses_a_non_digest_string():
    runner = FakeRunner()
    try:
        mb.extend_pcr(runner, 15, "not-a-digest")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert runner.calls == []


def test_extend_pcr_refuses_out_of_range_index():
    runner = FakeRunner()
    digest = mb.layer_digest("device_layer", {})
    for bad in (-1, 24):
        try:
            mb.extend_pcr(runner, bad, digest)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")
    assert runner.calls == []


def test_extend_pcr_raises_on_tool_failure_with_stderr():
    runner = FakeRunner(returncode=1, stderr="no tpm")
    digest = mb.layer_digest("device_layer", {})
    try:
        mb.extend_pcr(runner, 15, digest)
    except mb.PcrExtendError as exc:
        assert "no tpm" in str(exc)
    else:
        raise AssertionError("expected PcrExtendError")
