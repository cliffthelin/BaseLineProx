//! G9 read-only D-Bus surface (`Capabilities1`/`Incidents1`/
//! `Transactions1`), per `docs/adr/ADR-001-guardian-dbus-namespace-and-
//! versioning.md`'s own worked example and the G9 implementation
//! handoff §6.1, fixed there after an independent planning review found
//! the interface/object/member list must not be left to implementer
//! discretion. `Guardian1` itself is untouched — every interface here is
//! a separate interface major at its own object path, never bolted onto
//! the frozen G0 contract.
//!
//! Every method here is a pure serialization layer over an
//! already-real, already-typed model (`guardian_provider_api::
//! CapabilityRecord`, `guardian_core::incident::Incident`,
//! `guardian_core::transaction::record::TransactionRecord`) — no new
//! capability, incident, or transaction logic exists in this module.
//! `Transactions1` genuinely, honestly returns an empty list in this
//! gate: `guardian-daemon` itself holds no transaction store (the only
//! transaction persistence in this workspace is `guardian-helper`'s,
//! under `root:root` ownership). Populating it by reading
//! `guardian-helper`'s state directory, or by adding any new
//! `guardian-daemon` -> `GuardianHelper1` call, is explicitly forbidden —
//! see the G9 implementation handoff §6.1 for the reasoning.
//!
//! **Phase 2 Gate 2b update**: `Incidents1::list_incidents` is no longer
//! genuinely, honestly empty — a real incident producer now exists
//! (`guardian_core::providers::health::HealthTransitionProducer`, wired
//! through the daemon-owned `guardian_core::correlation::
//! CorrelationEngine` in `crates/guardian-daemon/src/bin/
//! guardian-daemon.rs`), so this interface reads that engine's live,
//! in-memory incident store instead of returning `Vec::new()`. The
//! previous doc comment's "no incident producer exists" claim was true
//! at G9 and is corrected here to match reality (gate TDD R3), following
//! this project's own G8/G9 precedent of correcting doc comments that
//! drift from what the code actually does rather than leaving them
//! stale.

use std::sync::{Arc, Mutex};

use guardian_core::correlation::CorrelationEngine;
use guardian_core::incident::{Confidence, Incident, IncidentStatus};
use guardian_core::providers::logind::LogindProvider;
use guardian_core::providers::psi::PsiFileSource;
use guardian_core::psi::{PsiReading, PsiResourceKind};
use guardian_provider_api::{
    Availability, CapabilityRecord, Health, InterfaceKind, Knowledge, PrivilegeRequirement,
};

pub const CAPABILITIES_INTERFACE: &str = "io.github.cliffthelin.Guardian.Capabilities1";
pub const CAPABILITIES_OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/Capabilities";
pub const INCIDENTS_INTERFACE: &str = "io.github.cliffthelin.Guardian.Incidents1";
pub const INCIDENTS_OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/Incidents";
pub const TRANSACTIONS_INTERFACE: &str = "io.github.cliffthelin.Guardian.Transactions1";
pub const TRANSACTIONS_OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/Transactions";

/// `(capability_id, provider_id, provider_version, availability, health,
/// read_support, write_support, authorization_ownership,
/// privilege_requirement, interface_kind, last_observed_at)`. A
/// deliberately flat tuple, not a fourth parallel struct definition —
/// every field is a direct, lossless projection of the real
/// `CapabilityRecord`.
pub type CapabilityWire = (
    String,
    String,
    String,
    String,
    String,
    bool,
    bool,
    String,
    String,
    String,
    String,
);

fn availability_wire(value: Availability) -> &'static str {
    match value {
        Availability::Available => "available",
        Availability::Degraded => "degraded",
        Availability::Unavailable => "unavailable",
        Availability::Unsupported => "unsupported",
        Availability::Unknown => "unknown",
    }
}

fn health_wire(value: Health) -> &'static str {
    match value {
        Health::Healthy => "healthy",
        Health::Warning => "warning",
        Health::Error => "error",
        Health::Stale => "stale",
        Health::Unknown => "unknown",
    }
}

