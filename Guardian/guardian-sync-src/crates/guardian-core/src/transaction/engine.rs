//! The G4 transaction engine's step functions (Snapshot / Validate /
//! Authorize / Apply / Observe / Confirm / Rollback / cancellation), plus
//! the immediate-pre-`Apply` TOCTOU recheck. Every step is a free function
//! operating on `&mut TransactionRecord` -- there is no hidden mutable
//! engine object, and `TransactionRecord::transition_to` is the only way
//! state ever changes, so every transition here is subject to the same
//! legal-transition/terminal-immutability check used everywhere else.

use std::fmt;
use std::path::Path;

use guardian_provider_api::{
    ActionRequest, CapabilityRecord, Knowledge, MutableCapabilityAdapter,
    ObservationExpectation as RawObservationExpectation, PrivilegeRequirement,
    StateSnapshot as RawStateSnapshot, Unsupported,
};

use crate::arbitration::{ArbitrationInput, arbitrate};
use crate::authorization::{AuthorizationOutcome, AuthorizationRequest, Authorizer, PolkitAction};
use crate::identity::CallerIdentity;
use crate::transaction::apply::{ApplyOutcome, ApplyRecord};
use crate::transaction::arbitration_source::ArbitrationStateSource;
use crate::transaction::observation::ObservationOutcome;
use crate::transaction::persistence::{PersistedTransactionRecord, persist};
use crate::transaction::record::{Snapshot, TransactionRecord, ValidationOutcome};
use crate::transaction::rollback::RollbackOutcome;
use crate::transaction::state::{IllegalTransition, TransactionState};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EngineError {
    Illegal(IllegalTransition),
    SnapshotFailed,
    ValidationFailed(String),
    AuthorizationDenied,
    StaleRevision,
    ProviderVanished,
    MustObserveBeforeRetry,
    ObservationInconclusive,
    MissingSnapshot,
    /// `Apply` was called on a record whose state is not a legal Apply
    /// entry point (audit Finding 1) -- returned *before* `provider.apply`
    /// is ever reached, never discovered afterward via an illegal-
    /// transition error.
    ApplyPreconditionNotMet(TransactionState),
    /// The durable Apply-intent/Apply-outcome persist call itself failed
    /// (audit Finding 3, G4 handoff §19.1). When this occurs *before* the
    /// provider is invoked, the provider call is skipped entirely.
    PersistenceFailed(String),
}

impl fmt::Display for EngineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Illegal(inner) => write!(formatter, "{inner}"),
            Self::SnapshotFailed => formatter.write_str("snapshot failed; apply is blocked"),
            Self::ValidationFailed(reason) => write!(formatter, "validation failed: {reason}"),
            Self::AuthorizationDenied => formatter.write_str("authorization denied"),
            Self::StaleRevision => {
                formatter.write_str("arbitration revision changed; apply is blocked")
            }
            Self::ProviderVanished => {
                formatter.write_str("provider identity changed since snapshot")
            }
            Self::MustObserveBeforeRetry => {
                formatter.write_str("apply outcome unknown; observe before retrying")
            }
            Self::ObservationInconclusive => {
                formatter.write_str("no conclusive observation recorded yet")
            }
            Self::MissingSnapshot => formatter.write_str("no snapshot recorded"),
            Self::ApplyPreconditionNotMet(state) => {
                write!(
                    formatter,
                    "apply is not a legal entry point from state {state}"
                )
            }
            Self::PersistenceFailed(reason) => {
                write!(formatter, "durable persistence failed: {reason}")
            }
        }
    }
}

impl std::error::Error for EngineError {}

impl From<IllegalTransition> for EngineError {
    fn from(value: IllegalTransition) -> Self {
        Self::Illegal(value)
    }
}

fn arbitration_input_for(
    record: &TransactionRecord,
    state_source: &impl ArbitrationStateSource,
) -> ArbitrationInput {
    ArbitrationInput {
        capability_id: record.capability_id.clone(),
        candidates: state_source.current_candidates(&record.capability_id),
        write_requested: true,
        risk_class: record.risk_class,
        revision: state_source.current_revision(&record.capability_id),
        external_writer_present: false,
    }
}

