//! The `Incident` correlation envelope (TDD contract §18; G3 handoff §8).
//!
//! An incident links existing [`crate::event::Event`]s by their stable
//! [`EventId`]s -- it never copies, merges, or deletes the events
//! themselves (P0-EVT-004).

use guardian_provider_api::{EventId, IncidentId};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IncidentStatus {
    Open,
    Monitoring,
    Closed,
    Unknown,
}

/// A deliberately discrete, explainable confidence representation rather
/// than an invented floating-point pseudo-probability (governing brief
/// §23) -- no governing document specifies a numeric scale.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Confidence {
    Hypothesis,
    Probable,
    Confirmed,
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Incident {
    pub incident_id: IncidentId,
    pub opened_at: String,
    pub closed_at: Option<String>,
    pub status: IncidentStatus,
    pub summary: String,
    pub confidence: Confidence,
    /// Every prior confidence value, in the order it held -- "confidence
    /// changes are recorded" (TDD contract §18) as a checked property, not
    /// a bare mutable field with no history.
    pub confidence_history: Vec<Confidence>,
    pub primary_resource: Option<String>,
    /// References to existing [`crate::event::Event`]s by stable
    /// [`EventId`] -- never the events themselves.
    pub event_ids: Vec<EventId>,
    pub evidence: Vec<String>,
    pub candidate_causes: Vec<String>,
    pub recommended_actions: Vec<String>,
    /// Reference shape only, for a future G4 transaction engine to
    /// populate -- no transaction runtime is implemented in this gate.
    pub transaction_ids: Vec<String>,
    pub outcome: Option<String>,
}

impl Incident {
    /// Links an existing event by its stable ID. Idempotent -- linking the
    /// same `event_id` twice does not duplicate the reference. Never takes
    /// or deletes the referenced [`crate::event::Event`].
    pub fn link_event(&mut self, event_id: EventId) {
        if !self.event_ids.contains(&event_id) {
            self.event_ids.push(event_id);
        }
    }

    /// Updates confidence, recording the previous value in
    /// [`Self::confidence_history`] rather than silently overwriting it.
    pub fn set_confidence(&mut self, new: Confidence) {
        self.confidence_history.push(self.confidence);
        self.confidence = new;
    }
}
