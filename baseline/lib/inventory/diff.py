"""Pure, offline comparison of two already-produced manifests.

Never touches a host. Never mutates either manifest. Never generates
executable remediation, installation commands, or applies anything -
`compare_manifests()` returns a list of findings for a human to read;
nothing in this module writes to disk, runs a subprocess, or promotes
a suggestion into an approved decision.

Every difference starts unresolved and receives exactly one of five
classifications:

  suggested_required         - present on the reference ("current-drive")
                                manifest, missing (or different) on the
                                new-build manifest, with nothing marking
                                it machine-specific or obsolete -
                                probably worth re-applying.
  suggested_machine_specific - a difference inside a category this
                                module knows is expected to legitimately
                                vary by hardware/identity (network
                                addressing, boot cmdline, Proxmox node/
                                vmid identity, scheduling identities -
                                anywhere an HMAC-tokenized value from
                                redact.py appears), evaluated only when
                                both manifests share the same comparison
                                key (see below).
  detected_secret_identity   - a compared value matches one of
                                validate.py's own secret-shape patterns
                                (raw IP/MAC/UUID, embedded URL
                                credential, private key marker, SSH key
                                material, Proxmox subscription-key
                                shape) - a safety signal, independent of
                                whether the two sides even differ.
  candidate_obsolete          - present only on the reference side AND
                                structurally recognized as something the
                                current build no longer deploys (applied
                                narrowly, only to Baseline's own
                                deployed-file list, where "no longer
                                present" has an authoritative source of
                                truth - this module does not guess for
                                packages or anything else).
  unknown                     - the default for every other real
                                difference. No narrow rule was confident
                                enough to say more; a human decides.

Cross-run HMAC comparison problem: two manifests collected at different
times, each with the default ephemeral key, tokenize the same hostname/
interface/address differently - comparing their tokens for equality
would always disagree even when the underlying value is identical, and
would never actually catch a real identity difference either. This
module never tries to guess around that. Instead:

  - Every HMAC token has a self-describing shape ("kind:12-hex-chars",
    exactly what Redactor.tokenize() produces) - _is_token_shaped()
    recognizes this by pattern, not by a hardcoded field-name list, so
    it can never miss a newly-added tokenized field.
  - Both manifests must carry the same redaction_report.key_id (a
    non-secret fingerprint of the key that produced them - see
    redact.py) for their token-shaped values to be compared at all.
    Without a shared key_id, every token-shaped value is skipped
    (recorded in `skipped_key_mismatch`, never silently treated as
    equal OR reported as a false difference).
"""
import json
import re

from . import validate

_TOKEN_SHAPE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,20}:[0-9a-f]{12}$")

# Category keys (as they appear in manifest["categories"]) whose values
# are expected to legitimately vary by hardware/host identity once a
# real difference IS found under a matching key.
IDENTITY_SENSITIVE_CATEGORIES = frozenset({"proxmox", "boot", "scheduling", "network"})

CLASSIFICATIONS = ("suggested_required", "suggested_machine_specific",
                    "detected_secret_identity", "candidate_obsolete", "unknown")


class ComparisonKeyError(Exception):
    """Raised only when the caller explicitly requires a matching key
    (require_matching_key=True) and the two manifests don't have one -
    never raised for the default, best-effort comparison mode."""


def _is_token_shaped(value):
    return isinstance(value, str) and bool(_TOKEN_SHAPE_RE.match(value))


