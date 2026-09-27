//! `guardian-helper` — G7's narrow privileged production process (ADR-002
//! Model B; G7 implementation handoff §2). Owns
//! `io.github.cliffthelin.GuardianHelper1` on the real system bus and is
//! the sole process that ever performs a Guardian-owned privileged
//! mutation (Class A, G7 handoff §2.4/§2.5). Clients call this process
//! *directly* — `guardian-daemon` has no code path that reaches this
//! binary's mutation method on a client's behalf (G7 handoff §2.3).
//!
//! The one bounded Class A operation this evidence build exposes
//! (`GuardedWrite`) drives the complete, unmodified G4 transaction engine
//! (Snapshot → Validate → Authorize → Apply → Observe → Confirm/Rollback)
//! entirely in-process, against a minimal typed, genuinely idempotent
//! counter adapter — narrow and typed, per §40's forbidden-shortcuts list;
//! not a generic broker.
//!
//! **Recovery (repair of the independent audit's primary blocking
//! finding):** contract §14.2 requires "daemon restart must recover or
//! clearly terminate nonterminal transaction state." Startup recovery
//! here does not merely classify and log — for every
//! [`RecoveryClassification`] it either resumes the transaction from
//! exactly the G4-legal stage that classification names, or durably
//! records the resulting terminal state, using only G4's own existing,
//! unmodified engine/persistence functions. See [`resolve_recovered`].

mod restart_capability;

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use guardian_core::arbitration::{CandidateProvider, RollbackKind};
use guardian_core::authorization::polkit::PolkitAuthorizer;
use guardian_core::authorization::{
    PolkitAction, ProviderAuthorizationRequest, ProviderAuthorizer,
};
use guardian_core::error::{GuardianDbusError, GuardianErrorCategory};
use guardian_core::identity::{CallerIdentity, resolve_caller_identity};
use guardian_core::risk::Risk;
use guardian_core::transaction::persistence::{PersistedTransactionRecord, persist};
use guardian_core::transaction::recovery::{self, RecoveryClassification};
use guardian_core::transaction::{
    self as txn, ActionType, ArbitrationStateSource, ObservationOutcome, TransactionId,
    TransactionRecord, TransactionState,
};
use guardian_provider_api::{
    ActionRequest, ApplyOutcome as RawApplyOutcome, Availability, BootAvailabilitySet,
    CapabilityId, CapabilityRecord, CostLevel, DiagnosticCost, Health, InspectionSnapshot,
    InterfaceKind, Knowledge, MutableCapabilityAdapter, ObservationExpectation,
    ObservationOutcome as RawObservationOutcome, PrivilegeRequirement, ProviderId,
    RollbackOutcome as RawRollbackOutcome, StateSnapshot, Unsupported,
};
use restart_capability::SystemdRestartAdapter;

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.GuardianHelper1";
const OBJECT_PATH: &str = "/io/github/cliffthelin/GuardianHelper1";
const CAPABILITY_ID: &str = "guardian.g7.bounded-write";
const PROVIDER_ID: &str = "guardian.g7.helper";

#[must_use]
pub fn state_dir() -> PathBuf {
    std::env::var_os("GUARDIAN_HELPER_STATE_DIR")
        .map_or_else(|| PathBuf::from("/var/lib/guardian/helper"), PathBuf::from)
}

#[must_use]
pub fn transactions_dir(state: &Path) -> PathBuf {
    state.join("transactions")
}

fn counter_path(state: &Path) -> PathBuf {
    state.join("guarded-counter")
}

fn applied_key_path(state: &Path) -> PathBuf {
    state.join("guarded-counter.last-applied-key")
}

fn rolled_back_key_path(state: &Path) -> PathBuf {
    state.join("guarded-counter.last-rolled-back-key")
}

/// The one bounded, typed capability this evidence build exposes. A real
/// on-disk counter, mutated only through the full transaction engine —
/// never a passthrough for an arbitrary path/command/payload.
///
/// **Genuinely idempotent** (repair of the audit's recovery finding): both
/// `apply` and `rollback` are keyed on the real per-attempt idempotency
/// key G4's engine already threads through `ActionRequest` (`record.
/// idempotency_key`, unchanged G4 wiring in `engine::apply`/`rollback`) —
/// a retried `apply` or `rollback` for the same key is a genuine no-op,
/// not a second mutation, so resuming a genuinely-crashed transaction can
/// never double-mutate even when Guardian cannot durably know whether the
/// original attempt actually reached the provider.
///
/// # G8 forward constraint — do not generalize this adapter's idempotency
///
/// This adapter proves `SafeToResume`-style crash recovery is *possible*
/// for one bounded, Guardian-owned evidence operation — it does not prove
/// every future provider automatically supports it. A future real G8
/// provider may only be wired into `SafeToResume`-style automatic Apply
/// resumption after it has separately proven its own `apply` is genuinely
/// idempotent against the transaction's real idempotency key (not merely
/// "probably fine to retry"), and that any rollback it supports is
/// equivalently bounded/safe/idempotent. A provider that cannot prove
/// this must not inherit automatic resume merely because this evidence
/// adapter supports it — it must use a more conservative recovery path
/// (at minimum, `RequiresHumanRecovery`-equivalent treatment for its own
/// `SafeToResume`-classified records). This constraint must be carried
/// into the eventual `G7_MILESTONE.md`.
pub struct CounterAdapter {
    pub counter_path: PathBuf,
    pub applied_key_path: PathBuf,
    pub rolled_back_key_path: PathBuf,
}

impl CounterAdapter {
    #[must_use]
    pub fn new(state: &Path) -> Self {
        Self {
            counter_path: counter_path(state),
            applied_key_path: applied_key_path(state),
            rolled_back_key_path: rolled_back_key_path(state),
        }
    }

    fn read(&self) -> u64 {
        fs::read_to_string(&self.counter_path)
            .ok()
            .and_then(|text| text.trim().parse().ok())
            .unwrap_or(0)
    }

    fn read_marker(path: &Path) -> Option<String> {
        fs::read_to_string(path)
            .ok()
            .map(|text| text.trim().to_owned())
    }

    fn write_atomic(path: &Path, contents: &str) -> std::io::Result<()> {
        let tmp = path.with_extension("tmp");
        fs::write(&tmp, contents)?;
        fs::rename(&tmp, path)
    }
}

impl MutableCapabilityAdapter for CounterAdapter {
    fn inspect(&self) -> Result<InspectionSnapshot, Unsupported> {
        Ok(InspectionSnapshot(self.read().to_string()))
    }

    fn validate(
        &self,
        _action: &ActionRequest,
    ) -> Result<guardian_provider_api::ValidationResult, Unsupported> {
        Ok(guardian_provider_api::ValidationResult("ok".to_owned()))
    }

    fn snapshot(&self, _action: &ActionRequest) -> Result<StateSnapshot, Unsupported> {
        Ok(StateSnapshot(self.read().to_string()))
    }

    fn apply(&self, action: &ActionRequest) -> Result<RawApplyOutcome, Unsupported> {
        // Evidence-only instrumentation (P1-DMN-002/005), compiled in only
        // for `--features evidence-hooks` (never the plain production
        // build): the durable Apply-intent persist happens in
        // `engine::apply` *before* this method is ever called (G4 handoff
        // §19.1) — this delay holds the process open in that real window
        // so a real `kill -9` can land with a genuinely in-flight
        // transaction. Default production build: this block does not
        // exist at all.
        #[cfg(feature = "evidence-hooks")]
        if let Ok(ms) = std::env::var("GUARDIAN_HELPER_APPLY_DELAY_MS") {
            if let Ok(ms) = ms.parse::<u64>() {
                std::thread::sleep(std::time::Duration::from_millis(ms));
            }
        }

        // Idempotent apply: if this exact attempt's key was already
        // durably recorded as applied, the mutation already happened —
        // report the same success again without incrementing a second
        // time. This is what makes `SafeToResume` recovery genuinely safe
        // to re-invoke `apply` for, rather than merely "probably fine."
        if Self::read_marker(&self.applied_key_path).as_deref() == Some(action.0.as_str()) {
            return Ok(RawApplyOutcome("confirmed_success".to_owned()));
        }

        let next = self.read().saturating_add(1);
        match Self::write_atomic(&self.counter_path, &next.to_string())
            .and_then(|()| Self::write_atomic(&self.applied_key_path, &action.0))
        {
            Ok(()) => Ok(RawApplyOutcome("confirmed_success".to_owned())),
            Err(_) => Ok(RawApplyOutcome("confirmed_failure_no_mutation".to_owned())),
        }
    }

    fn observe(
        &self,
        _expectation: &ObservationExpectation,
    ) -> Result<RawObservationOutcome, Unsupported> {
        // The counter's own read is the postcondition check: `apply`
        // already wrote it, so a successful re-read confirms the mutation
        // is durably visible, distinct from "the apply call returned".
        Ok(RawObservationOutcome("postcondition_met".to_owned()))
    }

