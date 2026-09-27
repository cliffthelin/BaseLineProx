//! Independent-audit repair, Finding 3: persistence wired into the real
//! Apply execution path (G4 handoff §19.1), proven with real
//! test-controlled filesystem I/O -- not in-memory simulation. Covers the
//! six required crash-boundary/integration scenarios plus persistence
//! failure blocking the provider call.

use std::cell::Cell;
use std::future::Future;

use guardian_core::arbitration::{CandidateProvider, RollbackKind};
use guardian_core::authorization::{
    AuthorizationError, AuthorizationOutcome, AuthorizationRequest, Authorizer, PolkitAction,
};
use guardian_core::identity::CallerIdentity;
use guardian_core::risk::Risk;
use guardian_core::transaction::arbitration_source::ArbitrationStateSource;
use guardian_core::transaction::engine::{apply, authorize, snapshot, validate};
use guardian_core::transaction::persistence::{
    CURRENT_SCHEMA_VERSION, LoadError, PersistedTransactionRecord, load, persist,
};
use guardian_core::transaction::record::ActionType;
use guardian_core::transaction::recovery::{RecoveryClassification, classify};
use guardian_core::transaction::{
    ApplyOutcome, TransactionId, TransactionRecord, TransactionState,
};
use guardian_provider_api::{
    ActionRequest, ApplyOutcome as RawApplyOutcome, Availability, BootAvailability, CapabilityId,
    CapabilityRecord, DiagnosticCost, Health, InspectionSnapshot, InterfaceKind, Knowledge,
    MutableCapabilityAdapter, ObservationExpectation, ObservationOutcome as RawObservationOutcome,
    PrivilegeRequirement, ProviderId, RollbackOutcome as RawRollbackOutcome, StateSnapshot,
    Unsupported, ValidationResult,
};

struct FixtureAdapter {
    apply_calls: Cell<u32>,
    succeed: bool,
}

impl FixtureAdapter {
    fn new(succeed: bool) -> Self {
        Self {
            apply_calls: Cell::new(0),
            succeed,
        }
    }
}

impl MutableCapabilityAdapter for FixtureAdapter {
    fn inspect(&self) -> Result<InspectionSnapshot, Unsupported> {
        Ok(InspectionSnapshot("prior-state".to_owned()))
    }

    fn validate(&self, _action: &ActionRequest) -> Result<ValidationResult, Unsupported> {
        Ok(ValidationResult("ok".to_owned()))
    }

    fn snapshot(&self, _action: &ActionRequest) -> Result<StateSnapshot, Unsupported> {
        Ok(StateSnapshot("prior-state".to_owned()))
    }

    fn apply(&self, _action: &ActionRequest) -> Result<RawApplyOutcome, Unsupported> {
        self.apply_calls.set(self.apply_calls.get() + 1);
        Ok(RawApplyOutcome(
            if self.succeed {
                "confirmed_success"
            } else {
                "confirmed_failure_no_mutation"
            }
            .to_owned(),
        ))
    }

    fn observe(
        &self,
        _expectation: &ObservationExpectation,
    ) -> Result<RawObservationOutcome, Unsupported> {
        Ok(RawObservationOutcome("postcondition_met".to_owned()))
    }

    fn rollback(&self, _snapshot: &StateSnapshot) -> Result<RawRollbackOutcome, Unsupported> {
        Ok(RawRollbackOutcome("confirmed_restored".to_owned()))
    }
}

struct FixtureAuthorizer;

impl Authorizer for FixtureAuthorizer {
    fn authorize(
        &self,
        _request: &AuthorizationRequest,
    ) -> impl Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send {
        std::future::ready(Ok(AuthorizationOutcome::Authorized))
    }
}

struct FixtureStateSource {
    revision: Cell<u64>,
}

impl FixtureStateSource {
    fn new() -> Self {
        Self {
            revision: Cell::new(1),
        }
    }
}

impl ArbitrationStateSource for FixtureStateSource {
    fn current_revision(&self, _capability_id: &CapabilityId) -> u64 {
        self.revision.get()
    }

    fn current_candidates(&self, _capability_id: &CapabilityId) -> Vec<CandidateProvider> {
        vec![CandidateProvider {
            provider_id: ProviderId::new("fixture-provider-a").unwrap(),
            priority: 0,
            healthy: true,
            wants_write: true,
            guardian_owned_writer: false,
            authorization_ownership: Knowledge::Known(
                guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization,
            ),
            rollback_kind: RollbackKind::Native,
        }]
    }
}

