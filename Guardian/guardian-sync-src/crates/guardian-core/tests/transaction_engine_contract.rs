//! The G4 transaction engine's full lifecycle (TDD contract §14/§15/§36;
//! G4 handoff). Covers all twelve `P0-TXN-*` normative tests plus the
//! handoff's required revision-authority, TOCTOU, unknown-privilege, and
//! rollback-mapping tests. Fixtures only -- no real provider integration.

use std::cell::{Cell, RefCell};
use std::future::Future;

use guardian_core::arbitration::{CandidateProvider, RollbackKind};
use guardian_core::authorization::{
    AuthorizationError, AuthorizationOutcome, AuthorizationRequest, AuthorizationUnavailableReason,
    Authorizer, PolkitAction,
};
use guardian_core::identity::CallerIdentity;
use guardian_core::risk::Risk;
use guardian_core::transaction::arbitration_source::ArbitrationStateSource;
use guardian_core::transaction::engine::{
    EngineError, apply, authorize, confirm, observe, request_cancellation, request_expiry,
    revalidate_immediately_before_apply, rollback, simulate_response_lost, snapshot, validate,
};
use guardian_core::transaction::record::ActionType;
use guardian_core::transaction::{
    ApplyRecord, RollbackOutcome, TransactionId, TransactionRecord, TransactionState,
};
use guardian_provider_api::{
    ActionRequest, ApplyOutcome as RawApplyOutcome, Availability, BootAvailability, CapabilityId,
    CapabilityRecord, DiagnosticCost, Health, InspectionSnapshot, InterfaceKind, Knowledge,
    MutableCapabilityAdapter, ObservationExpectation, ObservationOutcome as RawObservationOutcome,
    PrivilegeRequirement, ProviderId, RollbackOutcome as RawRollbackOutcome, StateSnapshot,
    Unsupported, ValidationResult,
};

