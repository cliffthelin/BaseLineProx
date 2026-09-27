//! The G5 bounded Flight Recorder contract (TDD contract §22; G5 handoff
//! §7). P0-REC-001..004, plus boundedness/failure adversarial checks.

use std::collections::BTreeMap;

use guardian_core::event::Event;
use guardian_core::recorder::{
    BoundedRecorder, RecorderSink, RemovableStatus, SpillError, SpillTarget, spill,
    validate_critical_target,
};
use guardian_core::risk::Risk;
use guardian_provider_api::{EventId, ProviderId};

fn event(monotonic: u64) -> Event {
    Event {
        event_id: EventId::new("guardian.diagnostic.recorded").unwrap(),
        timestamp_monotonic: monotonic,
        timestamp_wall: "2026-09-01T00:00:00Z".to_owned(),
        source_provider: ProviderId::new("fixture-provider-a").unwrap(),
        event_type: "diagnostic.recorded".to_owned(),
        resource_refs: Vec::new(),
        severity: Risk::Observe,
        normalized_key: "diagnostic recorded".to_owned(),
        raw_reference: "diagnostic recorded".to_owned(),
        attributes: BTreeMap::new(),
    }
}

/// P0-REC-001: ring buffer never grows beyond configured limit -- proven
/// at every step of a real stress push, not merely at the end.
#[test]
fn p0_rec_001_buffer_never_exceeds_configured_capacity_at_any_point() {
    let mut recorder = BoundedRecorder::new(5).unwrap();

    for i in 0..500_u64 {
        recorder.record(event(i));
        assert!(
            recorder.len() <= 5,
            "buffer length {} exceeded capacity 5 after push {i}",
            recorder.len()
        );
    }
    assert_eq!(recorder.len(), 5);
    assert_eq!(recorder.capacity(), 5);
}

/// P0-REC-002: overflow increments a real, public, observable dropped
/// counter -- exact arithmetic checked, not just `> 0`.
#[test]
fn p0_rec_002_dropped_counter_increments_exactly_once_per_eviction() {
    let mut recorder = BoundedRecorder::new(3).unwrap();
    assert_eq!(recorder.dropped_count(), 0);

    for i in 0..3_u64 {
        recorder.record(event(i));
    }
    assert_eq!(
        recorder.dropped_count(),
        0,
        "no eviction yet -- buffer not full"
    );

    for i in 3..10_u64 {
        recorder.record(event(i));
    }
    // 10 pushes total, capacity 3 -> 7 evictions.
    assert_eq!(recorder.dropped_count(), 7);
}

struct FailingSink;

impl RecorderSink for FailingSink {
    fn spill(&self, _events: &[Event]) -> Result<(), SpillError> {
        Err(SpillError("simulated storage failure".to_owned()))
    }
}

struct SucceedingSink;

impl RecorderSink for SucceedingSink {
    fn spill(&self, _events: &[Event]) -> Result<(), SpillError> {
        Ok(())
    }
}

/// P0-REC-003: persistence failure does not block the monitoring loop --
/// proven by forcing a real spill failure and confirming `record()` keeps
/// succeeding across many subsequent iterations, never panicking.
#[test]
fn p0_rec_003_persistence_failure_never_blocks_or_crashes_the_record_loop() {
    let mut recorder = BoundedRecorder::new(10).unwrap();
    let failing_sink = FailingSink;

    for i in 0..20_u64 {
        recorder.record(event(i));
        let spill_result = spill(&recorder, &failing_sink);
        assert!(spill_result.is_err(), "spill must genuinely fail here");
        // The record loop keeps running regardless -- proven by the next
        // iteration's record() call succeeding (no panic, no early exit)
        // and the buffer staying internally consistent.
        assert!(recorder.len() <= 10);
    }
    assert_eq!(recorder.len(), 10);

    // A working sink afterward still succeeds -- spill failure did not
    // corrupt the recorder's state.
    let succeeding_sink = SucceedingSink;
    assert!(spill(&recorder, &succeeding_sink).is_ok());
}

/// P0-REC-004: the critical recorder path cannot be configured to a
/// monitored removable device -- exercised for both outcomes so the test
/// cannot pass by a hard-coded always-true/always-false fixture.
#[test]
fn p0_rec_004_removable_critical_target_is_rejected_fixed_target_is_accepted() {
    let removable = SpillTarget {
        location: "/media/usb-drive/guardian-evidence".to_owned(),
        removable: RemovableStatus::Removable,
    };
    let fixed = SpillTarget {
        location: "/var/lib/guardian/recorder".to_owned(),
        removable: RemovableStatus::Fixed,
    };

    let removable_result = validate_critical_target(&removable);
    assert!(removable_result.is_err());
    assert_eq!(
        removable_result.unwrap_err().location,
        "/media/usb-drive/guardian-evidence"
    );

    let fixed_result = validate_critical_target(&fixed);
    assert!(fixed_result.is_ok());
}

// ---------------------------------------------------------------------
// Additional boundedness / determinism / retention checks
// ---------------------------------------------------------------------

#[test]
fn zero_capacity_is_rejected_at_construction() {
    let result = BoundedRecorder::new(0);
    assert!(result.is_err());
}

/// Eviction is deterministic FIFO -- the oldest event is always the one
/// evicted, proven by checking exactly which events survive.
#[test]
fn eviction_is_deterministic_oldest_first() {
    let mut recorder = BoundedRecorder::new(3).unwrap();
    for i in 0..5_u64 {
        recorder.record(event(i));
    }
    let surviving: Vec<u64> = recorder.iter().map(|e| e.timestamp_monotonic).collect();
    assert_eq!(
        surviving,
        vec![2, 3, 4],
        "oldest (0, 1) must be the ones evicted"
    );
}

/// Contract §22's "retain monotonic timestamp ordering" -- events pushed
/// in non-decreasing timestamp order are retained in that same order,
/// never reordered or sorted differently by the recorder.
#[test]
fn retains_monotonic_timestamp_ordering() {
    let mut recorder = BoundedRecorder::new(10).unwrap();
    let timestamps = [10_u64, 20, 20, 35, 100, 250];
    for &t in &timestamps {
        recorder.record(event(t));
    }
    let retained: Vec<u64> = recorder.iter().map(|e| e.timestamp_monotonic).collect();
    assert_eq!(retained, timestamps.to_vec());
    for window in retained.windows(2) {
        assert!(
            window[0] <= window[1],
            "retained order must be non-decreasing"
        );
    }
}

/// Real scratch mutation target: confirm the recorder never silently
/// accepts more than capacity by trying a large capacity too, proving the
/// bound is a real parameter, not a hard-coded constant.
#[test]
fn capacity_is_a_real_parameter_not_a_hard_coded_constant() {
    let mut small = BoundedRecorder::new(1).unwrap();
    let mut large = BoundedRecorder::new(1000).unwrap();

    for i in 0..2000_u64 {
        small.record(event(i));
        large.record(event(i));
    }

    assert_eq!(small.len(), 1);
    assert_eq!(large.len(), 1000);
    assert_eq!(small.dropped_count(), 1999);
    assert_eq!(large.dropped_count(), 1000);
}