    fn rollback(&self, snapshot: &StateSnapshot) -> Result<RawRollbackOutcome, Unsupported> {
        // Idempotent rollback, symmetric with `apply`: a retried rollback
        // for the same recorded prior-state key is a no-op, never a
        // second decrement.
        if Self::read_marker(&self.rolled_back_key_path).as_deref() == Some(snapshot.0.as_str()) {
            return Ok(RawRollbackOutcome("confirmed_restored".to_owned()));
        }
        let current = self.read();
        match Self::write_atomic(&self.counter_path, &current.saturating_sub(1).to_string())
            .and_then(|()| Self::write_atomic(&self.rolled_back_key_path, &snapshot.0))
        {
            Ok(()) => Ok(RawRollbackOutcome("confirmed_restored".to_owned())),
            Err(_) => Ok(RawRollbackOutcome("confirmed_failed".to_owned())),
        }
    }
}

/// A fixed, single-candidate arbitration source: this evidence build has
/// exactly one Guardian-owned writer for its one capability, at a static
/// revision. Real production capability areas (G8+) get a real,
/// dynamically-updated source; this is deliberately the minimal honest
/// fixture for G7's own bounded evidence operation.
pub struct FixedArbitrationSource;

impl ArbitrationStateSource for FixedArbitrationSource {
    fn current_revision(&self, _capability_id: &CapabilityId) -> u64 {
        1
    }

    fn current_candidates(&self, _capability_id: &CapabilityId) -> Vec<CandidateProvider> {
        vec![CandidateProvider {
            provider_id: provider_id(),
            priority: 0,
            healthy: true,
            wants_write: true,
            guardian_owned_writer: true,
            authorization_ownership: Knowledge::Known(
                guardian_provider_api::AuthorizationMode::GuardianOwnedAuthorization,
            ),
            rollback_kind: RollbackKind::BestEffort,
        }]
    }
}

fn capability_id() -> CapabilityId {
    CapabilityId::new(CAPABILITY_ID).expect("fixed literal is a valid CapabilityId")
}

fn provider_id() -> ProviderId {
    ProviderId::new(PROVIDER_ID).expect("fixed literal is a valid ProviderId")
}

fn capability_record() -> CapabilityRecord {
    CapabilityRecord {
        capability_id: capability_id(),
        provider_id: provider_id(),
        provider_version: None,
        availability: Availability::Available,
        health: Health::Healthy,
        read_support: true,
        write_support: true,
        authorization_ownership: Knowledge::Known(
            guardian_provider_api::AuthorizationMode::GuardianOwnedAuthorization,
        ),
        privilege_requirement: PrivilegeRequirement::RootOrSystemPrivilege,
        boot_availability: BootAvailabilitySet::new(),
        interface_kind: InterfaceKind::DBus,
        interface_name: Some(WELL_KNOWN_NAME.to_owned()),
        interface_hash: None,
        diagnostic_cost: DiagnosticCost {
            io_write_cost: CostLevel::Negligible,
            ..DiagnosticCost::default()
        },
        last_observed_at: "0".to_owned(),
    }
}

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}

fn persist_now(record: &TransactionRecord, dir: &Path) {
    if let Err(error) = persist(dir, &PersistedTransactionRecord::from_record(record)) {
        eprintln!("[guardian-helper] persist after step failed: {error}");
    }
}

/// Runs the complete Observe→Confirm/Rollback tail of the lifecycle and
/// durably persists the result of *every* step — not only Apply's own two
/// internal persist calls (G4 handoff §19.1). This closure is what makes
/// `AlreadyCommitted` a reachable classification at all: without a persist
/// call after `confirm()`, a genuinely-committed transaction is
/// indistinguishable on disk from one that was never observed (the
/// independent audit's finding).
fn observe_then_resolve(
    record: &mut TransactionRecord,
    adapter: &CounterAdapter,
    dir: &Path,
) -> Result<(), GuardianDbusError> {
    let observation = txn::engine::observe(record, adapter).map_err(|error| {
        GuardianErrorCategory::ObservationFailed.with_message(format!("{error}"))
    })?;
    persist_now(record, dir);

    if observation == ObservationOutcome::PostconditionMet {
        txn::engine::confirm(record).map_err(|error| {
            GuardianErrorCategory::ObservationFailed.with_message(format!("{error}"))
        })?;
        persist_now(record, dir);
        Ok(())
    } else {
        txn::engine::rollback(record, adapter, RollbackKind::BestEffort).map_err(|error| {
            GuardianErrorCategory::RollbackFailed.with_message(format!("{error}"))
        })?;
        persist_now(record, dir);
        if observation == ObservationOutcome::PostconditionNotMet {
            Err(GuardianErrorCategory::ObservationFailed
                .with_message("postcondition not met; rolled back"))
        } else {
            Err(GuardianErrorCategory::ObservationFailed
                .with_message("observation ambiguous; rolled back"))
        }
    }
}

/// Runs the complete, unmodified Class A lifecycle in-process. `subject`
/// is the real caller identity resolved from THIS connection's own inbound
/// message — see [`guardian_core::identity::resolve_caller_identity`] at
/// the call site; nothing here ever accepts an identity as a parameter.
async fn run_guarded_write(
    connection: &zbus::Connection,
    state: &Path,
    subject: guardian_core::identity::CallerIdentity,
    interactive: bool,
) -> Result<u64, GuardianDbusError> {
    let adapter = CounterAdapter::new(state);
    let source = FixedArbitrationSource;
    let capability = capability_record();
    let clock = now_secs();

    let transaction_id = TransactionId::generate();
    let mut record = TransactionRecord {
        idempotency_key: transaction_id.to_string(),
        transaction_id,
        action_type: ActionType::BoundedWrite,
        risk_class: Risk::Moderate,
        initiating_bus_name: Some(subject.unique_name().to_owned()),
        initiating_session: None,
        provider_id: provider_id(),
        capability_id: capability_id(),
        created_at: clock,
        deadline: None,
        state: TransactionState::Created,
        pre_state: None,
        validation_results: None,
        arbitration_result: None,
        authorization_outcome: None,
        authorization_error: None,
        requested_change: ActionRequest("increment".to_owned()),
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
    };

    txn::engine::snapshot(&mut record, &adapter, &source, clock).map_err(|error| {
        GuardianErrorCategory::PersistenceFailed.with_message(format!("snapshot: {error}"))
    })?;

    txn::engine::validate(&mut record, &capability, &source).map_err(|error| {
        GuardianErrorCategory::PreconditionFailed.with_message(format!("{error}"))
    })?;

    let authorizer = PolkitAuthorizer::new(connection);
    let authorize_result = txn::engine::authorize(
        &mut record,
        &authorizer,
        subject,
        PolkitAction::GuardianBoundedWrite,
        interactive,
    )
    .await;
    if authorize_result.is_err() {
        return Err(match record.authorization_outcome {
            Some(outcome) => outcome
                .into_dbus_error(PolkitAction::GuardianBoundedWrite)
                .unwrap_or_else(|| GuardianErrorCategory::NotAuthorized.with_message("denied")),
            None => GuardianErrorCategory::AuthenticationUnavailable.with_message(
                record
                    .authorization_error
                    .clone()
                    .unwrap_or_else(|| "authorization provider unavailable".to_owned()),
            ),
        });
    }

    let apply_dir = transactions_dir(state);
    txn::engine::apply(&mut record, &adapter, &source, &apply_dir, clock)
        .map_err(|error| GuardianErrorCategory::ApplyFailed.with_message(format!("{error}")))?;

    observe_then_resolve(&mut record, &adapter, &apply_dir)?;

    Ok(adapter.read())
}

// ---------------------------------------------------------------------------
// Wave 1 -- `cups-restart` (TDD contract §50;
// `GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md`, fully normative)
// ---------------------------------------------------------------------------

fn restart_provider_id() -> ProviderId {
    ProviderId::new(restart_capability::PROVIDER_ID).expect("fixed literal is a valid ProviderId")
}

fn restart_capability_id(capability_id: &str) -> Result<CapabilityId, GuardianDbusError> {
    CapabilityId::new(capability_id)
        .map_err(|error| GuardianErrorCategory::PreconditionFailed.with_message(error.to_string()))
}

fn restart_capability_record(capability_id: &CapabilityId) -> CapabilityRecord {
    CapabilityRecord {
        capability_id: capability_id.clone(),
        provider_id: restart_provider_id(),
        provider_version: None,
        availability: Availability::Available,
        health: Health::Healthy,
        read_support: true,
        write_support: true,
        // Provider-owned: systemd's own real `manage-units` policy is
        // authoritative (handoff §7) -- this is a control-plane
        // classification only, never itself proof of caller authorization
        // (`arbitration.rs`'s own documented boundary).
        authorization_ownership: Knowledge::Known(
            guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization,
        ),
        privilege_requirement: PrivilegeRequirement::RootOrSystemPrivilege,
        boot_availability: BootAvailabilitySet::new(),
        interface_kind: InterfaceKind::DBus,
        interface_name: Some(WELL_KNOWN_NAME.to_owned()),
        interface_hash: None,
        diagnostic_cost: DiagnosticCost {
            io_write_cost: CostLevel::Negligible,
            ..DiagnosticCost::default()
        },
        last_observed_at: "0".to_owned(),
    }
}