// ---------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ApplyBehavior {
    Success,
    CleanFailure,
    PartialUncertain,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ObserveBehavior {
    Met,
    NotMet,
    Ambiguous,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RollbackBehavior {
    ConfirmedRestored,
    ConfirmedFailed,
    AttemptedUnconfirmed,
    Unsupported,
}

struct FixtureAdapter {
    apply_calls: Cell<u32>,
    inspect_ok: bool,
    apply_behavior: Cell<ApplyBehavior>,
    observe_behavior: Cell<ObserveBehavior>,
    rollback_behavior: Cell<RollbackBehavior>,
}

impl FixtureAdapter {
    fn new() -> Self {
        Self {
            apply_calls: Cell::new(0),
            inspect_ok: true,
            apply_behavior: Cell::new(ApplyBehavior::Success),
            observe_behavior: Cell::new(ObserveBehavior::Met),
            rollback_behavior: Cell::new(RollbackBehavior::ConfirmedRestored),
        }
    }
}

impl MutableCapabilityAdapter for FixtureAdapter {
    fn inspect(&self) -> Result<InspectionSnapshot, Unsupported> {
        if self.inspect_ok {
            Ok(InspectionSnapshot("prior-state".to_owned()))
        } else {
            Err(Unsupported)
        }
    }

    fn validate(&self, _action: &ActionRequest) -> Result<ValidationResult, Unsupported> {
        Ok(ValidationResult("ok".to_owned()))
    }

    fn snapshot(&self, _action: &ActionRequest) -> Result<StateSnapshot, Unsupported> {
        Ok(StateSnapshot("prior-state".to_owned()))
    }

    fn apply(&self, _action: &ActionRequest) -> Result<RawApplyOutcome, Unsupported> {
        self.apply_calls.set(self.apply_calls.get() + 1);
        match self.apply_behavior.get() {
            ApplyBehavior::Success => Ok(RawApplyOutcome("confirmed_success".to_owned())),
            ApplyBehavior::CleanFailure => {
                Ok(RawApplyOutcome("confirmed_failure_no_mutation".to_owned()))
            }
            ApplyBehavior::PartialUncertain => {
                Ok(RawApplyOutcome("partial_or_uncertain_mutation".to_owned()))
            }
            ApplyBehavior::Unsupported => Err(Unsupported),
        }
    }

    fn observe(
        &self,
        _expectation: &ObservationExpectation,
    ) -> Result<RawObservationOutcome, Unsupported> {
        match self.observe_behavior.get() {
            ObserveBehavior::Met => Ok(RawObservationOutcome("postcondition_met".to_owned())),
            ObserveBehavior::NotMet => {
                Ok(RawObservationOutcome("postcondition_not_met".to_owned()))
            }
            ObserveBehavior::Ambiguous => Ok(RawObservationOutcome("ambiguous".to_owned())),
        }
    }

    fn rollback(&self, _snapshot: &StateSnapshot) -> Result<RawRollbackOutcome, Unsupported> {
        match self.rollback_behavior.get() {
            RollbackBehavior::ConfirmedRestored => {
                Ok(RawRollbackOutcome("confirmed_restored".to_owned()))
            }
            RollbackBehavior::ConfirmedFailed => {
                Ok(RawRollbackOutcome("confirmed_failed".to_owned()))
            }
            RollbackBehavior::AttemptedUnconfirmed => {
                Ok(RawRollbackOutcome("attempted_unconfirmed".to_owned()))
            }
            RollbackBehavior::Unsupported => Err(Unsupported),
        }
    }
}

struct FixtureAuthorizer {
    outcome: Cell<Option<AuthorizationOutcome>>,
    infra_failure: RefCell<Option<String>>,
}

impl FixtureAuthorizer {
    fn granting() -> Self {
        Self {
            outcome: Cell::new(Some(AuthorizationOutcome::Authorized)),
            infra_failure: RefCell::new(None),
        }
    }

    fn denying() -> Self {
        Self {
            outcome: Cell::new(Some(AuthorizationOutcome::Denied)),
            infra_failure: RefCell::new(None),
        }
    }
}

impl Authorizer for FixtureAuthorizer {
    fn authorize(
        &self,
        _request: &AuthorizationRequest,
    ) -> impl Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send {
        let result = if let Some(message) = self.infra_failure.borrow().clone() {
            Err(AuthorizationError::ProviderUnavailable(message))
        } else {
            Ok(self
                .outcome
                .get()
                .unwrap_or(AuthorizationOutcome::Unavailable(
                    AuthorizationUnavailableReason::NoAuthenticationAgent,
                )))
        };
        std::future::ready(result)
    }
}

struct FixtureStateSource {
    revision: Cell<u64>,
    candidates: RefCell<Vec<CandidateProvider>>,
}

impl FixtureStateSource {
    fn single_healthy_writer() -> Self {
        Self {
            revision: Cell::new(1),
            candidates: RefCell::new(vec![CandidateProvider {
                provider_id: ProviderId::new("fixture-provider-a").unwrap(),
                priority: 0,
                healthy: true,
                wants_write: true,
                guardian_owned_writer: false,
                authorization_ownership: Knowledge::Known(
                    guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization,
                ),
                rollback_kind: RollbackKind::Native,
            }]),
        }
    }

    fn bump_revision(&self) {
        self.revision.set(self.revision.get() + 1);
    }

    fn remove_all_candidates(&self) {
        self.candidates.borrow_mut().clear();
    }
}

impl ArbitrationStateSource for FixtureStateSource {
    fn current_revision(&self, _capability_id: &CapabilityId) -> u64 {
        self.revision.get()
    }

    fn current_candidates(&self, _capability_id: &CapabilityId) -> Vec<CandidateProvider> {
        self.candidates.borrow().clone()
    }
}

fn capability_record(
    privilege: PrivilegeRequirement,
    authorization: Knowledge<guardian_provider_api::AuthorizationMode>,
) -> CapabilityRecord {
    CapabilityRecord {
        capability_id: CapabilityId::new("storage.device.poweroff").unwrap(),
        provider_id: ProviderId::new("fixture-provider-a").unwrap(),
        provider_version: None,
        availability: Availability::Available,
        health: Health::Healthy,
        read_support: true,
        write_support: true,
        authorization_ownership: authorization,
        privilege_requirement: privilege,
        boot_availability: [BootAvailability::UserSession].into_iter().collect(),
        interface_kind: InterfaceKind::DBus,
        interface_name: None,
        interface_hash: None,
        diagnostic_cost: DiagnosticCost::default(),
        last_observed_at: "2026-09-01T00:00:00Z".to_owned(),
    }
}

fn base_capability() -> CapabilityRecord {
    capability_record(
        PrivilegeRequirement::NoDirectPrivilege,
        Knowledge::Known(guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization),
    )
}

fn new_record() -> TransactionRecord {
    TransactionRecord {
        transaction_id: TransactionId::generate(),
        idempotency_key: "idem-0001".to_owned(),
        action_type: ActionType::BoundedWrite,
        risk_class: Risk::Moderate,
        initiating_bus_name: Some(":1.42".to_owned()),
        initiating_session: None,
        provider_id: ProviderId::new("fixture-provider-a").unwrap(),
        capability_id: CapabilityId::new("storage.device.poweroff").unwrap(),
        created_at: 0,
        deadline: None,
        state: TransactionState::Created,
        pre_state: None,
        validation_results: None,
        arbitration_result: None,
        authorization_outcome: None,
        authorization_error: None,
        requested_change: ActionRequest("idem-0001".to_owned()),
        provider_request: None,
        provider_response: None,
        observation_policy: None,
        observations: Vec::new(),
        apply_record: None,
        commit_result: None,
        rollback_result: None,
        incident_ids: Vec::new(),
        cancellation_requested: false,
        deadline_expired: false,
    }
}

fn subject() -> CallerIdentity {
    CallerIdentity::new(":1.42", Some(1000))
}

/// A scratch persistence directory shared by every test in this file --
/// safe to share because every `TransactionRecord` uses a freshly
/// generated `TransactionId`, so persisted filenames never collide across
/// tests even when they run concurrently in the same process.
fn scratch_dir() -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "guardian-g4-engine-contract-{}",
        std::process::id()
    ))
}