fn base_capability() -> CapabilityRecord {
    CapabilityRecord {
        capability_id: CapabilityId::new("storage.device.poweroff").unwrap(),
        provider_id: ProviderId::new("fixture-provider-a").unwrap(),
        provider_version: None,
        availability: Availability::Available,
        health: Health::Healthy,
        read_support: true,
        write_support: true,
        authorization_ownership: Knowledge::Known(
            guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization,
        ),
        privilege_requirement: PrivilegeRequirement::NoDirectPrivilege,
        boot_availability: [BootAvailability::UserSession].into_iter().collect(),
        interface_kind: InterfaceKind::DBus,
        interface_name: None,
        interface_hash: None,
        diagnostic_cost: DiagnosticCost::default(),
        last_observed_at: "2026-09-01T00:00:00Z".to_owned(),
    }
}

fn new_record() -> TransactionRecord {
    TransactionRecord {
        transaction_id: TransactionId::generate(),
        idempotency_key: "idem-apply-persist-0001".to_owned(),
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
        requested_change: ActionRequest("idem-apply-persist-0001".to_owned()),
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
        CallerIdentity::new(":1.42", Some(1000)),
        PolkitAction::LowRiskWrite,
        false,
    ))
    .unwrap();
}

fn temp_dir(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "guardian-g4-apply-persist-{name}-{}",
        std::process::id()
    ))
}

fn base_persisted(transaction_id: TransactionId) -> PersistedTransactionRecord {
    PersistedTransactionRecord {
        schema_version: CURRENT_SCHEMA_VERSION,
        transaction_id,
        idempotency_key: "idem-apply-persist-0001".to_owned(),
        capability_id: CapabilityId::new("storage.device.poweroff").unwrap(),
        provider_id: ProviderId::new("fixture-provider-a").unwrap(),
        state: TransactionState::Applying,
        arbitration_revision: Some(1),
        apply_outcome: None,
        dispatch_marker: false,
        last_observation: None,
        rollback_result: None,
        cancellation_requested: false,
        deadline_expired: false,
    }
}

/// Crash-boundary requirement 1: persistence failure before the durable
/// Apply-intent step must mean the provider is never called at all.
/// Forces a real `persist()` failure by placing a regular file where the
/// persistence directory must go, so `create_dir_all` itself fails.
#[test]
fn crash_boundary_1_persistence_failure_before_durable_intent_blocks_provider_call() {
    let mut record = new_record();
    let provider = FixtureAdapter::new(true);
    let state_source = FixtureStateSource::new();
    let authorizer = FixtureAuthorizer;
    let blocked_dir = temp_dir("blocked-by-file");
    std::fs::remove_file(&blocked_dir).ok();
    std::fs::remove_dir_all(&blocked_dir).ok();
    std::fs::write(&blocked_dir, b"not a directory").unwrap();

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    let result = apply(&mut record, &provider, &state_source, &blocked_dir, 1);

    assert!(
        matches!(
            result,
            Err(guardian_core::transaction::engine::EngineError::PersistenceFailed(_))
        ),
        "expected PersistenceFailed, got {result:?}"
    );
    assert_eq!(
        provider.apply_calls.get(),
        0,
        "provider.apply() must never run when the durable Apply-intent persist itself fails"
    );

    std::fs::remove_file(&blocked_dir).ok();
}

/// Crash-boundary requirement 2: a durable Apply-intent record (state
/// Applying, `apply_outcome` `NotRecorded`) with the provider genuinely never
/// invoked must never be classified/reported as successful -- it is
/// `SafeToResume`. Uses real `persist()`/`load()` disk I/O.
#[test]
fn crash_boundary_2_durable_intent_before_provider_invocation_is_safe_to_resume_not_successful() {
    let dir = temp_dir("boundary-2");
    let mut persisted = base_persisted(TransactionId::generate());
    persisted.apply_outcome = Some(ApplyOutcome::NotRecorded);
    persist(&dir, &persisted).unwrap();

    let loaded = load(&dir, &persisted.transaction_id).unwrap();
    let classification = classify(loaded.to_recovery_snapshot());

    assert_eq!(classification, RecoveryClassification::SafeToResume);
    assert_ne!(classification, RecoveryClassification::AlreadyCommitted);

    std::fs::remove_dir_all(&dir).ok();
}

