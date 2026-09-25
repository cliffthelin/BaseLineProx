"""Domain-separated, authenticated synthetic manifest (PRD §4, §6).

Milestone-2 decisions this module implements (PRD §16's blocking
decisions for this milestone):

- Key derivation: a subkey derived from a base secret via a separate,
  named KDF domain per authority domain (HMAC-SHA256(base_secret,
  domain) - a minimal HKDF-style single-step derivation, adequate for
  this synthetic experiment; a production implementation may use a
  stronger KDF, but the domain-separation *property* this enforces is
  the actual requirement, not this specific construction).
- Every manifest write and authority_ledger entry is authenticated
  with an HMAC keyed under a domain string distinct for test vs.
  production authority, mirroring redact.py's _KEY_ID_DOMAIN pattern.
  A production-mode reader structurally rejects anything authenticated
  under the test domain, and vice versa - never a fallback to trusting
  a bare test_only boolean.
- Ledger entries are chained: each entry's authentication covers the
  previous entry's own mac, so a dropped or reordered entry is
  detectable even by an authorized-key holder acting outside the
  normal append path.
"""
import dataclasses
import hashlib
import hmac
import json

TEST_MANIFEST_DOMAIN = b"baseline-manifest-test-v1:"
PRODUCTION_MANIFEST_DOMAIN = b"baseline-manifest-production-v1:"


class ManifestAuthenticityError(Exception):
    pass


class SchemaVersionError(Exception):
    pass


def check_schema_version(manifest_schema_version: int, reader_supported_version: int) -> None:
    """PRD §13's "Newer-schema" failure mode: refuses to guess-parse a
    manifest whose schema_version is newer than this reader
    understands - never a partial/best-effort interpretation. An older
    manifest schema_version is not itself rejected here (that's a
    migration decision, out of Milestone-2 scope); only "newer than
    understood" is a hard refusal."""
    if manifest_schema_version > reader_supported_version:
        raise SchemaVersionError(
            f"manifest schema_version {manifest_schema_version} is newer than this "
            f"reader supports ({reader_supported_version}) - refusing to guess-parse")


def derive_manifest_key(base_secret: bytes, domain: bytes) -> bytes:
    """Milestone-2 key-derivation decision (see module docstring): a
    domain-separated subkey, never the base secret itself used
    directly for authentication."""
    return hmac.new(base_secret, domain, hashlib.sha256).digest()


def _mac(key: bytes, domain: bytes, payload: bytes) -> str:
    return hmac.new(key, domain + payload, hashlib.sha256).hexdigest()


def _canonical(sequence: int, event: str, payload: dict, previous_mac: str) -> bytes:
    return json.dumps(
        {"sequence": sequence, "event": event, "payload": payload,
         "previous_mac": previous_mac},
        sort_keys=True).encode()


@dataclasses.dataclass(frozen=True)
class LedgerEntry:
    """One authority_ledger entry (PRD §11)."""
    sequence: int
    event: str
    payload: dict
    previous_mac: str
    mac: str

    @staticmethod
    def create(sequence: int, event: str, payload: dict, previous_mac: str,
               key: bytes, domain: bytes) -> "LedgerEntry":
        mac = _mac(key, domain, _canonical(sequence, event, payload, previous_mac))
        return LedgerEntry(sequence, event, payload, previous_mac, mac)

    def verify(self, key: bytes, domain: bytes) -> bool:
        expected = _mac(key, domain,
                         _canonical(self.sequence, self.event, self.payload, self.previous_mac))
        return hmac.compare_digest(expected, self.mac)


@dataclasses.dataclass
class AuthorityLedger:
    """Append-only chained ledger, keyed under one authority domain
    (test or production - never both). verify_chain() detects a
    dropped or reordered entry."""
    key: bytes
    domain: bytes
    entries: list = dataclasses.field(default_factory=list)

    def append(self, event: str, payload: dict) -> LedgerEntry:
        previous_mac = self.entries[-1].mac if self.entries else ""
        entry = LedgerEntry.create(len(self.entries), event, payload, previous_mac,
                                    self.key, self.domain)
        self.entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        previous_mac = ""
        for entry in self.entries:
            if entry.previous_mac != previous_mac:
                return False
            if not entry.verify(self.key, self.domain):
                return False
            previous_mac = entry.mac
        return True


def domain_for(test_only: bool) -> bytes:
    return TEST_MANIFEST_DOMAIN if test_only else PRODUCTION_MANIFEST_DOMAIN


def assert_domain_matches_mode(manifest_domain: bytes, reader_is_test_mode: bool) -> None:
    """A production-mode reader must structurally reject a test-domain
    manifest, and a test-mode reader must equally reject a
    production-domain manifest - never a fallback to trusting a bare
    test_only field (PRD §6)."""
    expected = domain_for(reader_is_test_mode)
    if manifest_domain != expected:
        raise ManifestAuthenticityError(
            f"manifest authenticated under domain {manifest_domain!r}, reader "
            f"requires {expected!r} - refusing to read across the test/"
            f"production boundary")
