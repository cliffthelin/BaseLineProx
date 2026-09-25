"""Snapshot/restore semantics (PRD §11) - implements the Milestone-2
decision required by §16: a **non-rollback authority domain**. The
authority ledger's revocation records live in a namespace that
snapshot restore never rolls back, only ever appends to (see
manifest.AuthorityLedger, which is never itself part of a restore
proposal below). A restore proposal is validated against the CURRENT,
live ledger - never a snapshotted copy of it - so a revoked grant can
never silently return through restoration. This directly proves PRD
acceptance case 9.

(The PRD's other option, an independent monotonic anchor tied to
Baseline's own control-plane state, was not chosen for Milestone 2:
the non-rollback domain is simpler to state and verify in pure code,
since it needs no external clock/counter source. A future milestone
may still add a monotonic anchor as defense in depth; that is not
required for this proof.)"""
import dataclasses


@dataclasses.dataclass(frozen=True)
class SnapshotRestoreProposal:
    """A proposal to restore person/application namespaces to a prior
    snapshot generation. Deliberately does NOT carry a restored
    authority_ledger - the current, live ledger (never rolled back) is
    what apply_restore checks the proposal against."""
    target_generation: int
    restored_grant_ids: frozenset


class RollbackAuthorityViolation(Exception):
    pass


def validate_restore_against_current_ledger(proposal: SnapshotRestoreProposal,
                                             currently_revoked_grant_ids: frozenset) -> None:
    """Refuses a restore that would resurrect any grant the CURRENT
    (non-rollback) ledger already shows revoked. Raises rather than
    silently dropping just the offending grant, so the caller sees
    exactly why the whole restore was blocked."""
    resurrected = proposal.restored_grant_ids & currently_revoked_grant_ids
    if resurrected:
        raise RollbackAuthorityViolation(
            f"restore to generation {proposal.target_generation} would resurrect "
            f"{len(resurrected)} grant(s) already revoked in the current, "
            f"non-rollback authority ledger - refusing")


def apply_restore(proposal: SnapshotRestoreProposal, currently_revoked_grant_ids: frozenset,
                   ledger) -> None:
    """Validates, then records the restore itself as a new
    forward-moving ledger event (PRD §11) - never an edit to ledger
    history in place."""
    validate_restore_against_current_ledger(proposal, currently_revoked_grant_ids)
    ledger.append("snapshot_restored",
                   {"target_generation": proposal.target_generation,
                    "restored_grant_ids": sorted(proposal.restored_grant_ids)})
