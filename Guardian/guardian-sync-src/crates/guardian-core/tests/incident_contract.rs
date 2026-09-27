//! The `Incident` correlation envelope (TDD contract §18; G3 handoff §8).
//! P0-EVT-004.

use guardian_core::event::{Event, normalize_key};
use guardian_core::incident::{Confidence, Incident, IncidentStatus};
use guardian_core::risk::Risk;
use guardian_provider_api::{EventId, IncidentId, ProviderId};
use std::collections::BTreeMap;

fn event(id: &str, raw: &str) -> Event {
    Event {
        event_id: EventId::new(id).unwrap(),
        timestamp_monotonic: 1,
        timestamp_wall: "2026-08-31T00:00:00Z".to_owned(),
        source_provider: ProviderId::new("journald").unwrap(),
        event_type: "disk.full".to_owned(),
        resource_refs: vec!["storage.device.root".to_owned()],
        severity: Risk::Moderate,
        normalized_key: normalize_key(raw),
        raw_reference: raw.to_owned(),
        attributes: BTreeMap::new(),
    }
}

fn base_incident() -> Incident {
    Incident {
        incident_id: IncidentId::new("inc-0001").unwrap(),
        opened_at: "2026-08-31T00:00:00Z".to_owned(),
        closed_at: None,
        status: IncidentStatus::Open,
        summary: "root filesystem approaching capacity".to_owned(),
        confidence: Confidence::Hypothesis,
        confidence_history: Vec::new(),
        primary_resource: Some("storage.device.root".to_owned()),
        event_ids: Vec::new(),
        evidence: Vec::new(),
        candidate_causes: Vec::new(),
        recommended_actions: Vec::new(),
        transaction_ids: Vec::new(),
        outcome: None,
    }
}

#[test]
fn p0_evt_004_multiple_events_link_into_one_incident_without_deletion() {
    let event_a = event("evt-a", "disk full on /");
    let event_b = event("evt-b", "no space left on device: /");

    let mut incident = base_incident();
    incident.link_event(event_a.event_id.clone());
    incident.link_event(event_b.event_id.clone());

    assert_eq!(
        incident.event_ids,
        vec![event_a.event_id.clone(), event_b.event_id.clone()]
    );
    // Both original events remain fully intact -- nothing was consumed or
    // mutated by linking.
    assert_eq!(event_a.raw_reference, "disk full on /");
    assert_eq!(event_b.raw_reference, "no space left on device: /");
}

#[test]
fn linking_the_same_event_twice_does_not_duplicate_the_reference() {
    let event_a = event("evt-a", "disk full on /");
    let mut incident = base_incident();
    incident.link_event(event_a.event_id.clone());
    incident.link_event(event_a.event_id.clone());
    assert_eq!(incident.event_ids.len(), 1);
}

#[test]
fn correlation_can_be_updated_as_new_evidence_arrives() {
    let mut incident = base_incident();
    incident.link_event(EventId::new("evt-a").unwrap());
    assert_eq!(incident.event_ids.len(), 1);
    incident.link_event(EventId::new("evt-b").unwrap());
    assert_eq!(incident.event_ids.len(), 2);
}

#[test]
fn confidence_changes_are_recorded_not_silently_overwritten() {
    let mut incident = base_incident();
    assert_eq!(incident.confidence, Confidence::Hypothesis);
    incident.set_confidence(Confidence::Probable);
    incident.set_confidence(Confidence::Confirmed);
    assert_eq!(incident.confidence, Confidence::Confirmed);
    assert_eq!(
        incident.confidence_history,
        vec![Confidence::Hypothesis, Confidence::Probable]
    );
}

#[test]
fn an_incident_can_close_without_a_known_root_cause() {
    let mut incident = base_incident();
    assert!(incident.candidate_causes.is_empty());
    incident.status = IncidentStatus::Closed;
    incident.closed_at = Some("2026-08-31T01:00:00Z".to_owned());
    assert_eq!(incident.status, IncidentStatus::Closed);
    assert!(incident.candidate_causes.is_empty());
}

#[test]
fn incident_ids_do_not_regenerate_across_equivalent_constructions() {
    let first = base_incident();
    let second = base_incident();
    assert_eq!(first.incident_id, second.incident_id);
}
