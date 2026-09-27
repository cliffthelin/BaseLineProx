//! Restart-recovery classification (P0-TXN-011; G4 handoff §20). Six
//! distinguishable outcomes for a recovered *nonterminal* transaction --
//! not new transaction states, but the required output of the recovery
//! function that decides what must happen next.

use crate::transaction::apply::ApplyOutcome;
use crate::transaction::observation::ObservationOutcome;
use crate::transaction::state::TransactionState;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecoveryClassification {
    SafeToResume,
    MustObserve,
    MustRollback,
    AlreadyCommitted,
    StateAmbiguous,
    RequiresHumanRecovery,
}

/// Inputs available to the recovery classifier -- deliberately narrow: only
/// what is actually durable, never anything a recovering process would
/// have to guess.
#[derive(Clone, Copy, Debug)]
pub struct RecoverySnapshot {
    pub state: TransactionState,
    pub apply_outcome: Option<ApplyOutcome>,
    pub last_observation: Option<ObservationOutcome>,
    /// `true` iff the durable dispatch-start marker (G4 handoff §19.1a) was
    /// persisted for the current Apply attempt -- i.e. the provider call
    /// was about to be, or was, invoked. Distinguishes "provider dispatch
    /// definitely not entered" from "provider dispatch entered, outcome not
    /// yet durably known" when `apply_outcome` is `NotRecorded`/`None`. See
    /// [`crate::transaction::apply::ApplyRecord::dispatch_marker`].
    pub dispatch_marker: bool,
}

/// Classifies a recovered nonterminal transaction (G4 handoff §20). A
/// corrupt/unparseable persisted record never reaches this function at all
/// -- see [`crate::transaction::persistence`] -- it is classified
/// `RequiresHumanRecovery` directly at load time.
#[must_use]
pub fn classify(snapshot: RecoverySnapshot) -> RecoveryClassification {
    use TransactionState::{Applying, Observing, RollingBack};

    match snapshot.state {
        state if state.is_pre_mutation() => RecoveryClassification::SafeToResume,
        Applying => classify_applying(snapshot.apply_outcome, snapshot.dispatch_marker),
        Observing => classify_observing(snapshot.last_observation),
        RollingBack => RecoveryClassification::MustRollback,
        TransactionState::Committed => RecoveryClassification::AlreadyCommitted,
        // RollbackFailed ("an unresolved rollback with no further automated
        // path"), and defensively any other fully-resolved terminal state a
        // caller should not have passed in here at all: both fail closed to
        // the same answer rather than guessing differently for the
        // supposedly-unreachable branch.
        _ => RecoveryClassification::RequiresHumanRecovery,
    }
}

fn classify_applying(
    apply_outcome: Option<ApplyOutcome>,
    dispatch_marker: bool,
) -> RecoveryClassification {
    // Apply-intent recorded but no concrete outcome yet (or no Apply-intent
    // at all): intent alone is ambiguous about whether the provider was
    // ever invoked -- the durable dispatch marker (G4 handoff §19.1a) is
    // what disambiguates the `NotRecorded` case specifically. No marker (or
    // no intent at all): the provider call was never reached, still
    // provably safe to resume (G4 handoff §19.1: "crash before step 2").
    // Marker set: the provider call was about to be, or was, invoked, and
    // its outcome never got durably recorded -- Guardian cannot know
    // whether the external mutation happened, so this must never be
    // treated as safe to replay.
    if matches!(apply_outcome, None | Some(ApplyOutcome::NotRecorded)) && dispatch_marker {
        return RecoveryClassification::StateAmbiguous;
    }

    match apply_outcome {
        // Provably safe to resume: either no Apply-intent was ever
        // durably recorded, or intent was recorded with no dispatch marker
        // (provider call never reached), or the provider call cleanly
        // failed with no mutation (G4 handoff §19.1: "crash at/after step
        // 4, outcome durably known"). The dispatch-marker-set branch above
        // already returned for the one case where `NotRecorded` is instead
        // ambiguous.
        None | Some(ApplyOutcome::NotRecorded | ApplyOutcome::ConfirmedFailureNoMutation) => {
            RecoveryClassification::SafeToResume
        }
        // The provider call completed (or is believed to have completed --
        // ResponseLostOrUnknown, §19.1 "crash between step 4 and 5") and
        // Observe can still meaningfully answer what happened either way.
        Some(ApplyOutcome::ConfirmedSuccess | ApplyOutcome::ResponseLostOrUnknown) => {
            RecoveryClassification::MustObserve
        }
        // The provider call was in flight when the crash occurred -- whether
        // the external mutation happened is inherently uncertain from
        // Guardian's own persistence alone (§19.1, "crash during step 4").
        // Never guessed as either extreme.
        Some(ApplyOutcome::PartialOrUncertainMutation) => RecoveryClassification::StateAmbiguous,
    }
}

const fn classify_observing(
    last_observation: Option<ObservationOutcome>,
) -> RecoveryClassification {
    match last_observation {
        // No observation recorded yet, or the last one met the
        // postcondition: either way the remaining work is
        // Observe-then-Confirm, which this classification covers.
        None | Some(ObservationOutcome::PostconditionMet) => RecoveryClassification::MustObserve,
        Some(ObservationOutcome::PostconditionNotMet) => RecoveryClassification::MustRollback,
        Some(ObservationOutcome::Ambiguous) => RecoveryClassification::StateAmbiguous,
    }
}
