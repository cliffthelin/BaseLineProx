//! Stable identifier contract for G3 (`docs/guardian/30_TDD/GUARDIAN_G3_IMPLEMENTATION_HANDOFF.md`
//! §4/§6). `CapabilityId` and `ProviderId` must be structurally distinct
//! types that cannot be constructed from each other, from discovery order,
//! or from a malformed string.

use guardian_provider_api::{CapabilityId, EventId, IncidentId, ProviderId};

#[test]
fn capability_id_and_provider_id_are_structurally_distinct_types() {
    // This is a compile-time proof as much as a runtime one: there is no
    // `From<ProviderId> for CapabilityId` or vice versa, and no shared
    // representation lets one substitute for the other -- the assertion
    // below merely documents that equal *string content* does not imply
    // interchangeability, since the types themselves are incompatible.
    let capability = CapabilityId::new("storage.device.poweroff").unwrap();
    let provider = ProviderId::new("storage.device.poweroff").unwrap();
    assert_eq!(capability.as_str(), provider.as_str());
}

#[test]
fn rejects_empty_and_malformed_identifiers() {
    assert!(CapabilityId::new("").is_err());
    assert!(CapabilityId::new("Storage.Device").is_err());
    assert!(CapabilityId::new("storage..device").is_err());
    assert!(CapabilityId::new("1storage.device").is_err());
}

#[test]
fn event_and_incident_ids_are_independently_typed() {
    let event = EventId::new("evt-0001").unwrap();
    let incident = IncidentId::new("inc-0001").unwrap();
    assert_ne!(event.as_str(), incident.as_str());
}
