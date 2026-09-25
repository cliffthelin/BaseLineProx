"""Rollback-domain refusal (PRD §11, acceptance case 9) - the direct
proof obligation for the Milestone-2 blocker: a snapshot restore must
never resurrect a grant the CURRENT, non-rollback ledger already shows
revoked."""
import pytest

from testpersistence.manifest import TEST_MANIFEST_DOMAIN, AuthorityLedger, derive_manifest_key
from testpersistence.snapshot import (
    RollbackAuthorityViolation, SnapshotRestoreProposal, apply_restore,
    validate_restore_against_current_ledger,
)

BASE_SECRET = b"synthetic-base-secret-not-a-real-key-material"


def _ledger():
    key = derive_manifest_key(BASE_SECRET, TEST_MANIFEST_DOMAIN)
    return AuthorityLedger(key=key, domain=TEST_MANIFEST_DOMAIN)


def test_restore_that_does_not_touch_revoked_grants_is_allowed():
    proposal = SnapshotRestoreProposal(target_generation=1,
                                        restored_grant_ids=frozenset({"TestGrant-002"}))
    validate_restore_against_current_ledger(proposal, currently_revoked_grant_ids=frozenset({"TestGrant-001"}))


def test_restore_that_would_resurrect_a_currently_revoked_grant_is_refused():
    proposal = SnapshotRestoreProposal(target_generation=1,
                                        restored_grant_ids=frozenset({"TestGrant-001"}))
    with pytest.raises(RollbackAuthorityViolation):
        validate_restore_against_current_ledger(
            proposal, currently_revoked_grant_ids=frozenset({"TestGrant-001"}))


def test_acceptance_case_9_end_to_end():
    """Acceptance case 9 (PRD §14): restoring a snapshot taken before a
    revocation must not resurrect access, and the current, live ledger -
    never itself part of the restored snapshot - is what catches it."""
    ledger = _ledger()
    ledger.append("grant_issued", {"grant_id": "TestGrant-001"})
    # snapshot taken here, at generation 1, grant still active - the
    # snapshot's own copy of "restored_grant_ids" reflects that.
    snapshot_generation = 1
    ledger.append("grant_revoked", {"grant_id": "TestGrant-001"})  # revocation AFTER the snapshot

    currently_revoked = {"TestGrant-001"}
    proposal = SnapshotRestoreProposal(target_generation=snapshot_generation,
                                        restored_grant_ids=frozenset({"TestGrant-001"}))

    with pytest.raises(RollbackAuthorityViolation):
        apply_restore(proposal, frozenset(currently_revoked), ledger)

    # The refused restore must not have been recorded as if it succeeded.
    assert not any(e.event == "snapshot_restored" for e in ledger.entries)
    assert ledger.verify_chain()


def test_successful_restore_is_recorded_as_a_new_forward_moving_event_not_a_history_edit():
    ledger = _ledger()
    ledger.append("grant_issued", {"grant_id": "TestGrant-002"})
    proposal = SnapshotRestoreProposal(target_generation=1,
                                        restored_grant_ids=frozenset({"TestGrant-002"}))
    entries_before = len(ledger.entries)

    apply_restore(proposal, currently_revoked_grant_ids=frozenset(), ledger=ledger)

    assert len(ledger.entries) == entries_before + 1
    assert ledger.entries[-1].event == "snapshot_restored"
    assert ledger.verify_chain()