/// The `Snapshot` step (G4 handoff §11). Captures a real
/// `ArbitrationDecision` (via the `ArbitrationStateSource`, never a
/// caller-supplied revision) and the provider's own reported prior state.
/// Snapshot failure prevents `Apply` -- there is no path from a failed
/// snapshot to `APPLYING`.
///
/// # Errors
///
/// Returns [`EngineError::SnapshotFailed`] if the fixture provider cannot
/// report its current state, or [`EngineError::Illegal`] on a state-machine
/// violation.
pub fn snapshot<P: MutableCapabilityAdapter>(
    record: &mut TransactionRecord,
    provider: &P,
    state_source: &impl ArbitrationStateSource,
    clock: u64,
) -> Result<(), EngineError> {
    let decision = arbitrate(&arbitration_input_for(record, state_source));
    let prior_resource_state = provider
        .inspect()
        .map_err(|Unsupported| EngineError::SnapshotFailed)?
        .0;

    record.pre_state = Some(Snapshot {
        transaction_id: record.transaction_id.clone(),
        capability_id: record.capability_id.clone(),
        provider_id: record.provider_id.clone(),
        rollback_kind: decision.rollback_kind,
        risk_class: record.risk_class,
        arbitration_result: decision,
        prior_resource_state,
        captured_at: clock,
    });
    Ok(())
}

/// The `Validate` step (G4 handoff §9/§12). Not authorization -- confirms
/// transaction assumptions remain true, including the two G3-carried-
/// forward fail-closed checks: `privilege_requirement == Unknown` (NB-1,
/// §6) and `authorization_ownership == Unknown`, both rejected here before
/// `Authorize` is ever reached.
///
/// # Errors
///
/// Returns [`EngineError::ValidationFailed`] (record transitions to
/// `Rejected`) or [`EngineError::MissingSnapshot`]/[`EngineError::Illegal`].
pub fn validate(
    record: &mut TransactionRecord,
    capability: &CapabilityRecord,
    state_source: &impl ArbitrationStateSource,
) -> Result<(), EngineError> {
    record.transition_to(TransactionState::Validating)?;

    let reject = |record: &mut TransactionRecord, reason: String| -> Result<(), EngineError> {
        record.validation_results = Some(ValidationOutcome::Failed(reason.clone()));
        record.transition_to(TransactionState::Rejected)?;
        Err(EngineError::ValidationFailed(reason))
    };

    if capability.availability == guardian_provider_api::Availability::Unavailable {
        return reject(record, "capability is unavailable".to_owned());
    }
    if capability.provider_id != record.provider_id {
        return reject(
            record,
            "provider identity changed since snapshot (P0-TXN-010)".to_owned(),
        );
    }
    // NB-1 (§6): unknown privilege/access blocks Apply -- checked before
    // Authorize, independent of authorization_ownership's value.
    if capability.privilege_requirement == PrivilegeRequirement::Unknown {
        return reject(record, "privilege_requirement is Unknown (NB-1)".to_owned());
    }
    if matches!(capability.authorization_ownership, Knowledge::Unknown) {
        return reject(record, "authorization_ownership is Unknown".to_owned());
    }

    let decision = arbitrate(&arbitration_input_for(record, state_source));
    let Some(pre_state) = record.pre_state.as_ref() else {
        return Err(EngineError::MissingSnapshot);
    };
    if decision.revision != pre_state.arbitration_result.revision {
        return reject(
            record,
            "arbitration revision changed since snapshot".to_owned(),
        );
    }
    if !decision.write_permitted {
        return reject(
            record,
            format!("write not permitted: {}", decision.decision_reason),
        );
    }

    record.arbitration_result = Some(decision);
    record.validation_results = Some(ValidationOutcome::Passed);
    record.transition_to(TransactionState::Validated)?;
    Ok(())
}

