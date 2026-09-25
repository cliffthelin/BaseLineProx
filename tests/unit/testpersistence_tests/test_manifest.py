"""Domain-separated authenticated manifest/ledger (PRD §4, §6): test vs.
production domain crossing, chained ledger tamper detection, and
newer-schema refusal (malformed/newer schemas)."""
import pytest

from testpersistence.manifest import (
    PRODUCTION_MANIFEST_DOMAIN, TEST_MANIFEST_DOMAIN, AuthorityLedger,
    ManifestAuthenticityError, SchemaVersionError, assert_domain_matches_mode,
    check_schema_version, derive_manifest_key, domain_for,
)

BASE_SECRET = b"synthetic-base-secret-not-a-real-key-material"


def test_domain_for_selects_test_or_production():
    assert domain_for(test_only=True) == TEST_MANIFEST_DOMAIN
    assert domain_for(test_only=False) == PRODUCTION_MANIFEST_DOMAIN


def test_production_reader_rejects_test_domain_manifest():
    with pytest.raises(ManifestAuthenticityError):
        assert_domain_matches_mode(TEST_MANIFEST_DOMAIN, reader_is_test_mode=False)


def test_test_reader_rejects_production_domain_manifest():
    with pytest.raises(ManifestAuthenticityError):
        assert_domain_matches_mode(PRODUCTION_MANIFEST_DOMAIN, reader_is_test_mode=True)


def test_matching_domain_passes():
    assert_domain_matches_mode(TEST_MANIFEST_DOMAIN, reader_is_test_mode=True) is None
    assert_domain_matches_mode(PRODUCTION_MANIFEST_DOMAIN, reader_is_test_mode=False) is None


def test_derived_keys_differ_across_domains_even_from_the_same_base_secret():
    test_key = derive_manifest_key(BASE_SECRET, TEST_MANIFEST_DOMAIN)
    prod_key = derive_manifest_key(BASE_SECRET, PRODUCTION_MANIFEST_DOMAIN)
    assert test_key != prod_key


def test_newer_schema_is_refused_not_best_effort_parsed():
    with pytest.raises(SchemaVersionError):
        check_schema_version(manifest_schema_version=2, reader_supported_version=1)


def test_older_or_equal_schema_is_not_a_newer_schema_refusal():
    check_schema_version(manifest_schema_version=1, reader_supported_version=1)  # no raise
    check_schema_version(manifest_schema_version=0, reader_supported_version=1)  # no raise


# --- authenticated, chained ledger -----------------------------------------

def test_ledger_entries_are_authenticated_and_chained():
    key = derive_manifest_key(BASE_SECRET, TEST_MANIFEST_DOMAIN)
    ledger = AuthorityLedger(key=key, domain=TEST_MANIFEST_DOMAIN)
    ledger.append("grant_issued", {"grant_id": "TestGrant-001"})
    ledger.append("grant_revoked", {"grant_id": "TestGrant-001"})
    assert ledger.verify_chain()


def test_decrypting_alone_is_not_sufficient_to_forge_an_entry():
    """Simulates PRD §4's threat: someone with the decrypted volume
    content but not the domain-separated authenticating key cannot
    produce a validly-authenticated new entry."""
    key = derive_manifest_key(BASE_SECRET, TEST_MANIFEST_DOMAIN)
    ledger = AuthorityLedger(key=key, domain=TEST_MANIFEST_DOMAIN)
    ledger.append("grant_issued", {"grant_id": "TestGrant-001"})

    wrong_key = derive_manifest_key(b"a-different-secret-entirely", TEST_MANIFEST_DOMAIN)
    forged = ledger.entries[0]
    assert forged.verify(wrong_key, TEST_MANIFEST_DOMAIN) is False


def test_dropped_entry_breaks_the_chain():
    key = derive_manifest_key(BASE_SECRET, TEST_MANIFEST_DOMAIN)
    ledger = AuthorityLedger(key=key, domain=TEST_MANIFEST_DOMAIN)
    ledger.append("event_one", {})
    ledger.append("event_two", {})
    ledger.append("event_three", {})
    del ledger.entries[1]  # simulate a dropped entry
    assert ledger.verify_chain() is False


def test_reordered_entries_break_the_chain():
    key = derive_manifest_key(BASE_SECRET, TEST_MANIFEST_DOMAIN)
    ledger = AuthorityLedger(key=key, domain=TEST_MANIFEST_DOMAIN)
    ledger.append("event_one", {})
    ledger.append("event_two", {})
    ledger.entries[0], ledger.entries[1] = ledger.entries[1], ledger.entries[0]
    assert ledger.verify_chain() is False


def test_tampered_payload_fails_verification_even_with_correct_key():
    key = derive_manifest_key(BASE_SECRET, TEST_MANIFEST_DOMAIN)
    ledger = AuthorityLedger(key=key, domain=TEST_MANIFEST_DOMAIN)
    entry = ledger.append("grant_issued", {"grant_id": "TestGrant-001"})
    tampered = entry.__class__(entry.sequence, entry.event,
                                {"grant_id": "TestGrant-999"},  # payload altered
                                entry.previous_mac, entry.mac)
    assert tampered.verify(key, TEST_MANIFEST_DOMAIN) is False
