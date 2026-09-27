//! The typed `Provider`/`MutableCapabilityAdapter` contract (TDD contract
//! §12; G3 handoff §6). All fixtures here are deterministic and never call
//! a real system provider (`UDisks`, `NetworkManager`, systemd, NVML,
//! `UPower`, thermald, fwupd) -- that is G8 scope.

use guardian_provider_api::{
    ActionRequest, ApplyOutcome, Availability, BootAvailability, CapabilityId, CapabilityRecord,
    DiagnosticCost, Health, InspectionSnapshot, InterfaceKind, MutableCapabilityAdapter,
    ObservationExpectation, ObservationOutcome, ProbeResult, Provider, ProviderHealth,
    ProviderIdentity, ProviderProvenance, RollbackOutcome, StateSnapshot, Unsupported,
    ValidationResult,
};
use guardian_provider_api::{AuthorizationMode, Knowledge, PrivilegeRequirement, ProviderId};

/// Deterministic fixture: everything is controllable and read-only.
struct FixtureProviderA {
    capabilities: Vec<CapabilityRecord>,
    probe_result: ProbeResult,
    health: ProviderHealth,
}

impl Provider for FixtureProviderA {
    fn identity(&self) -> ProviderIdentity {
        ProviderIdentity {
            provider_id: ProviderId::new("fixture-provider-a").unwrap(),
            display_name: "Fixture Provider A".to_owned(),
        }
    }

    fn provenance(&self) -> ProviderProvenance {
        "provider_id=fixture-provider-a\nobserved_at=2026-08-31T00:00:00Z"
            .parse()
            .unwrap()
    }

    fn probe(&self) -> impl std::future::Future<Output = ProbeResult> + Send {
        std::future::ready(self.probe_result)
    }

    fn capabilities(&self) -> impl std::future::Future<Output = Vec<CapabilityRecord>> + Send {
        std::future::ready(self.capabilities.clone())
    }

    fn health(&self) -> impl std::future::Future<Output = ProviderHealth> + Send {
        std::future::ready(self.health)
    }

    fn subscribe_events(
        &self,
    ) -> impl std::future::Future<Output = Vec<guardian_provider_api::RawProviderEvent>> + Send
    {
        std::future::ready(Vec::new())
    }
}

fn capability_record(availability: Availability, health: Health) -> CapabilityRecord {
    CapabilityRecord {
        capability_id: CapabilityId::new("storage.device.poweroff").unwrap(),
        provider_id: ProviderId::new("fixture-provider-a").unwrap(),
        provider_version: None,
        availability,
        health,
        read_support: true,
        write_support: false,
        authorization_ownership: Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization),
        privilege_requirement: PrivilegeRequirement::NoDirectPrivilege,
        boot_availability: [BootAvailability::UserSession].into_iter().collect(),
        interface_kind: InterfaceKind::DBus,
        interface_name: None,
        interface_hash: None,
        diagnostic_cost: DiagnosticCost::default(),
        last_observed_at: "2026-08-31T00:00:00Z".to_owned(),
    }
}

/// P0-REG-001: an unavailable provider's capability yields `UNAVAILABLE`,
/// never rendered/treated as healthy.
#[test]
fn p0_reg_001_provider_unavailable_yields_unavailable_not_healthy() {
    async_io::block_on(async {
        let provider = FixtureProviderA {
            capabilities: vec![capability_record(Availability::Unavailable, Health::Error)],
            probe_result: ProbeResult::Unavailable,
            health: ProviderHealth::Error,
        };
        assert_eq!(provider.probe().await, ProbeResult::Unavailable);
        let capabilities = provider.capabilities().await;
        assert_eq!(capabilities[0].availability, Availability::Unavailable);
        assert!(!capabilities[0].availability.is_usable());
    });
}

/// P0-REG-002: a partially working provider's capability yields `DEGRADED`
/// with a distinguishable health reason, not silently folded into
/// available/healthy.
#[test]
fn p0_reg_002_degraded_provider_yields_degraded_with_distinguishable_health() {
    async_io::block_on(async {
        let provider = FixtureProviderA {
            capabilities: vec![capability_record(Availability::Degraded, Health::Warning)],
            probe_result: ProbeResult::Degraded,
            health: ProviderHealth::Warning,
        };
        assert_eq!(provider.probe().await, ProbeResult::Degraded);
        let capabilities = provider.capabilities().await;
        assert_eq!(capabilities[0].availability, Availability::Degraded);
        assert_eq!(capabilities[0].health, Health::Warning);
        assert_ne!(capabilities[0].availability, Availability::Available);
        assert_ne!(capabilities[0].health, Health::Healthy);
    });
}

#[test]
fn fixture_provider_a_is_deterministic_and_never_touches_a_real_provider() {
    async_io::block_on(async {
        let provider = FixtureProviderA {
            capabilities: Vec::new(),
            probe_result: ProbeResult::Ready,
            health: ProviderHealth::Healthy,
        };
        assert_eq!(provider.probe().await, ProbeResult::Ready);
        assert_eq!(provider.health().await, ProviderHealth::Healthy);
        assert!(provider.capabilities().await.is_empty());
        assert!(provider.subscribe_events().await.is_empty());
    });
}

/// A fixture that supports only read-oriented operations -- proves
/// `Unsupported` is a real, reachable outcome for a mutable-adapter method,
/// not merely a type that is never exercised (TDD contract §12).
struct ReadOnlyAdapter;

impl MutableCapabilityAdapter for ReadOnlyAdapter {
    fn inspect(&self) -> Result<InspectionSnapshot, Unsupported> {
        Ok(InspectionSnapshot("ok".to_owned()))
    }

    fn validate(&self, _action: &ActionRequest) -> Result<ValidationResult, Unsupported> {
        Err(Unsupported)
    }

    fn snapshot(&self, _action: &ActionRequest) -> Result<StateSnapshot, Unsupported> {
        Err(Unsupported)
    }

    fn apply(&self, _action: &ActionRequest) -> Result<ApplyOutcome, Unsupported> {
        Err(Unsupported)
    }

    fn observe(
        &self,
        _expectation: &ObservationExpectation,
    ) -> Result<ObservationOutcome, Unsupported> {
        Err(Unsupported)
    }

    fn rollback(&self, _snapshot: &StateSnapshot) -> Result<RollbackOutcome, Unsupported> {
        Err(Unsupported)
    }
}

#[test]
fn read_only_adapter_returns_unsupported_for_every_write_operation() {
    let adapter = ReadOnlyAdapter;
    assert!(adapter.inspect().is_ok());
    assert_eq!(
        adapter.validate(&ActionRequest("noop".to_owned())),
        Err(Unsupported)
    );
    assert_eq!(
        adapter.apply(&ActionRequest("noop".to_owned())),
        Err(Unsupported)
    );
    assert_eq!(
        adapter.rollback(&StateSnapshot("noop".to_owned())),
        Err(Unsupported)
    );
}