/// Immediate-pre-`Apply` TOCTOU recheck (G4 handoff §7.3/§10) -- re-derives
/// `revision` from the authoritative `ArbitrationStateSource` (never reuses
/// the `Validate`-time value) and blocks `Apply` if it has changed.
///
/// # Errors
///
/// Returns [`EngineError::StaleRevision`] or [`EngineError::MissingSnapshot`].
pub fn revalidate_immediately_before_apply(
    record: &TransactionRecord,
    state_source: &impl ArbitrationStateSource,
) -> Result<(), EngineError> {
    let pre_state = record
        .pre_state
        .as_ref()
        .ok_or(EngineError::MissingSnapshot)?;
    let fresh_revision = state_source.current_revision(&record.capability_id);
    if fresh_revision != pre_state.arbitration_result.revision {
        return Err(EngineError::StaleRevision);
    }
    Ok(())
}

/// The `Authorize` step (G4 handoff §5/§13). Coordinates a request to a
/// real [`Authorizer`] and records the outcome -- never reimplements or
/// bypasses it. Preserves G1/G2 ordering: strictly before `Apply`.
///
/// # Errors
///
/// Returns [`EngineError::AuthorizationDenied`] (record transitions to
/// `Rejected`) on denial or on an [`crate::authorization::AuthorizationError`]
/// infrastructure failure -- the distinguishing detail survives in
/// `authorization_error`, but neither outcome permits `Apply`.
pub async fn authorize<A: Authorizer>(
    record: &mut TransactionRecord,
    authorizer: &A,
    subject: CallerIdentity,
    action: PolkitAction,
    interactive: bool,
) -> Result<(), EngineError> {
    record.transition_to(TransactionState::Authorizing)?;
    let request = AuthorizationRequest::new(subject, action, interactive);
    match authorizer.authorize(&request).await {
        Ok(AuthorizationOutcome::Authorized) => {
            record.authorization_outcome = Some(AuthorizationOutcome::Authorized);
            record.transition_to(TransactionState::Authorized)?;
            Ok(())
        }
        Ok(other) => {
            record.authorization_outcome = Some(other);
            record.transition_to(TransactionState::Rejected)?;
            Err(EngineError::AuthorizationDenied)
        }
        Err(error) => {
            record.authorization_error = Some(format!("{error:?}"));
            record.transition_to(TransactionState::Rejected)?;
            Err(EngineError::AuthorizationDenied)
        }
    }
}

fn parse_apply_payload(raw: &guardian_provider_api::ApplyOutcome) -> ApplyOutcome {
    raw.0
        .parse()
        .unwrap_or(ApplyOutcome::PartialOrUncertainMutation)
}

