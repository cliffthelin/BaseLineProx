//! The transaction observation contract (TDD contract §15; G4 handoff §15).
//! "A provider returning 'method call succeeded' MUST NOT automatically
//! mean the transaction succeeded" -- `Observe`'s job is purely "did the
//! expected state occur," using the fixture's reported state. No G5
//! diagnostic-budget/PSI logic exists here.

use std::fmt;

/// Typed observation policy fields -- not a free-form opaque callback.
#[derive(Clone, Debug, Eq, PartialEq, Default)]
pub struct ObservationPolicy {
    pub expected_properties: Vec<String>,
    pub forbidden_properties: Vec<String>,
    pub minimum_observation_duration_ms: u64,
    pub maximum_observation_duration_ms: u64,
    pub health_checks: Vec<String>,
    pub commit_condition: String,
    pub rollback_condition: String,
}

/// A single observation result -- kept structurally distinct from "the
/// provider call itself succeeded" (that is `ApplyOutcome::ConfirmedSuccess`,
/// a different fact entirely).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObservationOutcome {
    PostconditionMet,
    PostconditionNotMet,
    Ambiguous,
}

impl ObservationOutcome {
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::PostconditionMet => "postcondition_met",
            Self::PostconditionNotMet => "postcondition_not_met",
            Self::Ambiguous => "ambiguous",
        }
    }
}

impl fmt::Display for ObservationOutcome {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

/// An unrecognized wire token becomes the explicit `Ambiguous` variant
/// (never a hard parse error) -- consistent with `ApplyOutcome`'s
/// unknown-becomes-a-real-variant discipline, and semantically correct
/// here: an observation outcome this build doesn't recognize is, by
/// definition, not something it can safely call `PostconditionMet`.
impl std::str::FromStr for ObservationOutcome {
    type Err = std::convert::Infallible;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(match value {
            "postcondition_met" => Self::PostconditionMet,
            "postcondition_not_met" => Self::PostconditionNotMet,
            _ => Self::Ambiguous,
        })
    }
}
