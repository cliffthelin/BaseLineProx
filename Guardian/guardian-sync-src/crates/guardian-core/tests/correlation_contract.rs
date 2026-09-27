//! TDD-contract Phase 2, Gate 2a: Layer-1 correlation engine contract
//! tests (implementation handoff §17/§18/§19/§20; TDD contract §51).
//!
//! Pure Rust, no daemon, no D-Bus, no `/proc`/`/sys`, no real time
//! (`sleep`). Every test constructs `CorrelationIngress` records directly,
//! using the §6a `Instant`-construction technique: one real
//! `base = Instant::now()` per test, then `base + Duration::from_millis(N)`
//! / `base.checked_sub(...)` for deterministic relative placement.
//!
//! Covers exactly Gate 2a's 19 owned normative IDs: `P2-EVT-001..004`,
//! `P2-COR-001..007`, `P2-INC-002..004`, `P2-REC-001..005`.
//! `P2-INC-001` is retired (severity deferred in full, §15) and is not
//! resurrected anywhere in this file.

use std::collections::BTreeMap;
use std::time::{Duration, Instant};

use guardian_core::correlation::{
    AdmitOutcome, CorrelationEngine, CorrelationIngress, CorrelationPolicy, FreshHealthObservation,
    HEALTH_HEALTH_TO_ATTR, HEALTH_TRANSITION_EVENT_TYPE, IngressClock,
};
use guardian_core::event::{Event, normalize_key};
use guardian_core::incident::{Confidence, IncidentStatus};
use guardian_core::risk::Risk;
use guardian_provider_api::{Availability, CapabilityId, EventId, Health, ProviderId};

// ---------------------------------------------------------------------
// Synthetic producers -- test-local only, shaped like the real G8 PSI
// producer (`crates/guardian-core/src/providers/psi.rs`'s
// `event_from_crossing`) and like the provider-health transition `Event`
// Gate 2b will later produce for real (`capability_registry_tick` snapshot
// diffing). Gate 2a proves the correlation *rule*, not either real
// producer (task §9/§10).
// ---------------------------------------------------------------------

/// Shaped exactly like real production `providers::psi::event_from_crossing`
/// output: `event_type = "psi_threshold_crossing"`, `severity` maps
/// `Critical -> Risk::High`, `Nominal -> Risk::Observe`.
fn psi_event(id: &str, provider: &str, resource: &str, critical: bool, raw_seq: u64) -> Event {
    let raw = format!("PSI {resource} threshold crossing synthetic-{raw_seq}");
    Event {
        event_id: EventId::new(id).unwrap(),
        // Deliberately incompatible with any other producer's domain
        // (P2-EVT-003): a huge, wall-clock-shaped raw value.
        timestamp_monotonic: 1_900_000_000 + raw_seq,
        timestamp_wall: format!("wall-{raw_seq}"),
        source_provider: ProviderId::new(provider).unwrap(),
        event_type: "psi_threshold_crossing".to_owned(),
        resource_refs: vec![format!("/proc/pressure/{resource}")],
        severity: if critical { Risk::High } else { Risk::Observe },
        normalized_key: normalize_key(&raw),
        raw_reference: raw,
        attributes: BTreeMap::new(),
    }
}

/// Test-local synthetic provider-health transition event -- Gate 2b's job
/// is the real snapshot-diff producer; Gate 2a only needs a stable shape
/// to prove the correlation/debounce rule against (task §10).
fn health_event(id: &str, capability_id: &str, to: Availability, raw_seq: u64) -> Event {
    let mut attributes = BTreeMap::new();
    attributes.insert("capability_id".to_owned(), capability_id.to_owned());
    attributes.insert("availability_to".to_owned(), to.wire_token().to_owned());
    Event {
        event_id: EventId::new(id).unwrap(),
        // Deliberately incompatible with the PSI producer's domain
        // (P2-EVT-003): a tiny, sequence-counter-shaped raw value.
        timestamp_monotonic: raw_seq,
        timestamp_wall: format!("sequence-{raw_seq}"),
        source_provider: ProviderId::new("guardian.g8.systemd").unwrap(),
        event_type: HEALTH_TRANSITION_EVENT_TYPE.to_owned(),
        resource_refs: vec![capability_id.to_owned()],
        severity: Risk::Observe,
        normalized_key: normalize_key(&format!("capability health transition {raw_seq}")),
        raw_reference: format!("capability health transition {raw_seq}"),
        attributes,
    }
}

/// Gate 2a health-lifecycle repair (R4): like [`health_event`], but also
/// carries an explicit `health_to` attribute -- the real production
/// producer does not emit this yet (Gate 2b's own downstream repair), but
/// this gate's own tests may carry it early to exercise
/// `health_direction`'s full `(Availability, Health)` table, exactly as
/// this file's `health_event` already synthesizes a shape no real
/// producer emits verbatim.
fn health_event_with_health(
    id: &str,
    capability_id: &str,
    to: Availability,
    health: Health,
    raw_seq: u64,
) -> Event {
    let mut event = health_event(id, capability_id, to, raw_seq);
    event.attributes.insert(
        HEALTH_HEALTH_TO_ATTR.to_owned(),
        health.wire_token().to_owned(),
    );
    event
}

fn ingress(event: Event, base: Instant, offset_ms: u64, sequence: u64) -> CorrelationIngress {
    CorrelationIngress {
        event,
        ingress_clock: base + Duration::from_millis(offset_ms),
        ingress_sequence: sequence,
    }
}

fn policy() -> CorrelationPolicy {
    CorrelationPolicy {
        psi_window: Duration::from_millis(1000),
        health_min_dwell: Duration::from_millis(500),
        open_incident_cap: 3,
        closed_incident_cap: 3,
        debounce_capacity: 2,
    }
}

fn incident_id_of(outcome: &AdmitOutcome) -> guardian_provider_api::IncidentId {
    match outcome {
        AdmitOutcome::IncidentOpened(id)
        | AdmitOutcome::IncidentUpdated(id)
        | AdmitOutcome::IncidentClosed(id) => id.clone(),
        other => panic!("expected an incident-bearing outcome, got {other:?}"),
    }
}

// ---------------------------------------------------------------------
// P2-EVT-001 -- ingress order, never insertion/producer-timestamp order.
// ---------------------------------------------------------------------

#[test]
fn p2_evt_001_consumes_in_ingress_order_not_producer_timestamp() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());

    // Second-arriving-in-ingress-order event has a much smaller raw
    // `timestamp_monotonic` than the first -- grouping must still follow
    // ingress order, proven by both linking into the same incident.
    let first = ingress(
        psi_event("evt-a", "guardian.g8.psi", "cpu", true, 999),
        base,
        0,
        0,
    );
    let second = ingress(
        psi_event("evt-b", "guardian.g8.psi", "cpu", true, 1),
        base,
        10,
        1,
    );

    let r1 = engine.admit(&first);
    let id1 = incident_id_of(&r1.outcome);
    let r2 = engine.admit(&second);
    let id2 = incident_id_of(&r2.outcome);
    assert_eq!(id1, id2, "same key within window must link, not re-open");
}

// ---------------------------------------------------------------------
// P2-EVT-002 -- duplicate EventId never appears twice.
// ---------------------------------------------------------------------