/// The `Apply` step (G4 handoff §14/§18), idempotency-aware (P0-TXN-009).
/// A duplicate `idempotency_key` whose durable outcome is already known
/// never re-invokes the provider; an outcome that is merely unknown
/// (§18.3) is refused with [`EngineError::MustObserveBeforeRetry`] rather
/// than silently re-applying or fabricating success.
///
/// **Entry precondition (audit Finding 1)**: `provider.apply` is reachable
/// only from `Authorized` (a fresh attempt), from `Applying` with an
/// existing `apply_record` (a legitimate in-flight retry -- e.g. a prior
/// durable-persistence failure that occurred before the provider was ever
/// called), or from `Observing` with a durably-known `ConfirmedSuccess`
/// (a pure idempotent no-op for a duplicate client request). Every other
/// state -- including every pre-Authorize state and every terminal state
/// such as `Rejected`/`Failed`/`Committed` -- is rejected immediately with
/// [`EngineError::ApplyPreconditionNotMet`], *before* `provider.apply` is
/// ever reached. This is a hard gate at the mutation boundary itself, not
/// a check that runs after the fact via an illegal-transition error.
///
/// **TOCTOU recheck (audit Finding 2)**: the immediate-pre-Apply revision
/// recheck ([`revalidate_immediately_before_apply`]) is folded directly
/// into this function's own entry path, unconditionally -- so no caller,
/// including any future recovery/resume orchestration built on top of
/// [`crate::transaction::recovery::classify`], can reach the provider call
/// while skipping it, regardless of how this record arrived at a
/// nominally-Authorized/in-flight state (e.g. after being reconstructed
/// from persisted historical state whose arbitration data may since have
/// changed).
///
/// **Durable Apply-intent (audit Finding 3, G4 handoff §19.1)**: the
/// Apply-intent record is durably persisted (via
/// [`crate::transaction::persistence::persist`], which itself performs a
/// real fsync/atomic-rename durability barrier) *before* `provider.apply`
/// is invoked. If that persist call fails, `provider.apply` is not called
/// at all and [`EngineError::PersistenceFailed`] is returned. The
/// Apply-outcome is durably persisted again immediately after the
/// provider call resolves.
///
/// # Errors
///
/// See variants above; [`EngineError::MustObserveBeforeRetry`] specifically
/// signals the caller must call [`observe`] before deciding anything
/// further.
pub fn apply<P: MutableCapabilityAdapter>(
    record: &mut TransactionRecord,
    provider: &P,
    state_source: &impl ArbitrationStateSource,
    persist_dir: &Path,
    clock: u64,
) -> Result<(), EngineError> {
    let existing_outcome = record
        .apply_record
        .as_ref()
        .map(|existing| existing.outcome);
    let entry_permitted = matches!(
        (record.state, existing_outcome),
        (TransactionState::Authorized, _)
            | (TransactionState::Applying, Some(_))
            | (
                TransactionState::Observing,
                Some(ApplyOutcome::ConfirmedSuccess)
            )
    );
    if !entry_permitted {
        return Err(EngineError::ApplyPreconditionNotMet(record.state));
    }

    // Immediate-pre-Apply TOCTOU recheck -- enforced unconditionally as
    // part of Apply's own entry path (see doc comment above); never a
    // separate step a caller could forget or skip.
    revalidate_immediately_before_apply(record, state_source)?;

    if record.state == TransactionState::Authorized {
        record.transition_to(TransactionState::Applying)?;
    }

    if let Some(existing) = &record.apply_record {
        match existing.outcome {
            ApplyOutcome::ConfirmedSuccess | ApplyOutcome::ConfirmedFailureNoMutation => {
                return Ok(());
            }
            ApplyOutcome::PartialOrUncertainMutation | ApplyOutcome::ResponseLostOrUnknown => {
                return Err(EngineError::MustObserveBeforeRetry);
            }
            // Defense in depth (G4 handoff §19.1a): a `NotRecorded` outcome
            // with the dispatch marker already set means a prior attempt's
            // provider call may have escaped before its outcome was
            // durably recorded. `recovery::classify` must never route such
            // a record back into `apply` as `SafeToResume` in the first
            // place -- but `apply` itself never trusts that alone and
            // refuses to re-invoke the provider here too.
            ApplyOutcome::NotRecorded if existing.dispatch_marker => {
                return Err(EngineError::MustObserveBeforeRetry);
            }
            ApplyOutcome::NotRecorded => {}
        }
    } else {
        record.apply_record = Some(ApplyRecord::intent_only(
            record.idempotency_key.clone(),
            clock,
        ));
    }

    // Durable Apply-intent (§19.1 steps 2-3): a real persist call, with a
    // real durability barrier inside `persist` itself, executed *before*
    // the provider is ever invoked. Persistence failure here means the
    // provider MUST NOT be called.
    persist(
        persist_dir,
        &PersistedTransactionRecord::from_record(record),
    )
    .map_err(|error| EngineError::PersistenceFailed(error.to_string()))?;

    // Durable dispatch-start marker (§19.1a, disclosed Wave-1-required G4
    // extension): persisted, with the same real durability barrier, in the
    // narrow window strictly between Apply-intent and the provider call
    // itself. This is what lets recovery distinguish "provider dispatch
    // definitely not entered" (no marker) from "provider dispatch entered,
    // outcome not yet durably known" (marker set, outcome still
    // `NotRecorded`) -- both of which otherwise look identical on reload.
    // Persistence failure here means the provider MUST NOT be called,
    // exactly like the Apply-intent persist above.
    if let Some(apply_record) = record.apply_record.as_mut() {
        apply_record.dispatch_marker = true;
    }
    persist(
        persist_dir,
        &PersistedTransactionRecord::from_record(record),
    )
    .map_err(|error| EngineError::PersistenceFailed(error.to_string()))?;

    let action = ActionRequest(record.idempotency_key.clone());
    let outcome = match provider.apply(&action) {
        Ok(raw) => parse_apply_payload(&raw),
        Err(Unsupported) => ApplyOutcome::ConfirmedFailureNoMutation,
    };
    if let Some(apply_record) = record.apply_record.as_mut() {
        apply_record.outcome = outcome;
    }

    match outcome {
        ApplyOutcome::ConfirmedSuccess => record.transition_to(TransactionState::Observing)?,
        ApplyOutcome::ConfirmedFailureNoMutation => {
            record.transition_to(TransactionState::Failed)?;
        }
        ApplyOutcome::PartialOrUncertainMutation => {
            record.transition_to(TransactionState::RollingBack)?;
        }
        ApplyOutcome::NotRecorded | ApplyOutcome::ResponseLostOrUnknown => {}
    }

    // Durable Apply-outcome (§19.1 step 5).
    persist(
        persist_dir,
        &PersistedTransactionRecord::from_record(record),
    )
    .map_err(|error| EngineError::PersistenceFailed(error.to_string()))?;

    Ok(())
}