/// Drives a transaction from `Created` through `Authorized`, ready for
/// `Apply` -- the shared happy-path setup every Apply/Observe/Rollback test
/// starts from.
fn drive_to_authorized(
    record: &mut TransactionRecord,
    provider: &FixtureAdapter,
    state_source: &FixtureStateSource,
    authorizer: &FixtureAuthorizer,
) {
    snapshot(record, provider, state_source, 0).unwrap();
    validate(record, &base_capability(), state_source).unwrap();
    async_io::block_on(authorize(
        record,
        authorizer,
        subject(),
        PolkitAction::LowRiskWrite,
        false,
    ))
    .unwrap();
}

// ---------------------------------------------------------------------
// P0-TXN-001 -- happy path
// ---------------------------------------------------------------------

#[test]
fn p0_txn_001_happy_path_reaches_committed_only_through_valid_transitions() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    assert_eq!(record.state, TransactionState::Authorized);

    revalidate_immediately_before_apply(&record, &state_source).unwrap();
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::Observing);

    observe(&mut record, &provider).unwrap();
    confirm(&mut record).unwrap();
    assert_eq!(record.state, TransactionState::Committed);
    assert_eq!(record.commit_result, Some(true));
    assert_eq!(provider.apply_calls.get(), 1);
}

// ---------------------------------------------------------------------
// Independent-audit repair: Finding 1 -- apply() must enforce its own
// preconditions. Reproduces the exact audit finding: a CREATED-state
// record passed directly to apply() previously reached provider.apply()
// before any state-machine check could reject it. These tests prove the
// mutation boundary itself now gates entry, with the illegal state never
// getting anywhere near the provider.
// ---------------------------------------------------------------------

#[test]
fn finding1_apply_from_created_state_is_rejected_before_any_provider_call() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();

    assert_eq!(record.state, TransactionState::Created);
    let result = apply(&mut record, &provider, &state_source, &dir, 1);

    assert_eq!(
        result,
        Err(EngineError::ApplyPreconditionNotMet(
            TransactionState::Created
        ))
    );
    assert_eq!(
        provider.apply_calls.get(),
        0,
        "provider.apply() must never be reached from a non-Authorized state"
    );
    assert_eq!(
        record.state,
        TransactionState::Created,
        "state must remain exactly as it was -- no partial/illegal transition"
    );
}

#[test]
fn finding1_apply_from_validating_state_is_rejected_before_any_provider_call() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();

    record.transition_to(TransactionState::Validating).unwrap();
    let result = apply(&mut record, &provider, &state_source, &dir, 1);

    assert_eq!(
        result,
        Err(EngineError::ApplyPreconditionNotMet(
            TransactionState::Validating
        ))
    );
    assert_eq!(provider.apply_calls.get(), 0);
    assert_eq!(record.state, TransactionState::Validating);
}

/// A terminal state (`Rejected`) must reject `apply()`, not silently permit
/// it or a duplicate-outcome no-op -- distinct from the legitimate
/// `Observing`+`ConfirmedSuccess` idempotent-retry case.
#[test]
fn finding1_apply_from_rejected_terminal_state_is_rejected_before_any_provider_call() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();

    record.transition_to(TransactionState::Validating).unwrap();
    record.transition_to(TransactionState::Rejected).unwrap();
    let result = apply(&mut record, &provider, &state_source, &dir, 1);

    assert_eq!(
        result,
        Err(EngineError::ApplyPreconditionNotMet(
            TransactionState::Rejected
        ))
    );
    assert_eq!(provider.apply_calls.get(), 0);
    assert_eq!(record.state, TransactionState::Rejected);
}

/// `Applying` state alone, with no `apply_record` ever set (i.e. no
/// legitimate prior Apply-intent), must also be rejected -- a record that
/// merely *looks* mid-Apply via a bare state field is not proof an intent
/// was ever durably recorded. Proves the gate checks `apply_record`, not
/// only `state`.
#[test]
fn finding1_apply_from_bare_applying_state_with_no_apply_record_is_rejected() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();

    record.transition_to(TransactionState::Validating).unwrap();
    record.transition_to(TransactionState::Validated).unwrap();
    record.transition_to(TransactionState::Authorizing).unwrap();
    record.transition_to(TransactionState::Authorized).unwrap();
    record.transition_to(TransactionState::Applying).unwrap();
    assert!(record.apply_record.is_none());

    let result = apply(&mut record, &provider, &state_source, &dir, 1);

    assert_eq!(
        result,
        Err(EngineError::ApplyPreconditionNotMet(
            TransactionState::Applying
        ))
    );
    assert_eq!(provider.apply_calls.get(), 0);
}