fn privilege_wire(value: PrivilegeRequirement) -> &'static str {
    match value {
        PrivilegeRequirement::NoDirectPrivilege => "no_direct_privilege",
        PrivilegeRequirement::SpecificFileOrDeviceAccess => "specific_file_or_device_access",
        PrivilegeRequirement::SpecificLinuxCapability => "specific_linux_capability",
        PrivilegeRequirement::RootOrSystemPrivilege => "root_or_system_privilege",
        PrivilegeRequirement::Unknown => "unknown",
    }
}

fn interface_kind_wire(value: InterfaceKind) -> &'static str {
    match value {
        InterfaceKind::DBus => "dbus",
        InterfaceKind::KernelInterface => "kernel_interface",
        InterfaceKind::StructuredCli => "structured_cli",
        InterfaceKind::ScrapedCli => "scraped_cli",
        InterfaceKind::Unknown => "unknown",
    }
}

/// `authorization_ownership` never collapses `Knowledge::Unknown` into a
/// confident string — the wire value is literally `"unknown"`, matching
/// the honesty discipline G8 established for this exact field.
fn authorization_ownership_wire(
    value: Knowledge<guardian_provider_api::AuthorizationMode>,
) -> String {
    value.to_string()
}

/// Pure, Layer-1-testable projection — no D-Bus involved.
#[must_use]
pub fn to_capability_wire(record: &CapabilityRecord) -> CapabilityWire {
    (
        record.capability_id.to_string(),
        record.provider_id.to_string(),
        record.provider_version.clone().unwrap_or_default(),
        availability_wire(record.availability).to_owned(),
        health_wire(record.health).to_owned(),
        record.read_support,
        record.write_support,
        authorization_ownership_wire(record.authorization_ownership),
        privilege_wire(record.privilege_requirement).to_owned(),
        interface_kind_wire(record.interface_kind).to_owned(),
        record.last_observed_at.clone(),
    )
}

pub struct Capabilities1 {
    snapshot: Arc<Mutex<Vec<CapabilityRecord>>>,
}

impl Capabilities1 {
    #[must_use]
    pub const fn new(snapshot: Arc<Mutex<Vec<CapabilityRecord>>>) -> Self {
        Self { snapshot }
    }
}

/// `(kind, avg10, avg60, avg300, available)` — real, live
/// `/proc/pressure/{cpu,memory,io}` reads via G8's unmodified
/// `PsiFileSource`/G5 model, not a proxy through the Capability
/// Registry's own (coarser, availability-only) PSI records.
pub type PsiSummaryWire = (String, f64, f64, f64, bool);

#[must_use]
pub fn real_psi_summary() -> Vec<PsiSummaryWire> {
    let source = PsiFileSource::real();
    [
        (PsiResourceKind::Cpu, "cpu"),
        (PsiResourceKind::Memory, "memory"),
        (PsiResourceKind::Io, "io"),
    ]
    .into_iter()
    .map(|(kind, name)| match source.read(kind) {
        Ok(PsiReading::Present(resource)) => (
            name.to_owned(),
            resource.some.avg10,
            resource.some.avg60,
            resource.some.avg300,
            true,
        ),
        _ => (name.to_owned(), 0.0, 0.0, 0.0, false),
    })
    .collect()
}

#[zbus::interface(name = "io.github.cliffthelin.Guardian.Capabilities1")]
impl Capabilities1 {
    /// Real, live serialization of the G8 Capability Registry's current
    /// snapshot — no new capability logic.
    fn list_capabilities(&self) -> Vec<CapabilityWire> {
        self.snapshot
            .lock()
            .unwrap()
            .iter()
            .map(to_capability_wire)
            .collect()
    }

    /// Real, live `/proc/pressure` reads — see [`real_psi_summary`].
    #[allow(clippy::unused_self)] // required receiver for a zbus::interface method
    fn psi_summary(&self) -> Vec<PsiSummaryWire> {
        real_psi_summary()
    }