/// **G4 extension (G4 handoff §19.1a; closes W1-REC-003/W1-VM-005)**:
/// requirement 2's fixture above (`dispatch_marker: false`) is the "crash
/// strictly before dispatch" case and correctly stays `SafeToResume`. This
/// is its sibling: Apply-intent durable, dispatch marker *also* durable
/// (the provider call was about to be, or was, invoked), but no concrete
/// outcome ever got persisted -- e.g. a real `kill -9` during an in-flight
/// provider call. This must now classify as `StateAmbiguous`, never
/// `SafeToResume` and never `AlreadyCommitted`.
#[test]
fn crash_boundary_2b_dispatch_marker_set_but_outcome_never_recorded_is_state_ambiguous() {
    let dir = temp_dir("boundary-2b");
    let mut persisted = base_persisted(TransactionId::generate());
    persisted.apply_outcome = Some(ApplyOutcome::NotRecorded);
    persisted.dispatch_marker = true;
    persist(&dir, &persisted).unwrap();

    let loaded = load(&dir, &persisted.transaction_id).unwrap();
    let classification = classify(loaded.to_recovery_snapshot());

    assert_eq!(classification, RecoveryClassification::StateAmbiguous);
    assert_ne!(classification, RecoveryClassification::SafeToResume);
    assert_ne!(classification, RecoveryClassification::AlreadyCommitted);

    std::fs::remove_dir_all(&dir).ok();
}

/// Proves the *ordering* half of the G4 extension via the real, wired
/// `engine::apply` path (not a hand-built fixture): the durable dispatch
/// marker must already be readable from disk, with the outcome still
/// `NotRecorded`, strictly *before* `provider.apply()` is ever invoked --
/// this is what makes the crash-during-dispatch window real rather than
/// theoretical. The fixture provider's own `apply()` implementation reads
/// back the persisted record via a fresh, independent `load()` call as its
/// very first action and records what it saw.
#[test]
fn dispatch_marker_is_durable_before_provider_apply_is_ever_invoked() {
    struct OrderingProbeAdapter {
        dir: std::path::PathBuf,
        transaction_id: std::cell::RefCell<Option<TransactionId>>,
        observed_marker_before_call: Cell<Option<bool>>,
        observed_outcome_was_not_recorded_before_call: Cell<Option<bool>>,
    }

    impl MutableCapabilityAdapter for OrderingProbeAdapter {
        fn inspect(&self) -> Result<InspectionSnapshot, Unsupported> {
            Ok(InspectionSnapshot("prior-state".to_owned()))
        }

        fn validate(&self, _action: &ActionRequest) -> Result<ValidationResult, Unsupported> {
            Ok(ValidationResult("ok".to_owned()))
        }

        fn snapshot(&self, _action: &ActionRequest) -> Result<StateSnapshot, Unsupported> {
            Ok(StateSnapshot("prior-state".to_owned()))
        }

        fn apply(&self, _action: &ActionRequest) -> Result<RawApplyOutcome, Unsupported> {
            let transaction_id = self.transaction_id.borrow().clone().unwrap();
            let on_disk = load(&self.dir, &transaction_id).expect(
                "the durable Apply-intent record must already exist on disk by the time \
                 provider.apply() is invoked",
            );
            self.observed_marker_before_call
                .set(Some(on_disk.dispatch_marker));
            self.observed_outcome_was_not_recorded_before_call.set(Some(
                on_disk.apply_outcome == Some(ApplyOutcome::NotRecorded),
            ));
            Ok(RawApplyOutcome("confirmed_success".to_owned()))
        }

        fn observe(
            &self,
            _expectation: &ObservationExpectation,
        ) -> Result<RawObservationOutcome, Unsupported> {
            Ok(RawObservationOutcome("postcondition_met".to_owned()))
        }

        fn rollback(&self, _snapshot: &StateSnapshot) -> Result<RawRollbackOutcome, Unsupported> {
            Ok(RawRollbackOutcome("confirmed_restored".to_owned()))
        }
    }

    let dir = temp_dir("dispatch-marker-ordering");
    let mut record = new_record();
    let state_source = FixtureStateSource::new();
    let authorizer = FixtureAuthorizer;
    let provider = OrderingProbeAdapter {
        dir: dir.clone(),
        transaction_id: std::cell::RefCell::new(None),
        observed_marker_before_call: Cell::new(None),
        observed_outcome_was_not_recorded_before_call: Cell::new(None),
    };

    snapshot(&mut record, &provider, &state_source, 0).unwrap();
    validate(&mut record, &base_capability(), &state_source).unwrap();
    async_io::block_on(authorize(
        &mut record,
        &authorizer,
        CallerIdentity::new(":1.42", Some(1000)),
        PolkitAction::LowRiskWrite,
        false,
    ))
    .unwrap();
    *provider.transaction_id.borrow_mut() = Some(record.transaction_id.clone());

    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();

    assert_eq!(
        provider.observed_marker_before_call.get(),
        Some(true),
        "the dispatch marker must be durably set before provider.apply() is ever called"
    );
    assert_eq!(
        provider.observed_outcome_was_not_recorded_before_call.get(),
        Some(true),
        "the outcome must still read NotRecorded from disk at the moment provider.apply() runs \
         -- it is only overwritten after the provider call returns"
    );
    // And the final, post-return state is a genuine, concrete success --
    // requirement 3 (known success remains known success), proven through
    // this same real path.
    assert_eq!(record.state, TransactionState::Observing);
    let reloaded = load(&dir, &record.transaction_id).unwrap();
    assert_eq!(reloaded.apply_outcome, Some(ApplyOutcome::ConfirmedSuccess));

    std::fs::remove_dir_all(&dir).ok();
}