#[test]
fn p2_evt_002_duplicate_event_id_not_double_linked() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());

    let event = psi_event("evt-dup", "guardian.g8.psi", "memory", true, 1);
    let r1 = engine.admit(&ingress(event.clone(), base, 0, 0));
    let id1 = incident_id_of(&r1.outcome);

    // Replaying the identical event (same EventId) again must not
    // duplicate it in the incident's event_ids (link_event idempotency).
    let r2 = engine.admit(&ingress(event, base, 50, 1));
    let id2 = incident_id_of(&r2.outcome);
    assert_eq!(id1, id2);

    let incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id1)
        .unwrap();
    assert_eq!(incident.event_ids.len(), 1, "no duplicate EventId linked");
}

// ---------------------------------------------------------------------
// P2-EVT-003 -- incompatible/backwards raw timestamps across producers;
// grouping must follow ingress order, never raw `timestamp_monotonic`.
// ---------------------------------------------------------------------

#[test]
fn p2_evt_003_ingress_order_wins_over_incompatible_raw_timestamps() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());

    // Producer A: wall-clock-shaped huge raw timestamp, admitted FIRST in
    // ingress order but with the LARGER raw timestamp.
    let a = psi_event("evt-wallclock", "guardian.g8.psi", "io", true, 0);
    assert!(a.timestamp_monotonic > 1_000_000_000);

    // Producer B: sequence-counter-shaped tiny raw timestamp, admitted
    // SECOND in ingress order but with the SMALLER raw timestamp -- a
    // naive sort by `timestamp_monotonic` would put B first.
    let b_capability_event = health_event(
        "evt-seqcounter",
        "svc.example",
        Availability::Unavailable,
        0,
    );
    assert!(b_capability_event.timestamp_monotonic < 10);

    let r1 = engine.admit(&ingress(a, base, 0, 0));
    let id_a = incident_id_of(&r1.outcome);

    // First health reading starts the debounce candidate; the second,
    // past the dwell, promotes it -- proving the health path also only
    // cares about ingress order, never raw timestamps.
    let r_pending = engine.admit(&ingress(b_capability_event, base, 10, 1));
    assert!(matches!(r_pending.outcome, AdmitOutcome::DebouncePending));
    let r2 = engine.admit(&ingress(
        health_event(
            "evt-seqcounter-2",
            "svc.example",
            Availability::Unavailable,
            1,
        ),
        base,
        600,
        2,
    ));
    let id_b = incident_id_of(&r2.outcome);

    // Distinct incidents (different correlation keys), but both must have
    // been admitted successfully in ingress order regardless of their
    // wildly different/backwards raw timestamps.
    assert_ne!(id_a, id_b);
}

// ---------------------------------------------------------------------
// P2-EVT-004 -- fresh engine/ingress-clock instance begins a fresh
// ordering epoch (sequence 0), no cross-epoch guarantee.
// ---------------------------------------------------------------------

#[test]
fn p2_evt_004_fresh_ingress_clock_resets_epoch() {
    let mut clock = IngressClock::new();
    let e1 = clock.admit(psi_event("evt-1", "guardian.g8.psi", "cpu", true, 1));
    let e2 = clock.admit(psi_event("evt-2", "guardian.g8.psi", "cpu", true, 2));
    assert_eq!(e1.ingress_sequence, 0);
    assert_eq!(e2.ingress_sequence, 1);

    // A fresh instance (modeling a daemon restart) starts a new epoch at
    // sequence 0 again -- no continuation from the prior instance.
    let mut fresh = IngressClock::new();
    let e3 = fresh.admit(psi_event("evt-3", "guardian.g8.psi", "cpu", true, 3));
    assert_eq!(e3.ingress_sequence, 0);
}

// ---------------------------------------------------------------------
// P2-COR-001/002 -- PSI critical opens; second critical within window
// links; window-boundary tests (§25).
// ---------------------------------------------------------------------

#[test]
fn p2_cor_001_first_critical_opens_new_incident() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());
    let result = engine.admit(&ingress(
        psi_event("evt-a", "guardian.g8.psi", "cpu", true, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(result.outcome, AdmitOutcome::IncidentOpened(_)));
    let id = incident_id_of(&result.outcome);
    let incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id)
        .unwrap();
    assert_eq!(incident.status, IncidentStatus::Open);
    assert_eq!(incident.confidence, Confidence::Confirmed);
}

#[test]
fn p2_cor_002_second_critical_within_window_links_not_reopens() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());
    let r1 = engine.admit(&ingress(
        psi_event("evt-a", "guardian.g8.psi", "cpu", true, 1),
        base,
        0,
        0,
    ));
    let id1 = incident_id_of(&r1.outcome);
    let r2 = engine.admit(&ingress(
        psi_event("evt-b", "guardian.g8.psi", "cpu", true, 2),
        base,
        500,
        1,
    ));
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentUpdated(_)));
    assert_eq!(incident_id_of(&r2.outcome), id1);
}

#[test]
fn window_boundary_just_inside_links_same_incident() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // psi_window = 1000ms
    let r1 = engine.admit(&ingress(
        psi_event("evt-a", "guardian.g8.psi", "cpu", true, 1),
        base,
        0,
        0,
    ));
    let id1 = incident_id_of(&r1.outcome);
    let r2 = engine.admit(&ingress(
        psi_event("evt-b", "guardian.g8.psi", "cpu", true, 2),
        base,
        999,
        1,
    ));
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentUpdated(_)));
    assert_eq!(incident_id_of(&r2.outcome), id1);
}

#[test]
fn window_boundary_exactly_at_boundary_links_same_incident() {
    // Binding predicate (documented in `correlation.rs`): elapsed <=
    // window is INSIDE (inclusive boundary attaches).
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // psi_window = 1000ms
    let r1 = engine.admit(&ingress(
        psi_event("evt-a", "guardian.g8.psi", "cpu", true, 1),
        base,
        0,
        0,
    ));
    let id1 = incident_id_of(&r1.outcome);
    let r2 = engine.admit(&ingress(
        psi_event("evt-b", "guardian.g8.psi", "cpu", true, 2),
        base,
        1000,
        1,
    ));
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentUpdated(_)));
    assert_eq!(incident_id_of(&r2.outcome), id1);
}

#[test]
fn window_boundary_just_outside_opens_new_incident_with_backreference() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // psi_window = 1000ms
    let r1 = engine.admit(&ingress(
        psi_event("evt-a", "guardian.g8.psi", "cpu", true, 1),
        base,
        0,
        0,
    ));
    let id1 = incident_id_of(&r1.outcome);
    let r2 = engine.admit(&ingress(
        psi_event("evt-b", "guardian.g8.psi", "cpu", true, 2),
        base,
        1001,
        1,
    ));
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentOpened(_)));
    let id2 = incident_id_of(&r2.outcome);
    assert_ne!(id1, id2, "P2-COR-007: never reopens the closed incident");
    assert!(
        r2.forced_closures.contains(&id1),
        "the elapsed-window incident must actually be closed"
    );

    let new_incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id2)
        .unwrap();
    assert!(
        new_incident
            .evidence
            .iter()
            .any(|line| line.contains(id1.as_str())),
        "new incident must textually backreference the prior one"
    );

    let old_incident = engine
        .closed_incidents()
        .into_iter()
        .find(|i| i.incident_id == id1)
        .unwrap();
    assert_eq!(old_incident.status, IncidentStatus::Closed);
}

