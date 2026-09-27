//! P0-TXN-011 restart recovery: all six classifications, each proven with a
//! purpose-built fixture (G4 handoff §20).

use guardian_core::transaction::observation::ObservationOutcome;
use guardian_core::transaction::recovery::{RecoveryClassification, RecoverySnapshot, classify};
use guardian_core::transaction::{ApplyOutcome, TransactionState};

fn snapshot(
    state: TransactionState,
    apply_outcome: Option<ApplyOutcome>,
    last_observation: Option<ObservationOutcome>,
) -> RecoverySnapshot {
    snapshot_with_dispatch_marker(state, apply_outcome, last_observation, false)
}

/// Same as [`snapshot`], but also controls the durable dispatch-start
/// marker (G4 handoff §19.1a, the disclosed Wave-1-required G4 extension
/// closing W1-REC-003/W1-VM-005) -- needed to distinguish "provider
/// dispatch definitely not entered" from "provider dispatch entered,
/// outcome not yet durably known" when `apply_outcome` is
/// `NotRecorded`/`None`.
fn snapshot_with_dispatch_marker(
    state: TransactionState,
    apply_outcome: Option<ApplyOutcome>,
    last_observation: Option<ObservationOutcome>,
    dispatch_marker: bool,
) -> RecoverySnapshot {
    RecoverySnapshot {
        state,
        apply_outcome,
        last_observation,
        dispatch_marker,
    }
}

/// "safe to resume (nonterminal, no Apply attempted yet)"
#[test]
fn safe_to_resume_when_no_apply_attempted() {
    for state in [
        TransactionState::Created,
        TransactionState::Validating,
        TransactionState::Validated,
        TransactionState::Authorizing,
        TransactionState::Authorized,
    ] {
        assert_eq!(
            classify(snapshot(state, None, None)),
            RecoveryClassification::SafeToResume
        );
    }
}

/// Crash-before-invocation: Apply-intent exists (or doesn't) but the
/// provider was provably never invoked -- still safe to resume (G4 handoff
/// §18.6/§19.1). Explicit `dispatch_marker: false` (G4 handoff §19.1a):
/// this is exactly the "crash strictly between Apply-intent and the
/// dispatch marker" case, and must retain the pre-extension semantics
/// unchanged.
#[test]
fn safe_to_resume_when_applying_but_provider_never_invoked() {
    let outcome = classify(snapshot_with_dispatch_marker(
        TransactionState::Applying,
        Some(ApplyOutcome::NotRecorded),
        None,
        false,
    ));
    assert_eq!(outcome, RecoveryClassification::SafeToResume);
    assert_ne!(outcome, RecoveryClassification::AlreadyCommitted);
}

/// Also safe to resume when there is no Apply-intent at all (`None`) --
/// distinct fixture from the `NotRecorded` case above, both provably safe.
#[test]
fn safe_to_resume_when_no_apply_intent_recorded_at_all() {
    let outcome = classify(snapshot(TransactionState::Applying, None, None));
    assert_eq!(outcome, RecoveryClassification::SafeToResume);
}

/// Known clean failure remains safe to resume, unaffected by the
/// dispatch-marker extension: the provider call durably completed with no
/// mutation, so there is nothing ambiguous left regardless of the marker.
#[test]
fn safe_to_resume_when_apply_confirmed_failure_no_mutation() {
    let outcome = classify(snapshot_with_dispatch_marker(
        TransactionState::Applying,
        Some(ApplyOutcome::ConfirmedFailureNoMutation),
        None,
        true,
    ));
    assert_eq!(outcome, RecoveryClassification::SafeToResume);
}

/// **The G4 extension's central case (W1-REC-003/W1-VM-005 fix, G4 handoff
/// §19.1a)**: the durable dispatch-start marker is set (the provider call
/// was about to be, or was, invoked) but no concrete `ApplyOutcome` was
/// ever durably recorded -- e.g. a real `kill -9` during an in-flight
/// `RestartUnit` call. This must classify as `StateAmbiguous`, never
/// `SafeToResume`: Guardian cannot know whether the external mutation
/// happened, and false ambiguity is required to be preferred over an
/// unsafe automatic replay.
#[test]
fn state_ambiguous_when_dispatch_marker_set_but_outcome_never_recorded() {
    let outcome = classify(snapshot_with_dispatch_marker(
        TransactionState::Applying,
        Some(ApplyOutcome::NotRecorded),
        None,
        true,
    ));
    assert_eq!(outcome, RecoveryClassification::StateAmbiguous);
    assert_ne!(outcome, RecoveryClassification::SafeToResume);
}

/// A stray dispatch marker on an outcome that is *not* `NotRecorded` must
/// have no effect -- the marker only disambiguates the `NotRecorded` case;
/// once a concrete outcome is durably known, that outcome alone governs.
#[test]
fn dispatch_marker_is_irrelevant_once_a_concrete_outcome_is_known() {
    assert_eq!(
        classify(snapshot_with_dispatch_marker(
            TransactionState::Applying,
            Some(ApplyOutcome::ConfirmedSuccess),
            None,
            true,
        )),
        RecoveryClassification::MustObserve
    );
    assert_eq!(
        classify(snapshot_with_dispatch_marker(
            TransactionState::Applying,
            Some(ApplyOutcome::ConfirmedFailureNoMutation),
            None,
            true,
        )),
        RecoveryClassification::SafeToResume
    );
    assert_eq!(
        classify(snapshot_with_dispatch_marker(
            TransactionState::Applying,
            Some(ApplyOutcome::PartialOrUncertainMutation),
            None,
            false,
        )),
        RecoveryClassification::StateAmbiguous
    );
}

