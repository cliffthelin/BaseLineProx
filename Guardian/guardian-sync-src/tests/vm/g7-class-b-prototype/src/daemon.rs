//! G7 Class B EVIDENCE PROTOTYPE — NON-PRODUCTION. DISPOSABLE.
//! NOT PART OF `guardian-daemon`.
//!
//! Exists for exactly one purpose: to evidence Class B's architecture
//! (provider-owned authorization; the transaction lifecycle owned by an
//! unprivileged daemon-like process; `guardian-helper` never involved) in
//! a real disposable VM, per the G7 independent audit's finding that the
//! original candidate merged this evidence-only demonstration directly
//! into the accepted production `Guardian1` D-Bus surface as
//! `Guardian1.Transactions1.AttemptProviderDelegatedWrite`, in violation
//! of the "no incidental permanent public API" guardrail — see
//! `docs/guardian/30_TDD/GUARDIAN_G7_IMPLEMENTATION_HANDOFF.md` §2.8/§6.
//!
//! This binary is explicitly and permanently disposable-prototype-only.
//! It MUST NOT be promoted into `crates/guardian-daemon` or given a
//! production D-Bus name under `io.github.cliffthelin.*` again. Follows
//! exactly the precedent of `tests/vm/g2-model-b/` (G2's own disposable
//! Model B evidence, never merged into production) and
//! `tests/vm/g6-daemon-evidence-stub/` (G6's disposable evidence stub,
//! explicitly forbidden from becoming production scaffolding).

use std::fs;
use std::path::PathBuf;

use guardian_core::arbitration::{CandidateProvider, RollbackKind};
use guardian_core::risk::Risk;
use guardian_core::transaction::{
    self as txn, ActionType, ArbitrationStateSource, TransactionId, TransactionRecord,
    TransactionState,
};
use guardian_provider_api::{
    ActionRequest, ApplyOutcome as RawApplyOutcome, Availability, BootAvailabilitySet,
    CapabilityId, CapabilityRecord, CostLevel, DiagnosticCost, Health, InspectionSnapshot,
    InterfaceKind, Knowledge, MutableCapabilityAdapter, ObservationExpectation,
    ObservationOutcome as RawObservationOutcome, PrivilegeRequirement, ProviderId,
    RollbackOutcome as RawRollbackOutcome, StateSnapshot, Unsupported,
};

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.G7ClassBPrototype1";
const OBJECT_PATH: &str = "/io/github/cliffthelin/G7ClassBPrototype1";
const CAPABILITY_ID: &str = "guardian.g7.prototype.provider-delegated-write";
const PROVIDER_ID: &str = "guardian.g7.prototype.stand-in-provider";

fn state_dir() -> PathBuf {
    std::env::var_os("G7_CLASS_B_STATE_DIR")
        .map(PathBuf::from)
        .expect("G7_CLASS_B_STATE_DIR must be set for this disposable prototype")
}

struct StandInProviderAdapter {
    counter_path: PathBuf,
}

impl StandInProviderAdapter {
    fn read(&self) -> u64 {
        fs::read_to_string(&self.counter_path)
            .ok()
            .and_then(|text| text.trim().parse().ok())
            .unwrap_or(0)
    }

    fn write_atomic(&self, value: u64) -> std::io::Result<()> {
        let tmp = self.counter_path.with_extension("tmp");
        fs::write(&tmp, value.to_string())?;
        fs::rename(&tmp, &self.counter_path)
    }
}

impl MutableCapabilityAdapter for StandInProviderAdapter {
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

    fn apply(&self, _action: &ActionRequest) -> Result<RawApplyOutcome, Unsupported> {
        let next = self.read().saturating_add(1);
        match self.write_atomic(next) {
            Ok(()) => Ok(RawApplyOutcome("confirmed_success".to_owned())),
            Err(_) => Ok(RawApplyOutcome("confirmed_failure_no_mutation".to_owned())),
        }
    }

