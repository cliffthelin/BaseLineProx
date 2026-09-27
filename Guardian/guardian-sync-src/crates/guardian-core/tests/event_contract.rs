//! The immutable normalized `Event` schema (TDD contract §17; G3 handoff
//! §8). P0-EVT-001/002/003.

use guardian_core::event::{Event, normalize_key, sort_by_monotonic_order};
use guardian_core::risk::Risk;
use guardian_provider_api::{EventId, ProviderId};
use std::collections::BTreeMap;

fn event(id: &str, monotonic: u64, wall: &str, raw: &str) -> Event {
    Event {
        event_id: EventId::new(id).unwrap(),
        timestamp_monotonic: monotonic,
        timestamp_wall: wall.to_owned(),
        source_provider: ProviderId::new("journald").unwrap(),
        event_type: "disk.full".to_owned(),
        resource_refs: vec!["storage.device.root".to_owned()],
        severity: Risk::Moderate,
        normalized_key: normalize_key(raw),
        raw_reference: raw.to_owned(),
        attributes: BTreeMap::new(),
    }
}

#[test]
fn p0_evt_001_monotonic_ordering_survives_backward_wall_clock_adjustment() {
    // The wall clock jumps backward between the second and third event
    // (e.g. NTP correction), but monotonic time keeps increasing.
    let mut events = vec![
        event("evt-1", 100, "2026-08-31T10:00:00Z", "disk full on /"),
        event("evt-2", 200, "2026-08-31T09:55:00Z", "disk full on /"),
        event("evt-3", 300, "2026-08-31T09:58:00Z", "disk full on /"),
    ];
    sort_by_monotonic_order(&mut events);
    let ids: Vec<_> = events.iter().map(|e| e.event_id.as_str()).collect();
    assert_eq!(ids, vec!["evt-1", "evt-2", "evt-3"]);
}

#[test]
fn p0_evt_002_equivalent_raw_variants_share_a_normalized_key() {
    let a = event("evt-a", 1, "2026-08-31T00:00:00Z", "Disk   full on /");
    let b = event("evt-b", 2, "2026-08-31T00:00:01Z", "disk full on /");
    assert_eq!(a.normalized_key, b.normalized_key);
}

#[test]
fn p0_evt_003_normalization_preserves_each_events_raw_reference() {
    let a = event("evt-a", 1, "2026-08-31T00:00:00Z", "Disk   full on /");
    let b = event("evt-b", 2, "2026-08-31T00:00:01Z", "disk full on /");
    assert_eq!(a.normalized_key, b.normalized_key);
    assert_ne!(a.raw_reference, b.raw_reference);
    assert_eq!(a.raw_reference, "Disk   full on /");
    assert_eq!(b.raw_reference, "disk full on /");
}

#[test]
fn normalize_key_is_pure_and_deterministic() {
    assert_eq!(normalize_key("  A   B  C "), normalize_key("a b c"));
}