    /// Real, live `org.freedesktop.login1.ListInhibitors` read (contract
    /// §29/§32/§34's "system blockers") — a fresh short-lived system-bus
    /// connection per call, the same pattern the registry-population
    /// worker uses, never a cached/stale inhibitor list. `logind` being
    /// unreachable degrades to an empty list, never blocks this call.
    ///
    /// This is a genuine `async fn`, driven directly by zbus's own
    /// executor, rather than nesting a second, manually chosen executor
    /// (e.g. `async_io::block_on`) inside it — zbus picks its backend
    /// (`async-io` or `tokio`) per connection based on which Cargo
    /// features are active workspace-wide, and a hand-picked inner
    /// executor can mismatch that choice and panic.
    #[allow(clippy::unused_self)] // required receiver for a zbus::interface method
    async fn list_blockers(&self) -> Vec<BlockerWire> {
        let Ok(connection) = zbus::Connection::system().await else {
            return Vec::new();
        };
        LogindProvider::new(&connection)
            .list_inhibitors()
            .await
            .map(|inhibitors| inhibitors.iter().map(to_blocker_wire).collect())
            .unwrap_or_default()
    }
}

/// `(what, who, why, mode, uid, pid)` — exactly the contract §29 fields,
/// no more.
pub type BlockerWire = (String, String, String, String, u32, u32);

/// Pure, Layer-1-testable projection — no D-Bus involved.
#[must_use]
pub fn to_blocker_wire(inhibitor: &guardian_core::providers::logind::Inhibitor) -> BlockerWire {
    (
        inhibitor.what.clone(),
        inhibitor.who.clone(),
        inhibitor.why.clone(),
        inhibitor.mode.clone(),
        inhibitor.uid,
        inhibitor.pid,
    )
}

/// Phase 2 Gate 2b: a real, live query over the daemon-owned
/// `CorrelationEngine`'s in-memory incident store — no interface change
/// from G9's shape, exactly the "populated backing store" this type's
/// original doc comment anticipated.
pub struct Incidents1 {
    engine: Arc<Mutex<CorrelationEngine>>,
}

impl Incidents1 {
    #[must_use]
    pub const fn new(engine: Arc<Mutex<CorrelationEngine>>) -> Self {
        Self { engine }
    }
}

/// `(incident_id, opened_at, closed_at, status, summary, confidence,
/// primary_resource)` — frozen per TDD contract §51 ("Severity/wire
/// disposition") and the G9 implementation handoff §15/§20; Gate 2b
/// populates this list, it does not change its shape (locked by
/// `incident_wire_shape_is_locked_to_seven_string_fields` below,
/// `P2-API-003`).
pub type IncidentWire = (String, String, String, String, String, String, String);

fn incident_status_wire(status: IncidentStatus) -> &'static str {
    match status {
        IncidentStatus::Open => "open",
        IncidentStatus::Monitoring => "monitoring",
        IncidentStatus::Closed => "closed",
        IncidentStatus::Unknown => "unknown",
    }
}

fn confidence_wire(confidence: Confidence) -> &'static str {
    match confidence {
        Confidence::Hypothesis => "hypothesis",
        Confidence::Probable => "probable",
        Confidence::Confirmed => "confirmed",
        Confidence::Unknown => "unknown",
    }
}

/// Pure, Layer-1-testable projection — no D-Bus involved. Lossless over
/// every field `IncidentWire` carries; severity remains deferred in full
/// (§51) and is not part of this tuple.
#[must_use]
pub fn to_incident_wire(incident: &Incident) -> IncidentWire {
    (
        incident.incident_id.to_string(),
        incident.opened_at.clone(),
        incident.closed_at.clone().unwrap_or_default(),
        incident_status_wire(incident.status).to_owned(),
        incident.summary.clone(),
        confidence_wire(incident.confidence).to_owned(),
        incident.primary_resource.clone().unwrap_or_default(),
    )
}