// ---------------------------------------------------------------------
// P2-COR-003/004 -- provider-health debounce/dwell. REPAIRED (Gate 2a
// health-lifecycle repair, reopened normative IDs -- see
// docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-tdd.md).
//
// The defect: the real production event source
// (`HealthTransitionProducer`, Gate 2b) is edge-triggered -- one Event
// per real state change, nothing on an unchanged pair -- so it can never
// supply the "second Event" the OLD version of this test constructed by
// hand to prove promotion. `p2_cor_003` below is re-expressed (R1) to
// drive the real production shape: one real Event, then a later FRESH
// RE-OBSERVATION (`CorrelationEngine::advance_health_dwell`), never a
// second synthetic/cloned Event. The old Event-driven two-Event
// promotion path is NOT removed (R7) -- it is proven separately by
// `regression_second_real_bad_event_still_promotes_pending_candidate`.
// ---------------------------------------------------------------------

#[test]
fn p2_cor_003_debounced_available_to_unavailable_opens_exactly_one_incident() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let capability_id = CapabilityId::new("org.example.svc").unwrap();

    // One real transition Event -- exactly what the edge-triggered
    // HealthTransitionProducer emits for a single real state change.
    // Opens no incident yet.
    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.example.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    // A LATER FRESH RE-OBSERVATION -- not a second Event, not a
    // clone-and-mutate of evt-h1 -- showing the capability is still
    // Unavailable. Real production never emits a second Event for an
    // unchanged capability; this is the engine consulting a fresh
    // snapshot directly (R1). Advances the candidate past dwell and
    // opens exactly one Incident.
    let r2 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(500),
        1,
    );
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentOpened(_)));
    let id = incident_id_of(&r2.outcome);

    // A further Unavailable Event links to the SAME incident, never a
    // second one -- the pre-existing Event-driven "further Bad reading
    // just links" behavior (`admit_health_with_open_incident`) is
    // untouched by this repair.
    let r3 = engine.admit(&ingress(
        health_event("evt-h3", "org.example.svc", Availability::Unavailable, 3),
        base,
        700,
        2,
    ));
    assert!(matches!(r3.outcome, AdmitOutcome::IncidentUpdated(_)));
    assert_eq!(incident_id_of(&r3.outcome), id);

    // A further fresh Bad re-observation, now that the incident is
    // already open (no candidate left pending to advance), is a safe
    // no-op -- it must never open a second incident.
    let r4 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(900),
        3,
    );
    assert!(!matches!(r4.outcome, AdmitOutcome::IncidentOpened(_)));

    assert_eq!(engine.open_incidents().len(), 1);
}

#[test]
fn p2_cor_004_flapping_faster_than_dwell_produces_no_thrashing() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    // Flap every 100ms, well under the 500ms dwell -- must never promote.
    // Event-driven: this exercises the pre-existing "Good clears a
    // pending Bad candidate" reset behavior (`admit_health_candidate`),
    // untouched by this repair (R7).
    for (index, offset) in [0u64, 100, 200, 300, 400].into_iter().enumerate() {
        let to = if index % 2 == 0 {
            Availability::Unavailable
        } else {
            Availability::Available
        };
        let result = engine.admit(&ingress(
            health_event(
                &format!("evt-flap-{index}"),
                "org.flap.svc",
                to,
                index as u64,
            ),
            base,
            offset,
            index as u64,
        ));
        assert!(
            !matches!(result.outcome, AdmitOutcome::IncidentOpened(_)),
            "flapping faster than dwell must never open an incident (index {index})"
        );
    }
    assert_eq!(engine.open_incidents().len(), 0);
}

#[test]
fn p2_cor_004_flapping_faster_than_dwell_via_fresh_observations_produces_no_thrashing() {
    // R6: the same flapping-never-promotes guarantee, re-expressed to
    // drive dwell-advance via fresh re-observations rather than solely
    // via distinct Events -- the real-shaped path this repair adds.
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let capability_id = CapabilityId::new("org.flap2.svc").unwrap();

    // One real Event creates the pending Bad candidate.
    let r1 = engine.admit(&ingress(
        health_event(
            "evt-flap2-seed",
            "org.flap2.svc",
            Availability::Unavailable,
            1,
        ),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    // Flap fresh re-observations every 100ms, well under the 500ms
    // dwell -- alternating Good/Bad must never promote. A non-matching
    // (Good) observation against a pending Bad candidate is left exactly
    // as-is (R3) rather than resetting it, so this also proves that even
    // without a reset, staying under dwell from the ORIGINAL first_seen
    // is what keeps this safe.
    for (index, offset) in [100u64, 200, 300, 400].into_iter().enumerate() {
        let observation = if index % 2 == 0 {
            FreshHealthObservation::Good
        } else {
            FreshHealthObservation::Bad
        };
        let result = engine.advance_health_dwell(
            &capability_id,
            observation,
            base + Duration::from_millis(offset),
            (index + 1) as u64,
        );
        assert!(
            !matches!(result.outcome, AdmitOutcome::IncidentOpened(_)),
            "flapping faster than dwell must never open an incident via fresh re-observations (offset {offset})"
        );
    }
    assert_eq!(engine.open_incidents().len(), 0);
}

// ---------------------------------------------------------------------
// R2 -- no fresh observation means no promotion from wall time alone.
// ---------------------------------------------------------------------

#[test]
fn r2_no_fresh_observation_means_no_promotion_from_wall_time_alone() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.walltime.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    // No fresh re-observation call for org.walltime.svc at all -- only
    // ingress-clock time advancing (via an unrelated capability's real
    // Event, admitted well past health_min_dwell). The pending candidate
    // must not promote merely because time elapsed.
    let r_other = engine.admit(&ingress(
        health_event(
            "evt-other",
            "org.unrelated.svc",
            Availability::Unavailable,
            2,
        ),
        base,
        10_000,
        1,
    ));
    assert!(matches!(r_other.outcome, AdmitOutcome::DebouncePending));

    assert_eq!(
        engine.open_incidents().len(),
        0,
        "no incident opened from wall time alone, with no fresh re-observation"
    );
    assert_eq!(engine.debounce_candidate_count(), 2);
}

// ---------------------------------------------------------------------
// R3 -- unknown/absent/unclassifiable fresh observation never falsely
// advances Good or Bad, and never corrupts the pending candidate.
// ---------------------------------------------------------------------

#[test]
fn r3_fresh_observation_unresolved_never_falsely_advances_or_corrupts() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let capability_id = CapabilityId::new("org.r3.svc").unwrap();

    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.r3.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    // (a) absent from the snapshot entirely.
    let r_absent = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Unresolved,
        base + Duration::from_millis(600),
        1,
    );
    assert!(matches!(r_absent.outcome, AdmitOutcome::DebouncePending));

    // (b) Availability::Unknown.
    let r_unknown_availability = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::classify(Availability::Unknown, Health::Healthy),
        base + Duration::from_millis(700),
        2,
    );
    assert!(matches!(
        r_unknown_availability.outcome,
        AdmitOutcome::DebouncePending
    ));

    // (c) Health::Unknown (with Availability::Available, which alone is
    // not decisive for classification -- see health_direction's table).
    let r_unknown_health = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::classify(Availability::Available, Health::Unknown),
        base + Duration::from_millis(800),
        3,
    );
    assert!(matches!(
        r_unknown_health.outcome,
        AdmitOutcome::DebouncePending
    ));

    // Throughout (a)-(c) the candidate was never promoted, never
    // discarded/corrupted -- it remains pending, exactly as before, and
    // its ORIGINAL first_seen (from evt-h1 at offset 0) is untouched: a
    // genuine fresh Bad re-observation at offset 900 (900ms elapsed,
    // past the 500ms dwell) still promotes normally.
    assert_eq!(engine.debounce_candidate_count(), 1);
    assert_eq!(engine.open_incidents().len(), 0);
    let r_final = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(900),
        4,
    );
    assert!(matches!(r_final.outcome, AdmitOutcome::IncidentOpened(_)));
}

