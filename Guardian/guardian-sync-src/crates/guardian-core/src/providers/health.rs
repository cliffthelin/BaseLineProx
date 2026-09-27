//! TDD-contract Phase 2, Gate 2b: the provider-health transition `Event`
//! producer (implementation handoff §4.2/§13; gate TDD R1). Diffs two
//! successive `capability_registry_tick` snapshots and emits one `Event`
//! per `capability_id` whose `Health` or `Availability` changed, in the
//! exact shape Gate 2a's `CorrelationEngine` already expects
//! ([`crate::correlation::HEALTH_TRANSITION_EVENT_TYPE`]).
//!
//! REQUIRED FOUNDATION only (gate TDD R1 scope note): this module produces
//! one generic Availability/Health signal, identical in shape across every
//! provider in the G8 Capability Registry. Per-source enrichment (`UDisks2`
//! device identity, logind inhibitor detail, `UPower` battery/AC detail,
//! `AccountsService` session specifics) is OPTIONAL FUTURE ENRICHMENT and is
//! deliberately not attempted here.
//!
//! Pure Rust, no I/O of any kind: this module never reads `/proc`, never
//! opens a D-Bus connection, and never constructs a
//! [`crate::correlation::CorrelationIngress`]/[`crate::correlation::
//! IngressClock`] of its own — `guardian-daemon` (Gate 2b's daemon-wiring
//! half) owns the single ingress admission point every event source feeds
//! through (gate TDD R2); this module only ever hands it plain [`Event`]
//! values to admit.

use std::collections::{BTreeMap, HashMap};

use guardian_provider_api::{Availability, CapabilityId, CapabilityRecord, EventId, ProviderId};

use crate::correlation::{
    HEALTH_AVAILABILITY_TO_ATTR, HEALTH_CAPABILITY_ID_ATTR, HEALTH_TRANSITION_EVENT_TYPE,
};
use crate::event::{Event, normalize_key};
use crate::risk::Risk;

/// The fixed, generic source-provider identity every provider-health
/// transition `Event` carries — this producer's own identity, never the
/// identity of whichever of the six underlying providers actually owns
/// the capability (that distinction remains recoverable from
/// `capability_id`/`resource_refs`, never collapsed away).
const HEALTH_PRODUCER_PROVIDER_ID: &str = "guardian.p2.capability-health";

/// A snapshot-diffing provider-health transition producer (gate TDD R1).
/// Holds exactly one prior snapshot, keyed by `capability_id` — process-
/// memory-only, matching the correlation engine's own §8/§9 "no
/// persistence" discipline. The very first snapshot ever observed
/// establishes the baseline only (nothing to diff against yet, so no
/// event is produced) — the same seeding pattern G8's own
/// `PsiEventDispatcher::new` uses for its first reading.
#[derive(Debug, Default)]
pub struct HealthTransitionProducer {
    previous: Option<HashMap<CapabilityId, (Availability, guardian_provider_api::Health)>>,
    sequence: u64,
}

impl HealthTransitionProducer {
    #[must_use]
    pub fn new() -> Self {
        Self {
            previous: None,
            sequence: 0,
        }
    }

    /// Observes one new `capability_registry_tick` snapshot. Returns
    /// exactly one [`Event`] for every `capability_id` present in both the
    /// previous and the current snapshot whose `(Availability, Health)`
    /// pair differs (gate TDD R1) — an unchanged pair emits nothing, and a
    /// `capability_id` with no prior observation is not yet a
    /// "transition" (it becomes eligible starting with the snapshot after
    /// this one).
    pub fn observe(&mut self, current: &[CapabilityRecord]) -> Vec<Event> {
        let current_state: HashMap<CapabilityId, (Availability, guardian_provider_api::Health)> =
            current
                .iter()
                .map(|record| {
                    (
                        record.capability_id.clone(),
                        (record.availability, record.health),
                    )
                })
                .collect();

        let mut events = Vec::new();
        if let Some(previous_state) = &self.previous {
            for (capability_id, &(availability, health)) in &current_state {
                let Some(&(prev_availability, prev_health)) = previous_state.get(capability_id)
                else {
                    // Newly appeared capability_id: no prior state to
                    // transition FROM, so this is not yet a transition.
                    continue;
                };
                if prev_availability == availability && prev_health == health {
                    continue;
                }
                self.sequence = self.sequence.saturating_add(1);
                events.push(transition_event(capability_id, availability, self.sequence));
            }
        }

        self.previous = Some(current_state);
        events
    }
}