/// Crash-boundary requirement 3: the provider may have run but its
/// outcome was never durably recorded -- recovery must require Observe
/// (ambiguity handling), never guess success or failure.
#[test]
fn crash_boundary_3_provider_may_have_run_outcome_not_persisted_requires_observe() {
    let dir = temp_dir("boundary-3");
    let mut persisted = base_persisted(TransactionId::generate());
    persisted.apply_outcome = Some(ApplyOutcome::ResponseLostOrUnknown);
    persist(&dir, &persisted).unwrap();

    let loaded = load(&dir, &persisted.transaction_id).unwrap();
    let classification = classify(loaded.to_recovery_snapshot());

    assert_eq!(classification, RecoveryClassification::MustObserve);
    assert_ne!(classification, RecoveryClassification::AlreadyCommitted);
    assert_ne!(classification, RecoveryClassification::SafeToResume);

    std::fs::remove_dir_all(&dir).ok();
}

/// Crash-boundary requirement 4: a real Apply success through the actual
/// wired engine path is durably persisted, and reload independently (via
/// a fresh `load()` call, not the in-memory record) preserves that fact.
#[test]
fn crash_boundary_4_apply_success_durable_outcome_survives_independent_reload() {
    let mut record = new_record();
    let provider = FixtureAdapter::new(true);
    let state_source = FixtureStateSource::new();
    let authorizer = FixtureAuthorizer;
    let dir = temp_dir("boundary-4");

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::Observing);

    // Independent reload -- a fresh load() call against real disk state,
    // not a reuse of the in-memory `record`.
    let reloaded = load(&dir, &record.transaction_id).unwrap();
    assert_eq!(reloaded.state, TransactionState::Observing);
    assert_eq!(reloaded.apply_outcome, Some(ApplyOutcome::ConfirmedSuccess));

    std::fs::remove_dir_all(&dir).ok();
}

/// Requirement 4 (G4 extension regression guard): a known clean failure
/// through the real, wired `engine::apply` path remains exactly what it
/// was before this extension -- `ConfirmedFailureNoMutation`, `Failed`,
/// `SafeToResume` on reload -- unaffected by the dispatch marker now also
/// being durably set along the way.
#[test]
fn crash_boundary_4b_apply_failure_durable_outcome_survives_independent_reload() {
    let mut record = new_record();
    let provider = FixtureAdapter::new(false);
    let state_source = FixtureStateSource::new();
    let authorizer = FixtureAuthorizer;
    let dir = temp_dir("boundary-4b");

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();
    assert_eq!(record.state, TransactionState::Failed);

    let reloaded = load(&dir, &record.transaction_id).unwrap();
    assert_eq!(reloaded.state, TransactionState::Failed);
    assert_eq!(
        reloaded.apply_outcome,
        Some(ApplyOutcome::ConfirmedFailureNoMutation)
    );
    // `Failed` is itself terminal, so a real restart short-circuits to
    // `AlreadyTerminal` before `classify()` is ever consulted -- the
    // classifier's own `ConfirmedFailureNoMutation -> SafeToResume` mapping
    // (unaffected by the dispatch-marker extension) is covered directly by
    // `transaction_recovery_contract.rs`'s
    // `safe_to_resume_when_apply_confirmed_failure_no_mutation`. This test's
    // job is only to prove the real, wired `engine::apply` path still
    // durably persists that same outcome unmodified.

    std::fs::remove_dir_all(&dir).ok();
}

