//! The immutable normalized `Event` schema (TDD contract §17; G3 handoff
//! §8).
//!
//! An event is not yet an incident (see [`crate::incident`]) -- normalizing
//! an event's correlation key must never destroy its raw source reference
//! or its provider provenance (P0-EVT-002/003).

use std::collections::BTreeMap;

use guardian_provider_api::{EventId, ProviderId};

use crate::risk::Risk;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Event {
    pub event_id: EventId,
    /// Nanoseconds since an arbitrary, process-local monotonic epoch.
    /// **Ordering/duration comparisons MUST use this field, never
    /// `timestamp_wall`** (TDD contract §17; P0-EVT-001) -- wall-clock time
    /// can jump backward (NTP correction, manual adjustment, DST) without
    /// this value ever doing so.
    pub timestamp_monotonic: u64,
    /// Retained for human correlation only (TDD contract §17) -- ISO 8601.
    pub timestamp_wall: String,
    pub source_provider: ProviderId,
    pub event_type: String,
    pub resource_refs: Vec<String>,
    pub severity: Risk,
    /// A deterministic correlation key -- see [`normalize_key`]. Equivalent
    /// raw variants of "the same" observation may share one normalized key
    /// without losing their own `raw_reference` (P0-EVT-002/003).
    pub normalized_key: String,
    /// The original, unnormalized source text/reference. MUST survive
    /// normalization unchanged -- forensic identity is never sacrificed for
    /// correlation convenience.
    pub raw_reference: String,
    pub attributes: BTreeMap<String, String>,
}

/// Deterministic normalization: lowercases, trims, and collapses internal
/// whitespace runs. Two differently-worded raw sources describing the same
/// condition can normalize to an identical key via this function while each
/// keeps its own distinct `raw_reference` (P0-EVT-002).
#[must_use]
pub fn normalize_key(raw: &str) -> String {
    raw.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

/// Sorts `events` by monotonic order in place (P0-EVT-001) -- deliberately
/// ignores `timestamp_wall` entirely, so a simulated backward wall-clock
/// jump cannot reorder events whose monotonic timestamps are already
/// correctly ordered.
pub fn sort_by_monotonic_order(events: &mut [Event]) {
    events.sort_by_key(|event| event.timestamp_monotonic);
}
