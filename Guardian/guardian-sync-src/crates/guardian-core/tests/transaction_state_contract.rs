//! The canonical G4 transaction state machine (TDD contract §14; G4 handoff
//! §4). Exactly the contract's 15 states; `CANCELLED`/`EXPIRED` legal only
//! as pre-mutation successors (§4.1/§17.4 safety repair).

use guardian_core::transaction::{TransactionState, is_legal_transition, transition};

#[test]
fn happy_path_transitions_are_legal() {
    use TransactionState::{
        Applying, Authorized, Authorizing, Committed, Created, Observing, Validated, Validating,
    };
    assert!(is_legal_transition(Created, Validating));
    assert!(is_legal_transition(Validating, Validated));
    assert!(is_legal_transition(Validated, Authorizing));
    assert!(is_legal_transition(Authorizing, Authorized));
    assert!(is_legal_transition(Authorized, Applying));
    assert!(is_legal_transition(Applying, Observing));
    assert!(is_legal_transition(Observing, Committed));
}

/// P0-TXN-008: a terminal transaction cannot re-enter an active state.
#[test]
fn p0_txn_008_terminal_states_reject_every_transition() {
    for terminal in [
        TransactionState::Committed,
        TransactionState::RolledBack,
        TransactionState::Rejected,
        TransactionState::Failed,
        TransactionState::RollbackFailed,
        TransactionState::Expired,
        TransactionState::Cancelled,
    ] {
        assert!(terminal.is_terminal());
        assert!(transition(terminal, TransactionState::Applying).is_err());
        assert!(transition(terminal, TransactionState::Validating).is_err());
    }
}

/// P0-TXN-008 (required by the handoff §4.1: "at least one illegal
/// transition... is rejected, not merely that legal ones succeed").
#[test]
fn p0_txn_008_illegal_transition_is_rejected_not_panicked() {
    let result = transition(TransactionState::Committed, TransactionState::Applying);
    assert!(result.is_err());
}

#[test]
fn illegal_transition_from_a_nonterminal_state_is_also_rejected() {
    // CREATED cannot jump straight to APPLYING, skipping the governed path.
    assert!(!is_legal_transition(
        TransactionState::Created,
        TransactionState::Applying
    ));
    assert!(transition(TransactionState::Created, TransactionState::Applying).is_err());
}

/// §17.4 adversarial items 26/28: cancellation/expiry are not legal direct
/// successors of `APPLYING`/`ROLLING_BACK` -- the exact defect the repair
/// closed.
#[test]
fn cancelled_and_expired_are_not_legal_successors_of_applying_or_rolling_back() {
    use TransactionState::{Applying, Cancelled, Expired, RollingBack};
    assert!(!is_legal_transition(Applying, Cancelled));
    assert!(!is_legal_transition(Applying, Expired));
    assert!(!is_legal_transition(RollingBack, Cancelled));
    assert!(!is_legal_transition(RollingBack, Expired));
}

#[test]
fn cancelled_and_expired_are_not_legal_successors_of_observing() {
    use TransactionState::{Cancelled, Expired, Observing};
    assert!(!is_legal_transition(Observing, Cancelled));
    assert!(!is_legal_transition(Observing, Expired));
}

#[test]
fn cancelled_and_expired_are_legal_successors_of_every_pre_mutation_state() {
    use TransactionState::{
        Authorized, Authorizing, Cancelled, Created, Expired, Validated, Validating,
    };
    for state in [Created, Validating, Validated, Authorizing, Authorized] {
        assert!(state.is_pre_mutation());
        assert!(is_legal_transition(state, Cancelled));
        assert!(is_legal_transition(state, Expired));
    }
}

#[test]
fn wire_tokens_round_trip() {
    for state in [
        TransactionState::Created,
        TransactionState::RollingBack,
        TransactionState::RollbackFailed,
    ] {
        let token = state.wire_token();
        let parsed: TransactionState = token.parse().unwrap();
        assert_eq!(parsed, state);
    }
}

#[test]
fn unrecognized_wire_token_is_a_typed_parse_failure() {
    assert!("future_state_xyz".parse::<TransactionState>().is_err());
}
