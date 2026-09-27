//! `guardian-daemon` — G7's unprivileged production process (ADR-002 Model
//! B; G7 implementation handoff §2). Owns `io.github.cliffthelin.Guardian1`
//! on the real system bus. Never relays a client's privileged write
//! request to `guardian-helper` (§2.3) — this binary has no code path that
//! constructs a call against `GuardianHelper1`, and never will while
//! `GuardianHelper1` remains the sole privileged-mutation surface.
//!
//! **G8 update to the G7 "no D-Bus client/proxy construction" claim**: G7's
//! original doc comment stated this binary constructed no D-Bus client/
//! proxy of any kind. That was true at G7 and is no longer true: G8 adds
//! exactly six read-only provider client proxies
//! ([`guardian_core::providers`] — systemd1, `PSI`, login1, `UDisks2`,
//! `UPower`, `Accounts`), driven from [`capability_registry_tick`]. None of
//! the six is `GuardianHelper1`; none performs a write; the G7 invariant
//! this comment originally protected (never proxying to the privileged
//! helper) is unchanged and still holds. Only the broader, imprecise
//! restatement of that invariant needed correcting.
//!
//! **Repair of the independent audit's public-API-scope finding**: this
//! binary previously served an additive `Guardian1.Transactions1` object
//! with one Class B evidence method
//! (`AttemptProviderDelegatedWrite`). That method was not required by any
//! of the nine G7 normative IDs and was removed — `Guardian1` now serves
//! only the frozen G0 contract
//! ([`guardian_daemon::GuardianContract`], unchanged since G0). Class B's
//! architecture (provider-owned authorization, daemon-local transaction
//! ownership, no helper involvement) is proved instead by a disposable
//! prototype under `tests/vm/g7-class-b-prototype/`, following the same
//! precedent G2's Model B evidence used — never merged into production.
//! G8's Capability Registry population is internal state only (handoff
//! §12) — it adds no new `Guardian1` object or method either.
//!
//! **G9 update**: this binary now also serves three real, read-only
//! interfaces at their own object paths — `Capabilities1`, `Incidents1`,
//! `Transactions1` (`crates/guardian-daemon/src/dbus_surface.rs`, ADR-001's
//! own worked example for the shape). `Guardian1` remains exactly
//! `ContractVersion`/`ServiceState`; none of the three new interfaces
//! shares an object path or method with it. `Incidents1`/`Transactions1`
//! are genuinely, honestly empty in this gate (no incident producer, no
//! daemon-side transaction store exists) — see `dbus_surface`'s own doc
//! comment for the two paths this explicitly forbids for populating
//! `Transactions1` (reading `guardian-helper`'s state; any new
//! `guardian-daemon` -> `GuardianHelper1` call).
//!
//! **Repair of the independent audit's G5 FC-2 finding**: this binary
//! evaluates `guardian_core::budget::recorder_policy_for()` on a real,
//! periodic, no-privilege monitoring tick and records a real `Event` into
//! a real `BoundedRecorder` — genuine production wiring, not a fixture.
//! It does **not** claim FC-2 closed: no real spill/retention sink exists
//! yet for either policy branch. See the module doc on
//! [`monitoring_tick`].
//!
//! **Phase 2 Gate 2b update**: this binary now also owns the single
//! daemon-wide `guardian_core::correlation::IngressClock`/
//! `CorrelationEngine` admission point (gate TDD R2) — every event source
//! this binary produces (the existing monitoring-tick producer, and the
//! new provider-health snapshot-diff producer) feeds through it, never
//! constructing its own ingress clock/sequence. The debounce ring's
//! `CapacityRejected` outcome (Gate 2a, `guardian-core`, zero I/O there by
//! design) is logged here — the daemon-owned half of `P2-REC-003` — using
//! this file's existing `eprintln!("[guardian-daemon] ...")` convention,
//! never a new logging facility. `guardian-daemon`'s live PSI event
//! production (real kernel `poll()`-triggered events,
//! `guardian_core::providers::psi::PsiEventSource`) is **not** added by
//! this gate: no such production loop exists anywhere in this binary
//! today (it exists only as a library capability plus a standalone
//! evidence example, `crates/guardian-core/examples/
//! g8_psi_trigger_evidence.rs`), Gate 2b's own R7 only conditionally
//! requires PSI-specific glue code ("if daemon wiring adds any..."), and
//! no `P2-*` ID this gate owns requires it — wiring a real PSI production
//! thread into this process remains a future gate's scope.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use guardian_core::budget::{self, FreeSpaceState};
use guardian_core::correlation::{
    AdmitOutcome, CorrelationEngine, CorrelationPolicy, IngressClock,
};
use guardian_core::event::Event;
use guardian_core::providers::health::HealthTransitionProducer;
use guardian_core::providers::udisks::{TopologyTracker, UdisksProvider};
use guardian_core::recorder::BoundedRecorder;
use guardian_core::risk::Risk;
use guardian_daemon::{GuardianContract, dbus_surface};
use guardian_provider_api::{CapabilityRecord, EventId, ProviderId};

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.Guardian1";
const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1";
const PROVIDER_ID: &str = "guardian.g7.daemon-monitor";
const CAPABILITY_REGISTRY_TICK_INTERVAL: Duration = Duration::from_secs(30);
const RECORDER_CAPACITY: usize = 256;
const MONITORING_TICK_INTERVAL: Duration = Duration::from_secs(30);