def _contains_token_shaped(value):
    if _is_token_shaped(value):
        return True
    if isinstance(value, dict):
        return any(_contains_token_shaped(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_token_shaped(v) for v in value)
    return False


def _secret_pattern_name(value):
    if not isinstance(value, str):
        return None
    for name, rx in validate._SECRET_VALUE_PATTERNS:
        if rx.search(value):
            return name
    return None


def _contains_secret_pattern(value):
    if isinstance(value, str):
        return _secret_pattern_name(value)
    if isinstance(value, dict):
        for v in value.values():
            found = _contains_secret_pattern(v)
            if found:
                return found
    if isinstance(value, list):
        for v in value:
            found = _contains_secret_pattern(v)
            if found:
                return found
    return None


def _canon(item):
    return json.dumps(item, sort_keys=True, default=str)


def _finding(category, key, a_value, b_value, side, classification, reason):
    return {
        "category": category, "key": key,
        "manifest_a_value": a_value, "manifest_b_value": b_value,
        "side": side, "classification": classification, "reason": reason,
    }


def _classify_scalar_diff(category, field_key, a_value, b_value, key_ok):
    """a_value is the reference (current-drive) side, b_value the
    new-build side. Exactly one of the five classifications, or None
    to mean "skip this finding entirely" (only for a key-mismatched
    token-shaped value)."""
    secret = _contains_secret_pattern(a_value) or _contains_secret_pattern(b_value)
    if secret:
        return "detected_secret_identity", f"value matches a known secret-shaped pattern ({secret})"

    is_identity = category in IDENTITY_SENSITIVE_CATEGORIES and (
        _contains_token_shaped(a_value) or _contains_token_shaped(b_value))
    if is_identity and not key_ok:
        return None, "skipped: HMAC-tokenized value, manifests do not share a comparison key"
    if is_identity:
        return "suggested_machine_specific", "identity/hardware-bound field, expected to vary by host"

    if a_value is not None and b_value is None:
        if category == "baseline_config" and field_key == "deployed_files":
            return "candidate_obsolete", "present on current-drive, no longer part of the current deploy"
        return "suggested_required", "present on current-drive, missing on the new build"
    if a_value is None and b_value is not None:
        return "unknown", "present on the new build, not on current-drive"
    return "unknown", "value differs between the two manifests"


def _compare_scalar_fields(category, dict_a, dict_b, key_ok, findings):
    if not isinstance(dict_a, dict) or not isinstance(dict_b, dict):
        return
    keys = set(dict_a) | set(dict_b)
    for key in sorted(keys):
        if key == "_collection_notes":
            continue
        a_value, b_value = dict_a.get(key), dict_b.get(key)
        if isinstance(a_value, list) or isinstance(b_value, list):
            continue  # handled by _compare_list_fields
        if isinstance(a_value, dict) or isinstance(b_value, dict):
            _compare_scalar_fields(category, a_value or {}, b_value or {}, key_ok, findings)
            continue
        if a_value == b_value:
            continue
        classification, reason = _classify_scalar_diff(category, key, a_value, b_value, key_ok)
        if classification is None:
            continue
        findings.append(_finding(category, key, a_value, b_value, "both" if a_value and b_value else
                                  ("a_only" if a_value is not None else "b_only"), classification, reason))


def _compare_list_fields(category, dict_a, dict_b, key_ok, findings):
    if not isinstance(dict_a, dict) or not isinstance(dict_b, dict):
        return
    keys = {k for k in set(dict_a) | set(dict_b)
            if isinstance(dict_a.get(k), list) or isinstance(dict_b.get(k), list)}
    for key in sorted(keys):
        list_a = dict_a.get(key) or []
        list_b = dict_b.get(key) or []
        a_map = {_canon(item): item for item in list_a}
        b_map = {_canon(item): item for item in list_b}
        for canon_key in sorted(set(a_map) - set(b_map)):
            item = a_map[canon_key]
            classification, reason = _classify_scalar_diff(category, key, item, None, key_ok)
            if classification is None:
                continue
            findings.append(_finding(category, key, item, None, "a_only", classification, reason))
        for canon_key in sorted(set(b_map) - set(a_map)):
            item = b_map[canon_key]
            classification, reason = _classify_scalar_diff(category, key, None, item, key_ok)
            if classification is None:
                continue
            findings.append(_finding(category, key, None, item, "b_only", classification, reason))


def _compare_config_files(entries_a, entries_b, key_ok):
    findings = []
    by_path_a = {e["path"]: e for e in entries_a}
    by_path_b = {e["path"]: e for e in entries_b}
    for path in sorted(set(by_path_a) | set(by_path_b)):
        a_entry, b_entry = by_path_a.get(path), by_path_b.get(path)
        if a_entry is None:
            findings.append(_finding("config_files", path, None, b_entry, "b_only", "unknown",
                                      "config file present only on the new build"))
            continue
        if b_entry is None:
            classification = ("candidate_obsolete" if a_entry.get("baseline_managed")
                               else "suggested_required")
            findings.append(_finding("config_files", path, a_entry, None, "a_only", classification,
                                      "config file present on current-drive, missing on the new build"))
            continue
        # Compare every field except content_identity (HMAC-tokenized,
        # key-gated) as plain metadata - permissions/owner/size/
        # conffile-modified drift is real signal even without a shared
        # comparison key.
        for field in sorted(set(a_entry) | set(b_entry)):
            if field == "content_identity":
                if not key_ok:
                    continue
                a_v, b_v = a_entry.get(field), b_entry.get(field)
                if a_v != b_v:
                    findings.append(_finding("config_files", f"{path}.content_identity", a_v, b_v, "both",
                                              "unknown", "file content differs between current-drive and the new build"))
                continue
            a_v, b_v = a_entry.get(field), b_entry.get(field)
            if a_v == b_v:
                continue
            findings.append(_finding("config_files", f"{path}.{field}", a_v, b_v, "both", "unknown",
                                      f"{field} differs for {path}"))
    return findings


def compare_manifests(manifest_a, manifest_b, require_matching_key=False):
    """manifest_a is treated as the reference (normally source=
    "current-drive"); manifest_b as the new build. Both are read-only
    inputs - neither is ever modified."""
    key_a = (manifest_a.get("redaction_report") or {}).get("key_id")
    key_b = (manifest_b.get("redaction_report") or {}).get("key_id")
    key_ok = bool(key_a) and key_a == key_b

    if require_matching_key and not key_ok:
        raise ComparisonKeyError(
            f"manifests do not share a comparison key (key_id a={key_a!r} b={key_b!r}) - "
            "identity-sensitive comparison refused; re-collect both manifests with the same "
            "--key-file/--key-fd, or pass require_matching_key=False to compare non-identity "
            "categories only")

    findings = []
    categories_a = manifest_a.get("categories", {})
    categories_b = manifest_b.get("categories", {})
    for category in sorted(set(categories_a) | set(categories_b)):
        if category == "config_files_collection":
            continue
        a_cat = categories_a.get(category) or {}
        b_cat = categories_b.get(category) or {}
        _compare_scalar_fields(category, a_cat, b_cat, key_ok, findings)
        _compare_list_fields(category, a_cat, b_cat, key_ok, findings)

    findings += _compare_config_files(manifest_a.get("config_files", []), manifest_b.get("config_files", []), key_ok)

    by_classification = {c: [] for c in CLASSIFICATIONS}
    for f in findings:
        by_classification[f["classification"]].append(f)

    return {
        "key_comparison": {"key_a": key_a, "key_b": key_b, "matched": key_ok},
        "findings": findings,
        "findings_by_classification": {k: len(v) for k, v in by_classification.items()},
        "reference_source": manifest_a.get("source"), "compared_source": manifest_b.get("source"),
    }