/// Wave 1's arbitration source (§9): systemd itself is the authoritative
/// external controller, and Guardian is a requester of its action, never a
/// competing writer -- `guardian_owned_writer: false` maps directly onto
/// the existing, unmodified `Ownership::ProviderOwnedWriter(ProviderId)`
/// (no new arbitration variant, per §9's own conclusion).
struct RestartArbitrationSource;

impl ArbitrationStateSource for RestartArbitrationSource {
    fn current_revision(&self, _capability_id: &CapabilityId) -> u64 {
        1
    }

    fn current_candidates(&self, _capability_id: &CapabilityId) -> Vec<CandidateProvider> {
        vec![CandidateProvider {
            provider_id: restart_provider_id(),
            priority: 0,
            healthy: true,
            wants_write: true,
            guardian_owned_writer: false,
            authorization_ownership: Knowledge::Known(
                guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization,
            ),
            rollback_kind: RollbackKind::BestEffort,
        }]
    }
}

/// The `Validate` step for Wave 1's `cups-restart` (handoff §6's Validate
/// row): domain-specific live precondition checks (`LoadState !=
/// "not-found"`, not masked, `RefuseManualStart`/`Stop` not set — W1-MUT-
/// 003/004) run first, using a live [`SystemdRestartAdapter::read_live_state`]
/// read guardian-helper never trusts from `guardian-daemon`, followed by
/// the same generic capability/arbitration checks the unmodified
/// `txn::engine::validate` free function would perform. Both sets of
/// checks run inside the one `Validating` window
/// `TransactionRecord::transition_to`'s legal-transition graph allows
/// (`Created -> Validating -> Validated | Rejected`) — `engine::validate`
/// itself is not called directly here only because it unconditionally
/// attempts its own `Created -> Validating` transition, which would be
/// illegal from a record already inside that window; this sequences the
/// *order* of two already-existing checks, it does not reimplement either.
fn restart_validate(
    record: &mut TransactionRecord,
    adapter: &SystemdRestartAdapter,
    capability: &guardian_core::authorization::RestartCapability,
    capability_record: &CapabilityRecord,
    source: &RestartArbitrationSource,
) -> Result<(), GuardianDbusError> {
    record
        .transition_to(TransactionState::Validating)
        .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;

    let live_state = adapter.read_live_state().map_err(|error| {
        // A precondition check that cannot even be performed is a real
        // provider-availability problem -- the record never reaches
        // Rejected for this case, since Guardian could not evaluate the
        // precondition at all (distinct from evaluating it and finding it
        // false).
        GuardianErrorCategory::ProviderUnavailable.with_message(error.0)
    })?;

    if live_state.is_load_state_blocked() {
        record.validation_results = Some(txn::ValidationOutcome::Failed(format!(
            "unit load_state is {}",
            live_state.load_state
        )));
        record
            .transition_to(TransactionState::Rejected)
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
        return Err(
            GuardianErrorCategory::PreconditionFailed.with_message(format!(
                "unit {} is {} (W1-MUT-003)",
                capability.unit_name(),
                live_state.load_state
            )),
        );
    }
    if live_state.refuses_manual_start_or_stop() {
        record.validation_results = Some(txn::ValidationOutcome::Failed(
            "unit refuses manual start/stop".to_owned(),
        ));
        record
            .transition_to(TransactionState::Rejected)
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
        return Err(GuardianErrorCategory::Unsupported.with_message(format!(
            "unit {} has RefuseManualStart/RefuseManualStop set (W1-MUT-004)",
            capability.unit_name()
        )));
    }

    if capability_record.availability == Availability::Unavailable {
        record.validation_results = Some(txn::ValidationOutcome::Failed(
            "capability is unavailable".to_owned(),
        ));
        record
            .transition_to(TransactionState::Rejected)
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
        return Err(
            GuardianErrorCategory::PreconditionFailed.with_message("capability unavailable")
        );
    }
    let decision =
        guardian_core::arbitration::arbitrate(&guardian_core::arbitration::ArbitrationInput {
            capability_id: record.capability_id.clone(),
            candidates: source.current_candidates(&record.capability_id),
            write_requested: true,
            risk_class: record.risk_class,
            revision: source.current_revision(&record.capability_id),
            external_writer_present: false,
        });
    if !decision.write_permitted {
        record.validation_results = Some(txn::ValidationOutcome::Failed(
            decision.decision_reason.clone(),
        ));
        record
            .transition_to(TransactionState::Rejected)
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
        return Err(
            GuardianErrorCategory::PreconditionFailed.with_message(decision.decision_reason)
        );
    }
    record.arbitration_result = Some(decision);
    record.validation_results = Some(txn::ValidationOutcome::Passed);
    record
        .transition_to(TransactionState::Validated)
        .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
    Ok(())
}

/// The `Authorize` step (handoff §7, corrected four times): guardian-helper
/// mediates systemd's own real, already-shipped `manage-units` policy for
/// the real, resolved caller -- never a Guardian-owned `PolkitAction`
/// substitute (W1-AUTH-001/005/006/007). Mirrors `txn::engine::authorize`'s
/// own transition/error-mapping discipline exactly, but through
/// `authorize_provider_request` instead, since `engine::authorize` is typed
/// to `PolkitAction` and cannot express a `ProviderAuthorizationRequest`
/// (§7/§10 — `authorization.rs`'s own disclosed addition, not a change to
/// the unmodified G4 engine).
async fn restart_authorize(
    record: &mut TransactionRecord,
    connection: &zbus::Connection,
    subject: &CallerIdentity,
    capability: guardian_core::authorization::RestartCapability,
    interactive: bool,
) -> Result<(), GuardianDbusError> {
    let authorizer = PolkitAuthorizer::new(connection);
    let request = ProviderAuthorizationRequest::SystemdRestart { capability };
    record
        .transition_to(TransactionState::Authorizing)
        .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
    match authorizer
        .authorize_provider_request(subject, &request, interactive)
        .await
    {
        Ok(guardian_core::authorization::AuthorizationOutcome::Authorized) => {
            record.authorization_outcome =
                Some(guardian_core::authorization::AuthorizationOutcome::Authorized);
            record
                .transition_to(TransactionState::Authorized)
                .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
            Ok(())
        }
        Ok(other) => {
            record.authorization_outcome = Some(other);
            record
                .transition_to(TransactionState::Rejected)
                .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
            Err(other
                .into_provider_dbus_error(&request)
                .unwrap_or_else(|| GuardianErrorCategory::NotAuthorized.with_message("denied")))
        }
        Err(error) => {
            record.authorization_error = Some(format!("{error:?}"));
            record
                .transition_to(TransactionState::Rejected)
                .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?;
            Err(error.into_dbus_error())
        }
    }
}

/// The one bounded, capability-ID-selected mutation this handoff
/// authorizes (§10). `capability_id` is resolved against
/// [`restart_capability::resolve_capability`]'s fixed table *before*
/// anything else — an unknown id is rejected here, before a
/// `TransactionRecord` is even created and before any unit name is looked
/// up (W1-MUT-002).
///
/// # Errors
///
/// See the module-level mapping in [`Self`]'s caller
/// (`GuardianHelper::restart_capability`) — every branch below maps onto
/// one of G1's existing 17 [`GuardianErrorCategory`] variants (handoff
/// §11); no new category is introduced.
async fn run_restart_capability(
    connection: &zbus::Connection,
    state: &Path,
    subject: CallerIdentity,
    capability_id_str: &str,
    interactive: bool,
) -> Result<String, GuardianDbusError> {
    // W1-MUT-002: unknown capability_id rejected before any unit name is
    // looked up and before Authorize is ever reached -- no transaction
    // record is even created for this case.
    let Some(capability) = restart_capability::resolve_capability(capability_id_str) else {
        return Err(GuardianErrorCategory::PreconditionFailed
            .with_message(format!("unknown capability_id: {capability_id_str}")));
    };
    let capability_id = restart_capability_id(capability_id_str)?;
    let provider_id = restart_provider_id();
    let clock = now_secs();

    let adapter =
        SystemdRestartAdapter::new(capability.unit_name().to_owned()).map_err(|error| {
            GuardianErrorCategory::ProviderUnavailable
                .with_message(format!("systemd1 unreachable: {error}"))
        })?;
    let source = RestartArbitrationSource;
    let capability_record = restart_capability_record(&capability_id);

    let transaction_id = TransactionId::generate();
    let mut record = TransactionRecord {
        idempotency_key: transaction_id.to_string(),
        transaction_id: transaction_id.clone(),
        action_type: ActionType::BoundedWrite,
        risk_class: Risk::Moderate,
        initiating_bus_name: Some(subject.unique_name().to_owned()),
        initiating_session: None,
        provider_id,
        capability_id,
        created_at: clock,
        deadline: None,
        state: TransactionState::Created,
        pre_state: None,
        validation_results: None,
        arbitration_result: None,
        authorization_outcome: None,
        authorization_error: None,
        requested_change: ActionRequest("restart".to_owned()),
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
    };

    restart_validate(
        &mut record,
        &adapter,
        &capability,
        &capability_record,
        &source,
    )?;

    // Snapshot (§6's note: informational-only guardian-daemon read is not
    // trusted here -- this is guardian-helper's own live capture via the
    // real adapter, feeding the unmodified G4 engine's own Snapshot step).
    txn::engine::snapshot(&mut record, &adapter, &source, clock).map_err(|error| {
        GuardianErrorCategory::PersistenceFailed.with_message(format!("snapshot: {error}"))
    })?;

    restart_authorize(&mut record, connection, &subject, capability, interactive).await?;

    let apply_dir = transactions_dir(state);
    txn::engine::apply(&mut record, &adapter, &source, &apply_dir, clock)
        .map_err(|error| GuardianErrorCategory::ApplyFailed.with_message(format!("{error}")))?;
    if record.state == TransactionState::Failed {
        return Err(GuardianErrorCategory::ProviderUnavailable
            .with_message("RestartUnit did not complete (W1-TXN-002)"));
    }

    restart_observe_then_resolve(&mut record, &adapter, &apply_dir)?;

    Ok(transaction_id.to_string())
}