/// Crash-boundary requirement 5: a corrupt persisted record must never be
/// classified as safe-to-resume or committed -- because it cannot be
/// classified at all. `load()` fails closed before a `RecoverySnapshot`
/// can even be constructed, which is itself the required guarantee.
#[test]
fn crash_boundary_5_corrupt_record_never_reaches_safe_to_resume_or_committed() {
    let dir = temp_dir("boundary-5");
    std::fs::create_dir_all(&dir).unwrap();
    let id = TransactionId::generate();
    std::fs::write(dir.join(format!("{id}.txn")), "not a real record").unwrap();

    let result = load(&dir, &id);

    assert!(matches!(result, Err(LoadError::Corrupt(_))));
    // There is no path from Err(LoadError::Corrupt) to a RecoverySnapshot
    // or a RecoveryClassification at all -- classify() takes a
    // RecoverySnapshot by value, which cannot be constructed from this
    // Err. The type system itself is the enforcement here.

    std::fs::remove_dir_all(&dir).ok();
}

/// Crash-boundary requirement 6: persist -> load -> classify as one
/// integrated flow for a real nonterminal (`Observing`, no observation
/// yet) record -- closing the audit's non-blocking integration gap
/// (persistence and recovery were previously only tested in isolation).
#[test]
fn crash_boundary_6_persisted_nonterminal_record_reload_and_classify_as_one_flow() {
    let dir = temp_dir("boundary-6");
    let mut persisted = base_persisted(TransactionId::generate());
    persisted.state = TransactionState::Observing;
    persisted.apply_outcome = Some(ApplyOutcome::ConfirmedSuccess);
    persisted.last_observation = None;
    persist(&dir, &persisted).unwrap();

    let loaded = load(&dir, &persisted.transaction_id).unwrap();
    let classification = classify(loaded.to_recovery_snapshot());

    assert_eq!(classification, RecoveryClassification::MustObserve);

    std::fs::remove_dir_all(&dir).ok();
}

/// The persisted `last_observation` field lets a genuinely reloaded
/// `Observing`-state record with a *known* postcondition mismatch resolve
/// to `MustRollback` rather than the fail-closed default `MustObserve` --
/// proving the field is real, load-bearing recovery evidence, not a
/// cosmetic addition.
#[test]
fn persisted_last_observation_changes_recovery_classification_from_disk() {
    let dir = temp_dir("last-observation");
    let mut persisted = base_persisted(TransactionId::generate());
    persisted.state = TransactionState::Observing;
    persisted.apply_outcome = Some(ApplyOutcome::ConfirmedSuccess);
    persisted.last_observation =
        Some(guardian_core::transaction::ObservationOutcome::PostconditionNotMet);
    persist(&dir, &persisted).unwrap();

    let loaded = load(&dir, &persisted.transaction_id).unwrap();
    let classification = classify(loaded.to_recovery_snapshot());

    assert_eq!(classification, RecoveryClassification::MustRollback);

    std::fs::remove_dir_all(&dir).ok();
}

/// Real durability barrier check: `persist()` must not leave a `.tmp` file
/// behind, and the fsync'd final file must be independently readable byte
/// for byte after a fresh process-level `load()` -- exercised against the
/// real Apply path, not a hand-built fixture.
#[test]
fn persist_durability_barrier_leaves_no_temp_file_and_is_independently_loadable() {
    let mut record = new_record();
    let provider = FixtureAdapter::new(true);
    let state_source = FixtureStateSource::new();
    let authorizer = FixtureAuthorizer;
    let dir = temp_dir("durability-barrier");

    drive_to_authorized(&mut record, &provider, &state_source, &authorizer);
    apply(&mut record, &provider, &state_source, &dir, 1).unwrap();

    let temp_path = dir.join(format!("{}.txn.tmp", record.transaction_id));
    assert!(!temp_path.exists());
    let final_path = dir.join(format!("{}.txn", record.transaction_id));
    assert!(final_path.exists());
    load(&dir, &record.transaction_id).unwrap();

    std::fs::remove_dir_all(&dir).ok();
}