fn state_dir() -> PathBuf {
    std::env::var_os("GUARDIAN_DAEMON_STATE_DIR")
        .map_or_else(|| PathBuf::from("/var/lib/guardian/daemon"), PathBuf::from)
}

fn provider_id() -> ProviderId {
    ProviderId::new(PROVIDER_ID).expect("fixed literal is a valid ProviderId")
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}

/// A real (not fixture) free-space signal, deliberately minimal: attempts
/// a small real write to `state`'s own probe file and observes whether the
/// OS reports `StorageFull`. This is a genuine host interaction — not a
/// full disk-usage provider (that remains G8 scope).
fn probe_free_space(state: &Path) -> FreeSpaceState {
    let probe_path = state.join(".free-space-probe");
    match fs::write(&probe_path, b"x") {
        Ok(()) => {
            let _ = fs::remove_file(&probe_path);
            FreeSpaceState::Sufficient
        }
        Err(error) if error.kind() == std::io::ErrorKind::StorageFull => FreeSpaceState::Critical,
        Err(_) => FreeSpaceState::Sufficient,
    }
}

fn humantime_wall() -> String {
    format!("{}s-since-epoch", now_secs())
}

/// The single daemon-owned `CorrelationIngress` admission point (gate TDD
/// R2): every event source this binary produces calls this and only this
/// function to reach the correlation engine — no producer constructs its
/// own `IngressClock`/sequence. The daemon-side half of `P2-REC-003`
/// (Gate 2a already performs the zero-I/O library half, `guardian-core`'s
/// `CorrelationEngine::reject_capacity()`) lives here: a `CapacityRejected`
/// outcome produces exactly one operational log line, using this file's
/// existing `eprintln!("[guardian-daemon] ...")` convention.
fn admit_event(
    ingress_clock: &Mutex<IngressClock>,
    engine: &Mutex<CorrelationEngine>,
    event: Event,
) {
    let ingress = ingress_clock.lock().unwrap().admit(event);
    let result = engine.lock().unwrap().admit(&ingress);
    if let AdmitOutcome::CapacityRejected(rejected) = &result.outcome {
        eprintln!(
            "[guardian-daemon] correlation debounce ring at capacity: rejected new candidate capability_id={} (rejection_count={})",
            rejected.capability_id, rejected.rejection_count
        );
    }
}