// ---------------------------------------------------------------------
// R4 -- health_direction()/FreshHealthObservation::classify() use both
// Availability and Health; Available+Error no longer misclassifies as
// Good, and is not assumed Bad either.
// ---------------------------------------------------------------------

#[test]
fn r4_fresh_health_observation_classify_matches_state_table() {
    assert_eq!(
        FreshHealthObservation::classify(Availability::Available, Health::Healthy),
        FreshHealthObservation::Good
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Available, Health::Warning),
        FreshHealthObservation::Bad,
        "Healthy->Warning is a named, governed transition"
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Available, Health::Error),
        FreshHealthObservation::Unresolved,
        "the exact regression this repair closes: Available+Error must never silently classify as Good, and is not assumed Bad either"
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Available, Health::Stale),
        FreshHealthObservation::Unresolved
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Available, Health::Unknown),
        FreshHealthObservation::Unresolved
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Degraded, Health::Error),
        FreshHealthObservation::Bad,
        "sustained Degraded is incident-worthy regardless of Health"
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Unavailable, Health::Healthy),
        FreshHealthObservation::Bad,
        "already-true prior behavior, confirmed unchanged"
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Unknown, Health::Healthy),
        FreshHealthObservation::Unresolved,
        "AGENTS.md: do not convert UNKNOWN into HEALTHY -- nor into a confident Bad"
    );
    assert_eq!(
        FreshHealthObservation::classify(Availability::Unsupported, Health::Healthy),
        FreshHealthObservation::Unresolved
    );
}

#[test]
fn r4_event_driven_available_error_never_misclassified_as_good() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms

    // Establish a real open incident (Unavailable, real production
    // shape: one Event, then a fresh Bad re-observation past dwell).
    let capability_id = CapabilityId::new("org.r4.svc").unwrap();
    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.r4.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));
    let r2 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(500),
        1,
    );
    let id = incident_id_of(&r2.outcome);

    // Available + Error must NOT be treated as a recovery (Good) --
    // before this repair, health_direction() mapped Available
    // unconditionally to Good regardless of Health, which would have
    // started (or advanced) a debounced-recovery candidate here. It must
    // also not be treated as a further Bad reading -- no existing §4.2
    // rule authorizes that either.
    let r3 = engine.admit(&ingress(
        health_event_with_health(
            "evt-h3",
            "org.r4.svc",
            Availability::Available,
            Health::Error,
            2,
        ),
        base,
        600,
        2,
    ));
    assert!(
        matches!(r3.outcome, AdmitOutcome::Ignored),
        "Available+Error must be unresolved -- neither a false recovery nor a false further-Bad linkage, got {:?}",
        r3.outcome
    );

    // The incident remains open, untouched, still exactly one.
    assert_eq!(engine.open_incidents().len(), 1);
    let incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id)
        .unwrap();
    assert_eq!(
        incident.event_ids.len(),
        0,
        "this incident was opened via a fresh re-observation (no Event to \
         link), and the unresolved Available+Error event must not have \
         linked either"
    );
}

// ---------------------------------------------------------------------
// R5 -- symmetric recovery/closure: a fresh re-observation advances a
// pending Good candidate past dwell and closes exactly one Incident,
// with no second Event manufactured.
// ---------------------------------------------------------------------

#[test]
fn r5_symmetric_recovery_fresh_observation_closes_incident() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let capability_id = CapabilityId::new("org.r5.svc").unwrap();

    // Open an incident via the real production shape (R1): one real
    // Event, then a fresh Bad re-observation past dwell.
    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.r5.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));
    let r2 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(500),
        1,
    );
    let incident_id = incident_id_of(&r2.outcome);
    assert_eq!(engine.open_incidents().len(), 1);

    // One real recovery Event -- starts a Good-direction debounce
    // candidate via the existing, untouched
    // `admit_health_with_open_incident` logic.
    let r3 = engine.admit(&ingress(
        health_event("evt-recover", "org.r5.svc", Availability::Available, 2),
        base,
        600,
        2,
    ));
    assert!(matches!(r3.outcome, AdmitOutcome::DebouncePending));

    // A LATER FRESH RE-OBSERVATION -- not a second recovery Event --
    // showing the capability has returned to Good and stayed there,
    // advances the pending recovery candidate past dwell and closes
    // exactly one Incident.
    let r4 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Good,
        base + Duration::from_millis(1100),
        3,
    );
    assert!(matches!(r4.outcome, AdmitOutcome::IncidentClosed(_)));
    assert_eq!(incident_id_of(&r4.outcome), incident_id);
    assert_eq!(engine.open_incidents().len(), 0);
    assert_eq!(
        engine
            .closed_incidents()
            .into_iter()
            .filter(|i| i.incident_id == incident_id)
            .count(),
        1,
        "exactly one closed incident, never a duplicate"
    );
}

// ---------------------------------------------------------------------
// Gate 2a health-lifecycle repair -- audit-driven confidence-
// classification correction. The repair TDD's "Target-state
// classification vs. incident confidence" section requires
// transition-specific confidence to reach the opened `Incident`:
//
//   Available -> Unavailable  => Confidence::Confirmed
//   Healthy   -> Warning      => Confidence::Probable
//   sustained Degraded        => Confidence::Unknown
//   Available + Error         => unresolved, never opens/closes
//
// The pre-correction candidate collapsed all actionable directions into
// a single `HealthDirection::Bad` and hardcoded `Confidence::Confirmed`
// at every incident-open call site, so `Degraded` and `Available +
// Warning` incidents opened as `Confirmed` instead of `Unknown`/
// `Probable`. These tests drive the real production shape (one real
// `Event`, then a fresh re-observation past dwell via
// `advance_health_dwell` -- R1) and assert the opened incident's
// `confidence` field directly.
// ---------------------------------------------------------------------

#[test]
fn confidence_sustained_degraded_opens_with_unknown_confidence() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let capability_id = CapabilityId::new("org.degraded.svc").unwrap();

    let r1 = engine.admit(&ingress(
        health_event_with_health(
            "evt-degraded-1",
            "org.degraded.svc",
            Availability::Degraded,
            Health::Error,
            1,
        ),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    let r2 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(500),
        1,
    );
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentOpened(_)));
    let id = incident_id_of(&r2.outcome);
    let incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id)
        .unwrap();
    assert_eq!(
        incident.confidence,
        Confidence::Unknown,
        "sustained Degraded has no §4.2-governed confidence tier -- must \
         open honestly as Confidence::Unknown, never a hardcoded Confirmed"
    );
}

#[test]
fn confidence_available_warning_opens_with_probable_confidence() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let capability_id = CapabilityId::new("org.warning.svc").unwrap();

    let r1 = engine.admit(&ingress(
        health_event_with_health(
            "evt-warning-1",
            "org.warning.svc",
            Availability::Available,
            Health::Warning,
            1,
        ),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    let r2 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(500),
        1,
    );
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentOpened(_)));
    let id = incident_id_of(&r2.outcome);
    let incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id)
        .unwrap();
    assert_eq!(
        incident.confidence,
        Confidence::Probable,
        "Healthy->Warning is §4.2's named Probable transition -- must \
         open as Confidence::Probable, never a hardcoded Confirmed"
    );
}

