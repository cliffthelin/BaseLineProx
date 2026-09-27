//! Fixture built directly from `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`'s
//! 24 rows -- proves every row is representable without information loss
//! across both `authorization_ownership` and `privilege_requirement`
//! (G3 handoff §5/§9, §16.1 items 3-4).
//!
//! Counts reproduced from the inventory's own summary: 9 `no privilege`, 6
//! `provider-owned authorization`, 1 `Guardian polkit authorization`, 8
//! `unknown -- requires host research`. The 8 unresearched rows carry a
//! *single* classification column in the inventory (no separate
//! authorization-ownership finding), so they MUST map to `Unknown` on
//! *both* dimensions here -- never a manufactured `Known` authorization
//! owner, regardless of how plausible one might seem architecturally.

use guardian_provider_api::{AuthorizationMode, Knowledge, PrivilegeRequirement};

#[derive(Clone, Copy)]
enum Row {
    NoPrivilege,
    ProviderOwned,
    GuardianOwned,
    Unresearched,
}

const INVENTORY: &[(&str, Row)] = &[
    ("systemd.read_unit_state", Row::NoPrivilege),
    ("systemd.start_stop_restart", Row::ProviderOwned),
    ("cgroups.transient_scopes", Row::ProviderOwned),
    ("psi.pressure_files", Row::NoPrivilege),
    ("udisks.read_topology", Row::NoPrivilege),
    ("udisks.power_off", Row::ProviderOwned),
    ("bpf_ebpf", Row::Unresearched),
    ("thermald.read_policy", Row::NoPrivilege),
    ("thermald.write_policy", Row::Unresearched),
    ("power_profiles.read_active", Row::NoPrivilege),
    ("power_profiles.hold_profile", Row::GuardianOwned),
    ("upower.read", Row::NoPrivilege),
    ("nvml_nvidia", Row::Unresearched),
    ("fwupd", Row::Unresearched),
    ("network_manager.read", Row::NoPrivilege),
    ("network_manager.write", Row::ProviderOwned),
    ("journald.read", Row::NoPrivilege),
    ("journald.rotation_capacity", Row::Unresearched),
    ("accounts_service.read_sessions", Row::NoPrivilege),
    ("accounts_service.set_session", Row::ProviderOwned),
    ("apt_package_state", Row::Unresearched),
    ("generic_hardware_control", Row::Unresearched),
    ("io_guardian.storage_power_off", Row::ProviderOwned),
    ("usb_security_usbguard", Row::Unresearched),
];

fn authorization_ownership_for(row: Row) -> Knowledge<AuthorizationMode> {
    match row {
        Row::NoPrivilege => Knowledge::Known(AuthorizationMode::NoAuthorizationRequired),
        Row::ProviderOwned => Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization),
        Row::GuardianOwned => Knowledge::Known(AuthorizationMode::GuardianOwnedAuthorization),
        // The inventory never established an authorization owner for these
        // rows -- do not manufacture one.
        Row::Unresearched => Knowledge::Unknown,
    }
}

fn privilege_requirement_for(row: Row) -> PrivilegeRequirement {
    match row {
        Row::NoPrivilege | Row::ProviderOwned | Row::GuardianOwned => {
            PrivilegeRequirement::NoDirectPrivilege
        }
        Row::Unresearched => PrivilegeRequirement::Unknown,
    }
}

#[test]
fn inventory_row_count_matches_the_g2_evidence_summary() {
    assert_eq!(INVENTORY.len(), 24);
}

#[test]
fn category_counts_reconcile_with_the_g2_evidence_summary() {
    let no_privilege = INVENTORY
        .iter()
        .filter(|(_, row)| matches!(row, Row::NoPrivilege))
        .count();
    let provider_owned = INVENTORY
        .iter()
        .filter(|(_, row)| matches!(row, Row::ProviderOwned))
        .count();
    let guardian_owned = INVENTORY
        .iter()
        .filter(|(_, row)| matches!(row, Row::GuardianOwned))
        .count();
    let unresearched = INVENTORY
        .iter()
        .filter(|(_, row)| matches!(row, Row::Unresearched))
        .count();

    assert_eq!(no_privilege, 9);
    assert_eq!(provider_owned, 6);
    assert_eq!(guardian_owned, 1);
    assert_eq!(unresearched, 8);
    assert_eq!(
        no_privilege + provider_owned + guardian_owned + unresearched,
        24
    );
}

/// §16.1 item 3: all eight unresearched rows remain
/// `authorization_ownership = Unknown`.
#[test]
fn all_eight_unresearched_rows_have_unknown_authorization_ownership() {
    let unresearched_ownership: Vec<_> = INVENTORY
        .iter()
        .filter(|(_, row)| matches!(row, Row::Unresearched))
        .map(|(name, row)| (*name, authorization_ownership_for(*row)))
        .collect();
    assert_eq!(unresearched_ownership.len(), 8);
    for (name, ownership) in unresearched_ownership {
        assert_eq!(
            ownership,
            Knowledge::Unknown,
            "{name} must not have a manufactured known authorization owner"
        );
    }
}

/// §16.1 item 4: all eight unresearched rows remain
/// `privilege_requirement = Unknown`.
#[test]
fn all_eight_unresearched_rows_have_unknown_privilege_requirement() {
    let unresearched_privilege: Vec<_> = INVENTORY
        .iter()
        .filter(|(_, row)| matches!(row, Row::Unresearched))
        .map(|(name, row)| (*name, privilege_requirement_for(*row)))
        .collect();
    assert_eq!(unresearched_privilege.len(), 8);
    for (name, privilege) in unresearched_privilege {
        assert_eq!(
            privilege,
            PrivilegeRequirement::Unknown,
            "{name} must remain unresearched"
        );
    }
}

#[test]
fn known_rows_preserve_their_researched_authorization_ownership() {
    for (name, row) in INVENTORY
        .iter()
        .filter(|(_, row)| !matches!(row, Row::Unresearched))
    {
        let ownership = authorization_ownership_for(*row);
        assert_ne!(
            ownership,
            Knowledge::Unknown,
            "{name} has researched evidence and must be Known"
        );
    }
}