/// Simulates a durably-recorded response loss for the *current* apply
/// attempt -- test-only affordance for P0-TXN-009: the provider call
/// itself already happened (see [`apply`]'s real invocation), this call
/// only overwrites what was *durably recorded* about its outcome, exactly
/// modeling "the process crashed after invoking the provider but before
/// persisting the result" (G4 handoff §19.1, crash between step 4 and 5).
///
/// Also resets `state` back to `Applying` when it had already advanced to
/// `Observing`: `ResponseLostOrUnknown` never legitimately coexists with a
/// state that has already advanced past `Applying` -- a real crash at this
/// boundary means the in-memory advancement to `Observing` itself would
/// not exist on reload (only the durably-fsynced Apply-intent record
/// would), so this directly models what a genuine restart would show,
/// rather than a state combination `apply`'s own entry gate would never
/// legitimately produce.
pub fn simulate_response_lost(record: &mut TransactionRecord) {
    if let Some(existing) = record.apply_record.as_mut() {
        existing.outcome = ApplyOutcome::ResponseLostOrUnknown;
    }
    if record.state == TransactionState::Observing {
        record.state = TransactionState::Applying;
    }
}

fn parse_observation_payload(
    raw: &guardian_provider_api::ObservationOutcome,
) -> ObservationOutcome {
    match raw.0.as_str() {
        "postcondition_met" => ObservationOutcome::PostconditionMet,
        "postcondition_not_met" => ObservationOutcome::PostconditionNotMet,
        _ => ObservationOutcome::Ambiguous,
    }
}

/// The `Observe` step (G4 handoff §15). "A provider returning 'method call
/// succeeded' MUST NOT automatically mean the transaction succeeded" -- this
/// is a genuinely separate call/result from `apply`'s.
///
/// # Errors
///
/// Returns [`EngineError::Illegal`] on a state-machine violation. Does not
/// itself transition on `Ambiguous` -- callers must not treat an
/// inconclusive observation as either success or failure.
pub fn observe<P: MutableCapabilityAdapter>(
    record: &mut TransactionRecord,
    provider: &P,
) -> Result<ObservationOutcome, EngineError> {
    if record.state == TransactionState::Applying {
        record.transition_to(TransactionState::Observing)?;
    }
    let expectation = RawObservationExpectation(record.idempotency_key.clone());
    let outcome = match provider.observe(&expectation) {
        Ok(raw) => parse_observation_payload(&raw),
        Err(Unsupported) => ObservationOutcome::Ambiguous,
    };
    record.observations.push(outcome);
    Ok(outcome)
}

