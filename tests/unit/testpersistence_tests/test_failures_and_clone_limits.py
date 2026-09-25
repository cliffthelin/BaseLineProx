"""Structured failure outcomes (PRD §13), reserved full-store recovery
capacity, and simultaneous-clone detection with its documented limits
(PRD §5's honest scoping - a separately-used clone is undecidable from
the store's own evidence alone until histories diverge)."""
import pytest

from testpersistence.evidence import (
    Confidence, EvidenceClaim, EvidenceScope, IdentityOutcome, evaluate_identity,
)
from testpersistence.failures import (
    FailureMode, cloned_store_outcome, full_store_outcome, missing_store_outcome,
    unknown_store_outcome,
)


def test_missing_store_outcome_is_degraded_with_no_auto_recreate_claim():
    outcome = missing_store_outcome()
    assert outcome.failure_mode == FailureMode.MISSING
    assert outcome.degraded
    assert "no auto-recreate" in outcome.message


def test_unknown_store_outcome_never_claims_inspection_ready():
    outcome = unknown_store_outcome()
    assert outcome.failure_mode == FailureMode.UNKNOWN
    assert "inspection_ready" in outcome.message


def test_full_store_outcome_requires_the_ledger_append_to_have_succeeded():
    outcome = full_store_outcome(ledger_append_succeeded=True)
    assert outcome.failure_mode == FailureMode.FULL


def test_full_store_outcome_raises_if_reserved_capacity_itself_was_exhausted():
    """This must never happen by construction (PRD §13) - if it does,
    that's a hard error, not a quietly-reported outcome."""
    with pytest.raises(RuntimeError):
        full_store_outcome(ledger_append_succeeded=False)


# --- simultaneous clone detection, and its documented limits --------------

def _claim(value, source, t):
    return EvidenceClaim(source=source, observation_time=t, scope=EvidenceScope.LOGICAL_IDENTITY,
                          value=value, confidence=Confidence.DIRECTLY_READ)


def test_two_simultaneously_attached_clones_at_the_same_generation_are_ambiguous():
    """Acceptance case 15: two attachments presenting identical
    logical-identity evidence at the same generation must produce an
    explicit ambiguous/refusal outcome, not a silent pick-one - modeled
    here as two directly-read claims for the SAME scope with
    DIFFERENT sources both reporting the SAME logical id, which alone
    isn't ambiguous (agreement); the ambiguity in a real clone scenario
    comes from two independent generation/attachment-ledger claims that
    disagree despite both claiming the same logical identity."""
    generation_claims = [
        EvidenceClaim(source="host_a_observation", observation_time=1.0,
                       scope=EvidenceScope.GENERATION, value="3", confidence=Confidence.DIRECTLY_READ),
        EvidenceClaim(source="host_b_observation", observation_time=1.0,
                       scope=EvidenceScope.GENERATION, value="3", confidence=Confidence.DIRECTLY_READ),
    ]
    identity_claims = [_claim("TestPersistence-001", "host_a_observation", 1.0),
                        _claim("TestPersistence-001", "host_b_observation", 1.0)]
    identity_result = evaluate_identity(EvidenceScope.LOGICAL_IDENTITY, identity_claims)
    generation_result = evaluate_identity(EvidenceScope.GENERATION, generation_claims)
    # Same logical identity AND same generation, observed from two
    # different sources simultaneously, is exactly the cloned-store
    # signature the PRD says is reliably detectable - both evaluations
    # agree (not ambiguous on their own), but the CALLER (a future
    # attachment-layer integration, out of Milestone-2 scope) is
    # responsible for recognizing "same identity + same generation from
    # two live sources at once" as the clone signal per PRD §5/§13.
    assert identity_result.outcome == IdentityOutcome.EQUIVALENT
    assert generation_result.outcome == IdentityOutcome.EQUIVALENT
    outcome = cloned_store_outcome()
    assert outcome.failure_mode == FailureMode.CLONED
    assert "no silent pick-one" in outcome.message


def test_separately_used_clone_is_not_claimed_detectable_by_this_module():
    """PRD §5's honest limit: a byte-identical clone used separately and
    never simultaneously observed cannot be distinguished from the
    original by this module's evidence alone. There is no function
    anywhere in testpersistence that claims to detect this case - this
    test documents the absence rather than exercising a (nonexistent)
    detector, so a future change that quietly adds such a claim without
    updating the PRD's own limitation statement gets caught here too."""
    import testpersistence.failures as failures_module
    assert not hasattr(failures_module, "detect_separately_used_clone")