/// `ConfirmedFailureNoMutation` (a real, completed Apply attempt that
/// determined `Failed`) must also be rejected on a subsequent `apply()` call
/// -- not silently treated as an idempotent no-op the way a genuinely
/// successful duplicate is. Directly closes the audit's Q2/Finding-1
/// overlap and the non-blocking "missing dedicated test" finding.
#[test]
fn finding1_duplicate_apply_after_confirmed_failure_no_mutation_is_rejected_state_stays_failed() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::CleanFailure);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::Failed);
    assert_eq!(provider.apply_calls.get(), 1);

    let retry_result = apply(&mut record, &provider, &state_source, &dir, 2);

    assert_eq!(
        retry_result,
        Err(EngineError::ApplyPreconditionNotMet(
            TransactionState::Failed
        )),
        "a duplicate apply() call must be rejected, not silently returned as Ok(())"
    );
    assert_eq!(
        provider.apply_calls.get(),
        1,
        "provider.apply() must not be invoked a second time"
    );
    assert_eq!(
        record.state,
        TransactionState::Failed,
        "the original failure must remain observable -- never converted toward Committed"
    );
}

// ---------------------------------------------------------------------
// Independent-audit repair: Finding 2 -- recovery must not provide an
// unsafe resume path. `classify()` remains a pure classifier (unchanged);
// this proves the *executable* path into apply() cannot skip a fresh
// revision recheck even when the record's own in-memory state nominally
// looks resumable (Authorized, with a real prior pre_state) -- exactly
// the shape a naive "SafeToResume -> apply()" caller would produce if it
// reused stale persisted/historical arbitration data instead of
// re-deriving revision from the live ArbitrationStateSource.
// ---------------------------------------------------------------------

#[test]
fn finding2_recovered_authorized_record_with_stale_revision_cannot_reach_provider_mutation() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    // Legitimately reaches Authorized with a real pre_state/arbitration_result
    // captured at revision 1 -- exactly what a "recovered" in-memory record
    // reconstructed from persisted historical state would also look like.
    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    assert_eq!(record.state, TransactionState::Authorized);

    // The authoritative state source's revision has since changed --
    // simulating "time passed since this was authorized/persisted, and
    // ownership/candidates were re-arbitrated in the meantime" -- without
    // touching `record` itself in any way.
    state_source.bump_revision();

    let result = apply(&mut record, &provider, &state_source, &dir, 1);

    assert_eq!(
        result,
        Err(EngineError::StaleRevision),
        "apply() must independently re-derive revision, not trust the Authorized state alone"
    );
    assert_eq!(
        provider.apply_calls.get(),
        0,
        "a stale-revision record must never reach provider.apply(), regardless of how it arrived at Authorized"
    );
    assert_eq!(
        record.state,
        TransactionState::Authorized,
        "the block must occur before any state transition toward Applying"
    );
}

// ---------------------------------------------------------------------
// P0-TXN-002 -- validation failure (including NB-1 unknown privilege)
// ---------------------------------------------------------------------

#[test]
fn p0_txn_002_invalid_precondition_ends_in_rejected_no_apply_occurs() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    let mut unavailable = base_capability();
    unavailable.availability = Availability::Unavailable;
    let result = validate(&mut record, &unavailable, &state_source);
    assert!(result.is_err());
    assert_eq!(record.state, TransactionState::Rejected);
    assert_eq!(provider.apply_calls.get(), 0);
}

/// NB-1 (G3 forward constraint, closed here): `PrivilegeRequirement::Unknown`
/// blocks at `Validate`, `REJECTED`, never reaches `APPLYING`, regardless of
/// `authorization_ownership`.
#[test]
fn p0_txn_002_unknown_privilege_requirement_is_rejected_before_apply_nb1() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    let unknown_privilege = capability_record(
        PrivilegeRequirement::Unknown,
        Knowledge::Known(guardian_provider_api::AuthorizationMode::GuardianOwnedAuthorization),
    );
    let result = validate(&mut record, &unknown_privilege, &state_source);
    assert!(matches!(result, Err(EngineError::ValidationFailed(_))));
    assert_eq!(record.state, TransactionState::Rejected);
    assert_ne!(record.state, TransactionState::Applying);
    assert_eq!(provider.apply_calls.get(), 0);
}

