"""Evidence-based identity (PRD §4): contradictory evidence produces an
explicit ambiguous/refusal outcome, never a best guess. Also covers
store/carrier replacement (logical identity survives a carrier swap)."""
from testpersistence.evidence import (
    Confidence, CorroborationStatus, EvidenceClaim, EvidenceScope, IdentityOutcome,
    evaluate_identity,
)
from testpersistence.identity import CarrierIdentity, LogicalStoreIdentity, is_same_logical_store


def _claim(scope, value, confidence=Confidence.DIRECTLY_READ, source="test", t=0.0):
    return EvidenceClaim(source=source, observation_time=t, scope=scope, value=value,
                          confidence=confidence)


def test_agreeing_evidence_is_equivalent():
    claims = [
        _claim(EvidenceScope.LOGICAL_IDENTITY, "TestPersistence-001", source="manifest_field"),
        _claim(EvidenceScope.LOGICAL_IDENTITY, "TestPersistence-001", source="external_observation",
               confidence=Confidence.EXTERNALLY_REPORTED),
    ]
    result = evaluate_identity(EvidenceScope.LOGICAL_IDENTITY, claims)
    assert result.outcome == IdentityOutcome.EQUIVALENT


def test_contradictory_evidence_is_ambiguous_refusal_not_majority_vote():
    claims = [
        _claim(EvidenceScope.LOGICAL_IDENTITY, "TestPersistence-001"),
        _claim(EvidenceScope.LOGICAL_IDENTITY, "TestPersistence-001"),
        _claim(EvidenceScope.LOGICAL_IDENTITY, "TestPersistence-002"),  # one dissenting claim
    ]
    result = evaluate_identity(EvidenceScope.LOGICAL_IDENTITY, claims)
    assert result.outcome == IdentityOutcome.AMBIGUOUS_REFUSAL


def test_no_evidence_for_scope_is_also_ambiguous_refusal_not_assumed_absent():
    result = evaluate_identity(EvidenceScope.CARRIER_IDENTITY, [])
    assert result.outcome == IdentityOutcome.AMBIGUOUS_REFUSAL


def test_evidence_for_other_scopes_does_not_leak_into_this_evaluation():
    claims = [
        _claim(EvidenceScope.CARRIER_IDENTITY, "TestPersistenceDisk-001"),
        _claim(EvidenceScope.CARRIER_IDENTITY, "TestPersistenceDisk-999"),  # conflicting, different scope
        _claim(EvidenceScope.LOGICAL_IDENTITY, "TestPersistence-001"),
    ]
    result = evaluate_identity(EvidenceScope.LOGICAL_IDENTITY, claims)
    assert result.outcome == IdentityOutcome.EQUIVALENT


def test_corroboration_status_is_carried_but_not_required_for_equivalence():
    claim = _claim(EvidenceScope.GENERATION, "1")
    assert claim.corroboration == CorroborationStatus.UNCORROBORATED
    corroborated = EvidenceClaim(source="ledger", observation_time=1.0,
                                  scope=EvidenceScope.GENERATION, value="1",
                                  confidence=Confidence.DIRECTLY_READ,
                                  corroboration=CorroborationStatus.CORROBORATING)
    assert corroborated.corroboration == CorroborationStatus.CORROBORATING


# --- store/carrier replacement (acceptance cases 4 and 5) -----------------

def test_logical_identity_unchanged_across_carrier_replacement():
    before = LogicalStoreIdentity(logical_id="TestPersistence-001", generation=1)
    after_migration = LogicalStoreIdentity(logical_id="TestPersistence-001", generation=1)
    assert is_same_logical_store(before, after_migration)


def test_carrier_identity_is_never_compared_as_logical_identity():
    carrier_a = CarrierIdentity(carrier_id="TestPersistenceDisk-001")
    carrier_b = CarrierIdentity(carrier_id="TestPersistenceDisk-002")
    # Carriers differ (a real migration), but nothing in this module ever
    # equates a CarrierIdentity with a LogicalStoreIdentity - there is no
    # comparison function that even accepts both types together.
    assert carrier_a.carrier_id != carrier_b.carrier_id
    assert not hasattr(CarrierIdentity, "logical_id")


def test_different_logical_ids_are_not_the_same_store_even_with_same_generation():
    a = LogicalStoreIdentity(logical_id="TestPersistence-001", generation=3)
    b = LogicalStoreIdentity(logical_id="TestPersistence-999", generation=3)
    assert not is_same_logical_store(a, b)