/// Genuine, no-privilege, Class C periodic monitoring work (G7 handoff
/// §2.4: "the recorder is a Class C/monitoring concern and lives in
/// `guardian-daemon`"). Every tick: probes real free space, calls G5's
/// `recorder_policy_for()` on that real input, records a real `Event`
/// into the real bounded recorder, and logs which policy branch was
/// selected.
///
/// **What this closes and what it does not (G5 FC-2)**: `RecorderPolicy`
/// is genuinely evaluated against a real signal on a real, permanent
/// production runtime path (not merely constructed and discarded, and not
/// only exercised once at a client's request) — this is real
/// improvement over the original candidate, where the policy was only
/// ever evaluated inside the now-removed Class B evidence method. It does
/// **not** close FC-2: neither `RecorderPolicy::Normal` nor
/// `RecorderPolicy::MemoryFirst` yet drives a real spill/retention sink —
/// no such sink exists in this build. FC-2 remains open; closure is
/// assigned to the first gate that instantiates an actual spill/retention
/// path (see `docs/evidence/g7/G7_DAEMON_HELPER_EVIDENCE.md`'s corrected
/// disposition).
fn monitoring_tick(
    recorder: &Mutex<BoundedRecorder>,
    state: &Path,
    ingress_clock: &Mutex<IngressClock>,
    engine: &Mutex<CorrelationEngine>,
) {
    let free_space = probe_free_space(state);
    let policy = budget::recorder_policy_for(free_space);

    let event_type = "daemon_monitoring_tick";
    let event = Event {
        event_id: EventId::new("guardian.g7.daemon-tick").expect("fixed literal is valid"),
        timestamp_monotonic: now_secs(),
        timestamp_wall: humantime_wall(),
        source_provider: provider_id(),
        event_type: event_type.to_owned(),
        resource_refs: Vec::new(),
        severity: Risk::Observe,
        normalized_key: guardian_core::event::normalize_key(event_type),
        raw_reference: event_type.to_owned(),
        attributes: std::collections::BTreeMap::new(),
    };

    // The same Event already produced for the recorder also feeds the
    // one shared correlation-ingress admission point (gate TDD R2) — no
    // second provider read, no second event construction.
    admit_event(ingress_clock, engine, event.clone());

    let mut guard = recorder.lock().unwrap();
    guard.record(event);
    eprintln!(
        "[guardian-daemon] monitoring tick: recorder len={} dropped={} policy={policy:?} free_space={free_space:?} (FC-2 not closed: no spill sink wired)",
        guard.len(),
        guard.dropped_count()
    );
}

/// Real, internal G8 Capability Registry population (implementation
/// handoff §11/§12): connects to the real system bus as a client — the
/// six read-only provider proxies described in the module doc — and logs
/// a genuine snapshot. This is internal `guardian-daemon` state only: no
/// `Guardian1` object or method exposes it to any client (handoff §12
/// assigns that to G9, when a real consumer exists). One provider being
/// unreachable never stops the others: [`guardian_core::providers::
/// registry::populate_registry`] treats each of the six independently.
fn capability_registry_tick(
    connection: &zbus::Connection,
    health_producer: &mut HealthTransitionProducer,
    ingress_clock: &Mutex<IngressClock>,
    engine: &Mutex<CorrelationEngine>,
) -> Vec<CapabilityRecord> {
    let records = async_io::block_on(guardian_core::providers::registry::populate_registry(
        connection,
    ));
    let available = records
        .iter()
        .filter(|r| r.availability.is_usable())
        .count();
    eprintln!(
        "[guardian-daemon] capability registry tick: {available}/{} capabilities available",
        records.len()
    );

    // Gate 2b's new provider-health transition producer (gate TDD R1):
    // diffs this snapshot against the previous one and feeds any
    // resulting Events through the one shared ingress point (R2) — no
    // new provider read is performed here beyond the snapshot already
    // collected above.
    for event in health_producer.observe(&records) {
        admit_event(ingress_clock, engine, event);
    }

    records
}

fn replace_registry_snapshot(
    snapshot: &Mutex<Vec<CapabilityRecord>>,
    records: Vec<CapabilityRecord>,
) {
    *snapshot.lock().unwrap() = records;
}