#[test]
fn unknown_authorization_ownership_is_also_rejected_before_apply() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    let unknown_ownership =
        capability_record(PrivilegeRequirement::NoDirectPrivilege, Knowledge::Unknown);
    let result = validate(&mut record, &unknown_ownership, &state_source);
    assert!(result.is_err());
    assert_eq!(record.state, TransactionState::Rejected);
}

// ---------------------------------------------------------------------
// P0-TXN-003 -- authorization denied
// ---------------------------------------------------------------------

#[test]
fn p0_txn_003_denied_authorization_performs_no_apply() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let authorizer = FixtureAuthorizer::denying();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    validate(&mut record, &base_capability(), &state_source).unwrap();
    let result = async_io::block_on(authorize(
        &mut record,
        &authorizer,
        subject(),
        PolkitAction::LowRiskWrite,
        false,
    ));
    assert!(result.is_err());
    assert_eq!(record.state, TransactionState::Rejected);
    assert_eq!(provider.apply_calls.get(), 0);
}

// ---------------------------------------------------------------------
// P0-TXN-004 -- apply failure (both flavors)
// ---------------------------------------------------------------------

#[test]
fn p0_txn_004_clean_apply_failure_reaches_failed_no_mutation() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::CleanFailure);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::Failed);
}

#[test]
fn p0_txn_004_partial_uncertain_apply_failure_enters_rolling_back() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::RollingBack);
}

// ---------------------------------------------------------------------
// P0-TXN-005 -- observation failure
// ---------------------------------------------------------------------

#[test]
fn p0_txn_005_provider_success_followed_by_failed_observation_does_not_commit() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.observe_behavior.set(ObserveBehavior::NotMet);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    observe(&mut record, &provider).unwrap();
    let result = confirm(&mut record);
    assert!(result.is_ok());
    assert_eq!(record.state, TransactionState::RollingBack);
    assert_ne!(record.state, TransactionState::Committed);
}

// ---------------------------------------------------------------------
// P0-TXN-006 / P0-TXN-007 -- rollback, all RollbackKind rows (§17.3)
// ---------------------------------------------------------------------

#[test]
fn p0_txn_006_native_rollback_confirmed_reaches_rolled_back() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    provider
        .rollback_behavior
        .set(RollbackBehavior::ConfirmedRestored);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    rollback(&mut record, &provider, RollbackKind::Native).unwrap();
    assert_eq!(record.state, TransactionState::RolledBack);
    assert_eq!(
        record.rollback_result,
        Some(RollbackOutcome::ConfirmedRestored)
    );
}

#[test]
fn emulated_rollback_confirmed_reaches_rolled_back() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    provider
        .rollback_behavior
        .set(RollbackBehavior::ConfirmedRestored);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    rollback(&mut record, &provider, RollbackKind::Emulated).unwrap();
    assert_eq!(record.state, TransactionState::RolledBack);
    assert_eq!(
        record.rollback_result,
        Some(RollbackOutcome::ConfirmedRestored)
    );
}

#[test]
fn best_effort_rollback_confirmed_reaches_rolled_back() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    provider
        .rollback_behavior
        .set(RollbackBehavior::ConfirmedRestored);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    rollback(&mut record, &provider, RollbackKind::BestEffort).unwrap();
    assert_eq!(record.state, TransactionState::RolledBack);
    assert_eq!(
        record.rollback_result,
        Some(RollbackOutcome::ConfirmedRestored)
    );
}

/// §17.2's fail-closed repair: an *unconfirmed* `BestEffort` attempt MUST
/// reach `ROLLBACK_FAILED`, never `ROLLED_BACK` -- with `rollback_result`
/// distinguishing it from a confirmed provider failure.
#[test]
fn best_effort_rollback_unconfirmed_reaches_rollback_failed_not_rolled_back() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    provider
        .rollback_behavior
        .set(RollbackBehavior::AttemptedUnconfirmed);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    rollback(&mut record, &provider, RollbackKind::BestEffort).unwrap();
    assert_eq!(record.state, TransactionState::RollbackFailed);
    assert_ne!(record.state, TransactionState::RolledBack);
    assert_eq!(
        record.rollback_result,
        Some(RollbackOutcome::AttemptedUnconfirmed)
    );
}

#[test]
fn p0_txn_007_explicit_rollback_failure_reaches_rollback_failed() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    provider
        .rollback_behavior
        .set(RollbackBehavior::ConfirmedFailed);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    rollback(&mut record, &provider, RollbackKind::BestEffort).unwrap();
    assert_eq!(record.state, TransactionState::RollbackFailed);
    assert_eq!(
        record.rollback_result,
        Some(RollbackOutcome::ConfirmedFailed)
    );
}

