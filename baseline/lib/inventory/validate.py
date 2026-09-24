"""Pre-run/pre-share manifest validator.

This is defense in depth, not upload authorization (Cliff's own framing):
it re-checks the already-written manifest independently of the collectors
that produced it, the same way atomic_write() re-validates independently
of an earlier check rather than trusting it. Passing this validator does
not mean the manifest is safe to upload or commit anywhere - a human still
inspects it first, per the design doc's read-only guarantee and the
first-run procedure.

Five things are checked, each returning its own list of findings:

1. schema_validity        - required top-level keys present, schema_version
                             matches this codebase's SCHEMA_VERSION.
2. output_permissions      - the written file is mode 0600, nothing looser.
3. forbidden_field_names   - no key anywhere in the manifest looks like a
                             raw secret field (password/secret/apitoken/
                             keyring/encryption/cipassword/privkey), except
                             the handful of "_token"-suffixed keys that are
                             this tool's own redaction-token field names,
                             not secrets.
4. secret_value_patterns   - no string value anywhere matches a raw IPv4/
                             IPv6 address, MAC address, UUID, an embedded
                             URL credential, a private-key marker, SSH key
                             material, or a Proxmox-subscription-key shape.
5. large_text_values       - a soft heuristic (not a hard failure): any
                             single string value long enough to look like
                             retained raw command output rather than a
                             normalized field, flagged for manual review.

A sixth pass, collect_degraded_categories(), is not pass/fail - it
collects every place a collector reported timed_out/permission_denied/
unavailable/output_truncated/an "available": False category, so a human
reviewer sees the whole list in one place instead of hunting for it
(this is what "every unavailable/timed_out/truncated/denied category is
visibly reported" actually depends on - see collectors/status_notes.py).
"""
import os
import re
import stat

from . import schema

_FORBIDDEN_KEY_RE = re.compile(r"(password|secret|apitoken|keyring|encryption|cipassword|privkey)", re.IGNORECASE)
# This tool's own redaction-token field names - they hold HMAC tokens
# derived from a value, never the value itself, so "token" in the name
# is not a forbidden-field-name violation.
_ALLOWED_KEY_EXCEPTIONS = {"vmid_token", "name_token", "fields_redacted"}

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_RE = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")
_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_URL_CRED_RE = re.compile(r"://[^/\s@]+:[^/\s@]+@")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_SSH_KEY_RE = re.compile(r"\b(ssh-rsa|ssh-ed25519|ssh-dss|ecdsa-sha2-\S+)\s+[A-Za-z0-9+/]")
# Approximates the real pve<N><channel>-<10 hex chars> subscription-key
# shape closely enough to catch one, without this session ever having
# seen a real one to confirm the exact format against.
_SUBSCRIPTION_KEY_RE = re.compile(r"\bpve\d[a-z]-[0-9a-f]{10}\b", re.IGNORECASE)

_SECRET_VALUE_PATTERNS = (
    ("raw_ipv4", _IPV4_RE),
    ("raw_ipv6", _IPV6_RE),
    ("raw_mac", _MAC_RE),
    ("raw_uuid", _UUID_RE),
    ("embedded_url_credential", _URL_CRED_RE),
    ("private_key_marker", _PRIVATE_KEY_RE),
    ("ssh_key_material", _SSH_KEY_RE),
    ("proxmox_subscription_key", _SUBSCRIPTION_KEY_RE),
)

LARGE_TEXT_VALUE_THRESHOLD = 4000


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k, v
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def check_schema_validity(manifest):
    issues = []
    required = {
        "schema_version", "generated_at", "source", "host_label",
        "categories", "config_files", "redaction_report",
    }
    missing = required - set(manifest.keys())
    if missing:
        issues.append(f"missing top-level keys: {sorted(missing)}")
    if manifest.get("schema_version") != schema.SCHEMA_VERSION:
        issues.append(f"schema_version {manifest.get('schema_version')!r} != expected {schema.SCHEMA_VERSION}")
    return issues


def check_output_permissions(output_path):
    """None means "not checked" (only happens calling this module
    directly without a file - the CLI's `validate` subcommand always
    passes the manifest's own path), not a violation, so it never fails
    the run on its own."""
    if output_path is None:
        return []
    mode = stat.S_IMODE(os.stat(output_path).st_mode)
    if mode != 0o600:
        return [f"output file mode is {oct(mode)}, expected 0o600"]
    return []


def check_forbidden_field_names(manifest):
    issues = []
    for path, key, _value in _walk(manifest):
        if key in _ALLOWED_KEY_EXCEPTIONS:
            continue
        if _FORBIDDEN_KEY_RE.search(key):
            issues.append(f"forbidden-shaped key name '{key}' at {path or '<root>'}")
    return issues


def check_secret_value_patterns(manifest):
    issues = []
    for path, key, value in _walk(manifest):
        if not isinstance(value, str):
            continue
        field_path = f"{path}.{key}" if path else key
        for name, rx in _SECRET_VALUE_PATTERNS:
            if rx.search(value):
                issues.append(f"{name} pattern found in value at {field_path}")
    return issues


def check_large_text_values(manifest):
    issues = []
    for path, key, value in _walk(manifest):
        if isinstance(value, str) and len(value) > LARGE_TEXT_VALUE_THRESHOLD:
            field_path = f"{path}.{key}" if path else key
            issues.append(f"large text value ({len(value)} chars) at {field_path} - review manually for retained raw output")
    return issues


def collect_degraded_categories(manifest):
    """Not pass/fail. Surfaces every place a collector reported a
    non-clean state, so a human reviewer sees them all in one place."""
    found = []
    for path, key, value in _walk(manifest):
        field_path = f"{path}.{key}" if path else key
        if key in ("available", "ok") and value is False:
            found.append(field_path)
        elif key in ("timed_out", "output_truncated", "permission_denied") and value is True:
            found.append(field_path)
        elif key == "subscription_status" and value == "unavailable":
            found.append(field_path)
        elif key == "_collection_notes" and value:
            found.append(f"{field_path} ({len(value)} note(s))")
    return sorted(set(found))


_HARD_FAILURE_CHECKS = ("schema_validity", "output_permissions", "forbidden_field_names", "secret_value_patterns")


def validate_manifest(manifest, output_path=None):
    issues = {
        "schema_validity": check_schema_validity(manifest),
        "output_permissions": check_output_permissions(output_path),
        "forbidden_field_names": check_forbidden_field_names(manifest),
        "secret_value_patterns": check_secret_value_patterns(manifest),
        "large_text_values_for_manual_review": check_large_text_values(manifest),
    }
    passed = all(not issues[c] for c in _HARD_FAILURE_CHECKS)
    return {
        "passed": passed,
        "issues": issues,
        "degraded_categories_reported": collect_degraded_categories(manifest),
    }