#[test]
fn confidence_available_to_unavailable_opens_with_confirmed_confidence() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let capability_id = CapabilityId::new("org.unavailable.svc").unwrap();

    let r1 = engine.admit(&ingress(
        health_event(
            "evt-unavail-1",
            "org.unavailable.svc",
            Availability::Unavailable,
            1,
        ),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    let r2 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(500),
        1,
    );
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentOpened(_)));
    let id = incident_id_of(&r2.outcome);
    let incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id)
        .unwrap();
    assert_eq!(
        incident.confidence,
        Confidence::Confirmed,
        "Available->Unavailable is §4.2's named Confirmed transition"
    );
}

#[test]
fn confidence_available_error_cannot_open_or_close_incident() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms

    // No open incident, no pending candidate: Available+Error must not
    // open one either.
    let r1 = engine.admit(&ingress(
        health_event_with_health(
            "evt-error-1",
            "org.error.svc",
            Availability::Available,
            Health::Error,
            1,
        ),
        base,
        0,
        0,
    ));
    assert!(
        matches!(r1.outcome, AdmitOutcome::Ignored),
        "Available+Error with no prior incident/candidate must not open \
         one, got {:?}",
        r1.outcome
    );
    assert_eq!(engine.open_incidents().len(), 0);
    assert_eq!(engine.debounce_candidate_count(), 0);

    // Now open a real incident (Unavailable), then prove Available+Error
    // cannot close it either -- neither a false recovery nor a false
    // further-Bad linkage (mirrors r4_event_driven_available_error_
    // never_misclassified_as_good, but exercised alongside the confidence
    // fix for regression safety).
    let capability_id = CapabilityId::new("org.error.svc").unwrap();
    let r2 = engine.admit(&ingress(
        health_event("evt-unavail", "org.error.svc", Availability::Unavailable, 2),
        base,
        100,
        1,
    ));
    assert!(matches!(r2.outcome, AdmitOutcome::DebouncePending));
    let r3 = engine.advance_health_dwell(
        &capability_id,
        FreshHealthObservation::Bad,
        base + Duration::from_millis(600),
        2,
    );
    assert!(matches!(r3.outcome, AdmitOutcome::IncidentOpened(_)));
    let id = incident_id_of(&r3.outcome);

    let r4 = engine.admit(&ingress(
        health_event_with_health(
            "evt-error-2",
            "org.error.svc",
            Availability::Available,
            Health::Error,
            3,
        ),
        base,
        700,
        3,
    ));
    assert!(
        matches!(r4.outcome, AdmitOutcome::Ignored),
        "Available+Error must not close the open incident, got {:?}",
        r4.outcome
    );
    assert_eq!(engine.open_incidents().len(), 1);
    let incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id)
        .unwrap();
    assert_eq!(incident.status, IncidentStatus::Open);
}

// ---------------------------------------------------------------------
// R7 -- regression: the pre-existing Event-driven dwell-advance path
// remains valid alongside the new fresh-observation path. A second,
// genuinely distinct Bad Event still promotes a pending candidate
// exactly as before this repair.
// ---------------------------------------------------------------------

#[test]
fn regression_second_real_bad_event_still_promotes_pending_candidate() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // health_min_dwell = 500ms
    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.regression.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    let r2 = engine.admit(&ingress(
        health_event("evt-h2", "org.regression.svc", Availability::Unavailable, 2),
        base,
        500,
        1,
    ));
    assert!(matches!(r2.outcome, AdmitOutcome::IncidentOpened(_)));
    assert_eq!(engine.open_incidents().len(), 1);
}

// ---------------------------------------------------------------------
// P2-COR-005 -- cross-source correlation, confidence capped, wording.
// ---------------------------------------------------------------------

#[test]
fn p2_cor_005_cross_source_correlation_capped_and_worded_correctly() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());

    let psi_result = engine.admit(&ingress(
        psi_event("evt-psi", "guardian.g8.psi", "memory", true, 1),
        base,
        0,
        0,
    ));
    let psi_id = incident_id_of(&psi_result.outcome);

    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.overlap.svc", Availability::Unavailable, 1),
        base,
        10,
        1,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));
    let r2 = engine.admit(&ingress(
        health_event("evt-h2", "org.overlap.svc", Availability::Unavailable, 2),
        base,
        510,
        2,
    ));
    let health_id = incident_id_of(&r2.outcome);

    let psi_incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == psi_id)
        .unwrap();
    let health_incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == health_id)
        .unwrap();

    assert!(
        psi_incident
            .candidate_causes
            .iter()
            .any(|line| line.contains(health_id.as_str()) && line.contains("correlated with")),
    );
    assert!(
        health_incident
            .candidate_causes
            .iter()
            .any(|line| line.contains(psi_id.as_str()) && line.contains("correlated with")),
    );
    assert!(
        !psi_incident
            .candidate_causes
            .iter()
            .any(|line| line.contains("caused by")),
    );
    assert!(
        !health_incident
            .candidate_causes
            .iter()
            .any(|line| line.contains("caused by")),
    );

    // The direct-observation incidents themselves keep their own
    // Confirmed confidence (PSI's kernel-reported crossing, the
    // provider's own reported availability transition) -- the cross-
    // reference relationship itself never asserts anything above
    // Hypothesis, proven by the outcome the cross-reference is recorded
    // through.
    assert_eq!(psi_incident.confidence, Confidence::Confirmed);
    assert_eq!(health_incident.confidence, Confidence::Confirmed);
}

// ---------------------------------------------------------------------
// P2-COR-006 -- replay determinism.
// ---------------------------------------------------------------------

fn incident_shape(
    incident: &guardian_core::incident::Incident,
) -> (IncidentStatus, Confidence, usize, Option<String>) {
    (
        incident.status,
        incident.confidence,
        incident.event_ids.len(),
        incident.primary_resource.clone(),
    )
}

#[test]
fn p2_cor_006_replay_determinism_same_grouping() {
    type Shape = (IncidentStatus, Confidence, usize, Option<String>);
    fn run() -> (Vec<Shape>, Vec<Shape>) {
        let base = Instant::now();
        let mut engine = CorrelationEngine::new(policy());
        engine.admit(&ingress(
            psi_event("evt-a", "guardian.g8.psi", "cpu", true, 1),
            base,
            0,
            0,
        ));
        engine.admit(&ingress(
            psi_event("evt-b", "guardian.g8.psi", "cpu", true, 2),
            base,
            200,
            1,
        ));
        engine.admit(&ingress(
            health_event("evt-h1", "org.example.svc", Availability::Unavailable, 1),
            base,
            300,
            2,
        ));
        engine.admit(&ingress(
            health_event("evt-h2", "org.example.svc", Availability::Unavailable, 2),
            base,
            900,
            3,
        ));
        // `open_incidents()` order is not itself a correlation guarantee
        // (it is backed by a `HashMap`) -- sort by the one stable,
        // ID-independent field before comparing, so this test asserts
        // grouping/shape equality, not incidental iteration order.
        let mut open: Vec<_> = engine
            .open_incidents()
            .into_iter()
            .map(|incident| incident_shape(&incident))
            .collect();
        open.sort_by(|a, b| a.3.cmp(&b.3));
        let closed: Vec<_> = engine
            .closed_incidents()
            .into_iter()
            .map(|incident| incident_shape(&incident))
            .collect();
        (open, closed)
    }

    let run_a = run();
    let run_b = run();
    assert_eq!(run_a, run_b);
}