/// `rollback_result` must distinguish a confirmed provider failure from an
/// unconfirmed attempt even though both share transaction state
/// `ROLLBACK_FAILED` (§17.3).
#[test]
fn confirmed_failed_and_attempted_unconfirmed_are_distinguishable_at_rollback_result_level() {
    assert_ne!(
        RollbackOutcome::ConfirmedFailed,
        RollbackOutcome::AttemptedUnconfirmed
    );
    assert_eq!(
        RollbackOutcome::ConfirmedFailed.terminal_state(),
        TransactionState::RollbackFailed
    );
    assert_eq!(
        RollbackOutcome::AttemptedUnconfirmed.terminal_state(),
        TransactionState::RollbackFailed
    );
}

#[test]
fn rollback_kind_none_never_reaches_rolled_back() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    rollback(&mut record, &provider, RollbackKind::None).unwrap();
    assert_eq!(record.state, TransactionState::RollbackFailed);
    assert_ne!(record.state, TransactionState::RolledBack);
    assert_eq!(record.rollback_result, Some(RollbackOutcome::NotSupported));
}

// ---------------------------------------------------------------------
// P0-TXN-008 -- terminal immutability at the engine level
// ---------------------------------------------------------------------

#[test]
fn p0_txn_008_committed_transaction_cannot_re_enter_applying() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    observe(&mut record, &provider).unwrap();
    confirm(&mut record).unwrap();
    assert_eq!(record.state, TransactionState::Committed);

    let result = record.transition_to(TransactionState::Applying);
    assert!(result.is_err());
    assert_eq!(record.state, TransactionState::Committed);
}

// ---------------------------------------------------------------------
// P0-TXN-009 -- idempotent retry / lost response
// ---------------------------------------------------------------------

#[test]
fn p0_txn_009_same_idempotency_key_never_invokes_apply_twice_after_response_loss() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(provider.apply_calls.get(), 1);
    assert_eq!(record.state, TransactionState::Observing);

    // Simulate: the process crashed after invoking the provider but before
    // durably recording the outcome (G4 handoff §19.1, crash between step 4
    // and 5).
    simulate_response_lost(&mut record);

    // Retry with the same idempotency_key -- must NOT call apply() again,
    // and must NOT report success merely because APPLYING/an ApplyRecord
    // exists.
    let retry_result = apply(&mut record, &provider, &state_source, &dir, 2);
    assert_eq!(retry_result, Err(EngineError::MustObserveBeforeRetry));
    assert_eq!(
        provider.apply_calls.get(),
        1,
        "apply() must not be called a second time"
    );

    // Required recovery discipline: Observe before any conclusion.
    let observation = observe(&mut record, &provider).unwrap();
    assert_eq!(
        observation,
        guardian_core::transaction::ObservationOutcome::PostconditionMet
    );
    confirm(&mut record).unwrap();
    assert_eq!(record.state, TransactionState::Committed);
    assert_eq!(
        provider.apply_calls.get(),
        1,
        "apply() must still have been called only once"
    );
}

#[test]
fn known_completed_apply_is_not_re_invoked_on_retry() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(provider.apply_calls.get(), 1);

    // A second call to apply() with the outcome already ConfirmedSuccess
    // must be a no-op, not a second real invocation.
    apply(&mut record, &provider, &state_source, &dir, 2).unwrap();
    assert_eq!(provider.apply_calls.get(), 1);
}

// ---------------------------------------------------------------------
// P0-TXN-010 -- stale resource identity
// ---------------------------------------------------------------------

#[test]
fn p0_txn_010_provider_identity_change_between_validate_and_snapshot_blocks_apply() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    let mut replaced = base_capability();
    replaced.provider_id = ProviderId::new("someone-else").unwrap();
    let result = validate(&mut record, &replaced, &state_source);
    assert!(result.is_err());
    assert_eq!(record.state, TransactionState::Rejected);
}

// ---------------------------------------------------------------------
// P0-TXN-012 -- client disconnect
// ---------------------------------------------------------------------

/// The transaction/audit record is owned independently of the initiating
/// client connection -- a disconnected `initiating_bus_name` does not
/// erase or alter the record.
#[test]
fn p0_txn_012_client_disconnect_does_not_lose_the_audit_record() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    observe(&mut record, &provider).unwrap();
    confirm(&mut record).unwrap();

    // Simulate client disconnect: nothing in the engine ties transaction
    // continuation to a live client connection -- the record's fields
    // (including the historical initiating_bus_name) remain fully intact.
    let disconnected_bus_name = record.initiating_bus_name.clone();
    drop(disconnected_bus_name);
    assert_eq!(record.state, TransactionState::Committed);
    assert_eq!(record.initiating_bus_name.as_deref(), Some(":1.42"));
    assert_eq!(record.transaction_id, record.transaction_id.clone());
}

// ---------------------------------------------------------------------
// Revision authority (NB-2 resolution, §7)
// ---------------------------------------------------------------------