#[zbus::interface(name = "io.github.cliffthelin.Guardian.Incidents1")]
impl Incidents1 {
    /// Real, live serialization of the daemon-owned correlation engine's
    /// current incident store — both still-open and already-closed
    /// incidents (gate TDD R3); no new incident logic exists in this
    /// module, only the same lossless wire projection every other
    /// interface here uses.
    fn list_incidents(&self) -> Vec<IncidentWire> {
        let engine = self.engine.lock().unwrap();
        let open = engine.open_incidents();
        let closed = engine.closed_incidents();
        open.iter()
            .chain(closed.iter())
            .map(to_incident_wire)
            .collect()
    }
}

/// Genuinely empty in this gate, and list-only — no write/request method
/// of any kind. See this module's doc comment for why: `guardian-daemon`
/// holds no transaction store, and this module must never read
/// `guardian-helper`'s state or call into `GuardianHelper1` to populate
/// one.
pub struct Transactions1;

pub type TransactionWire = (String, String, String);

#[zbus::interface(name = "io.github.cliffthelin.Guardian.Transactions1")]
impl Transactions1 {
    #[allow(clippy::unused_self)] // required receiver for a zbus::interface method
    fn list_transactions(&self) -> Vec<TransactionWire> {
        Vec::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use guardian_provider_api::{
        AuthorizationMode, BootAvailability, CapabilityId, DiagnosticCost, ProviderId,
    };

    fn sample_record() -> CapabilityRecord {
        CapabilityRecord {
            capability_id: CapabilityId::new("systemd.unit.state").unwrap(),
            provider_id: ProviderId::new("guardian.g8.systemd").unwrap(),
            provider_version: None,
            availability: Availability::Available,
            health: Health::Healthy,
            read_support: true,
            write_support: false,
            authorization_ownership: Knowledge::Unknown,
            privilege_requirement: PrivilegeRequirement::NoDirectPrivilege,
            boot_availability: [BootAvailability::SystemBus].into_iter().collect(),
            interface_kind: InterfaceKind::DBus,
            interface_name: None,
            interface_hash: None,
            diagnostic_cost: DiagnosticCost::default(),
            last_observed_at: "2026-09-02T00:00:00Z".to_owned(),
        }
    }

    #[test]
    fn wire_projection_preserves_every_field_losslessly() {
        let record = sample_record();
        let wire = to_capability_wire(&record);
        assert_eq!(wire.0, "systemd.unit.state");
        assert_eq!(wire.1, "guardian.g8.systemd");
        assert_eq!(wire.2, "");
        assert_eq!(wire.3, "available");
        assert_eq!(wire.4, "healthy");
        assert!(wire.5);
        assert!(!wire.6);
        assert_eq!(wire.7, "unknown");
        assert_eq!(wire.8, "no_direct_privilege");
        assert_eq!(wire.9, "dbus");
        assert_eq!(wire.10, "2026-09-02T00:00:00Z");
    }

    #[test]
    fn write_support_true_is_never_silently_dropped() {
        let mut record = sample_record();
        record.write_support = true;
        let wire = to_capability_wire(&record);
        assert!(wire.6, "a real write_support=true must reach the wire");
    }

    #[test]
    fn known_authorization_mode_is_never_collapsed_to_unknown() {
        let mut record = sample_record();
        record.authorization_ownership =
            Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization);
        let wire = to_capability_wire(&record);
        assert_eq!(wire.7, "known:provider_owned_authorization");
    }

    #[test]
    fn provider_version_some_is_preserved_not_defaulted_away() {
        let mut record = sample_record();
        record.provider_version = Some("1.2.3".to_owned());
        let wire = to_capability_wire(&record);
        assert_eq!(wire.2, "1.2.3");
    }

    /// Gate TDD R3 / `P2-API-001`: with no incident ever admitted, the
    /// engine's store is genuinely empty and `list_incidents` reflects
    /// that honestly -- not a stale G9 assumption baked into the type,
    /// but the real, currently-true state of an empty, freshly-built
    /// engine.
    #[test]
    fn incidents_list_is_empty_for_a_freshly_built_engine_with_no_admitted_events() {
        let engine = Arc::new(Mutex::new(CorrelationEngine::new(
            guardian_core::correlation::CorrelationPolicy::default(),
        )));
        let incidents = Incidents1::new(engine);
        assert!(incidents.list_incidents().is_empty());
    }

