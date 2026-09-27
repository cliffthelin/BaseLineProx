//! The typed `Provider` contract (TDD contract §12). G3 defines the shape
//! only -- no real adapter (`UDisks`, `NetworkManager`, systemd, NVML,
//! `UPower`, thermald, fwupd) is implemented here; that is G8 scope.

use std::future::Future;

use crate::ProviderProvenance;
use crate::capability::{CapabilityRecord, ProviderHealth};
use crate::ids::ProviderId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderIdentity {
    pub provider_id: ProviderId,
    pub display_name: String,
}

/// The result of a lightweight provider probe -- distinct from
/// [`ProviderHealth`], which describes an already-running provider's
/// ongoing condition.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProbeResult {
    Ready,
    Unavailable,
    Degraded,
}

/// A minimal, provider-api-local event envelope for
/// [`Provider::subscribe_events`]'s typed shape. Deliberately does not
/// reuse `guardian_core::Event` -- `guardian-core` depends on
/// `guardian-provider-api`, not the other way around, so a raw provider
/// envelope here is normalized into a real `Event` by whatever code
/// consumes it (not built in G3).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RawProviderEvent {
    pub source_provider: ProviderId,
    pub payload: String,
}

/// A provider that could not perform the requested operation at all --
/// distinct from an operation that ran and failed (TDD contract §12: "Not
/// every provider must support every operation. Unsupported operations
/// MUST return an explicit typed `Unsupported` result.").
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Unsupported;

/// TDD contract §12's read-oriented provider lifecycle. Async methods
/// mirror `guardian_core::authorization::Authorizer`'s existing style
/// (`impl Future<...> + Send`, not native `async fn`) for consistency.
pub trait Provider {
    fn identity(&self) -> ProviderIdentity;
    fn provenance(&self) -> ProviderProvenance;
    fn probe(&self) -> impl Future<Output = ProbeResult> + Send;
    fn capabilities(&self) -> impl Future<Output = Vec<CapabilityRecord>> + Send;
    fn health(&self) -> impl Future<Output = ProviderHealth> + Send;
    fn subscribe_events(&self) -> impl Future<Output = Vec<RawProviderEvent>> + Send;
}

/// Opaque, provider-api-local placeholders for the mutable-adapter
/// method shapes below. G4 owns the real transaction semantics (Snapshot /
/// Validate / Authorize / Apply / Observe / Confirm / Commit / Rollback);
/// G3 only proves the typed shape exists and that `Unsupported` is a real,
/// reachable outcome, not that any of these placeholders orchestrate a
/// transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InspectionSnapshot(pub String);
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionRequest(pub String);
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidationResult(pub String);
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateSnapshot(pub String);
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ApplyOutcome(pub String);
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservationExpectation(pub String);
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservationOutcome(pub String);
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RollbackOutcome(pub String);

/// TDD contract §12's mutable-adapter shape. Not every provider supports
/// every operation -- an unsupported operation MUST return `Err(Unsupported)`,
/// never a fabricated success or a panic. Every method below returns
/// `Err(Unsupported)` when the implementing provider does not support that
/// specific operation (documented once here rather than per method).
#[allow(clippy::missing_errors_doc)]
pub trait MutableCapabilityAdapter {
    fn inspect(&self) -> Result<InspectionSnapshot, Unsupported>;
    fn validate(&self, action: &ActionRequest) -> Result<ValidationResult, Unsupported>;
    fn snapshot(&self, action: &ActionRequest) -> Result<StateSnapshot, Unsupported>;
    fn apply(&self, action: &ActionRequest) -> Result<ApplyOutcome, Unsupported>;
    fn observe(
        &self,
        expectation: &ObservationExpectation,
    ) -> Result<ObservationOutcome, Unsupported>;
    fn rollback(&self, snapshot: &StateSnapshot) -> Result<RollbackOutcome, Unsupported>;
}