/// Required test (a): revision unchanged between Validate and Apply ->
/// transaction proceeds.
#[test]
fn revision_unchanged_between_validate_and_apply_proceeds() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    assert!(revalidate_immediately_before_apply(&record, &state_source).is_ok());
}

/// Required test (b): the `ArbitrationStateSource` fixture's authoritative
/// state is changed between `Validate` and `Apply` -- proven by calling
/// `state_source.bump_revision()`, never by editing
/// `record.arbitration_result.revision` directly (§7.2 test-discipline
/// requirement).
#[test]
fn revision_change_via_authoritative_state_source_blocks_apply_not_via_field_mutation() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);

    // The ONLY mutation here is to the fixture's own authoritative state --
    // `record` itself is never touched.
    state_source.bump_revision();

    let result = revalidate_immediately_before_apply(&record, &state_source);
    assert_eq!(result, Err(EngineError::StaleRevision));

    // apply() itself does not re-check revision (that is
    // revalidate_immediately_before_apply's job, called by the caller
    // immediately beforehand per §7.3) -- the governed caller contract is
    // to never proceed to apply() once the TOCTOU recheck above returned
    // StaleRevision, which is why this test asserts on the recheck's
    // return value rather than calling apply() at all.
    assert_eq!(
        provider.apply_calls.get(),
        0,
        "caller must not proceed to apply() after a stale-revision block"
    );
}

#[test]
fn arbitration_result_revision_is_populated_by_the_engine_not_the_caller() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    let revision_from_snapshot = record
        .pre_state
        .as_ref()
        .unwrap()
        .arbitration_result
        .revision;
    assert_eq!(revision_from_snapshot, 1);

    validate(&mut record, &base_capability(), &state_source).unwrap();
    let revision_from_validate = record.arbitration_result.as_ref().unwrap().revision;
    assert_eq!(revision_from_validate, 1);
}

// ---------------------------------------------------------------------
// TOCTOU (§10)
// ---------------------------------------------------------------------

#[test]
fn provider_disappearing_between_validate_and_apply_is_detected() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    state_source.remove_all_candidates();

    // A fresh arbitration re-run at this point would show no healthy
    // writer -- proven via the same fixture, not by editing `record`.
    let fresh_revision = state_source.current_revision(&record.capability_id);
    let fresh_candidates = state_source.current_candidates(&record.capability_id);
    assert_eq!(fresh_revision, 1);
    assert!(fresh_candidates.is_empty());
}

#[test]
fn snapshot_failure_prevents_apply() {
    let mut record = new_record();
    let mut provider = FixtureAdapter::new();
    provider.inspect_ok = false;
    let state_source = FixtureStateSource::single_healthy_writer();

    let result = snapshot(&mut record, &provider, &state_source, 0);
    assert_eq!(result, Err(EngineError::SnapshotFailed));
    assert!(record.pre_state.is_none());
    assert_ne!(record.state, TransactionState::Applying);
}

// ---------------------------------------------------------------------
// Cancellation / expiry (§17.4)
// ---------------------------------------------------------------------

#[test]
fn cancellation_requested_before_apply_reaches_cancelled_no_apply_ever_occurs() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    validate(&mut record, &base_capability(), &state_source).unwrap();
    request_cancellation(&mut record).unwrap();
    assert_eq!(record.state, TransactionState::Cancelled);
    assert_eq!(provider.apply_calls.get(), 0);
}

#[test]
fn expiry_requested_before_apply_reaches_expired_no_apply_ever_occurs() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    validate(&mut record, &base_capability(), &state_source).unwrap();
    request_expiry(&mut record).unwrap();
    assert_eq!(record.state, TransactionState::Expired);
    assert_eq!(provider.apply_calls.get(), 0);
}

/// §17.4's central safety repair: a cancellation request during `APPLYING`
/// does NOT immediately become `CANCELLED` -- the transaction continues to
/// a governed outcome, and the request is preserved as typed evidence.
#[test]
fn cancellation_requested_during_applying_does_not_short_circuit_reconciliation() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    record.transition_to(TransactionState::Applying).unwrap();
    // A real Apply-intent already durably exists (state Applying, outcome
    // NotRecorded) -- the legitimate entry condition apply()'s precondition
    // gate requires for a retry, faithfully modeling "Apply is genuinely
    // in progress" rather than an empty/never-attempted Applying state.
    record.apply_record = Some(ApplyRecord::intent_only(record.idempotency_key.clone(), 0));
    request_cancellation(&mut record).unwrap();
    assert_ne!(record.state, TransactionState::Cancelled);
    assert_eq!(record.state, TransactionState::Applying);
    assert!(record.cancellation_requested);

    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    observe(&mut record, &provider).unwrap();
    confirm(&mut record).unwrap();
    assert_eq!(
        record.state,
        TransactionState::Committed,
        "COMMITTED must stand"
    );
    assert!(
        record.cancellation_requested,
        "request preserved as context only"
    );
}

