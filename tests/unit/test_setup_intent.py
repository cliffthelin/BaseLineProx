"""Unit tests for setup_intent.py (Milestone 1, promoted from Investigation
9's prototype - see decision record 09). All keys are freshly generated
Ed25519 test keys held only in memory; ledger state lives under pytest's
tmp_path. No device access, no privileged operation, no network."""
import json
import os
import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import setup_intent as si

NOW = 1_800_000_000.0


@pytest.fixture
def keys():
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


@pytest.fixture
def trusted(keys):
    _, pub = keys
    return {"key-legit-2026": pub}


def common_kwargs(ledger_dir):
    return dict(
        now=NOW,
        expected_target_install_session_id="install-session-abc123",
        ledger_dir=str(ledger_dir),
        allowed_actions={"apply_firewall_policy", "set_hostname"},
        max_actions=5,
    )


def fresh_payload(**overrides):
    base = dict(
        intent_id="intent-0001",
        created_at=NOW - 60,
        expires_at=NOW + 3600,
        target_install_session_id="install-session-abc123",
        actions=[{"action": "apply_firewall_policy", "params": {"policy": "default-deny"}}],
        policy_bounds={"max_actions": 5},
    )
    base.update(overrides)
    return si.make_payload(**base)


def test_valid_signed_intent_passes_full_chain(keys, trusted, tmp_path):
    priv, _ = keys
    signed = si.sign_intent(fresh_payload(), priv, "key-legit-2026").__dict__
    ok, reason = si.verify_intent(signed, trusted_keys=trusted, **common_kwargs(tmp_path))
    assert ok, reason


def test_tampered_payload_fails_signature_verification(keys, trusted):
    priv, _ = keys
    signed = si.sign_intent(fresh_payload(intent_id="intent-0002"), priv, "key-legit-2026").__dict__
    tampered = {**signed, "payload": {**signed["payload"], "actions": [{"action": "wipe_disk", "params": {}}]}}
    assert not si.verify_signature(tampered, trusted)


def test_substituted_attacker_key_fails_even_with_spoofed_key_id(trusted):
    attacker_priv = Ed25519PrivateKey.generate()
    forged = si.sign_intent(fresh_payload(intent_id="intent-0003"), attacker_priv, "key-legit-2026").__dict__
    assert not si.verify_signature(forged, trusted)


def test_unknown_signer_key_id_is_rejected(trusted, tmp_path):
    attacker_priv = Ed25519PrivateKey.generate()
    signed = si.sign_intent(fresh_payload(intent_id="intent-0003b"), attacker_priv, "key-unknown-9999").__dict__
    ok, reason = si.verify_intent(signed, trusted_keys=trusted, **common_kwargs(tmp_path))
    assert not ok
    assert "signer key not trusted" in reason


def test_duplicate_key_json_is_rejected_not_silently_resolved():
    dup_raw = b'{"intent_id":"x","intent_id":"y"}'
    with pytest.raises(si.DuplicateKeyError):
        si.parse_strict(dup_raw)


def test_expired_intent_rejected_despite_valid_signature(keys, trusted, tmp_path):
    priv, _ = keys
    signed = si.sign_intent(
        fresh_payload(intent_id="intent-0005", created_at=NOW - 7200, expires_at=NOW - 3600),
        priv, "key-legit-2026",
    ).__dict__
    ok, reason = si.verify_intent(signed, trusted_keys=trusted, **common_kwargs(tmp_path))
    assert not ok
    assert reason == "expired intent"


def test_future_dated_intent_rejected(keys, trusted, tmp_path):
    priv, _ = keys
    signed = si.sign_intent(
        fresh_payload(intent_id="intent-0005b", created_at=NOW + 3600, expires_at=NOW + 7200),
        priv, "key-legit-2026",
    ).__dict__
    ok, reason = si.verify_intent(signed, trusted_keys=trusted, **common_kwargs(tmp_path))
    assert not ok
    assert reason == "future-dated intent"


def test_target_mismatch_rejected(keys, trusted, tmp_path):
    priv, _ = keys
    signed = si.sign_intent(
        fresh_payload(intent_id="intent-0006", target_install_session_id="install-session-DIFFERENT"),
        priv, "key-legit-2026",
    ).__dict__
    ok, reason = si.verify_intent(signed, trusted_keys=trusted, **common_kwargs(tmp_path))
    assert not ok
    assert reason == "target mismatch"


def test_action_outside_allowed_set_rejected_no_expansion(keys, trusted, tmp_path):
    priv, _ = keys
    signed = si.sign_intent(
        fresh_payload(intent_id="intent-0007", actions=[{"action": "format_disk", "params": {}}]),
        priv, "key-legit-2026",
    ).__dict__
    ok, reason = si.verify_intent(signed, trusted_keys=trusted, **common_kwargs(tmp_path))
    assert not ok
    assert reason.startswith("action expansion")


def test_downgraded_schema_rejected_even_with_valid_signature(keys, trusted, tmp_path):
    priv, _ = keys
    payload = fresh_payload(intent_id="intent-0007b")
    payload["schema"] = "baseline.setup-intent.v0-legacy"
    resigned = si.sign_intent(payload, priv, "key-legit-2026").__dict__
    ok, reason = si.verify_intent(resigned, trusted_keys=trusted, **common_kwargs(tmp_path))
    assert not ok
    assert reason == "unknown or downgraded schema"


def test_replay_of_consumed_intent_id_rejected(keys, trusted, tmp_path):
    priv, _ = keys
    signed = si.sign_intent(fresh_payload(intent_id="intent-0008"), priv, "key-legit-2026").__dict__
    kwargs = common_kwargs(tmp_path)
    ok, reason = si.verify_intent(signed, trusted_keys=trusted, **kwargs)
    assert ok, reason
    si.record_consumption(str(tmp_path), "intent-0008", "install-session-abc123")
    ok2, reason2 = si.verify_intent(signed, trusted_keys=trusted, **kwargs)
    assert not ok2
    assert reason2 == "intent already consumed (replay)"


def test_interrupted_consumption_write_leaves_intent_not_consumed(tmp_path):
    ledger_dir = str(tmp_path)
    os.makedirs(ledger_dir, exist_ok=True)
    tmp_file = os.path.join(ledger_dir, f".tmp-{secrets.token_hex(8)}")
    with open(tmp_file, "w") as f:
        f.write(json.dumps({"intent_id": "intent-0009", "target_id": "x", "consumed_at": 0}))
        f.flush()
        os.fsync(f.fileno())
    # Deliberately no os.replace() - simulating a crash between write and rename.
    assert not si.is_consumed(ledger_dir, "intent-0009")

    si.record_consumption(ledger_dir, "intent-0009", "install-session-abc123")
    assert si.is_consumed(ledger_dir, "intent-0009")

    # The stray tmp file is inert - it never becomes the canonical record.
    assert os.path.exists(tmp_file)
    assert not tmp_file.endswith(".json")


def test_corrupted_ledger_entry_still_counts_as_consumed_fail_closed(tmp_path):
    ledger_dir = str(tmp_path)
    os.makedirs(ledger_dir, exist_ok=True)
    corrupt_final = os.path.join(ledger_dir, "intent-0009b.json")
    with open(corrupt_final, "w") as f:
        f.write("{not valid json at all")
    assert si.is_consumed(ledger_dir, "intent-0009b")
