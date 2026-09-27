//! The ten required authorization-ownership / privilege-requirement
//! dimensional-independence tests
//! (`docs/guardian/30_TDD/GUARDIAN_G3_IMPLEMENTATION_HANDOFF.md` §16.1).
//!
//! Items 3, 4, and 10 (the eight unresearched G2 inventory rows, and
//! arbitration failing closed on unknown authorization ownership) live in
//! `crates/guardian-provider-api/tests/g2_inventory_contract.rs` and
//! `crates/guardian-core/tests/arbitration_contract.rs` respectively, since
//! they require either the full inventory fixture or the arbitrator.

use guardian_provider_api::{
    AuthorizationMode, CapabilityId, Knowledge, PrivilegeRequirement, ProviderId,
};

/// §16.1 item 1: `Known(NoAuthorizationRequired)` differs from `Unknown`.
#[test]
fn known_no_authorization_required_differs_from_unknown() {
    let known = Knowledge::Known(AuthorizationMode::NoAuthorizationRequired);
    let unknown: Knowledge<AuthorizationMode> = Knowledge::Unknown;
    assert_ne!(known, unknown);
    assert_ne!(known.to_string(), unknown.to_string());
}

/// §16.1 item 8: unknown authorization ownership serializes distinctly from
/// known-no-auth (and both round-trip correctly).
#[test]
fn unknown_authorization_ownership_round_trips_distinctly_from_known_no_auth() {
    let known = Knowledge::Known(AuthorizationMode::NoAuthorizationRequired);
    let unknown: Knowledge<AuthorizationMode> = Knowledge::Unknown;

    let known_wire = known.to_string();
    let unknown_wire = unknown.to_string();
    assert_ne!(known_wire, unknown_wire);

    assert_eq!(Knowledge::parse_wire(&known_wire).unwrap(), known);
    assert_eq!(Knowledge::parse_wire(&unknown_wire).unwrap(), unknown);
}

/// §16.1 item 5: a known provider-owned row round-trips correctly.
#[test]
fn known_provider_owned_row_round_trips() {
    let value = Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization);
    let wire = value.to_string();
    assert_eq!(Knowledge::parse_wire(&wire).unwrap(), value);
}

/// §16.1 item 6: a known Guardian-owned row round-trips correctly.
#[test]
fn known_guardian_owned_row_round_trips() {
    let value = Knowledge::Known(AuthorizationMode::GuardianOwnedAuthorization);
    let wire = value.to_string();
    assert_eq!(Knowledge::parse_wire(&wire).unwrap(), value);
}

/// §16.1 item 7 (and item 2, by construction: the malformed token never
/// becomes `Unknown`, let alone `Known(NoAuthorizationRequired)`): an
/// unsupported future `AuthorizationMode` wire token is a typed parse
/// failure.
#[test]
fn unsupported_future_wire_token_is_a_typed_parse_failure_not_unknown() {
    let result = Knowledge::parse_wire("known:future_mode_xyz");
    assert!(
        result.is_err(),
        "malformed token must fail closed: {result:?}"
    );
}

/// §16.1: `privilege_requirement`'s own unrecognized-value rule (Rule 3) --
/// distinct from `AuthorizationMode`'s Rule 1 above: unresearched/future
/// tokens become the real `Unknown` variant, not an error, and never
/// `NoDirectPrivilege`.
#[test]
fn unresearched_privilege_requirement_wire_value_becomes_explicit_unknown_not_no_direct() {
    let parsed: PrivilegeRequirement = "future_privilege_xyz".parse().unwrap();
    assert_eq!(parsed, PrivilegeRequirement::Unknown);
    assert_ne!(parsed, PrivilegeRequirement::NoDirectPrivilege);
}

