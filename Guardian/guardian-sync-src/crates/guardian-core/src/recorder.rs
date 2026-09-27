//! The bounded, memory-first Flight Recorder (TDD contract §22; G5
//! handoff §7). Distinct from [`crate::transaction::persistence`] (G4
//! milestone forward constraint FC-3) -- that module is a
//! transaction-record-specific, schema-versioned, durable store; this
//! module is a bounded *memory* ring buffer with an optional, best-effort
//! spill path that must never block or fail the recording caller.

use std::collections::VecDeque;
use std::fmt;

use crate::event::Event;

/// A forced-nonzero capacity -- a zero-capacity recorder is a
/// contradiction (nothing could ever be retained), so this is rejected at
/// construction rather than silently behaving as "always overflow."
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ZeroCapacity;

impl fmt::Display for ZeroCapacity {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("recorder capacity must be at least 1")
    }
}

impl std::error::Error for ZeroCapacity {}

/// A bounded, memory-first ring buffer of [`Event`]s. Never exceeds its
/// configured capacity (P0-REC-001); overflow evicts the oldest retained
/// event (deterministic FIFO) and increments a real, public dropped
/// counter (P0-REC-002).
#[derive(Clone, Debug)]
pub struct BoundedRecorder {
    capacity: usize,
    buffer: VecDeque<Event>,
    dropped: u64,
}

impl BoundedRecorder {
    /// # Errors
    ///
    /// Returns [`ZeroCapacity`] if `capacity == 0`.
    pub fn new(capacity: usize) -> Result<Self, ZeroCapacity> {
        if capacity == 0 {
            return Err(ZeroCapacity);
        }
        Ok(Self {
            capacity,
            buffer: VecDeque::with_capacity(capacity),
            dropped: 0,
        })
    }

    /// Records one event. Always succeeds -- there is no `Result` here on
    /// purpose: recording must never itself be a fallible operation a
    /// caller has to handle on the hot path (only the separate, optional
    /// [`spill`] step is fallible, per P0-REC-003).
    ///
    /// Retains insertion order: events pushed with non-decreasing
    /// `timestamp_monotonic` are retained in that same non-decreasing
    /// order (contract §22, "retain monotonic timestamp ordering") --
    /// this module never reorders, sorts, or otherwise perturbs sequence.
    pub fn record(&mut self, event: Event) {
        if self.buffer.len() >= self.capacity {
            self.buffer.pop_front();
            self.dropped += 1;
        }
        self.buffer.push_back(event);
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.buffer.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.buffer.is_empty()
    }

    #[must_use]
    pub const fn capacity(&self) -> usize {
        self.capacity
    }

    /// The number of events evicted due to overflow -- real, public,
    /// observable state (P0-REC-002), not an internal detail a test must
    /// infer indirectly.
    #[must_use]
    pub const fn dropped_count(&self) -> u64 {
        self.dropped
    }

    /// Retained events, oldest first.
    pub fn iter(&self) -> impl Iterator<Item = &Event> {
        self.buffer.iter()
    }
}

/// A spill-target's removability -- a typed, injectable fact (G5 handoff
/// §7.1), never a real `udev`/`lsblk` call in this gate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RemovableStatus {
    Removable,
    Fixed,
}

/// A candidate spill target for the recorder's one configurable path.
/// This gate's recorder has exactly one such target -- it is always the
/// "critical path" the contract's P0-REC-004 refers to, so no separate
/// "optional target" concept exists here to create ambiguity about which
/// target the removable-media rule applies to.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SpillTarget {
    pub location: String,
    pub removable: RemovableStatus,
}

/// The critical recorder path was configured to a monitored removable
/// device -- rejected before configuration takes effect (P0-REC-004).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemovableTargetRejected {
    pub location: String,
}

impl fmt::Display for RemovableTargetRejected {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "recorder critical path cannot be a monitored removable device: {}",
            self.location
        )
    }
}

impl std::error::Error for RemovableTargetRejected {}

/// A spill (persistence) attempt failed. Kept structurally distinct from
/// any failure of [`BoundedRecorder::record`] -- spill is optional and
/// best-effort; recording is not (P0-REC-003).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SpillError(pub String);

impl fmt::Display for SpillError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "recorder spill failed: {}", self.0)
    }
}

impl std::error::Error for SpillError {}

/// The recorder's optional, fallible persistence step. A real
/// implementation (test fixture in this gate; a real bounded local file
/// in a later gate) implements this trait; [`spill`] proves that a
/// failure here never propagates as a panic or as a failure of the thing
/// being recorded.
pub trait RecorderSink {
    /// # Errors
    ///
    /// Returns [`SpillError`] if the underlying write fails for any
    /// reason. Must never panic.
    fn spill(&self, events: &[Event]) -> Result<(), SpillError>;
}

/// Validates `target` before it is accepted as the recorder's critical
/// spill path -- the actual enforcement point for P0-REC-004. A rejected
/// target never becomes the configured target (no partial/silent
/// acceptance).
///
/// # Errors
///
/// Returns [`RemovableTargetRejected`] if `target.removable ==
/// RemovableStatus::Removable`.
pub fn validate_critical_target(target: &SpillTarget) -> Result<(), RemovableTargetRejected> {
    match target.removable {
        RemovableStatus::Removable => Err(RemovableTargetRejected {
            location: target.location.clone(),
        }),
        RemovableStatus::Fixed => Ok(()),
    }
}

/// Attempts to spill every currently-retained event through `sink`. A
/// failure here is reported to the caller as a normal `Result` -- it does
/// not touch, truncate, or otherwise mutate `recorder`'s in-memory buffer,
/// and (by construction, since this is a separate function from
/// [`BoundedRecorder::record`]) can never prevent a subsequent `record`
/// call from succeeding (P0-REC-003).
///
/// # Errors
///
/// Returns [`SpillError`] if `sink.spill` fails.
pub fn spill(recorder: &BoundedRecorder, sink: &dyn RecorderSink) -> Result<(), SpillError> {
    let events: Vec<Event> = recorder.iter().cloned().collect();
    sink.spill(&events)
}