    fn observe(
        &self,
        _expectation: &ObservationExpectation,
    ) -> Result<RawObservationOutcome, Unsupported> {
        Ok(RawObservationOutcome("postcondition_met".to_owned()))
    }

    fn rollback(&self, _snapshot: &StateSnapshot) -> Result<RawRollbackOutcome, Unsupported> {
        let current = self.read();
        match self.write_atomic(current.saturating_sub(1)) {
            Ok(()) => Ok(RawRollbackOutcome("confirmed_restored".to_owned())),
            Err(_) => Ok(RawRollbackOutcome("confirmed_failed".to_owned())),
        }
    }
}

struct FixedArbitrationSource;

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
            guardian_owned_writer: false,
            authorization_ownership: Knowledge::Known(
                guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization,
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
            guardian_provider_api::AuthorizationMode::ProviderOwnedAuthorization,
        ),
        privilege_requirement: PrivilegeRequirement::NoDirectPrivilege,
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

struct ClassBPrototype {
    state: PathBuf,
}

#[zbus::interface(name = "io.github.cliffthelin.G7ClassBPrototype1")]
impl ClassBPrototype {
    /// Prototype-only. Demonstrates: daemon-local transaction ownership,
    /// `Authorize` delegated to a stand-in provider (no `CheckAuthorization`
    /// call anywhere in this file), no involvement of any privileged
    /// helper process.
    fn attempt_provider_delegated_write(&self) -> Result<u64, zbus::fdo::Error> {
        let adapter = StandInProviderAdapter {
            counter_path: self.state.join("prototype-counter"),
        };
        let source = FixedArbitrationSource;
        let capability = capability_record();
        let clock = now_secs();

        let transaction_id = TransactionId::generate();
        let mut record = TransactionRecord {
            idempotency_key: transaction_id.to_string(),
            transaction_id,
            action_type: ActionType::BoundedWrite,
            risk_class: Risk::Low,
            initiating_bus_name: None,
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

        let fail = |message: String| zbus::fdo::Error::Failed(message);

        txn::engine::snapshot(&mut record, &adapter, &source, clock)
            .map_err(|error| fail(format!("snapshot: {error}")))?;
        txn::engine::validate(&mut record, &capability, &source)
            .map_err(|error| fail(format!("validate: {error}")))?;

        // Authorize (delegated): no CheckAuthorization call anywhere in
        // this prototype -- the stand-in provider is modeled as already
        // having authorized the action itself.
        record
            .transition_to(TransactionState::Authorizing)
            .and_then(|()| {
                record.authorization_outcome =
                    Some(guardian_core::authorization::AuthorizationOutcome::Authorized);
                record.transition_to(TransactionState::Authorized)
            })
            .map_err(|error| fail(format!("authorize: {error}")))?;

        let apply_dir = self.state.join("transactions");
        txn::engine::apply(&mut record, &adapter, &source, &apply_dir, clock)
            .map_err(|error| fail(format!("apply: {error}")))?;
        let observation = txn::engine::observe(&mut record, &adapter)
            .map_err(|error| fail(format!("observe: {error}")))?;

        if observation == guardian_core::transaction::ObservationOutcome::PostconditionMet {
            txn::engine::confirm(&mut record).map_err(|error| fail(format!("confirm: {error}")))?;
        } else {
            txn::engine::rollback(&mut record, &adapter, RollbackKind::BestEffort)
                .map_err(|error| fail(format!("rollback: {error}")))?;
            return Err(fail("postcondition not met; rolled back".to_owned()));
        }

        Ok(adapter.read())
    }
}

fn main() -> zbus::Result<()> {
    let state = state_dir();
    fs::create_dir_all(state.join("transactions")).expect("create prototype state directory");

    let connection = zbus::blocking::connection::Builder::system()?
        .name(WELL_KNOWN_NAME)?
        .serve_at(OBJECT_PATH, ClassBPrototype { state })?
        .build()?;
    eprintln!(
        "[g7-class-b-daemon PROTOTYPE, NON-PRODUCTION] serving {WELL_KNOWN_NAME} at {OBJECT_PATH}, unique_name={}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}