fn main() -> zbus::Result<()> {
    let state = state_dir();
    fs::create_dir_all(&state).expect("create daemon state directory");

    let recorder = std::sync::Arc::new(Mutex::new(
        BoundedRecorder::new(RECORDER_CAPACITY).expect("fixed positive capacity"),
    ));

    // Phase 2 Gate 2b: the single daemon-owned `CorrelationIngress`
    // admission point (gate TDD R2) — every event source below feeds
    // through this one `IngressClock`/`CorrelationEngine` pair, never
    // constructing its own.
    let ingress_clock = std::sync::Arc::new(Mutex::new(IngressClock::new()));
    let engine = std::sync::Arc::new(Mutex::new(CorrelationEngine::new(
        CorrelationPolicy::default(),
    )));

    let recorder_for_thread = std::sync::Arc::clone(&recorder);
    let state_for_thread = state.clone();
    let ingress_clock_for_monitoring = std::sync::Arc::clone(&ingress_clock);
    let engine_for_monitoring = std::sync::Arc::clone(&engine);
    std::thread::spawn(move || {
        loop {
            monitoring_tick(
                &recorder_for_thread,
                &state_for_thread,
                &ingress_clock_for_monitoring,
                &engine_for_monitoring,
            );
            std::thread::sleep(MONITORING_TICK_INTERVAL);
        }
    });

    // A second, genuine system-bus connection dedicated to the G8
    // Capability Registry's six read-only provider proxies — kept
    // entirely separate from the `Guardian1`-serving connection below, so
    // a provider read never shares a connection with (or can block) the
    // daemon's own served object.
    let registry_snapshot = std::sync::Arc::new(Mutex::new(Vec::<CapabilityRecord>::new()));
    let registry_snapshot_for_thread = std::sync::Arc::clone(&registry_snapshot);
    let ingress_clock_for_registry = std::sync::Arc::clone(&ingress_clock);
    let engine_for_registry = std::sync::Arc::clone(&engine);
    std::thread::spawn(move || {
        let mut topology_tracker = TopologyTracker::new();
        let mut health_producer = HealthTransitionProducer::new();
        loop {
            // Reconnect each bounded cycle. A missing bus or a connection
            // lost since the previous cycle therefore cannot permanently
            // kill this worker or retain a stale healthy snapshot.
            match async_io::block_on(zbus::Connection::system()) {
                Ok(registry_connection) => {
                    replace_registry_snapshot(
                        &registry_snapshot_for_thread,
                        capability_registry_tick(
                            &registry_connection,
                            &mut health_producer,
                            &ingress_clock_for_registry,
                            &engine_for_registry,
                        ),
                    );
                    if let Ok(topology) =
                        async_io::block_on(UdisksProvider::new(&registry_connection).topology())
                    {
                        for event in topology_tracker.observe(&topology) {
                            eprintln!("[guardian-daemon] UDisks topology event: {event:?}");
                        }
                    }
                }
                Err(error) => {
                    replace_registry_snapshot(&registry_snapshot_for_thread, Vec::new());
                    eprintln!(
                        "[guardian-daemon] capability registry: system bus unavailable; retrying: {error}"
                    );
                }
            }
            std::thread::sleep(CAPABILITY_REGISTRY_TICK_INTERVAL);
        }
    });

    // G9's three read-only interfaces, each a separate interface major at
    // its own object path (per ADR-001's own worked example) — never
    // bolted onto the frozen `Guardian1` object above. `Capabilities1`
    // shares the same `registry_snapshot` the worker thread above already
    // maintains; it never opens a second registry connection of its own.
    let connection = zbus::blocking::connection::Builder::system()?
        .name(WELL_KNOWN_NAME)?
        .serve_at(OBJECT_PATH, GuardianContract::default())?
        .serve_at(
            dbus_surface::CAPABILITIES_OBJECT_PATH,
            dbus_surface::Capabilities1::new(std::sync::Arc::clone(&registry_snapshot)),
        )?
        .serve_at(
            dbus_surface::INCIDENTS_OBJECT_PATH,
            dbus_surface::Incidents1::new(std::sync::Arc::clone(&engine)),
        )?
        .serve_at(
            dbus_surface::TRANSACTIONS_OBJECT_PATH,
            dbus_surface::Transactions1,
        )?
        .build()?;
    eprintln!(
        "[guardian-daemon] serving {WELL_KNOWN_NAME} at {OBJECT_PATH}, unique_name={}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}

#[cfg(test)]
mod tests {
    use super::{admit_event, monitoring_tick, probe_free_space, replace_registry_snapshot};
    use guardian_core::budget::FreeSpaceState;
    use guardian_core::correlation::{
        CorrelationEngine, CorrelationPolicy, HEALTH_AVAILABILITY_TO_ATTR,
        HEALTH_CAPABILITY_ID_ATTR, HEALTH_TRANSITION_EVENT_TYPE, IngressClock,
    };
    use guardian_core::event::Event;
    use guardian_core::recorder::BoundedRecorder;
    use guardian_core::risk::Risk;
    use guardian_provider_api::{EventId, ProviderId};
    use std::sync::Mutex;

    fn temp_dir(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "guardian-daemon-test-{name}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn shared_ingress() -> (Mutex<IngressClock>, Mutex<CorrelationEngine>) {
        (
            Mutex::new(IngressClock::new()),
            Mutex::new(CorrelationEngine::new(CorrelationPolicy::default())),
        )
    }

    #[test]
    fn probe_free_space_reports_sufficient_for_a_real_writable_directory() {
        let dir = temp_dir("probe-sufficient");
        assert_eq!(probe_free_space(&dir), FreeSpaceState::Sufficient);
    }

    #[test]
    fn probe_free_space_does_not_leave_the_probe_file_behind() {
        let dir = temp_dir("probe-cleanup");
        probe_free_space(&dir);
        assert!(!dir.join(".free-space-probe").exists());
    }

    #[test]
    fn monitoring_tick_records_a_real_event_and_does_not_panic() {
        let dir = temp_dir("tick-records-event");
        let recorder = Mutex::new(BoundedRecorder::new(4).unwrap());
        let (ingress_clock, engine) = shared_ingress();
        monitoring_tick(&recorder, &dir, &ingress_clock, &engine);
        assert_eq!(recorder.lock().unwrap().len(), 1);
        monitoring_tick(&recorder, &dir, &ingress_clock, &engine);
        assert_eq!(recorder.lock().unwrap().len(), 2);
    }

    #[test]
    fn monitoring_tick_respects_the_recorder_bound_across_many_ticks() {
        let dir = temp_dir("tick-bounded");
        let recorder = Mutex::new(BoundedRecorder::new(2).unwrap());
        let (ingress_clock, engine) = shared_ingress();
        for _ in 0..5 {
            monitoring_tick(&recorder, &dir, &ingress_clock, &engine);
        }
        let guard = recorder.lock().unwrap();
        assert_eq!(guard.len(), 2, "must never exceed the configured capacity");
        assert_eq!(
            guard.dropped_count(),
            3,
            "the 3 oldest ticks must be counted as dropped"
        );
    }

    /// Gate TDD R2 evidence: every source feeding `admit_event` — here,
    /// several `monitoring_tick` calls plus a directly-admitted
    /// provider-health event — receives strictly increasing
    /// `ingress_sequence` values from the one shared admission point,
    /// regardless of which source produced the event.
    #[test]
    fn monitoring_tick_and_a_second_source_share_one_monotonically_increasing_ingress_sequence() {
        let dir = temp_dir("tick-shared-ingress");
        let recorder = Mutex::new(BoundedRecorder::new(8).unwrap());
        let (ingress_clock, engine) = shared_ingress();

        monitoring_tick(&recorder, &dir, &ingress_clock, &engine);
        assert_eq!(ingress_clock.lock().unwrap().sequence(), 1);

        let health_event = sample_health_event(0, "available");
        admit_event(&ingress_clock, &engine, health_event);
        assert_eq!(
            ingress_clock.lock().unwrap().sequence(),
            2,
            "a second source admitted through the same point must continue the same sequence"
        );

        monitoring_tick(&recorder, &dir, &ingress_clock, &engine);
        assert_eq!(
            ingress_clock.lock().unwrap().sequence(),
            3,
            "ingress_sequence keeps increasing regardless of which source produced the event"
        );
    }

    /// Gate TDD R6 / `P2-REC-003` daemon-side half: a `CapacityRejected`
    /// outcome consumed by `admit_event` does not panic and the engine's
    /// own rejection counter increments — the log line itself is asserted
    /// indirectly here (this test proves the outcome is real and handled,
    /// not silently dropped); the exact log text is documented at the
    /// `admit_event` call site.
    #[test]
    fn admit_event_handles_a_capacity_rejected_outcome_without_panicking() {
        let ingress_clock = Mutex::new(IngressClock::new());
        let policy = CorrelationPolicy {
            debounce_capacity: 1,
            ..CorrelationPolicy::default()
        };
        let engine = Mutex::new(CorrelationEngine::new(policy));

        admit_event(
            &ingress_clock,
            &engine,
            sample_health_event(0, "unavailable"),
        );
        admit_event(
            &ingress_clock,
            &engine,
            sample_health_event_for("b.cap", 1, "unavailable"),
        );

        assert_eq!(
            engine.lock().unwrap().rejection_count(),
            1,
            "the second, brand-new candidate key must be rejected once the ring is at capacity"
        );
    }

    fn sample_health_event(sequence: u64, availability_to: &str) -> Event {
        sample_health_event_for("a.cap", sequence, availability_to)
    }

    fn sample_health_event_for(capability_id: &str, sequence: u64, availability_to: &str) -> Event {
        let mut attributes = std::collections::BTreeMap::new();
        attributes.insert(
            HEALTH_CAPABILITY_ID_ATTR.to_owned(),
            capability_id.to_owned(),
        );
        attributes.insert(
            HEALTH_AVAILABILITY_TO_ATTR.to_owned(),
            availability_to.to_owned(),
        );
        Event {
            event_id: EventId::new(format!("guardian.health.test.event-{sequence}")).unwrap(),
            timestamp_monotonic: sequence,
            timestamp_wall: format!("sequence-{sequence}"),
            source_provider: ProviderId::new("guardian.p2.capability-health").unwrap(),
            event_type: HEALTH_TRANSITION_EVENT_TYPE.to_owned(),
            resource_refs: vec![capability_id.to_owned()],
            severity: Risk::Observe,
            normalized_key: guardian_core::event::normalize_key("test"),
            raw_reference: "test".to_owned(),
            attributes,
        }
    }

    #[test]
    fn registry_snapshot_is_replaced_not_retained_after_outage() {
        let snapshot = Mutex::new(vec![
            guardian_core::providers::registry::psi_capabilities().remove(0),
        ]);
        replace_registry_snapshot(&snapshot, Vec::new());
        assert!(snapshot.lock().unwrap().is_empty());
    }

    #[test]
    fn admit_outcome_ignored_for_unrecognized_event_type_still_advances_ingress() {
        // A "daemon_monitoring_tick" event matches no correlation rule
        // (`AdmitOutcome::Ignored`) but must still have been admitted
        // through the one shared point -- this is what proves the
        // daemon-tick producer is a real ingress source, not merely
        // recorder-only.
        let (ingress_clock, engine) = shared_ingress();
        let dir = temp_dir("ignored-still-advances");
        let recorder = Mutex::new(BoundedRecorder::new(4).unwrap());
        monitoring_tick(&recorder, &dir, &ingress_clock, &engine);
        let engine_guard = engine.lock().unwrap();
        assert_eq!(engine_guard.admitted_ingress_count(), 1);
        assert_eq!(
            engine_guard.open_incidents().len(),
            0,
            "a daemon-tick event never opens an incident on its own"
        );
    }
}
