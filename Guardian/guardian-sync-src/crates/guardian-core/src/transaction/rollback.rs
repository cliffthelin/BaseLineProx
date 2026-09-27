//! `RollbackOutcome` -- the typed evidence field that resolves the
//! `BestEffort`-ambiguity contradiction (G4 handoff §17.1/§17.2) without
//! adding a new transaction state. Maps deterministically onto the
//! canonical `ROLLED_BACK`/`ROLLBACK_FAILED` states, fail-closed: at the
//! *state* level, `ROLLBACK_FAILED` means only "Guardian cannot positively
//! establish successful rollback" -- the finer distinction (confirmed
//! provider failure vs. genuinely unconfirmed attempt) survives losslessly
//! in this field.

use std::fmt;

use crate::transaction::state::TransactionState;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RollbackOutcome {
    ConfirmedRestored,
    ConfirmedFailed,
    AttemptedUnconfirmed,
    NotSupported,
}

impl RollbackOutcome {
    /// The exact fail-closed mapping required by G4 handoff §17.2 --
    /// `ConfirmedRestored` is the only variant reaching `RolledBack`; every
    /// other variant (including a genuinely unconfirmed attempt) reaches
    /// `RollbackFailed`.
    #[must_use]
    pub const fn terminal_state(self) -> TransactionState {
        match self {
            Self::ConfirmedRestored => TransactionState::RolledBack,
            Self::ConfirmedFailed | Self::AttemptedUnconfirmed | Self::NotSupported => {
                TransactionState::RollbackFailed
            }
        }
    }

    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::ConfirmedRestored => "confirmed_restored",
            Self::ConfirmedFailed => "confirmed_failed",
            Self::AttemptedUnconfirmed => "attempted_unconfirmed",
            Self::NotSupported => "not_supported",
        }
    }
}

impl fmt::Display for RollbackOutcome {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RollbackOutcomeParseError;

impl fmt::Display for RollbackOutcomeParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("unrecognized rollback_result wire token")
    }
}

impl std::error::Error for RollbackOutcomeParseError {}

impl std::str::FromStr for RollbackOutcome {
    type Err = RollbackOutcomeParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(match value {
            "confirmed_restored" => Self::ConfirmedRestored,
            "confirmed_failed" => Self::ConfirmedFailed,
            "attempted_unconfirmed" => Self::AttemptedUnconfirmed,
            "not_supported" => Self::NotSupported,
            _ => return Err(RollbackOutcomeParseError),
        })
    }
}