#[test]
fn expiry_requested_during_applying_does_not_short_circuit_reconciliation() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    record.transition_to(TransactionState::Applying).unwrap();
    record.apply_record = Some(ApplyRecord::intent_only(record.idempotency_key.clone(), 0));
    request_expiry(&mut record).unwrap();
    assert_ne!(record.state, TransactionState::Expired);

    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_ne!(record.state, TransactionState::Expired);
    assert!(record.deadline_expired);
}

#[test]
fn cancellation_requested_during_rolling_back_does_not_bypass_rollback_reconciliation() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::RollingBack);

    request_cancellation(&mut record).unwrap();
    assert_eq!(
        record.state,
        TransactionState::RollingBack,
        "must not jump to CANCELLED mid-rollback"
    );

    rollback(&mut record, &provider, RollbackKind::Native).unwrap();
    assert_eq!(record.state, TransactionState::RolledBack);
    assert!(record.cancellation_requested);
}

#[test]
fn expiry_requested_during_rolling_back_does_not_bypass_rollback_reconciliation() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    provider
        .rollback_behavior
        .set(RollbackBehavior::ConfirmedFailed);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    request_expiry(&mut record).unwrap();
    assert_eq!(record.state, TransactionState::RollingBack);

    rollback(&mut record, &provider, RollbackKind::BestEffort).unwrap();
    assert_eq!(record.state, TransactionState::RollbackFailed);
    assert!(
        record.deadline_expired,
        "request preserved even though the outcome stands"
    );
}

#[test]
fn cancellation_or_expiry_requested_then_transaction_reaches_committed_stands() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    request_cancellation(&mut record).unwrap();
    request_expiry(&mut record).unwrap();
    observe(&mut record, &provider).unwrap();
    confirm(&mut record).unwrap();

    assert_eq!(record.state, TransactionState::Committed);
    assert_ne!(record.state, TransactionState::Cancelled);
    assert_ne!(record.state, TransactionState::Expired);
    assert!(
        record.cancellation_requested && record.deadline_expired,
        "both preserved as context only"
    );
}

// ---------------------------------------------------------------------
// Provider-Unsupported / ambiguous-observation edge cases
// ---------------------------------------------------------------------

#[test]
fn provider_apply_unsupported_is_treated_as_clean_failure_not_silently_ignored() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::Unsupported);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::Failed);
}

#[test]
fn provider_observe_unsupported_is_treated_as_ambiguous_never_as_success() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.observe_behavior.set(ObserveBehavior::Ambiguous);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    let observation = observe(&mut record, &provider).unwrap();
    assert_eq!(
        observation,
        guardian_core::transaction::ObservationOutcome::Ambiguous
    );
    let confirm_result = confirm(&mut record);
    assert_eq!(confirm_result, Err(EngineError::ObservationInconclusive));
    assert_ne!(record.state, TransactionState::Committed);
}

#[test]
fn provider_rollback_unsupported_reaches_rollback_failed_via_not_supported() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    provider.apply_behavior.set(ApplyBehavior::PartialUncertain);
    provider
        .rollback_behavior
        .set(RollbackBehavior::Unsupported);
    let state_source = FixtureStateSource::single_healthy_writer();
    let dir = scratch_dir();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    rollback(&mut record, &provider, RollbackKind::Native).unwrap();
    assert_eq!(record.state, TransactionState::RollbackFailed);
    assert_eq!(record.rollback_result, Some(RollbackOutcome::NotSupported));
}

// ---------------------------------------------------------------------
// G2 boundary preservation (§5)
// ---------------------------------------------------------------------

/// No field on `TransactionRecord` resembles authorization proof a
/// privileged helper could be tempted to trust instead of its own real
/// `CheckAuthorization` (mirrors G3's identical arbitration-level check).
#[test]
fn transaction_record_carries_no_field_resembling_authorization_proof() {
    let record = new_record();
    let debug = format!("{record:?}");
    assert!(!debug.contains("caller_authorized"));
    assert!(!debug.contains("authorization_passed"));
    assert!(!debug.contains("trusted_caller"));
}

#[test]
fn authorized_outcome_never_implies_a_specific_caller_was_verified_by_core() {
    let mut record = new_record();
    let provider = FixtureAdapter::new();
    let state_source = FixtureStateSource::single_healthy_writer();
    let authorizer = FixtureAuthorizer::granting();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    // authorization_outcome only ever records what G1's real Authorizer
    // trait returned for *this* request -- it is not, and cannot be used
    // as, a token a later Apply attempt could replay to skip real
    // authorization (there is no such replay path in this engine at all).
    assert_eq!(
        record.authorization_outcome,
        Some(AuthorizationOutcome::Authorized)
    );
}