fn transition_event(
    capability_id: &CapabilityId,
    availability: Availability,
    sequence: u64,
) -> Event {
    let raw = format!(
        "capability {} health transition to {}",
        capability_id.as_str(),
        availability
    );
    let mut attributes = BTreeMap::new();
    attributes.insert(
        HEALTH_CAPABILITY_ID_ATTR.to_owned(),
        capability_id.as_str().to_owned(),
    );
    attributes.insert(
        HEALTH_AVAILABILITY_TO_ATTR.to_owned(),
        availability.to_string(),
    );

    Event {
        event_id: EventId::new(format!(
            "guardian.health.{}.event-{sequence}",
            capability_id.as_str()
        ))
        .expect("capability_id is already a valid dotted identifier"),
        timestamp_monotonic: sequence,
        timestamp_wall: format!("sequence-{sequence}"),
        source_provider: ProviderId::new(HEALTH_PRODUCER_PROVIDER_ID)
            .expect("fixed literal is a valid ProviderId"),
        event_type: HEALTH_TRANSITION_EVENT_TYPE.to_owned(),
        resource_refs: vec![capability_id.as_str().to_owned()],
        severity: match availability {
            Availability::Available => Risk::Observe,
            Availability::Unavailable => Risk::High,
            Availability::Degraded | Availability::Unsupported | Availability::Unknown => {
                Risk::Moderate
            }
        },
        normalized_key: normalize_key(&raw),
        raw_reference: raw,
        attributes,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use guardian_provider_api::{
        BootAvailability, DiagnosticCost, Health, InterfaceKind, Knowledge, PrivilegeRequirement,
    };

    fn record(cap_id: &str, availability: Availability, health: Health) -> CapabilityRecord {
        CapabilityRecord {
            capability_id: CapabilityId::new(cap_id).unwrap(),
            provider_id: ProviderId::new("guardian.g8.test").unwrap(),
            provider_version: None,
            availability,
            health,
            read_support: true,
            write_support: false,
            authorization_ownership: Knowledge::Unknown,
            privilege_requirement: PrivilegeRequirement::NoDirectPrivilege,
            boot_availability: [BootAvailability::SystemBus].into_iter().collect(),
            interface_kind: InterfaceKind::DBus,
            interface_name: None,
            interface_hash: None,
            diagnostic_cost: DiagnosticCost::default(),
            last_observed_at: "2026-09-06T00:00:00Z".to_owned(),
        }
    }

    #[test]
    fn first_snapshot_ever_observed_emits_no_event() {
        let mut producer = HealthTransitionProducer::new();
        let snapshot = vec![record(
            "psi.pressure.cpu",
            Availability::Available,
            Health::Healthy,
        )];
        assert!(producer.observe(&snapshot).is_empty());
    }

    #[test]
    fn unchanged_snapshot_pair_emits_no_event() {
        let mut producer = HealthTransitionProducer::new();
        let snapshot = vec![record(
            "psi.pressure.cpu",
            Availability::Available,
            Health::Healthy,
        )];
        producer.observe(&snapshot);
        let events = producer.observe(&snapshot);
        assert!(
            events.is_empty(),
            "an unchanged snapshot pair must emit no Event"
        );
    }

    #[test]
    fn availability_change_for_one_capability_emits_exactly_one_correlatable_event() {
        let mut producer = HealthTransitionProducer::new();
        let baseline = vec![record(
            "systemd.unit.state",
            Availability::Available,
            Health::Healthy,
        )];
        producer.observe(&baseline);

        let changed = vec![record(
            "systemd.unit.state",
            Availability::Unavailable,
            Health::Error,
        )];
        let events = producer.observe(&changed);
        assert_eq!(
            events.len(),
            1,
            "exactly one Event for one changed capability"
        );
        let event = &events[0];
        assert_eq!(event.event_type, HEALTH_TRANSITION_EVENT_TYPE);
        assert_eq!(
            event.attributes[HEALTH_CAPABILITY_ID_ATTR],
            "systemd.unit.state"
        );
        assert_eq!(event.attributes[HEALTH_AVAILABILITY_TO_ATTR], "unavailable");
        assert_eq!(event.resource_refs, ["systemd.unit.state"]);
    }

    #[test]
    fn health_only_change_with_stable_availability_still_emits_an_event() {
        let mut producer = HealthTransitionProducer::new();
        let baseline = vec![record(
            "upower.display-device",
            Availability::Available,
            Health::Healthy,
        )];
        producer.observe(&baseline);

        let degraded_health = vec![record(
            "upower.display-device",
            Availability::Available,
            Health::Warning,
        )];
        let events = producer.observe(&degraded_health);
        assert_eq!(events.len(), 1, "a Health-only diff must still emit");
    }

    #[test]
    fn multiple_changed_capabilities_each_emit_their_own_event() {
        let mut producer = HealthTransitionProducer::new();
        let baseline = vec![
            record("a.cap", Availability::Available, Health::Healthy),
            record("b.cap", Availability::Available, Health::Healthy),
            record("c.cap", Availability::Available, Health::Healthy),
        ];
        producer.observe(&baseline);

        let changed = vec![
            record("a.cap", Availability::Unavailable, Health::Error),
            record("b.cap", Availability::Available, Health::Healthy),
            record("c.cap", Availability::Degraded, Health::Warning),
        ];
        let events = producer.observe(&changed);
        assert_eq!(
            events.len(),
            2,
            "only the two genuinely-changed capabilities emit"
        );
        let ids: Vec<&str> = events
            .iter()
            .map(|e| e.attributes[HEALTH_CAPABILITY_ID_ATTR].as_str())
            .collect();
        assert!(ids.contains(&"a.cap"));
        assert!(ids.contains(&"c.cap"));
    }

    #[test]
    fn a_newly_appeared_capability_id_is_not_yet_a_transition() {
        let mut producer = HealthTransitionProducer::new();
        let baseline = vec![record(
            "systemd.unit.state",
            Availability::Available,
            Health::Healthy,
        )];
        producer.observe(&baseline);

        let with_new_capability = vec![
            record(
                "systemd.unit.state",
                Availability::Available,
                Health::Healthy,
            ),
            record(
                "logind.inhibitors",
                Availability::Available,
                Health::Healthy,
            ),
        ];
        let events = producer.observe(&with_new_capability);
        assert!(
            events.is_empty(),
            "a brand-new capability_id has no prior state to transition from"
        );
    }
}
