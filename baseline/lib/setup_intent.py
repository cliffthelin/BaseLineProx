"""Setup-intent trust model (Investigation 9 prototype).

Entirely offline, synthetic-key, no privileged access of any kind.
Uses only already-installed libraries (cryptography, stdlib) -- nothing
was installed for this investigation.

Two deliberately separate concerns, per the milestone-0 brief:

  1. Canonical serialization + strict parsing, so a document with
     duplicate/ambiguous keys can never produce two different
     "the signed bytes were X" interpretations between the signer and
     the verifier.
  2. Ed25519 signature verification against a *caller-supplied* trust
     store (verify_signature never trusts a key_id it wasn't handed) --
     policy checks (expiry, target binding, replay, schema, action
     bounds) are deliberately kept separate from signature validity,
     because "signature valid" and "execution authorized" are NOT the
     same claim (see decision record 09).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SCHEMA = "baseline.setup-intent.v1"
KNOWN_SCHEMAS = {SCHEMA}  # a verifier that doesn't recognize a schema must reject, not best-effort-parse


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains the same key twice."""


def _reject_duplicate_keys(pairs):
    seen = set()
    result = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKeyError(f"duplicate key in signed document: {key!r}")
        seen.add(key)
        result[key] = value
    return result


def parse_strict(raw: bytes) -> dict:
    """Parse JSON, refusing any object with a duplicate key.

    Without this, `json.loads`'s default behavior (last-value-wins) means
    a document could contain two different values for the same field --
    a naive implementation might display one value on tty1 while the
    bytes that were actually signed encode the other, since some
    canonicalizers reject dupes and some silently keep the last one.
    """
    return json.loads(raw, object_pairs_hook=_reject_duplicate_keys)


def canonical_bytes(payload: dict) -> bytes:
    """Deterministic byte representation: sorted keys, compact separators,
    ASCII-escaped. Two structurally-equal dicts always produce identical
    bytes; this is what actually gets signed and verified, never the
    original (possibly differently-formatted) wire bytes.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


@dataclass
class SignedIntent:
    payload: dict
    signature_hex: str
    signer_key_id: str

    def to_json(self) -> str:
        return json.dumps(
            {"payload": self.payload, "signature_hex": self.signature_hex, "signer_key_id": self.signer_key_id},
            sort_keys=True,
        )


def make_payload(
    *,
    intent_id: str,
    created_at: float,
    expires_at: float,
    target_install_session_id: str,
    actions: list,
    policy_bounds: dict,
    schema: str = SCHEMA,
) -> dict:
    return {
        "schema": schema,
        "intent_id": intent_id,
        "created_at": created_at,
        "expires_at": expires_at,
        "target": {"install_session_id": target_install_session_id},
        "actions": actions,
        "policy_bounds": policy_bounds,
    }


def sign_intent(payload: dict, priv: Ed25519PrivateKey, key_id: str) -> SignedIntent:
    body = canonical_bytes(payload)
    signature = priv.sign(body)
    return SignedIntent(payload=payload, signature_hex=signature.hex(), signer_key_id=key_id)


def verify_signature(signed: dict, trusted_keys: dict[str, Ed25519PublicKey]) -> bool:
    """Cryptographic check ONLY. Says nothing about expiry, target,
    replay, or policy -- see verify_intent for the full fail-closed chain.
    """
    key_id = signed.get("signer_key_id")
    pub = trusted_keys.get(key_id)
    if pub is None:
        return False  # unknown or revoked key -- same code path deliberately
    try:
        body = canonical_bytes(signed["payload"])
        pub.verify(bytes.fromhex(signed["signature_hex"]), body)
        return True
    except (InvalidSignature, ValueError, KeyError):
        return False


# --- Durable, existence-based consumed-intent ledger -----------------
#
# Deliberately checks *file existence*, not parsed content, for the
# block/allow decision. A corrupted ledger entry must never be treated
# as "not consumed" (that would silently re-enable replay) -- so the
# safe read path only ever asks "does a record exist for this
# intent_id", never "can I successfully parse what's inside it".
# Content is retained for audit/debugging only.

def record_consumption(ledger_dir: str, intent_id: str, target_id: str) -> None:
    os.makedirs(ledger_dir, exist_ok=True)
    entry = {"intent_id": intent_id, "target_id": target_id, "consumed_at": time.time()}
    final_path = os.path.join(ledger_dir, f"{intent_id}.json")
    tmp_path = os.path.join(ledger_dir, f".tmp-{secrets.token_hex(8)}")
    with open(tmp_path, "w") as f:
        f.write(json.dumps(entry))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)  # atomic rename -- partial writes never appear at the final name
    dir_fd = os.open(ledger_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)  # durability for the rename itself, not just the file content
    finally:
        os.close(dir_fd)


def is_consumed(ledger_dir: str, intent_id: str) -> bool:
    return os.path.exists(os.path.join(ledger_dir, f"{intent_id}.json"))


# --- Full fail-closed policy chain ------------------------------------

def verify_intent(
    signed: dict,
    *,
    trusted_keys: dict[str, Ed25519PublicKey],
    now: float,
    expected_target_install_session_id: str,
    ledger_dir: str,
    allowed_actions: set[str],
    max_actions: int,
) -> tuple[bool, str]:
    """Returns (ok, reason). Every branch is a rejection with a specific
    reason; there is no default-permit branch.
    """
    payload = signed.get("payload")
    if not isinstance(payload, dict):
        return False, "malformed: no payload object"

    if payload.get("schema") not in KNOWN_SCHEMAS:
        return False, "unknown or downgraded schema"

    if not verify_signature(signed, trusted_keys):
        return False, "signature invalid or signer key not trusted"

    intent_id = payload.get("intent_id")
    if not intent_id:
        return False, "malformed: missing intent_id"

    created_at = payload.get("created_at")
    expires_at = payload.get("expires_at")
    if not isinstance(created_at, (int, float)) or not isinstance(expires_at, (int, float)):
        return False, "malformed: missing/invalid timestamps"
    if created_at > now:
        return False, "future-dated intent"
    if now > expires_at:
        return False, "expired intent"

    target = payload.get("target", {})
    if target.get("install_session_id") != expected_target_install_session_id:
        return False, "target mismatch"

    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return False, "malformed: no actions"
    if len(actions) > max_actions:
        return False, "policy bounds exceeded: too many actions"
    for action in actions:
        if action.get("action") not in allowed_actions:
            return False, f"action expansion: {action.get('action')!r} not in allowed set"

    if is_consumed(ledger_dir, intent_id):
        return False, "intent already consumed (replay)"

    return True, "ok"
