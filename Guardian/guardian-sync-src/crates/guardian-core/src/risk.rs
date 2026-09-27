//! The canonical Guardian risk taxonomy (TDD contract §10).
//!
//! This is the single shared risk type -- arbitration, events, incidents,
//! and any future transaction engine reuse this enum rather than each
//! defining a competing one (G3 handoff §33).

use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum Risk {
    Observe,
    Low,
    Moderate,
    High,
    VeryHigh,
}

impl Risk {
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::Observe => "observe",
            Self::Low => "low",
            Self::Moderate => "moderate",
            Self::High => "high",
            Self::VeryHigh => "very_high",
        }
    }
}

impl fmt::Display for Risk {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}
