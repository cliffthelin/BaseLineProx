//! `CapabilityRecord` contract (TDD contract §11; G3 handoff §5/§6/§7).

use guardian_provider_api::{
    AuthorizationMode, Availability, BootAvailability, CapabilityId, CapabilityRecord, CostLevel,
    DiagnosticCost, Health, InterfaceKind, Knowledge, PrivilegeRequirement, ProviderId,
};

fn base_record() -> CapabilityRecord {
    CapabilityRecord {
        capability_id: CapabilityId::new("storage.device.poweroff").unwrap(),
        provider_id: ProviderId::new("udisks2").unwrap(),
        provider_version: Some("2.10".to_owned()),
        availability: Availability::Available,
        health: Health::Healthy,
        read_support: true,
        write_support: true,
        authorization_ownership: Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization),
        privilege_requirement: PrivilegeRequirement::NoDirectPrivilege,
        boot_availability: [BootAvailability::UserSession].into_iter().collect(),
        interface_kind: InterfaceKind::DBus,
        interface_name: Some("org.freedesktop.UDisks2.Drive".to_owned()),
        interface_hash: None,
        diagnostic_cost: DiagnosticCost::default(),
        last_observed_at: "2026-08-31T00:00:00Z".to_owned(),
    }
}

#[test]
fn provider_swap_does_not_alter_capability_identity() {
    let original = base_record();
    let swapped = original.with_provider(ProviderId::new("udisks-alt").unwrap());
    assert_eq!(original.capability_id, swapped.capability_id);
    assert_ne!(original.provider_id, swapped.provider_id);
}

#[test]
fn changing_privilege_requirement_does_not_alter_capability_identity() {
    let original = base_record();
    let mut changed = original.clone();
    changed.privilege_requirement = PrivilegeRequirement::Unknown;
    assert_eq!(original.capability_id, changed.capability_id);
}

#[test]
fn changing_authorization_ownership_does_not_alter_provider_identity() {
    let original = base_record();
    let mut changed = original.clone();
    changed.authorization_ownership = Knowledge::Unknown;
    assert_eq!(original.provider_id, changed.provider_id);
    assert_eq!(original.capability_id, changed.capability_id);
}

#[test]
fn unrecognized_availability_value_is_explicit_unknown_not_a_panic_or_available() {
    let parsed: Availability = "future_state_xyz".parse().unwrap();
    assert_eq!(parsed, Availability::Unknown);
    assert!(!parsed.is_usable());
    assert_ne!(parsed, Availability::Available);
}

#[test]
fn cost_level_defaults_to_negligible_not_an_unsafe_zero() {
    assert_eq!(CostLevel::default(), CostLevel::Negligible);
}
