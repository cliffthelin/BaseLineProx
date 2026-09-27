//! `TransactionRecord` (TDD contract §14.1; G4 handoff §4.2) and its
//! supporting typed sub-records. Every field reuses an existing G1/G3 type
//! where one already exists for the concept -- `risk_class` is
//! [`crate::risk::Risk`], `arbitration_result` is the real
//! [`crate::arbitration::ArbitrationDecision`], `provider_id`/
//! `capability_id`/`incident_ids` reuse `guardian_provider_api` unchanged.

use guardian_provider_api::{CapabilityId, IncidentId, ProviderId};

use crate::arbitration::{ArbitrationDecision, RollbackKind};
use crate::authorization::AuthorizationOutcome;
use crate::risk::Risk;
use crate::transaction::apply::ApplyRecord;
use crate::transaction::id::TransactionId;
use crate::transaction::observation::{ObservationOutcome, ObservationPolicy};
use crate::transaction::rollback::RollbackOutcome;
use crate::transaction::state::TransactionState;

/// A narrow, enumerable action classification -- deliberately not a free
/// string or opaque payload (G4 handoff, `TransactionRecord.action_type`).
/// G4 has exactly one fixture-scoped action shape; a future gate adding
/// real actions extends this enum, it does not turn it into a generic
/// carrier.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ActionType {
    BoundedWrite,
}

/// `Validate`'s typed result -- validation is not authorization (G4
/// handoff §12); this is a distinct field/type from `authorization_outcome`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ValidationOutcome {
    Passed,
    Failed(String),
}

/// The `Snapshot` step's captured evidence (G4 handoff §11; TDD contract
/// §14.1's `pre_state`). Must carry enough to support later rollback and
/// TOCTOU rechecks -- in particular the real `ArbitrationDecision`
/// (including its `revision`), not a paraphrase.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Snapshot {
    pub transaction_id: TransactionId,
    pub capability_id: CapabilityId,
    pub provider_id: ProviderId,
    pub arbitration_result: ArbitrationDecision,
    pub prior_resource_state: String,
    pub rollback_kind: RollbackKind,
    pub risk_class: Risk,
    pub captured_at: u64,
}

/// TDD contract §14.1's canonical transaction record, in-memory shape.
#[derive(Clone, Debug, PartialEq)]
pub struct TransactionRecord {
    pub transaction_id: TransactionId,
    pub idempotency_key: String,
    pub action_type: ActionType,
    pub risk_class: Risk,
    pub initiating_bus_name: Option<String>,
    pub initiating_session: Option<String>,
    pub provider_id: ProviderId,
    pub capability_id: CapabilityId,

    pub created_at: u64,
    pub deadline: Option<u64>,

    pub state: TransactionState,

    pub pre_state: Option<Snapshot>,
    pub validation_results: Option<ValidationOutcome>,
    pub arbitration_result: Option<ArbitrationDecision>,
    pub authorization_outcome: Option<AuthorizationOutcome>,
    pub authorization_error: Option<String>,

    pub requested_change: guardian_provider_api::ActionRequest,
    pub provider_request: Option<String>,
    pub provider_response: Option<String>,

    pub observation_policy: Option<ObservationPolicy>,
    pub observations: Vec<ObservationOutcome>,

    pub apply_record: Option<ApplyRecord>,

    pub commit_result: Option<bool>,
    pub rollback_result: Option<RollbackOutcome>,

    pub incident_ids: Vec<IncidentId>,

    /// Typed evidence of a cancellation *request* -- orthogonal to the
    /// state machine, exactly like `rollback_result` (G4 handoff §17.4).
    /// Never itself causes a transition; a mutation in flight or a
    /// rollback in progress must reconcile before this can be honored.
    pub cancellation_requested: bool,
    /// Same discipline as `cancellation_requested`, for a deadline having
    /// elapsed (G4 handoff §17.4).
    pub deadline_expired: bool,
}

impl TransactionRecord {
    /// Attempts the named transition, enforcing terminal immutability and
    /// the legal-transition graph (P0-TXN-008). The only place `state` is
    /// ever mutated -- there is no bare public setter.
    ///
    /// # Errors
    ///
    /// Returns [`crate::transaction::state::IllegalTransition`] if the
    /// transition is not legal from the record's current state.
    pub fn transition_to(
        &mut self,
        to: TransactionState,
    ) -> Result<(), crate::transaction::state::IllegalTransition> {
        self.state = crate::transaction::state::transition(self.state, to)?;
        Ok(())
    }
}
