//! `TransactionId` -- generated record identity, deliberately distinct from
//! `CapabilityId`'s domain-identity validator (G3 NB-4; G4 handoff §8).

use guardian_core::transaction::TransactionId;

#[test]
fn generated_ids_are_unique_and_well_formed() {
    let a = TransactionId::generate();
    let b = TransactionId::generate();
    assert_ne!(a, b);
    assert!(TransactionId::new(a.as_str().to_owned()).is_ok());
}

#[test]
fn rejects_capability_id_style_dotted_names() {
    assert!(TransactionId::new("storage.device.poweroff").is_err());
}

#[test]
fn rejects_uppercase_and_malformed_groups() {
    assert!(TransactionId::new("AAAAAAAA-bbbb-cccc-dddd-eeeeeeeeeeee").is_err());
    assert!(TransactionId::new("not-a-uuid").is_err());
}

#[test]
fn display_and_new_round_trip() {
    let id = TransactionId::generate();
    let text = id.to_string();
    assert_eq!(TransactionId::new(text).unwrap(), id);
}