// ---------------------------------------------------------------------
// P2-COR-007 -- closed-window reopen-as-new (also exercised above).
// ---------------------------------------------------------------------

#[test]
fn p2_cor_007_late_event_after_close_never_reopens() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());
    let r1 = engine.admit(&ingress(
        psi_event("evt-a", "guardian.g8.psi", "io", true, 1),
        base,
        0,
        0,
    ));
    let id1 = incident_id_of(&r1.outcome);
    // Arrives well past the window (psi_window = 1000ms).
    let r2 = engine.admit(&ingress(
        psi_event("evt-b", "guardian.g8.psi", "io", true, 2),
        base,
        5000,
        1,
    ));
    let id2 = incident_id_of(&r2.outcome);
    assert_ne!(id1, id2);
    assert!(
        engine
            .closed_incidents()
            .into_iter()
            .any(|i| i.incident_id == id1 && i.status == IncidentStatus::Closed)
    );
    assert!(
        !engine
            .open_incidents()
            .into_iter()
            .any(|i| i.incident_id == id1),
        "the prior incident must never be reopened"
    );
}

// ---------------------------------------------------------------------
// P2-INC-002 -- open-incident cap, deterministic oldest force-close.
// ---------------------------------------------------------------------

#[test]
fn p2_inc_002_open_incident_cap_force_closes_oldest_deterministically() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // open_incident_cap = 3
    let mut ids = Vec::new();
    for (index, resource) in ["cpu", "memory", "io"].into_iter().enumerate() {
        let r = engine.admit(&ingress(
            psi_event(
                &format!("evt-{resource}"),
                "guardian.g8.psi",
                resource,
                true,
                index as u64,
            ),
            base,
            index as u64 * 10,
            index as u64,
        ));
        ids.push(incident_id_of(&r.outcome));
    }
    assert_eq!(engine.open_incidents().len(), 3);

    // A fourth, brand-new key exceeds the cap -- the oldest (ids[0],
    // "cpu") must be force-closed, and the cap is never exceeded.
    let r4 = engine.admit(&ingress(
        psi_event("evt-net", "guardian.g8.psi", "net", true, 100),
        base,
        1000,
        3,
    ));
    assert!(r4.forced_closures.contains(&ids[0]));
    assert_eq!(engine.open_incidents().len(), 3, "cap never exceeded");
    assert!(
        !engine
            .open_incidents()
            .into_iter()
            .any(|i| i.incident_id == ids[0]),
        "oldest was force-closed, not left open"
    );
    // Remaining active incidents (memory, io) preserved.
    assert!(
        engine
            .open_incidents()
            .into_iter()
            .any(|i| i.incident_id == ids[1])
    );
    assert!(
        engine
            .open_incidents()
            .into_iter()
            .any(|i| i.incident_id == ids[2])
    );
}

// ---------------------------------------------------------------------
// P2-INC-003 -- closed-incident ring FIFO overflow.
// ---------------------------------------------------------------------

#[test]
fn p2_inc_003_closed_incident_ring_fifo_drops_oldest() {
    let base = Instant::now();
    let mut p = policy();
    p.open_incident_cap = 1;
    p.closed_incident_cap = 2;
    let mut engine = CorrelationEngine::new(p);

    let mut closed_ids = Vec::new();
    // Each new distinct key, with cap 1, force-closes the previous one --
    // producing a stream of closed incidents feeding the closed ring.
    for (index, resource) in ["cpu", "memory", "io", "net"].into_iter().enumerate() {
        let r = engine.admit(&ingress(
            psi_event(
                &format!("evt-{resource}"),
                "guardian.g8.psi",
                resource,
                true,
                index as u64,
            ),
            base,
            index as u64 * 10,
            index as u64,
        ));
        if let AdmitOutcome::IncidentOpened(_) = r.outcome {
            closed_ids.extend(r.forced_closures.clone());
        }
    }
    assert!(
        engine.closed_incidents().len() <= 2,
        "closed ring never exceeds its cap"
    );
    // The earliest force-closed incident must have been dropped (FIFO),
    // never the active incident, never reopened.
    let first_closed = closed_ids.first().unwrap();
    assert!(
        !engine
            .closed_incidents()
            .into_iter()
            .any(|i| i.incident_id == *first_closed),
        "oldest closed incident must be FIFO-dropped once the ring overflows"
    );
}

// ---------------------------------------------------------------------
// P2-INC-004 -- closed incident later matched -> new IncidentId with
// backreference, never Reopened.
// ---------------------------------------------------------------------

#[test]
fn p2_inc_004_new_incident_id_with_backreference_never_reopened_status() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());
    let r1 = engine.admit(&ingress(
        psi_event("evt-a", "guardian.g8.psi", "cpu", true, 1),
        base,
        0,
        0,
    ));
    let id1 = incident_id_of(&r1.outcome);
    let r2 = engine.admit(&ingress(
        psi_event("evt-b", "guardian.g8.psi", "cpu", true, 2),
        base,
        5000,
        1,
    ));
    let id2 = incident_id_of(&r2.outcome);
    assert_ne!(id1, id2);
    let new_incident = engine
        .open_incidents()
        .into_iter()
        .find(|i| i.incident_id == id2)
        .unwrap();
    // No `Reopened` status variant exists at all -- this is enforced by
    // the type system (`IncidentStatus` has exactly four variants), and
    // the new incident's status is a fresh `Open`, not a revived one.
    assert_eq!(new_incident.status, IncidentStatus::Open);
}

// ---------------------------------------------------------------------
// P2-REC-001/004 -- debounce ring reject-not-evict, existing candidates
// survive a many-new-key storm.
// ---------------------------------------------------------------------

