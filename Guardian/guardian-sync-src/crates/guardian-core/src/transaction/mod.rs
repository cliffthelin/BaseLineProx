//! The G4 Transaction Engine (TDD contract §14/§15/§23; G4 handoff).
//!
//! Turns G3's data models into a real, deterministic transaction
//! lifecycle: every risky mutation is bounded, authorized, observable,
//! recoverable, and auditable (GP-05). Exercised only against deterministic
//! fixture providers/adapters -- no real provider integration exists here
//! (that is G8 scope).

pub mod apply;
pub mod arbitration_source;
pub mod engine;
pub mod id;
pub mod observation;
pub mod persistence;
pub mod record;
pub mod recovery;
pub mod rollback;
pub mod state;

pub use apply::{ApplyOutcome, ApplyRecord};
pub use arbitration_source::ArbitrationStateSource;
pub use engine::EngineError;
pub use id::{TransactionId, TransactionIdParseError};
pub use observation::{ObservationOutcome, ObservationPolicy};
pub use record::{ActionType, Snapshot, TransactionRecord, ValidationOutcome};
pub use recovery::{RecoveryClassification, RecoverySnapshot, classify};
pub use rollback::RollbackOutcome;
pub use state::{IllegalTransition, TransactionState, is_legal_transition, transition};
