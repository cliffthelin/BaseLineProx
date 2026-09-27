use guardian_provider_api::{ContractSnapshot, DriftStatus, ProviderProvenance};

const KNOWN: &[u8] =
    include_bytes!("../../../tests/fixtures/providers/freedesktop-dbus/introspection.xml");
const PROVENANCE: &str =
    include_str!("../../../tests/fixtures/providers/freedesktop-dbus/provenance.txt");

#[test]
fn p0_reg_003_provider_contract_provenance_preserves_unknowns() {
    let provenance: ProviderProvenance = PROVENANCE.parse().unwrap();

    assert_eq!(provenance.interface_version, None);
    assert_eq!(provenance.policy_hash, None);
    assert_eq!(provenance.provider_id, "org.freedesktop.DBus");
    assert_eq!(
        provenance.introspection_hash.as_deref(),
        Some(ContractSnapshot::sha256(KNOWN).as_str())
    );
}

#[test]
fn p0_reg_004_source_interface_drift_is_meaningfully_detected() {
    let known = ContractSnapshot::from_bytes("org.freedesktop.DBus", KNOWN);
    assert_eq!(known.compare(Some(KNOWN)).status, DriftStatus::Match);

    let changed = String::from_utf8(KNOWN.to_vec())
        .unwrap()
        .replace("ListNames", "ListPeers");
    let result = known.compare(Some(changed.as_bytes()));
    assert_eq!(result.status, DriftStatus::Drift);
    assert_eq!(result.provider_id, "org.freedesktop.DBus");
    assert_ne!(result.expected_hash, result.observed_hash.unwrap());

    assert_eq!(known.compare(None).status, DriftStatus::Missing);
    let invalid = ContractSnapshot::from_hash("org.freedesktop.DBus", "not-a-sha256");
    assert_eq!(invalid.compare(Some(KNOWN)).status, DriftStatus::Invalid);
}