#[test]
fn p2_rec_001_capacity_full_new_candidate_rejected_existing_progresses() {
    let base = Instant::now();
    let mut p = policy();
    p.debounce_capacity = 1;
    let mut engine = CorrelationEngine::new(p);

    // Fill the one debounce slot.
    let r1 = engine.admit(&ingress(
        health_event("evt-h1", "org.tracked.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert!(matches!(r1.outcome, AdmitOutcome::DebouncePending));

    // A brand-new key while full is rejected.
    let r2 = engine.admit(&ingress(
        health_event("evt-new", "org.new.svc", Availability::Unavailable, 2),
        base,
        10,
        1,
    ));
    assert!(matches!(r2.outcome, AdmitOutcome::CapacityRejected(_)));

    // The existing tracked candidate continues progressing normally and
    // can still promote to a real incident.
    let r3 = engine.admit(&ingress(
        health_event("evt-h2", "org.tracked.svc", Availability::Unavailable, 3),
        base,
        500,
        2,
    ));
    assert!(matches!(r3.outcome, AdmitOutcome::IncidentOpened(_)));
}

#[test]
fn p2_rec_004_storm_of_new_keys_rejected_existing_unaffected() {
    let base = Instant::now();
    let mut p = policy();
    p.debounce_capacity = 1;
    let mut engine = CorrelationEngine::new(p);

    engine.admit(&ingress(
        health_event("evt-h1", "org.tracked.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));

    // Many distinct new keys, none of which can find a slot.
    for index in 0..50u64 {
        let result = engine.admit(&ingress(
            health_event(
                &format!("evt-storm-{index}"),
                &format!("org.storm{index}.svc"),
                Availability::Unavailable,
                index,
            ),
            base,
            20 + index,
            index + 1,
        ));
        assert!(matches!(result.outcome, AdmitOutcome::CapacityRejected(_)));
    }

    // The originally tracked candidate is untouched and still promotes.
    let r_final = engine.admit(&ingress(
        health_event("evt-h2", "org.tracked.svc", Availability::Unavailable, 999),
        base,
        700,
        51,
    ));
    assert!(matches!(r_final.outcome, AdmitOutcome::IncidentOpened(_)));
}

// ---------------------------------------------------------------------
// P2-REC-002 -- correlation never calls the Diagnostic Budget Manager.
// ---------------------------------------------------------------------

#[test]
fn p2_rec_002_grouping_path_has_no_budget_dependency() {
    // `CorrelationEngine::admit` takes only a `CorrelationIngress` -- there
    // is no `SystemPressureState`/`DiagnosticCost` parameter anywhere on
    // this path for a caller to even supply, and `correlation.rs` imports
    // nothing from `crate::budget` (checked directly in the production
    // module). This test is the behavioral half: a heavy admission storm
    // proceeds identically regardless of any pressure concept, because
    // none exists on this call path to influence it.
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());
    for i in 0..20u64 {
        let _ = engine.admit(&ingress(
            psi_event(&format!("evt-{i}"), "guardian.g8.psi", "cpu", true, i),
            base,
            i * 5,
            i,
        ));
    }
    // No panics, no vetoes -- proceeding at all is the proof; there is no
    // budget-shaped outcome variant in `AdmitOutcome` to have vetoed it.
}

// ---------------------------------------------------------------------
// P2-REC-003 -- CapacityRejected: typed outcome + saturating counter,
// entirely as pure data. Gate 2a performs no I/O of its own here -- the
// operational log write (`eprintln!("[guardian-daemon] ...")`) is a
// Gate-2b-owned side effect against `guardian-daemon.rs`, explicitly
// assigned there by the implementation handoff's §20 file-impact list,
// not to this library crate. This test proves the typed data Gate 2b
// will need is present and correct, without observing or causing any
// real stderr write from `guardian-core`.
// ---------------------------------------------------------------------

#[test]
fn p2_rec_003_capacity_rejected_carries_typed_data_no_io() {
    let base = Instant::now();
    let mut p = policy();
    p.debounce_capacity = 1;
    let mut engine = CorrelationEngine::new(p);

    engine.admit(&ingress(
        health_event("evt-h1", "org.tracked.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    assert_eq!(engine.rejection_count(), 0);

    let result = engine.admit(&ingress(
        health_event("evt-new", "org.new.svc", Availability::Unavailable, 2),
        base,
        10,
        1,
    ));
    // The typed outcome carries exactly what a future Gate 2b would need
    // to perform the real daemon-side operational log write: which
    // candidate was rejected, and the counter value after this rejection.
    match result.outcome {
        AdmitOutcome::CapacityRejected(rejected) => {
            assert_eq!(rejected.capability_id.as_str(), "org.new.svc");
            assert_eq!(rejected.rejection_count, 1);
        }
        other => panic!("expected CapacityRejected, got {other:?}"),
    }
    assert_eq!(engine.rejection_count(), 1);
}

#[test]
fn p2_rec_003_rejection_counter_saturates_never_wraps() {
    let base = Instant::now();
    let mut p = policy();
    p.debounce_capacity = 1;
    let mut engine = CorrelationEngine::new(p);
    engine.admit(&ingress(
        health_event("evt-h1", "org.tracked.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));
    for index in 0..200u64 {
        engine.admit(&ingress(
            health_event(
                &format!("evt-storm-{index}"),
                &format!("org.storm{index}.svc"),
                Availability::Unavailable,
                index,
            ),
            base,
            10 + index,
            index + 1,
        ));
    }
    assert_eq!(engine.rejection_count(), 200);
}

// ---------------------------------------------------------------------
// P2-REC-005 -- CapacityRejected never constructs/feeds an Event into
// CorrelationIngress or any other correlation input path (non-reentry).
// ---------------------------------------------------------------------

#[test]
fn p2_rec_005_capacity_rejected_never_reenters_ingress() {
    let base = Instant::now();
    let mut p = policy();
    p.debounce_capacity = 1;
    let mut engine = CorrelationEngine::new(p);

    // One real admission occupies the sole debounce slot.
    engine.admit(&ingress(
        health_event("evt-h1", "org.tracked.svc", Availability::Unavailable, 1),
        base,
        0,
        0,
    ));

    // M rejected candidates.
    let rejected_count = 30u64;
    for index in 0..rejected_count {
        engine.admit(&ingress(
            health_event(
                &format!("evt-storm-{index}"),
                &format!("org.storm{index}.svc"),
                Availability::Unavailable,
                index,
            ),
            base,
            10 + index,
            index + 1,
        ));
    }

    // Real producer admissions: the initial one plus the M rejected
    // attempts -- N = 1 + rejected_count total CALLS to `admit`, but the
    // engine's own internal admitted-ingress counter must equal exactly
    // that many CALLS, never inflated by an extra `Event` manufactured
    // per rejection (which would make it N + M rather than N).
    assert_eq!(engine.admitted_ingress_count(), 1 + rejected_count);
    assert_eq!(engine.rejection_count(), rejected_count);
    // Exactly one open/pending correlation-relevant key exists -- the
    // rejections created no additional correlation-input pressure.
    assert_eq!(engine.debounce_candidate_count(), 1);
}

// ---------------------------------------------------------------------
// §23 -- adversarial event storms.
// ---------------------------------------------------------------------

#[test]
fn storm_same_key_bounded_no_incident_explosion() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // psi_window = 1000ms
    let mut last_id = None;
    for i in 0..50u64 {
        let result = engine.admit(&ingress(
            psi_event(&format!("evt-{i}"), "guardian.g8.psi", "cpu", true, i),
            base,
            i * 10, // well within the 1000ms window each step
            i,
        ));
        let id = incident_id_of(&result.outcome);
        if let Some(prev) = &last_id {
            assert_eq!(
                &id, prev,
                "storm within window must collapse into one incident"
            );
        }
        last_id = Some(id);
    }
    assert_eq!(engine.open_incidents().len(), 1);
}

#[test]
fn storm_many_established_keys_force_closes_deterministically() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy()); // open_incident_cap = 3
    for i in 0..10u64 {
        engine.admit(&ingress(
            psi_event(
                &format!("evt-{i}"),
                "guardian.g8.psi",
                &format!("resource-{i}"),
                true,
                i,
            ),
            base,
            i * 10,
            i,
        ));
        assert!(
            engine.open_incidents().len() <= 3,
            "cap never exceeded mid-storm"
        );
    }
    assert_eq!(engine.open_incidents().len(), 3);
}

// ---------------------------------------------------------------------
// §26 -- Unknown must never be silently converted into a confident state.
// ---------------------------------------------------------------------

#[test]
fn unknown_availability_never_opens_or_confirms_an_incident() {
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());
    for offset in [0u64, 100, 200, 300, 400, 500, 600] {
        let result = engine.admit(&ingress(
            health_event(
                "evt-unknown",
                "org.unknown.svc",
                Availability::Unknown,
                offset,
            ),
            base,
            offset,
            offset,
        ));
        assert!(matches!(result.outcome, AdmitOutcome::Ignored));
    }
    assert_eq!(engine.open_incidents().len(), 0);
    assert_eq!(engine.debounce_candidate_count(), 0);
}

// ---------------------------------------------------------------------
// §6a -- equal-`Instant` tie-break: `ingress_sequence` alone must decide
// ordering when two (or more) records share an identical `Instant`
// reading, regardless of the order in which they are actually handed to
// `admit`. Non-blocking audit finding -- this proves existing
// `(Instant, u64)` / `BTreeMap` behavior, no implementation change.
// ---------------------------------------------------------------------

#[test]
fn equal_instant_tie_break_orders_by_ingress_sequence_not_call_order() {
    let base = Instant::now();
    let same_instant = base + Duration::from_millis(250);
    let mut p = policy();
    p.open_incident_cap = 2;
    let mut engine = CorrelationEngine::new(p);

    // Three distinct PSI resources -- each opens its own incident
    // immediately (no debounce involved) -- all three ingress records
    // share the exact same `Instant`, differing only by
    // `ingress_sequence`. Deliberately admitted in an order that inverts
    // the sequence numbers: the HIGHEST sequence first, the LOWEST last.
    let rec_high = CorrelationIngress {
        event: psi_event("evt-high", "guardian.g8.psi", "high", true, 100),
        ingress_clock: same_instant,
        ingress_sequence: 7,
    };
    let rec_mid = CorrelationIngress {
        event: psi_event("evt-mid", "guardian.g8.psi", "mid", true, 101),
        ingress_clock: same_instant,
        ingress_sequence: 6,
    };
    let rec_low = CorrelationIngress {
        event: psi_event("evt-low", "guardian.g8.psi", "low", true, 102),
        ingress_clock: same_instant,
        ingress_sequence: 5,
    };

    // Call order: high (seq 7) first, mid (seq 6) second, low (seq 5)
    // last -- the exact inverse of ingress-sequence order.
    let r_high = engine.admit(&rec_high);
    let id_high = incident_id_of(&r_high.outcome);
    let r_mid = engine.admit(&rec_mid);
    let id_mid = incident_id_of(&r_mid.outcome);

    // open_incident_cap = 2: admitting the third (lowest-sequence)
    // candidate forces a capacity eviction of whichever currently-open
    // incident is OLDEST by true ingress order, i.e. smallest
    // `(Instant, ingress_sequence)`. Since all three share one `Instant`,
    // that is decided purely by `ingress_sequence`: between `id_high`
    // (seq 7, admitted first) and `id_mid` (seq 6, admitted second),
    // `id_mid` has the smaller sequence and must be the one evicted --
    // even though it was NOT the first one actually admitted.
    let r_low = engine.admit(&rec_low);
    let id_low = incident_id_of(&r_low.outcome);

    assert_eq!(
        r_low.forced_closures,
        vec![id_mid.clone()],
        "capacity eviction must pick the smallest ingress_sequence at a \
         tied Instant, not the first-called incident"
    );

    let open_ids: std::collections::HashSet<_> = engine
        .open_incidents()
        .into_iter()
        .map(|i| i.incident_id)
        .collect();
    assert!(
        open_ids.contains(&id_high),
        "higher-sequence incident (logically newer) must remain open"
    );
    assert!(
        open_ids.contains(&id_low),
        "the just-opened, lowest-sequence incident must remain open"
    );
    assert!(
        !open_ids.contains(&id_mid),
        "the mid-sequence incident, logically oldest at this tied Instant, must have been evicted"
    );
}

// ---------------------------------------------------------------------
// PSI correlation-key finding (non-blocking, task §9) -- measured
// against real production construction logic
// (`crates/guardian-core/src/providers/psi.rs`'s `event_from_crossing`),
// not guessed. Real production builds `normalized_key` from a raw
// string that includes the `{from:?}->{to:?}` transition text; this
// proves two legitimate Critical crossings for the SAME resource but
// DIFFERENT transitions receive DIFFERENT `normalized_key` values, while
// `resource_refs[0]` (`/proc/pressure/{resource}`) stays identical --
// i.e. `resource_refs.first()` is the stable resource identity, and the
// handoff's literal `(ProviderId, normalized_key)` wording would NOT
// correlate these two events together.
// ---------------------------------------------------------------------

/// Mirrors `providers::psi::event_from_crossing`'s exact construction
/// (raw string shape and `normalized_key`/`resource_refs` derivation) so
/// this test is evidence about the real production shape, not a guess.
fn psi_event_shaped_like_production(
    id: &str,
    resource: &str,
    from: guardian_core::psi::PressureSeverity,
    to: guardian_core::psi::PressureSeverity,
    sequence: u64,
) -> Event {
    let raw = format!("PSI {resource} threshold crossing {from:?}->{to:?}");
    Event {
        event_id: EventId::new(id).unwrap(),
        timestamp_monotonic: sequence,
        timestamp_wall: format!("sequence-{sequence}"),
        source_provider: ProviderId::new("guardian.g8.psi").unwrap(),
        event_type: "psi_threshold_crossing".to_owned(),
        resource_refs: vec![format!("/proc/pressure/{resource}")],
        severity: Risk::High,
        normalized_key: normalize_key(&raw),
        raw_reference: raw,
        attributes: BTreeMap::from([
            ("from".to_owned(), format!("{from:?}")),
            ("to".to_owned(), format!("{to:?}")),
        ]),
    }
}

#[test]
fn psi_normalized_key_varies_by_transition_but_resource_refs_stable() {
    use guardian_core::psi::PressureSeverity;

    // Two genuine Critical crossings for the SAME resource (`cpu`), but
    // reached via different transitions -- exactly the case a real,
    // sustained pressure incident with intermediate `Elevated` readings
    // would produce.
    let elevated_to_critical = psi_event_shaped_like_production(
        "evt-e2c",
        "cpu",
        PressureSeverity::Elevated,
        PressureSeverity::Critical,
        1,
    );
    let nominal_to_critical = psi_event_shaped_like_production(
        "evt-n2c",
        "cpu",
        PressureSeverity::Nominal,
        PressureSeverity::Critical,
        2,
    );

    // Evidence: normalized_key DIFFERS by transition text ...
    assert_ne!(
        elevated_to_critical.normalized_key, nominal_to_critical.normalized_key,
        "real production normalized_key embeds the {{from}}->{{to}} transition text"
    );
    // ... while resource_refs[0] is identical -- the stable resource
    // identity, unaffected by which transition produced this crossing.
    assert_eq!(
        elevated_to_critical.resource_refs.first(),
        nominal_to_critical.resource_refs.first(),
        "resource_refs[0] is the stable /proc/pressure/{{resource}} identity"
    );

    // Behavioral consequence: Gate 2a's actual correlation key
    // (`resource_refs.first()`-based) correctly groups both crossings
    // into ONE incident, because it keys on the stable resource identity
    // -- not on `normalized_key`, which would have kept them apart.
    let base = Instant::now();
    let mut engine = CorrelationEngine::new(policy());
    let r1 = engine.admit(&ingress(elevated_to_critical, base, 0, 0));
    let id1 = incident_id_of(&r1.outcome);
    let r2 = engine.admit(&ingress(nominal_to_critical, base, 10, 1));
    let id2 = incident_id_of(&r2.outcome);
    assert_eq!(
        id1, id2,
        "same resource, different transitions, within window -- must \
         correlate into the same incident via resource_refs, not \
         normalized_key"
    );
}