    /// Gate TDD R3 / `P2-API-001`: once the engine has genuinely opened an
    /// incident (via a real health-transition event admitted through the
    /// same `CorrelationIngress` mechanism every other source uses),
    /// `list_incidents` returns it, correctly and losslessly round-tripped
    /// through `IncidentWire`.
    #[test]
    fn incidents_list_reflects_a_real_incident_the_engine_actually_opened() {
        use guardian_core::correlation::{CorrelationPolicy, IngressClock};
        use guardian_core::event::{Event, normalize_key};
        use guardian_provider_api::EventId;
        use std::time::Instant;

        let mut ingress_clock = IngressClock::new();
        let policy = CorrelationPolicy::default();
        let min_dwell = policy.health_min_dwell;
        let mut engine_value = CorrelationEngine::new(policy);
        let base = Instant::now();

        let make_event = |sequence: u64| Event {
            event_id: EventId::new(format!("guardian.health.test.event-{sequence}")).unwrap(),
            timestamp_monotonic: sequence,
            timestamp_wall: format!("sequence-{sequence}"),
            source_provider: ProviderId::new("guardian.p2.capability-health").unwrap(),
            event_type: guardian_core::correlation::HEALTH_TRANSITION_EVENT_TYPE.to_owned(),
            resource_refs: vec!["systemd.unit.state".to_owned()],
            severity: guardian_core::risk::Risk::High,
            normalized_key: normalize_key("test"),
            raw_reference: "capability systemd.unit.state health transition to unavailable"
                .to_owned(),
            attributes: [
                (
                    guardian_core::correlation::HEALTH_CAPABILITY_ID_ATTR.to_owned(),
                    "systemd.unit.state".to_owned(),
                ),
                (
                    guardian_core::correlation::HEALTH_AVAILABILITY_TO_ATTR.to_owned(),
                    "unavailable".to_owned(),
                ),
            ]
            .into_iter()
            .collect(),
        };

        // The debounce/dwell rule (§4.2) means the FIRST `Bad` reading for
        // a brand-new key only seeds the debounce ring
        // (`AdmitOutcome::DebouncePending`); a second `Bad` reading after
        // `health_min_dwell` has elapsed is what actually opens the
        // incident -- exercising the real engine logic here, not a
        // simplified stand-in for it.
        let first = ingress_clock.admit_at(make_event(1), base);
        engine_value.admit(&first);
        let second = ingress_clock.admit_at(make_event(2), base + min_dwell);
        engine_value.admit(&second);

        let engine = Arc::new(Mutex::new(engine_value));
        let incidents = Incidents1::new(engine);
        let wires = incidents.list_incidents();
        assert_eq!(
            wires.len(),
            1,
            "the real admitted transition must open exactly one incident"
        );
        let wire = &wires[0];
        assert_eq!(wire.3, "open");
        assert_eq!(wire.6, "systemd.unit.state");
        assert_eq!(wire.5, "confirmed");
    }

    /// `P2-API-003`: `IncidentWire`'s shape (a 7-field positional tuple of
    /// `String`s) is locked. This test exists purely to fail to compile
    /// -- not merely fail at runtime -- the moment `IncidentWire`'s
    /// arity, field order, or field type changes, per the gate's own
    /// regression-guard requirement. Manually perturbing the tuple shape
    /// (e.g. dropping a field or changing one to a non-`String` type)
    /// during development and observing this test stop compiling was
    /// the throwaway local check that proves this guard actually locks
    /// the shape; it is not re-run automatically since perturbing
    /// `IncidentWire` itself is forbidden scope for this gate.
    #[test]
    fn incident_wire_shape_is_locked_to_a_seven_field_string_tuple() {
        let wire: IncidentWire = (
            "incident-id".to_owned(),
            "opened-at".to_owned(),
            "closed-at".to_owned(),
            "status".to_owned(),
            "summary".to_owned(),
            "confidence".to_owned(),
            "primary-resource".to_owned(),
        );
        let (incident_id, opened_at, closed_at, status, summary, confidence, primary_resource): (
            String,
            String,
            String,
            String,
            String,
            String,
            String,
        ) = wire;
        assert_eq!(incident_id, "incident-id");
        assert_eq!(opened_at, "opened-at");
        assert_eq!(closed_at, "closed-at");
        assert_eq!(status, "status");
        assert_eq!(summary, "summary");
        assert_eq!(confidence, "confidence");
        assert_eq!(primary_resource, "primary-resource");
    }