/// Exhaustive property (requirement 6 of the G4 extension): no
/// `Applying`-state snapshot that is genuinely ambiguous about whether the
/// provider was invoked (dispatch marker set, outcome not durably known)
/// ever classifies as `SafeToResume`, for either value of the marker on
/// every `ApplyOutcome`/`Option` combination.
#[test]
fn no_ambiguous_applying_snapshot_ever_classifies_as_safe_to_resume() {
    let all_outcomes = [
        None,
        Some(ApplyOutcome::NotRecorded),
        Some(ApplyOutcome::ConfirmedSuccess),
        Some(ApplyOutcome::ConfirmedFailureNoMutation),
        Some(ApplyOutcome::PartialOrUncertainMutation),
        Some(ApplyOutcome::ResponseLostOrUnknown),
    ];
    for outcome in all_outcomes {
        for dispatch_marker in [false, true] {
            let classification = classify(snapshot_with_dispatch_marker(
                TransactionState::Applying,
                outcome,
                None,
                dispatch_marker,
            ));
            // The one condition that is genuinely ambiguous about whether
            // the provider call happened is exactly: dispatch entered
            // (marker set) and no concrete outcome recorded yet
            // (`NotRecorded`). `outcome == None` with `dispatch_marker ==
            // true` is not a reachable combination from real persisted
            // data (the marker only ever exists on an `ApplyRecord`, so no
            // record at all implies no marker either -- see
            // `PersistedTransactionRecord::from_record`) and is
            // deliberately excluded here rather than asserted against.
            let is_ambiguous =
                dispatch_marker && matches!(outcome, Some(ApplyOutcome::NotRecorded));
            if is_ambiguous {
                assert_ne!(
                    classification,
                    RecoveryClassification::SafeToResume,
                    "outcome={outcome:?} dispatch_marker={dispatch_marker} must never be SafeToResume"
                );
            }
            // `PartialOrUncertainMutation` is unconditionally ambiguous
            // regardless of the marker (it is itself the concrete durable
            // signal of an uncertain mutation).
            if matches!(outcome, Some(ApplyOutcome::PartialOrUncertainMutation)) {
                assert_eq!(classification, RecoveryClassification::StateAmbiguous);
            }
        }
    }
}

/// "must observe (Apply attempted, no Observe result recorded)"
#[test]
fn must_observe_when_apply_confirmed_success_but_not_yet_observed() {
    assert_eq!(
        classify(snapshot(
            TransactionState::Applying,
            Some(ApplyOutcome::ConfirmedSuccess),
            None
        )),
        RecoveryClassification::MustObserve
    );
}

/// "must rollback (Apply attempted, Observe failed/ambiguous, rollback not
/// yet attempted)"
#[test]
fn must_rollback_when_observation_determined_postcondition_not_met() {
    assert_eq!(
        classify(snapshot(
            TransactionState::Observing,
            Some(ApplyOutcome::ConfirmedSuccess),
            Some(ObservationOutcome::PostconditionNotMet)
        )),
        RecoveryClassification::MustRollback
    );
}

/// "already committed (Apply + Observe + Confirm all recorded successful)"
#[test]
fn already_committed_when_state_is_committed() {
    assert_eq!(
        classify(snapshot(
            TransactionState::Committed,
            Some(ApplyOutcome::ConfirmedSuccess),
            None
        )),
        RecoveryClassification::AlreadyCommitted
    );
}

/// "state ambiguous (Apply attempted, response lost, no Observe possible)"
#[test]
fn state_ambiguous_when_apply_outcome_is_partial_or_uncertain() {
    assert_eq!(
        classify(snapshot(
            TransactionState::Applying,
            Some(ApplyOutcome::PartialOrUncertainMutation),
            None
        )),
        RecoveryClassification::StateAmbiguous
    );
}

#[test]
fn state_ambiguous_when_observation_itself_was_ambiguous() {
    assert_eq!(
        classify(snapshot(
            TransactionState::Observing,
            Some(ApplyOutcome::ConfirmedSuccess),
            Some(ObservationOutcome::Ambiguous)
        )),
        RecoveryClassification::StateAmbiguous
    );
}

/// "requires human/recovery handling (... `ROLLBACK_FAILED` with no further
/// automated path)"
#[test]
fn requires_human_recovery_when_rollback_failed() {
    assert_eq!(
        classify(snapshot(
            TransactionState::RollbackFailed,
            Some(ApplyOutcome::PartialOrUncertainMutation),
            None
        )),
        RecoveryClassification::RequiresHumanRecovery
    );
}

/// Rolling-back-still-in-progress must resume rollback, never be silently
/// treated as resolved.
#[test]
fn must_rollback_when_rolling_back_was_interrupted() {
    assert_eq!(
        classify(snapshot(
            TransactionState::RollingBack,
            Some(ApplyOutcome::PartialOrUncertainMutation),
            None
        )),
        RecoveryClassification::MustRollback
    );
}

/// Lost-response case specifically: the call is believed to have completed,
/// so Observe (not a guess) is the required next step -- never silently
/// `AlreadyCommitted`.
#[test]
fn response_lost_routes_to_must_observe_not_already_committed() {
    let outcome = classify(snapshot(
        TransactionState::Applying,
        Some(ApplyOutcome::ResponseLostOrUnknown),
        None,
    ));
    assert_eq!(outcome, RecoveryClassification::MustObserve);
    assert_ne!(outcome, RecoveryClassification::AlreadyCommitted);
}