/// The `Confirm` step (G4 handoff §16). Keeps "provider call succeeded"
/// (`ApplyOutcome::ConfirmedSuccess`) structurally distinct from "desired
/// state confirmed" (this function's own outcome).
///
/// # Errors
///
/// Returns [`EngineError::ObservationInconclusive`] if the last recorded
/// observation was `Ambiguous` or none was recorded -- confirmation must
/// not guess.
pub fn confirm(record: &mut TransactionRecord) -> Result<(), EngineError> {
    match record.observations.last().copied() {
        Some(ObservationOutcome::PostconditionMet) => {
            record.commit_result = Some(true);
            record.transition_to(TransactionState::Committed)?;
            Ok(())
        }
        Some(ObservationOutcome::PostconditionNotMet) => {
            record.commit_result = Some(false);
            record.transition_to(TransactionState::RollingBack)?;
            Ok(())
        }
        Some(ObservationOutcome::Ambiguous) | None => Err(EngineError::ObservationInconclusive),
    }
}

fn parse_rollback_payload(raw: &guardian_provider_api::RollbackOutcome) -> RollbackOutcome {
    match raw.0.as_str() {
        "confirmed_restored" => RollbackOutcome::ConfirmedRestored,
        "confirmed_failed" => RollbackOutcome::ConfirmedFailed,
        _ => RollbackOutcome::AttemptedUnconfirmed,
    }
}

/// The `Rollback` step (G4 handoff §17). Implements the fail-closed
/// `RollbackOutcome` mapping (§17.2) -- an unconfirmed `BestEffort` attempt
/// reaches `ROLLBACK_FAILED`, never `ROLLED_BACK`, with the finer evidence
/// preserved in `rollback_result`.
///
/// # Errors
///
/// Returns [`EngineError::Illegal`] on a state-machine violation.
pub fn rollback<P: MutableCapabilityAdapter>(
    record: &mut TransactionRecord,
    provider: &P,
    rollback_kind: crate::arbitration::RollbackKind,
) -> Result<(), EngineError> {
    if record.state == TransactionState::Applying || record.state == TransactionState::Observing {
        record.transition_to(TransactionState::RollingBack)?;
    }

    let outcome = if rollback_kind == crate::arbitration::RollbackKind::None {
        RollbackOutcome::NotSupported
    } else {
        let snapshot_payload = RawStateSnapshot(record.idempotency_key.clone());
        match provider.rollback(&snapshot_payload) {
            Ok(raw) => parse_rollback_payload(&raw),
            Err(Unsupported) => RollbackOutcome::NotSupported,
        }
    };

    record.rollback_result = Some(outcome);
    record.transition_to(outcome.terminal_state())?;
    Ok(())
}

/// A cancellation *request* (G4 handoff §17.4). Safe to honor directly only
/// pre-mutation; while `APPLYING`/`OBSERVING`/`ROLLING_BACK`, the request is
/// durably recorded as typed evidence and the transaction continues through
/// its governed path -- this function never itself causes `APPLYING` or
/// `ROLLING_BACK` to jump to `CANCELLED`.
///
/// # Errors
///
/// Returns [`EngineError::Illegal`] only if called on an already-terminal
/// record.
pub fn request_cancellation(record: &mut TransactionRecord) -> Result<(), EngineError> {
    if record.state.is_terminal() {
        return Err(EngineError::Illegal(IllegalTransition {
            from: record.state,
            to: TransactionState::Cancelled,
        }));
    }
    if record.state.is_pre_mutation() {
        record.transition_to(TransactionState::Cancelled)?;
    } else {
        record.cancellation_requested = true;
    }
    Ok(())
}

/// A deadline-expiry *request* -- identical discipline to
/// [`request_cancellation`] (G4 handoff §17.4).
///
/// # Errors
///
/// Returns [`EngineError::Illegal`] only if called on an already-terminal
/// record.
pub fn request_expiry(record: &mut TransactionRecord) -> Result<(), EngineError> {
    if record.state.is_terminal() {
        return Err(EngineError::Illegal(IllegalTransition {
            from: record.state,
            to: TransactionState::Expired,
        }));
    }
    if record.state.is_pre_mutation() {
        record.transition_to(TransactionState::Expired)?;
    } else {
        record.deadline_expired = true;
    }
    Ok(())
}