fn record_with(
    authorization_ownership: Knowledge<AuthorizationMode>,
    privilege_requirement: PrivilegeRequirement,
) -> guardian_provider_api::CapabilityRecord {
    guardian_provider_api::CapabilityRecord {
        capability_id: CapabilityId::new("power.profile.hold").unwrap(),
        provider_id: ProviderId::new("power-profiles-daemon").unwrap(),
        provider_version: None,
        availability: guardian_provider_api::Availability::Available,
        health: guardian_provider_api::Health::Healthy,
        read_support: true,
        write_support: true,
        authorization_ownership,
        privilege_requirement,
        boot_availability: [guardian_provider_api::BootAvailability::UserSession]
            .into_iter()
            .collect(),
        interface_kind: guardian_provider_api::InterfaceKind::DBus,
        interface_name: None,
        interface_hash: None,
        diagnostic_cost: guardian_provider_api::DiagnosticCost::default(),
        last_observed_at: "2026-08-31T00:00:00Z".to_owned(),
    }
}

/// Worked dimensional example (G3 handoff §5/§11): `power-profiles-daemon`
/// `HoldProfile` is Guardian-owned authorization requiring no further OS
/// privilege -- `GuardianOwnedAuthorization` does not imply
/// `RootOrSystemPrivilege`.
#[test]
fn guardian_owned_authorization_does_not_imply_root_privilege() {
    let record = record_with(
        Knowledge::Known(AuthorizationMode::GuardianOwnedAuthorization),
        PrivilegeRequirement::NoDirectPrivilege,
    );
    assert_eq!(
        record.authorization_ownership,
        Knowledge::Known(AuthorizationMode::GuardianOwnedAuthorization)
    );
    assert_eq!(
        record.privilege_requirement,
        PrivilegeRequirement::NoDirectPrivilege
    );
}

/// Worked dimensional example: `UDisks PowerOff` is provider-owned
/// authorization requiring no further OS privilege --
/// `ProviderOwnedAuthorization` does not imply `RootOrSystemPrivilege`
/// either.
#[test]
fn provider_owned_authorization_does_not_imply_root_privilege() {
    let record = record_with(
        Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization),
        PrivilegeRequirement::NoDirectPrivilege,
    );
    assert_eq!(
        record.authorization_ownership,
        Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization)
    );
    assert_eq!(
        record.privilege_requirement,
        PrivilegeRequirement::NoDirectPrivilege
    );
}

/// Independence in the other direction: a hypothetical provider that needs
/// root-level access but performs its own authorization proves
/// `RootOrSystemPrivilege` does not imply `GuardianOwnedAuthorization`.
#[test]
fn root_privilege_requirement_does_not_imply_guardian_owned_authorization() {
    let record = record_with(
        Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization),
        PrivilegeRequirement::RootOrSystemPrivilege,
    );
    assert_eq!(
        record.authorization_ownership,
        Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization)
    );
    assert_ne!(
        record.authorization_ownership,
        Knowledge::Known(AuthorizationMode::GuardianOwnedAuthorization)
    );
}

/// §16.1 item 5 (independence, not just round-trip): the two dimensions
/// vary independently across every combination of known/unknown.
#[test]
fn authorization_ownership_and_privilege_requirement_vary_independently() {
    for authorization_ownership in [
        Knowledge::Known(AuthorizationMode::NoAuthorizationRequired),
        Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization),
        Knowledge::Known(AuthorizationMode::GuardianOwnedAuthorization),
        Knowledge::Unknown,
    ] {
        for privilege_requirement in [
            PrivilegeRequirement::NoDirectPrivilege,
            PrivilegeRequirement::SpecificFileOrDeviceAccess,
            PrivilegeRequirement::SpecificLinuxCapability,
            PrivilegeRequirement::RootOrSystemPrivilege,
            PrivilegeRequirement::Unknown,
        ] {
            let record = record_with(authorization_ownership, privilege_requirement);
            assert_eq!(record.authorization_ownership, authorization_ownership);
            assert_eq!(record.privilege_requirement, privilege_requirement);
        }
    }
}