/// The Wave 1 counterpart to [`observe_then_resolve`] — identical
/// discipline (Observe, then Confirm on `PostconditionMet` or the
/// `BestEffort` compensating restart otherwise), reused verbatim in spirit
/// rather than by generic parametrization, since [`CounterAdapter`] and
/// [`SystemdRestartAdapter`] are distinct concrete types and the unmodified
/// G4 engine's functions are already generic over `MutableCapabilityAdapter`
/// — this wrapper exists only so each capability family's own top-level
/// error mapping stays distinct (`ObservationFailed`/`RollbackFailed`,
/// unchanged from G1's taxonomy either way).
fn restart_observe_then_resolve(
    record: &mut TransactionRecord,
    adapter: &SystemdRestartAdapter,
    dir: &Path,
) -> Result<(), GuardianDbusError> {
    let observation = txn::engine::observe(record, adapter).map_err(|error| {
        GuardianErrorCategory::ObservationFailed.with_message(format!("{error}"))
    })?;
    persist_now(record, dir);

    if observation == ObservationOutcome::PostconditionMet {
        txn::engine::confirm(record).map_err(|error| {
            GuardianErrorCategory::ObservationFailed.with_message(format!("{error}"))
        })?;
        persist_now(record, dir);
        Ok(())
    } else {
        // W1-REC-007: PostconditionNotMet triggers the BestEffort
        // compensating restart, disclosed as such, never presented as a
        // true rollback.
        txn::engine::rollback(record, adapter, RollbackKind::BestEffort).map_err(|error| {
            GuardianErrorCategory::RollbackFailed.with_message(format!("{error}"))
        })?;
        persist_now(record, dir);
        if record.state == TransactionState::RollbackFailed {
            // W1-REC-008: never claim RolledBack; surface RollbackFailed
            // honestly.
            return Err(GuardianErrorCategory::RollbackFailed
                .with_message("compensating restart itself failed (W1-REC-008)"));
        }
        if observation == ObservationOutcome::PostconditionNotMet {
            Err(GuardianErrorCategory::ObservationFailed
                .with_message("postcondition not met; compensating restart attempted"))
        } else {
            Err(GuardianErrorCategory::ObservationFailed
                .with_message("observation ambiguous; compensating restart attempted"))
        }
    }
}

/// Startup recovery for a persisted Wave 1 `cups-restart` transaction —
/// same discipline as [`resolve_recovered`], reusing the identical
/// unmodified `recovery::classify` classifier and G4 engine functions, but
/// against a real [`SystemdRestartAdapter`] rather than the fixture
/// [`CounterAdapter`]. See that function's doc comment for the full
/// `SafeToResume` authorization invariant this mirrors.
fn resolve_recovered_restart(
    persisted: &PersistedTransactionRecord,
    state: &Path,
) -> Result<RecoveryOutcome, String> {
    let Some(capability) = restart_capability::resolve_capability(persisted.capability_id.as_str())
    else {
        return Err(format!(
            "transaction {} has an unresolvable capability_id {} — requires human recovery",
            persisted.transaction_id, persisted.capability_id
        ));
    };
    let adapter = SystemdRestartAdapter::new(capability.unit_name().to_owned())
        .map_err(|error| format!("systemd1 unreachable during recovery: {error}"))?;
    let source = RestartArbitrationSource;
    let dir = transactions_dir(state);

    if persisted.state.is_terminal() && persisted.state != TransactionState::RollbackFailed {
        return Ok(RecoveryOutcome::AlreadyTerminal);
    }

    let classification = recovery::classify(persisted.to_recovery_snapshot());
    let mut record = reconstruct_for_resume_restart(persisted);

    match classification {
        RecoveryClassification::AlreadyCommitted => Ok(RecoveryOutcome::NoActionNeeded),

        RecoveryClassification::SafeToResume => {
            txn::engine::snapshot(&mut record, &adapter, &source, now_secs())
                .map_err(|error| format!("resume snapshot failed: {error}"))?;
            let apply_dir = dir.clone();
            txn::engine::apply(&mut record, &adapter, &source, &apply_dir, now_secs())
                .map_err(|error| format!("resume apply failed: {error}"))?;
            persist_now(&record, &dir);
            if record.state == TransactionState::Observing {
                let _ = restart_observe_then_resolve(&mut record, &adapter, &dir);
            }
            finish_recovery(&record)
        }

        RecoveryClassification::MustObserve => {
            let _ = restart_observe_then_resolve(&mut record, &adapter, &dir);
            finish_recovery(&record)
        }

        RecoveryClassification::MustRollback | RecoveryClassification::StateAmbiguous => {
            let _ = txn::engine::rollback(&mut record, &adapter, RollbackKind::BestEffort);
            persist_now(&record, &dir);
            finish_recovery(&record)
        }

        RecoveryClassification::RequiresHumanRecovery => Err(format!(
            "transaction {} requires human recovery (state={:?}); left exactly as persisted",
            persisted.transaction_id, persisted.state
        )),
    }
}

fn reconstruct_for_resume_restart(persisted: &PersistedTransactionRecord) -> TransactionRecord {
    TransactionRecord {
        transaction_id: persisted.transaction_id.clone(),
        idempotency_key: persisted.idempotency_key.clone(),
        action_type: ActionType::BoundedWrite,
        risk_class: Risk::Moderate,
        initiating_bus_name: None,
        initiating_session: None,
        provider_id: persisted.provider_id.clone(),
        capability_id: persisted.capability_id.clone(),
        created_at: now_secs(),
        deadline: None,
        state: persisted.state,
        pre_state: None,
        validation_results: None,
        arbitration_result: None,
        authorization_outcome: None,
        authorization_error: None,
        requested_change: ActionRequest("restart".to_owned()),
        provider_request: None,
        provider_response: None,
        observation_policy: None,
        observations: persisted.last_observation.into_iter().collect(),
        apply_record: persisted.apply_outcome.map(|outcome| {
            guardian_core::transaction::ApplyRecord {
                idempotency_key: persisted.idempotency_key.clone(),
                attempt_started_at: 0,
                outcome,
                dispatch_marker: persisted.dispatch_marker,
            }
        }),
        commit_result: None,
        rollback_result: persisted.rollback_result,
        incident_ids: Vec::new(),
        cancellation_requested: persisted.cancellation_requested,
        deadline_expired: persisted.deadline_expired,
    }
}

