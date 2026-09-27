//! The canonical G4 transaction state machine (TDD contract §14, G4 handoff
//! §4). Exactly the contract's 15 states, exactly its named transitions --
//! no renamed/merged/invented states, no arbitrary `set_state`.

use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum TransactionState {
    Created,
    Validating,
    Validated,
    Authorizing,
    Authorized,
    Applying,
    Observing,
    Committed,
    RollingBack,
    RolledBack,
    Rejected,
    Failed,
    RollbackFailed,
    Expired,
    Cancelled,
}

impl TransactionState {
    /// Terminal states MUST be immutable (P0-TXN-008).
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Committed
                | Self::RolledBack
                | Self::Rejected
                | Self::Failed
                | Self::RollbackFailed
                | Self::Expired
                | Self::Cancelled
        )
    }

    /// `true` for the pre-mutation states from which a direct
    /// `CANCELLED`/`EXPIRED` transition is safe (G4 handoff §4.1/§17.4) --
    /// no provider mutation has begun.
    #[must_use]
    pub const fn is_pre_mutation(self) -> bool {
        matches!(
            self,
            Self::Created
                | Self::Validating
                | Self::Validated
                | Self::Authorizing
                | Self::Authorized
        )
    }

    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Validating => "validating",
            Self::Validated => "validated",
            Self::Authorizing => "authorizing",
            Self::Authorized => "authorized",
            Self::Applying => "applying",
            Self::Observing => "observing",
            Self::Committed => "committed",
            Self::RollingBack => "rolling_back",
            Self::RolledBack => "rolled_back",
            Self::Rejected => "rejected",
            Self::Failed => "failed",
            Self::RollbackFailed => "rollback_failed",
            Self::Expired => "expired",
            Self::Cancelled => "cancelled",
        }
    }
}

impl fmt::Display for TransactionState {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TransactionStateParseError;

impl fmt::Display for TransactionStateParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("unrecognized transaction state wire token")
    }
}

impl std::error::Error for TransactionStateParseError {}

impl std::str::FromStr for TransactionState {
    type Err = TransactionStateParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(match value {
            "created" => Self::Created,
            "validating" => Self::Validating,
            "validated" => Self::Validated,
            "authorizing" => Self::Authorizing,
            "authorized" => Self::Authorized,
            "applying" => Self::Applying,
            "observing" => Self::Observing,
            "committed" => Self::Committed,
            "rolling_back" => Self::RollingBack,
            "rolled_back" => Self::RolledBack,
            "rejected" => Self::Rejected,
            "failed" => Self::Failed,
            "rollback_failed" => Self::RollbackFailed,
            "expired" => Self::Expired,
            "cancelled" => Self::Cancelled,
            _ => return Err(TransactionStateParseError),
        })
    }
}

/// An illegal transition was attempted -- returned as a typed error, never
/// a panic (P0-TXN-008).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IllegalTransition {
    pub from: TransactionState,
    pub to: TransactionState,
}

impl fmt::Display for IllegalTransition {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "illegal transition: {} -> {}",
            self.from, self.to
        )
    }
}

impl std::error::Error for IllegalTransition {}

/// `true` if `to` is a legal direct successor of `from`, per the governing
/// contract's §14 state machine (G4 handoff §4.1). `CANCELLED`/`EXPIRED`
/// are legal successors only of the pre-mutation states -- see §17.4's
/// safety repair: a direct `APPLYING`/`OBSERVING`/`ROLLING_BACK` ->
/// `CANCELLED`/`EXPIRED` transition is deliberately absent and MUST NOT be
/// added, because it would let Guardian mark a transaction immutably
/// terminal while an external mutation may still be unreconciled.
#[must_use]
pub const fn is_legal_transition(from: TransactionState, to: TransactionState) -> bool {
    use TransactionState::{
        Applying, Authorized, Authorizing, Cancelled, Committed, Created, Expired, Failed,
        Observing, Rejected, RollbackFailed, RolledBack, RollingBack, Validated, Validating,
    };
    matches!(
        (from, to),
        (Created, Validating)
            | (Validating, Validated | Rejected)
            | (Validated, Authorizing)
            | (Authorizing, Authorized | Rejected)
            | (Authorized, Applying)
            | (Applying, Observing | Failed | RollingBack)
            | (Observing, Committed | RollingBack | Failed)
            | (RollingBack, RolledBack | RollbackFailed)
            | (
                Created | Validating | Validated | Authorizing | Authorized,
                Cancelled | Expired
            )
    )
}

/// Attempts the transition, enforcing terminal immutability (P0-TXN-008)
/// and the legal-transition graph. The only way `TransactionState` ever
/// changes -- there is no bare public setter.
///
/// # Errors
///
/// Returns [`IllegalTransition`] if `from` is terminal or `to` is not a
/// legal direct successor of `from`.
pub const fn transition(
    from: TransactionState,
    to: TransactionState,
) -> Result<TransactionState, IllegalTransition> {
    if from.is_terminal() || !is_legal_transition(from, to) {
        return Err(IllegalTransition { from, to });
    }
    Ok(to)
}