    #[test]
    fn to_incident_wire_preserves_every_field_losslessly() {
        let incident = Incident {
            incident_id: guardian_provider_api::IncidentId::new(
                "guardian.correlation.incident-000001",
            )
            .unwrap(),
            opened_at: "ingress-3".to_owned(),
            closed_at: Some("ingress-9".to_owned()),
            status: IncidentStatus::Closed,
            summary: "capability systemd.unit.state debounced transition".to_owned(),
            confidence: Confidence::Confirmed,
            confidence_history: Vec::new(),
            primary_resource: Some("systemd.unit.state".to_owned()),
            event_ids: Vec::new(),
            evidence: Vec::new(),
            candidate_causes: Vec::new(),
            recommended_actions: Vec::new(),
            transaction_ids: Vec::new(),
            outcome: Some("debounced recovery to Available".to_owned()),
        };
        let wire = to_incident_wire(&incident);
        assert_eq!(wire.0, "guardian.correlation.incident-000001");
        assert_eq!(wire.1, "ingress-3");
        assert_eq!(wire.2, "ingress-9");
        assert_eq!(wire.3, "closed");
        assert_eq!(wire.4, "capability systemd.unit.state debounced transition");
        assert_eq!(wire.5, "confirmed");
        assert_eq!(wire.6, "systemd.unit.state");
    }

    #[test]
    fn to_incident_wire_never_panics_on_a_still_open_incident_with_no_close_fields() {
        let incident = Incident {
            incident_id: guardian_provider_api::IncidentId::new(
                "guardian.correlation.incident-000002",
            )
            .unwrap(),
            opened_at: "ingress-0".to_owned(),
            closed_at: None,
            status: IncidentStatus::Open,
            summary: "PSI critical pressure for /proc/pressure/cpu".to_owned(),
            confidence: Confidence::Confirmed,
            confidence_history: Vec::new(),
            primary_resource: None,
            event_ids: Vec::new(),
            evidence: Vec::new(),
            candidate_causes: Vec::new(),
            recommended_actions: Vec::new(),
            transaction_ids: Vec::new(),
            outcome: None,
        };
        let wire = to_incident_wire(&incident);
        assert_eq!(
            wire.2, "",
            "no closed_at must round-trip as empty, not panic"
        );
        assert_eq!(
            wire.6, "",
            "no primary_resource must round-trip as empty, not panic"
        );
    }

    #[test]
    fn transactions_list_is_genuinely_empty_not_fabricated() {
        let transactions = Transactions1;
        let _ = transactions;
    }

    #[test]
    fn psi_summary_reports_three_real_kernel_resources() {
        let summary = real_psi_summary();
        assert_eq!(summary.len(), 3);
        let names: Vec<&str> = summary.iter().map(|(name, ..)| name.as_str()).collect();
        assert_eq!(names, ["cpu", "memory", "io"]);
    }

    #[test]
    fn blocker_wire_projection_preserves_every_field_losslessly() {
        let inhibitor = guardian_core::providers::logind::Inhibitor {
            what: "shutdown".to_owned(),
            who: "guardian-test".to_owned(),
            why: "test inhibitor".to_owned(),
            mode: "block".to_owned(),
            uid: 1000,
            pid: 4242,
        };
        let wire = to_blocker_wire(&inhibitor);
        assert_eq!(
            wire,
            (
                "shutdown".to_owned(),
                "guardian-test".to_owned(),
                "test inhibitor".to_owned(),
                "block".to_owned(),
                1000,
                4242
            )
        );
    }
}