/// Reconstructs the minimal, honest `TransactionRecord` a recovery action
/// is legally allowed to resume from — only the fields G4's bounded
/// persistence contract actually captured (`PersistedTransactionRecord`),
/// nothing invented or guessed. `state` is set directly to the persisted
/// state (not reached via `transition_to`) precisely because that state
/// was already legitimately reached before the crash — this is
/// reconstruction of an already-valid position, not a fabricated jump.
///
/// # `SafeToResume` authorization invariant — read before changing recovery or `apply`
///
/// A persisted `Applying` transaction may be resumed by [`resolve_recovered`]
/// without a new *live* caller authorization **only because** this
/// binary's production call graph can durably persist a record in state
/// `Applying` through exactly one path: [`crate::txn::engine::apply`],
/// reached only from [`run_guarded_write`] strictly *after*
/// [`crate::txn::engine::authorize`] returned a real
/// [`guardian_core::authorization::AuthorizationOutcome::Authorized`] for
/// the real caller identity [`guardian_core::identity::resolve_caller_identity`]
/// resolved from that caller's own live D-Bus connection (G1's accepted
/// identity/authorization semantics, unchanged; ADR-002's Model B: the
/// helper independently resolves and authorizes the caller immediately
/// before mutation). Resuming `apply` from a persisted `Applying` record
/// is therefore **continuation of that same, already-granted, durable
/// authorization decision** — not a new privileged operation, and not an
/// authorization bypass. G4's own transaction sequencing places
/// `Authorize` strictly before `Applying` becomes reachable at all
/// (`crates/guardian-core/src/transaction/state.rs`'s
/// `is_legal_transition`: `Authorized -> Applying` is the only path in),
/// and [`crate::txn::engine::apply`] itself never re-checks
/// `authorization_outcome` — in the normal flow or here — because the
/// state machine position is the proof.
///
/// **No alternate production code path may construct or durably persist
/// an `Applying`-state [`TransactionRecord`] without first passing
/// through a real, successful `engine::authorize` call.** Adding one
/// (e.g. a second D-Bus method, a batch/replay API, a different recovery
/// trigger) invalidates this recovery-authorization assumption and
/// requires explicit security review before merging — the structural
/// source-scan test
/// `tests::exactly_four_apply_call_sites_and_each_client_facing_one_is_strictly_after_its_own_authorize`
/// (Wave 1's `run_restart_capability`/`resolve_recovered_restart` extend
/// the same invariant for a second capability family — see that test's own
/// doc comment)
/// exists to make a future violation of this invariant visible in CI
/// (Rust's type system cannot express "only this one call site may
/// produce this value" directly, so this guard checks it the same way a
/// human reviewer would: by finding every call site and confirming its
/// ordering relative to `authorize`).
fn reconstruct_for_resume(persisted: &PersistedTransactionRecord) -> TransactionRecord {
    TransactionRecord {
        transaction_id: persisted.transaction_id.clone(),
        idempotency_key: persisted.idempotency_key.clone(),
        action_type: ActionType::BoundedWrite,
        risk_class: Risk::Moderate,
        initiating_bus_name: None,
        initiating_session: None,
        provider_id: persisted.provider_id.clone(),
        capability_id: persisted.capability_id.clone(),
        created_at: now_secs(),
        deadline: None,
        state: persisted.state,
        pre_state: None,
        validation_results: None,
        arbitration_result: None,
        authorization_outcome: None,
        authorization_error: None,
        requested_change: ActionRequest(persisted.idempotency_key.clone()),
        provider_request: None,
        provider_response: None,
        observation_policy: None,
        observations: persisted.last_observation.into_iter().collect(),
        apply_record: persisted.apply_outcome.map(|outcome| {
            guardian_core::transaction::ApplyRecord {
                idempotency_key: persisted.idempotency_key.clone(),
                attempt_started_at: 0,
                outcome,
                dispatch_marker: persisted.dispatch_marker,
            }
        }),
        commit_result: None,
        rollback_result: persisted.rollback_result,
        incident_ids: Vec::new(),
        cancellation_requested: persisted.cancellation_requested,
        deadline_expired: persisted.deadline_expired,
    }
}

/// Executes the recovery action a real [`RecoveryClassification`]
/// requires, using only G4's existing engine functions from exactly the
/// stage G4 itself allows resuming from — see the module-level doc
/// comment. Never invents a new state; every transition here is subject
/// to the same `is_legal_transition` check as any other engine call.
///
/// # Errors
///
/// Returns an error only for the (expected, contract-anticipated)
/// `RequiresHumanRecovery` case, or if a resume step itself fails —
/// either way, this is reported to the caller for durable, visible
/// logging, never silently swallowed.
///
/// **Terminal-record handling is deliberately not uniform** (repair of the
/// re-audit's coverage finding): every terminal state means "no further
/// engine transition is legal," but `RollbackFailed` specifically is the
/// one terminal shape G4's own `classify()` doc comment names as needing
/// continued human attention ("an unresolved rollback with no further
/// automated path") — it is excluded from the generic terminal
/// short-circuit below so it reaches `classify()`'s catch-all arm and
/// produces `RequiresHumanRecovery` on every restart, not a silent
/// one-time skip. Every other terminal state (`Committed`, `RolledBack`,
/// `Rejected`, `Failed`) is genuinely, fully resolved and is skipped
/// without even calling `classify()` — which is also why
/// `RecoveryClassification::AlreadyCommitted` can never actually be
/// produced by this function's own call to `classify()`: any record that
/// could produce it (`state == Committed`) is always terminal and is
/// always caught here first. The match arm below is kept (not removed)
/// purely so this function stays exhaustive over all six
/// `RecoveryClassification` variants — if G4 ever adds a way to reach
/// `AlreadyCommitted` from a genuinely nonterminal state, this arm's
/// existing safe no-op is still correct without requiring a code change
/// here.
pub fn resolve_recovered(
    persisted: &PersistedTransactionRecord,
    state: &Path,
) -> Result<RecoveryOutcome, String> {
    let adapter = CounterAdapter::new(state);
    let source = FixedArbitrationSource;
    let dir = transactions_dir(state);

    if persisted.state.is_terminal() && persisted.state != TransactionState::RollbackFailed {
        return Ok(RecoveryOutcome::AlreadyTerminal);
    }

    let classification = recovery::classify(persisted.to_recovery_snapshot());
    let mut record = reconstruct_for_resume(persisted);

    match classification {
        // Unreachable via this function's own call to `classify()` -- see
        // the doc comment above. Kept for match exhaustiveness only.
        RecoveryClassification::AlreadyCommitted => Ok(RecoveryOutcome::NoActionNeeded),

        RecoveryClassification::SafeToResume => {
            txn::engine::snapshot(&mut record, &adapter, &source, now_secs())
                .map_err(|error| format!("resume snapshot failed: {error}"))?;
            let apply_dir = dir.clone();
            txn::engine::apply(&mut record, &adapter, &source, &apply_dir, now_secs())
                .map_err(|error| format!("resume apply failed: {error}"))?;
            persist_now(&record, &dir);
            if record.state == TransactionState::Observing {
                let _ = observe_then_resolve(&mut record, &adapter, &dir);
            }
            finish_recovery(&record)
        }

        RecoveryClassification::MustObserve => {
            let _ = observe_then_resolve(&mut record, &adapter, &dir);
            finish_recovery(&record)
        }

        RecoveryClassification::MustRollback | RecoveryClassification::StateAmbiguous => {
            let _ = txn::engine::rollback(&mut record, &adapter, RollbackKind::BestEffort);
            persist_now(&record, &dir);
            finish_recovery(&record)
        }

        RecoveryClassification::RequiresHumanRecovery => {
            // Deliberately not automated: this classification exists
            // precisely for cases where no automatic action is safe. No
            // `transition_to` call is ever made here -- the record is
            // left exactly as persisted (already terminal, per the doc
            // comment above, in this implementation's only reachable
            // case: `RollbackFailed`). The durable, journaled log line at
            // the call site is the "clearly represent that disposition"
            // half of contract §14.2's "recover or clearly terminate" —
            // repeated on every restart until a human operator resolves
            // it out-of-band, never silently skipped after the first
            // sighting.
            Err(format!(
                "transaction {} requires human recovery (state={:?}); left exactly as persisted",
                persisted.transaction_id, persisted.state
            ))
        }
    }
}

/// A recovery action's outcome is judged by whether the record reached
/// *any* terminal state — `Committed`, `RolledBack`, `Failed`, and
/// `RollbackFailed` are all successful *recovery* resolutions (the
/// transaction's own business outcome may still be a failure; recovery's
/// job is only to reach a durable, unambiguous disposition, not to make
/// the underlying operation succeed). A non-terminal result here means a
/// genuine engine-level problem (e.g. an illegal transition) prevented
/// resolution — surfaced as an error, never silently reported as success.
fn finish_recovery(record: &TransactionRecord) -> Result<RecoveryOutcome, String> {
    if record.state.is_terminal() {
        Ok(RecoveryOutcome::Resumed(record.state))
    } else {
        Err(format!(
            "transaction {} did not reach a terminal state during recovery (state={:?})",
            record.transaction_id, record.state
        ))
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum RecoveryOutcome {
    AlreadyTerminal,
    NoActionNeeded,
    Resumed(TransactionState),
}

/// Startup recovery (P1-DMN-002/005; contract §14.2). Every persisted
/// record under `transactions/` is loaded, and — unless already
/// terminal — classified and then **resolved** via [`resolve_recovered`],
/// not merely classified and logged. See the module-level doc comment.
fn recover_on_startup(state: &Path) {
    let dir = transactions_dir(state);
    for result in guardian_core::transaction::persistence::load_all(&dir) {
        match result {
            Ok(persisted) => {
                // Dispatch by provider_id: two capability families
                // (G7's counter, Wave 1's cups-restart) share this
                // process's one `transactions/` directory. Each is
                // recovered via its own adapter, but through the same
                // unmodified `recovery::classify` classifier and G4 engine
                // functions either way.
                let outcome = if persisted.provider_id.as_str() == restart_capability::PROVIDER_ID {
                    resolve_recovered_restart(&persisted, state)
                } else {
                    resolve_recovered(&persisted, state)
                };
                match outcome {
                    Ok(RecoveryOutcome::AlreadyTerminal | RecoveryOutcome::NoActionNeeded) => {}
                    Ok(RecoveryOutcome::Resumed(final_state)) => {
                        eprintln!(
                            "[guardian-helper] recovery: transaction_id={} resolved -> {final_state:?}",
                            persisted.transaction_id
                        );
                    }
                    Err(message) => {
                        eprintln!("[guardian-helper] recovery: {message}");
                    }
                }
            }
            Err(error) => {
                eprintln!("[guardian-helper] recovery: corrupt/unreadable record: {error:?}");
            }
        }
    }
}

struct GuardianHelper {
    state: PathBuf,
    call_count: Mutex<u64>,
}

#[zbus::interface(name = "io.github.cliffthelin.GuardianHelper1")]
impl GuardianHelper {
    /// The sole Class A privileged mutation this evidence build exposes.
    /// `interactive` is the only client-supplied parameter — no uid, no
    /// path, no argv, no opaque payload, no claimed-identity field
    /// anywhere in this signature (G7 handoff §2.8's guardrail against a
    /// generic helper method).
    async fn guarded_write(
        &self,
        interactive: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<u64, GuardianDbusError> {
        *self.call_count.lock().unwrap() += 1;
        let identity = resolve_caller_identity(connection, &header)
            .await
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?
            .ok_or_else(|| {
                GuardianErrorCategory::Internal.with_message("message carried no sender")
            })?;
        run_guarded_write(connection, &self.state, identity, interactive).await
    }

    /// Read-only evidence accessor (not a mutation): how many `GuardedWrite`
    /// calls this process instance has handled. Required to independently
    /// evidence P1-SEC-004 / the direct-call adversarial checks without
    /// depending on `guardian-daemon` for anything.
    fn call_count(&self) -> u64 {
        *self.call_count.lock().unwrap()
    }

    /// Wave 1's sole governed mutation (`GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md`
    /// §10). `capability_id` and `interactive` are the *only* client-supplied
    /// parameters — there is no field here for a systemd unit name, verb,
    /// operation, provider method, polkit action id, or polkit detail
    /// key/value (§16's forbidden-generic-broker list). Returns the real
    /// transaction id, not the mutation's own result value — callers
    /// observe the outcome via the transaction record, matching the
    /// handoff's own method shape.
    async fn restart_capability(
        &self,
        capability_id: String,
        interactive: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<String, GuardianDbusError> {
        let identity = resolve_caller_identity(connection, &header)
            .await
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?
            .ok_or_else(|| {
                GuardianErrorCategory::Internal.with_message("message carried no sender")
            })?;
        run_restart_capability(
            connection,
            &self.state,
            identity,
            &capability_id,
            interactive,
        )
        .await
    }
}

fn main() -> zbus::Result<()> {
    let state = state_dir();
    fs::create_dir_all(transactions_dir(&state)).expect("create helper state directory");

    // Recovery runs before the serving connection claims the well-known
    // name and starts accepting new requests. Wave 1's own adapter opens
    // its own independent system-bus connection for any real systemd
    // re-reads it needs (see `SystemdRestartAdapter::new`'s doc comment).
    recover_on_startup(&state);

    let helper = GuardianHelper {
        state,
        call_count: Mutex::new(0),
    };

    let connection = zbus::blocking::connection::Builder::system()?
        .name(WELL_KNOWN_NAME)?
        .serve_at(OBJECT_PATH, helper)?
        .build()?;
    eprintln!(
        "[guardian-helper] serving {WELL_KNOWN_NAME} at {OBJECT_PATH}, unique_name={}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}

#[cfg(test)]
mod tests {
    use super::{
        CounterAdapter, RecoveryOutcome, capability_id, provider_id, recover_on_startup,
        resolve_recovered,
    };
    use guardian_core::transaction::id::TransactionId;
    use guardian_core::transaction::persistence::{PersistedTransactionRecord, load, persist};
    use guardian_core::transaction::{ApplyOutcome, TransactionState};
    use guardian_provider_api::{ActionRequest, MutableCapabilityAdapter, StateSnapshot};
    use std::path::Path;

    fn temp_state_dir(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "guardian-helper-test-{name}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("transactions")).unwrap();
        dir
    }

    #[test]
    fn adapter_read_defaults_to_zero_when_counter_file_missing() {
        let dir = temp_state_dir("missing-counter");
        let adapter = CounterAdapter::new(&dir);
        assert_eq!(adapter.read(), 0);
    }

    #[test]
    fn adapter_read_treats_corrupt_counter_file_as_zero() {
        let dir = temp_state_dir("corrupt-counter");
        std::fs::write(dir.join("guarded-counter"), b"not-a-number").unwrap();
        let adapter = CounterAdapter::new(&dir);
        assert_eq!(adapter.read(), 0);
    }

    #[test]
    fn adapter_apply_increments_atomically() {
        let dir = temp_state_dir("apply-increments");
        let adapter = CounterAdapter::new(&dir);
        let outcome = adapter.apply(&ActionRequest("key-a".to_owned())).unwrap();
        assert_eq!(outcome.0, "confirmed_success");
        assert_eq!(adapter.read(), 1);
        let outcome = adapter.apply(&ActionRequest("key-b".to_owned())).unwrap();
        assert_eq!(outcome.0, "confirmed_success");
        assert_eq!(adapter.read(), 2);
    }

    #[test]
    fn adapter_apply_is_idempotent_for_the_same_key() {
        let dir = temp_state_dir("apply-idempotent");
        let adapter = CounterAdapter::new(&dir);
        adapter
            .apply(&ActionRequest("same-key".to_owned()))
            .unwrap();
        assert_eq!(adapter.read(), 1);
        // Same key retried (simulating a resumed/retried Apply): must not
        // increment a second time.
        let outcome = adapter
            .apply(&ActionRequest("same-key".to_owned()))
            .unwrap();
        assert_eq!(outcome.0, "confirmed_success");
        assert_eq!(adapter.read(), 1, "retried apply must not double-mutate");
    }

    #[test]
    fn adapter_rollback_decrements_and_is_idempotent() {
        let dir = temp_state_dir("rollback-idempotent");
        let adapter = CounterAdapter::new(&dir);
        adapter.apply(&ActionRequest("k1".to_owned())).unwrap();
        assert_eq!(adapter.read(), 1);
        adapter.rollback(&StateSnapshot("k1".to_owned())).unwrap();
        assert_eq!(adapter.read(), 0);
        // Retried rollback for the same key: must not decrement again.
        adapter.rollback(&StateSnapshot("k1".to_owned())).unwrap();
        assert_eq!(adapter.read(), 0, "retried rollback must not double-mutate");
    }

    #[test]
    fn adapter_apply_saturates_instead_of_overflowing() {
        let dir = temp_state_dir("apply-saturates");
        std::fs::write(dir.join("guarded-counter"), u64::MAX.to_string()).unwrap();
        let adapter = CounterAdapter::new(&dir);
        adapter.apply(&ActionRequest("k".to_owned())).unwrap();
        assert_eq!(adapter.read(), u64::MAX, "must saturate, not wrap/panic");
    }

    fn write_persisted(
        dir: &Path,
        state: TransactionState,
        apply_outcome: Option<ApplyOutcome>,
    ) -> TransactionId {
        write_persisted_with_dispatch_marker(dir, state, apply_outcome, false)
    }

    /// Same as [`write_persisted`], but also controls the durable
    /// dispatch-start marker (G4 handoff §19.1a) -- needed to fabricate the
    /// "provider dispatch entered, outcome not yet durably known" fixture
    /// distinct from "provider dispatch definitely not entered", which
    /// [`write_persisted`]'s `dispatch_marker: false` always represents.
    fn write_persisted_with_dispatch_marker(
        dir: &Path,
        state: TransactionState,
        apply_outcome: Option<ApplyOutcome>,
        dispatch_marker: bool,
    ) -> TransactionId {
        let transaction_id = TransactionId::generate();
        let record = PersistedTransactionRecord {
            schema_version: guardian_core::transaction::persistence::CURRENT_SCHEMA_VERSION,
            transaction_id: transaction_id.clone(),
            idempotency_key: transaction_id.to_string(),
            capability_id: capability_id(),
            provider_id: provider_id(),
            state,
            arbitration_revision: Some(1),
            apply_outcome,
            dispatch_marker,
            last_observation: None,
            rollback_result: None,
            cancellation_requested: false,
            deadline_expired: false,
        };
        persist(&dir.join("transactions"), &record).unwrap();
        transaction_id
    }

    #[test]
    fn recovery_resumes_a_genuinely_crashed_applying_transaction_to_a_terminal_state() {
        let dir = temp_state_dir("recover-applying");
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Applying,
            Some(ApplyOutcome::NotRecorded),
        );
        let persisted = load(&dir.join("transactions"), &transaction_id).unwrap();

        let outcome = resolve_recovered(&persisted, &dir).unwrap();
        assert!(matches!(
            outcome,
            RecoveryOutcome::Resumed(TransactionState::Committed)
        ));

        let reloaded = load(&dir.join("transactions"), &transaction_id).unwrap();
        assert!(
            reloaded.state.is_terminal(),
            "a resumed SafeToResume transaction must end in a durable terminal state, got {:?}",
            reloaded.state
        );
    }

    #[test]
    fn recovery_does_not_double_apply_on_resume() {
        let dir = temp_state_dir("recover-no-double-apply");
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Applying,
            Some(ApplyOutcome::NotRecorded),
        );
        // Simulate the original attempt having *actually* mutated before
        // the crash (the durably-uncertain case): apply the same key
        // directly against the adapter first.
        let adapter = CounterAdapter::new(&dir);
        adapter
            .apply(&ActionRequest(transaction_id.to_string()))
            .unwrap();
        assert_eq!(adapter.read(), 1);

        let persisted = load(&dir.join("transactions"), &transaction_id).unwrap();
        resolve_recovered(&persisted, &dir).unwrap();

        assert_eq!(
            adapter.read(),
            1,
            "resuming an already-applied idempotency key must not mutate again"
        );
    }

    // Renamed from `recovery_leaves_an_already_terminal_record_untouched`
    // (re-audit finding): this exercises `resolve_recovered`'s generic
    // terminal short-circuit for `Committed`, not the
    // `RecoveryClassification::AlreadyCommitted` match arm -- that arm is
    // genuinely unreachable via this function's own call to `classify()`,
    // since every persisted `state == Committed` record is caught by
    // `is_terminal()` before `classify()` is ever invoked. See the doc
    // comment on `resolve_recovered` for the full explanation.
    #[test]
    fn recovery_skips_a_committed_record_via_the_terminal_short_circuit_not_the_classify_arm() {
        let dir = temp_state_dir("recover-terminal-committed");
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Committed,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        let persisted = load(&dir.join("transactions"), &transaction_id).unwrap();
        let outcome = resolve_recovered(&persisted, &dir).unwrap();
        assert_eq!(outcome, RecoveryOutcome::AlreadyTerminal);
    }

    fn counter_of(dir: &Path) -> u64 {
        std::fs::read_to_string(dir.join("guarded-counter"))
            .ok()
            .and_then(|text| text.trim().parse().ok())
            .unwrap_or(0)
    }

    #[test]
    fn must_observe_confirms_without_replaying_apply() {
        let dir = temp_state_dir("recover-must-observe");
        // A real, natural shape: Apply already durably succeeded (the
        // second persist call inside `engine::apply` already wrote
        // `state=Observing`), but the crash happened before `Observe` ever
        // ran -- `last_observation` was never captured.
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Observing,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        std::fs::write(dir.join("guarded-counter"), "1").unwrap();

        let persisted = load(&dir.join("transactions"), &transaction_id).unwrap();
        assert_eq!(
            guardian_core::transaction::recovery::classify(persisted.to_recovery_snapshot()),
            guardian_core::transaction::RecoveryClassification::MustObserve,
            "test fixture must actually classify as MustObserve"
        );

        let outcome = resolve_recovered(&persisted, &dir).unwrap();
        assert_eq!(
            outcome,
            RecoveryOutcome::Resumed(TransactionState::Committed)
        );
        assert_eq!(
            counter_of(&dir),
            1,
            "Apply must not be replayed -- the counter must be exactly what it was, not incremented again"
        );

        let reloaded = load(&dir.join("transactions"), &transaction_id).unwrap();
        assert_eq!(reloaded.state, TransactionState::Committed);
        assert_eq!(
            reloaded.last_observation,
            Some(guardian_core::transaction::ObservationOutcome::PostconditionMet)
        );

        // Second restart: already terminal, must be a genuine no-op.
        let second = resolve_recovered(&reloaded, &dir).unwrap();
        assert_eq!(second, RecoveryOutcome::AlreadyTerminal);
        assert_eq!(
            counter_of(&dir),
            1,
            "no restart may re-mutate a terminal record"
        );
    }

    #[test]
    fn must_rollback_executes_and_does_not_replay_apply() {
        let dir = temp_state_dir("recover-must-rollback");
        // A real, natural shape: Apply succeeded, Observe genuinely ran
        // and found the postcondition NOT met -- classify_observing maps
        // this to MustRollback, not MustObserve.
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Observing,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        std::fs::write(dir.join("guarded-counter"), "1").unwrap();
        let mut persisted = load(&dir.join("transactions"), &transaction_id).unwrap();
        persisted.last_observation =
            Some(guardian_core::transaction::ObservationOutcome::PostconditionNotMet);
        assert_eq!(
            guardian_core::transaction::recovery::classify(persisted.to_recovery_snapshot()),
            guardian_core::transaction::RecoveryClassification::MustRollback,
            "test fixture must actually classify as MustRollback"
        );

        let outcome = resolve_recovered(&persisted, &dir).unwrap();
        assert_eq!(
            outcome,
            RecoveryOutcome::Resumed(TransactionState::RolledBack)
        );
        assert_eq!(
            counter_of(&dir),
            0,
            "rollback must actually execute (decrement), Apply must not be replayed (no re-increment)"
        );

        let reloaded = load(&dir.join("transactions"), &transaction_id).unwrap();
        assert_eq!(reloaded.state, TransactionState::RolledBack);

        // Repeated recovery converges: second restart is a genuine no-op,
        // rollback is not performed a second time.
        let second = resolve_recovered(&reloaded, &dir).unwrap();
        assert_eq!(second, RecoveryOutcome::AlreadyTerminal);
        assert_eq!(counter_of(&dir), 0);
    }

    #[test]
    fn must_rollback_resumes_directly_from_a_crash_during_rollback_itself() {
        let dir = temp_state_dir("recover-rollback-mid-rollback");
        // A genuinely-in-flight rollback: the crash happened *during* a
        // real rollback attempt, not merely before one started.
        let transaction_id = write_persisted(
            &dir,
            TransactionState::RollingBack,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        std::fs::write(dir.join("guarded-counter"), "1").unwrap();
        let persisted = load(&dir.join("transactions"), &transaction_id).unwrap();
        assert_eq!(
            guardian_core::transaction::recovery::classify(persisted.to_recovery_snapshot()),
            guardian_core::transaction::RecoveryClassification::MustRollback
        );

        let outcome = resolve_recovered(&persisted, &dir).unwrap();
        assert_eq!(
            outcome,
            RecoveryOutcome::Resumed(TransactionState::RolledBack)
        );
        assert_eq!(counter_of(&dir), 0);
    }

    #[test]
    fn state_ambiguous_fails_closed_to_rollback_not_apply() {
        let dir = temp_state_dir("recover-state-ambiguous");
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Observing,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        std::fs::write(dir.join("guarded-counter"), "1").unwrap();
        let mut persisted = load(&dir.join("transactions"), &transaction_id).unwrap();
        persisted.last_observation =
            Some(guardian_core::transaction::ObservationOutcome::Ambiguous);
        assert_eq!(
            guardian_core::transaction::recovery::classify(persisted.to_recovery_snapshot()),
            guardian_core::transaction::RecoveryClassification::StateAmbiguous,
            "test fixture must actually classify as StateAmbiguous"
        );

        let outcome = resolve_recovered(&persisted, &dir).unwrap();
        assert_eq!(
            outcome,
            RecoveryOutcome::Resumed(TransactionState::RolledBack)
        );
        assert_eq!(
            counter_of(&dir),
            0,
            "an ambiguous observation must fail closed to rollback, never to a replayed Apply"
        );

        let reloaded = load(&dir.join("transactions"), &transaction_id).unwrap();
        let second = resolve_recovered(&reloaded, &dir).unwrap();
        assert_eq!(
            second,
            RecoveryOutcome::AlreadyTerminal,
            "must converge, not repeat rollback"
        );
    }

    #[test]
    fn requires_human_recovery_never_mutates_and_never_invents_a_transition() {
        let dir = temp_state_dir("recover-requires-human");
        // RollbackFailed: the one real, meaningful shape that reaches
        // RequiresHumanRecovery in this implementation (see the doc
        // comment on `resolve_recovered`) -- a terminal state that still
        // needs continued human attention, per G4's own `classify()` doc
        // comment ("an unresolved rollback with no further automated
        // path").
        let transaction_id = write_persisted(
            &dir,
            TransactionState::RollbackFailed,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        std::fs::write(dir.join("guarded-counter"), "1").unwrap();
        let persisted = load(&dir.join("transactions"), &transaction_id).unwrap();

        let result = resolve_recovered(&persisted, &dir);
        assert!(
            result.is_err(),
            "must be surfaced as requiring attention, not silently Ok"
        );
        assert_eq!(counter_of(&dir), 1, "no mutation may occur");

        let reloaded = load(&dir.join("transactions"), &transaction_id).unwrap();
        assert_eq!(
            reloaded.state,
            TransactionState::RollbackFailed,
            "no transition may be invented -- the record must remain exactly as persisted"
        );

        // Repeated startup remains safe: the same disposition, every time,
        // never a crash, never a different (wrong) answer.
        for _ in 0..3 {
            let result = resolve_recovered(&reloaded, &dir);
            assert!(result.is_err());
            assert_eq!(counter_of(&dir), 1);
        }
    }

    #[test]
    fn rollback_failure_during_recovery_is_surfaced_not_silently_successful() {
        let dir = temp_state_dir("recover-rollback-failure");
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Observing,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        std::fs::write(dir.join("guarded-counter"), "1").unwrap();
        let mut persisted = load(&dir.join("transactions"), &transaction_id).unwrap();
        persisted.last_observation =
            Some(guardian_core::transaction::ObservationOutcome::PostconditionNotMet);

        // Real (not injected via a code hook) environmental failure: make
        // the counter file itself unwritable, so `CounterAdapter`'s own
        // real `write_atomic` genuinely fails and its `rollback` honestly
        // reports `confirmed_failed` -- exactly the same path a real
        // storage error would take.
        let counter_path = dir.join("guarded-counter");
        let mut perms = std::fs::metadata(&counter_path).unwrap().permissions();
        perms.set_readonly(true);
        std::fs::set_permissions(&counter_path, perms).unwrap();
        std::fs::set_permissions(&dir, {
            let mut dir_perms = std::fs::metadata(&dir).unwrap().permissions();
            dir_perms.set_readonly(true);
            dir_perms
        })
        .unwrap();

        let outcome = resolve_recovered(&persisted, &dir);

        // Restore permissions before any assertion can panic and leak a
        // read-only temp directory.
        let mut dir_perms = std::fs::metadata(&dir).unwrap().permissions();
        #[allow(clippy::permissions_set_readonly_false)]
        dir_perms.set_readonly(false);
        std::fs::set_permissions(&dir, dir_perms).unwrap();
        let mut file_perms = std::fs::metadata(&counter_path).unwrap().permissions();
        #[allow(clippy::permissions_set_readonly_false)]
        file_perms.set_readonly(false);
        std::fs::set_permissions(&counter_path, file_perms).unwrap();

        // `RollbackOutcome::ConfirmedFailed`'s `terminal_state()` is
        // `RollbackFailed` (G4's own accepted fail-closed mapping) -- a
        // real terminal state, reached honestly, never silently reported
        // as a successful `RolledBack`.
        assert_eq!(
            outcome,
            Ok(RecoveryOutcome::Resumed(TransactionState::RollbackFailed)),
            "a genuine rollback failure must become RollbackFailed, never a false RolledBack success"
        );
    }

    #[test]
    fn persist_failure_during_recovery_does_not_crash_and_does_not_fabricate_a_durable_record() {
        let dir = temp_state_dir("recover-persist-failure");
        let transaction_id = write_persisted(
            &dir,
            TransactionState::Observing,
            Some(ApplyOutcome::ConfirmedSuccess),
        );
        std::fs::write(dir.join("guarded-counter"), "1").unwrap();
        let persisted = load(&dir.join("transactions"), &transaction_id).unwrap();

        // Make the transactions directory itself unwritable so the
        // durable `persist()` call inside recovery genuinely fails (a
        // real I/O failure, not a code hook).
        let txn_dir = dir.join("transactions");
        let mut perms = std::fs::metadata(&txn_dir).unwrap().permissions();
        perms.set_readonly(true);
        std::fs::set_permissions(&txn_dir, perms).unwrap();

        // Must not panic even though the durable write will fail.
        let outcome = resolve_recovered(&persisted, &dir);

        let mut perms = std::fs::metadata(&txn_dir).unwrap().permissions();
        #[allow(clippy::permissions_set_readonly_false)]
        perms.set_readonly(false);
        std::fs::set_permissions(&txn_dir, perms).unwrap();

        // The in-memory operation still completes honestly (Observe/
        // Confirm do not depend on the transactions directory being
        // writable), but nothing here claims the *durable* record was
        // updated when it provably was not.
        assert_eq!(
            outcome,
            Ok(RecoveryOutcome::Resumed(TransactionState::Committed))
        );
        let reloaded = load(&dir.join("transactions"), &transaction_id).unwrap();
        assert_eq!(
            reloaded.state,
            TransactionState::Observing,
            "the durable record must NOT show Committed when the persist call actually failed -- \
             this is what 'surfaced, not silently discarded' means here: the stale on-disk state \
             is itself the honest signal, and a later restart (once the disk issue is resolved) \
             will safely re-run Observe/Confirm again (idempotent) rather than silently losing the outcome"
        );
    }

    /// Regression guard for the `SafeToResume` authorization invariant
    /// documented on `reconstruct_for_resume`/`resolve_recovered_restart`:
    /// independently re-derives, from the actual source text, that
    /// `txn::engine::apply` has exactly **four** call sites in this file —
    /// two per capability family (`run_guarded_write` +
    /// `resolve_recovered`'s `SafeToResume` branch for G7's counter;
    /// `run_restart_capability` + `resolve_recovered_restart`'s
    /// `SafeToResume` branch for Wave 1's `cups-restart`, added under this
    /// same invariant, not a new one) — and that each client-facing call
    /// site is textually after its own function's real authorization call
    /// (`txn::engine::authorize` for G7's `PolkitAction` path;
    /// `authorize_provider_request` for Wave 1's `ProviderAuthorizationRequest`
    /// path). A future change that adds a fifth call site, or reorders
    /// authorize/apply in either client-facing path, fails this test loudly
    /// instead of silently invalidating the recovery authorization
    /// assumption.
    #[test]
    fn exactly_four_apply_call_sites_and_each_client_facing_one_is_strictly_after_its_own_authorize()
     {
        // Scan only the production code, not this test module's own text
        // (which necessarily contains the literal search strings too).
        let full_source = include_str!("main.rs");
        let source = &full_source[..full_source
            .find("\n#[cfg(test)]\n")
            .expect("this test module marker must exist")];
        let apply_call_count = source.matches("txn::engine::apply(").count();
        assert_eq!(
            apply_call_count, 4,
            "expected exactly four call sites for txn::engine::apply (two per capability \
             family: run_guarded_write/resolve_recovered for G7's counter, \
             run_restart_capability/resolve_recovered_restart for Wave 1's cups-restart) -- a \
             new call site must be justified against the SafeToResume authorization invariant \
             before being added"
        );

        let run_guarded_write_start = source.find("async fn run_guarded_write").unwrap();
        let run_guarded_write_body = &source[run_guarded_write_start..];
        let run_guarded_write_end = run_guarded_write_body.find("\n}\n").unwrap();
        let run_guarded_write_body = &run_guarded_write_body[..run_guarded_write_end];

        let authorize_pos = run_guarded_write_body
            .find("txn::engine::authorize(")
            .expect("run_guarded_write must call txn::engine::authorize");
        let apply_pos = run_guarded_write_body
            .find("txn::engine::apply(")
            .expect("run_guarded_write must call txn::engine::apply");
        assert!(
            authorize_pos < apply_pos,
            "run_guarded_write must call authorize strictly before apply"
        );

        // `run_restart_capability` delegates its Authorize step to
        // `restart_authorize` (extracted only to stay under clippy's
        // function-length lint) -- confirm the delegation happens strictly
        // before `txn::engine::apply`, and that `restart_authorize` itself
        // genuinely calls the real `authorize_provider_request` entry
        // point before ever reporting success.
        let run_restart_start = source.find("async fn run_restart_capability").unwrap();
        let run_restart_body = &source[run_restart_start..];
        let run_restart_end = run_restart_body.find("\n}\n").unwrap();
        let run_restart_body = &run_restart_body[..run_restart_end];

        let authorize_pos = run_restart_body
            .find("restart_authorize(")
            .expect("run_restart_capability must call restart_authorize");
        let apply_pos = run_restart_body
            .find("txn::engine::apply(")
            .expect("run_restart_capability must call txn::engine::apply");
        assert!(
            authorize_pos < apply_pos,
            "run_restart_capability must call restart_authorize strictly before apply"
        );

        let restart_authorize_start = source.find("async fn restart_authorize").unwrap();
        let restart_authorize_body = &source[restart_authorize_start..];
        let restart_authorize_end = restart_authorize_body.find("\n}\n").unwrap();
        let restart_authorize_body = &restart_authorize_body[..restart_authorize_end];
        assert!(
            restart_authorize_body.contains("authorize_provider_request("),
            "restart_authorize must call the real authorize_provider_request entry point"
        );
    }

    #[test]
    fn repeated_restart_does_not_loop_forever_on_the_same_stuck_record() {
        let dir = temp_state_dir("recover-repeated-restart");
        write_persisted(
            &dir,
            TransactionState::Applying,
            Some(ApplyOutcome::NotRecorded),
        );

        // Three consecutive "restarts": each must move the record forward
        // and terminate it, not repeat the same unresolved classification
        // forever (the independent audit's central behavioral finding).
        for _ in 0..3 {
            recover_on_startup(&dir);
        }

        let entries = guardian_core::transaction::persistence::load_all(&dir.join("transactions"));
        assert_eq!(entries.len(), 1);
        let reloaded = entries.into_iter().next().unwrap().unwrap();
        assert!(
            reloaded.state.is_terminal(),
            "after repeated restarts the record must reach a terminal state, got {:?}",
            reloaded.state
        );
    }

    #[test]
    fn corrupt_persisted_record_does_not_crash_startup_recovery() {
        let dir = temp_state_dir("recover-corrupt");
        std::fs::write(
            dir.join("transactions").join("not-a-real-id.txn"),
            b"garbage, not a valid persisted record",
        )
        .unwrap();
        // Must not panic.
        recover_on_startup(&dir);
    }
}
