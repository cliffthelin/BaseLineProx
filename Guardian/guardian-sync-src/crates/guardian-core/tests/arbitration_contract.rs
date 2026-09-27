//! The Provider Arbitrator (TDD contract §13; G3 handoff §7).
//! P0-ARB-001/002/003/004, plus determinism and G2-boundary proofs.

use guardian_core::arbitration::{
    ArbitrationInput, CandidateProvider, Ownership, RollbackKind, arbitrate,
};
use guardian_core::risk::Risk;
use guardian_provider_api::{AuthorizationMode, CapabilityId, Knowledge, ProviderId};

fn cap(name: &str) -> CapabilityId {
    CapabilityId::new(name).unwrap()
}

fn provider(name: &str) -> ProviderId {
    ProviderId::new(name).unwrap()
}

fn candidate(name: &str, priority: u32, wants_write: bool) -> CandidateProvider {
    CandidateProvider {
        provider_id: provider(name),
        priority,
        healthy: true,
        wants_write,
        guardian_owned_writer: false,
        authorization_ownership: Knowledge::Known(AuthorizationMode::ProviderOwnedAuthorization),
        rollback_kind: RollbackKind::Native,
    }
}

fn base_input(candidates: Vec<CandidateProvider>) -> ArbitrationInput {
    ArbitrationInput {
        capability_id: cap("storage.device.poweroff"),
        candidates,
        write_requested: true,
        risk_class: Risk::Moderate,
        revision: 1,
        external_writer_present: false,
    }
}

#[test]
fn p0_arb_001_single_writer_two_candidates_cannot_both_win() {
    let input = base_input(vec![
        candidate("provider-a", 0, true),
        candidate("provider-b", 1, true),
    ]);
    let decision = arbitrate(&input);
    assert_eq!(
        decision.authoritative_provider,
        Some(provider("provider-a"))
    );
    assert!(decision.write_permitted);
    assert!(!matches!(decision.current_owner, Ownership::Conflict));
}

#[test]
fn p0_arb_002_ambiguous_equal_priority_fails_closed() {
    let input = base_input(vec![
        candidate("provider-a", 0, true),
        candidate("provider-b", 0, true),
    ]);
    let decision = arbitrate(&input);
    assert!(!decision.write_permitted);
    assert!(matches!(decision.current_owner, Ownership::Conflict));
    assert_eq!(decision.authoritative_provider, None);
    assert_eq!(
        decision.conflicts,
        vec![provider("provider-a"), provider("provider-b")]
    );
}

#[test]
fn p0_arb_004_rollback_kind_is_disclosed_in_the_decision() {
    let mut only = candidate("provider-a", 0, true);
    only.rollback_kind = RollbackKind::Emulated;
    let decision = arbitrate(&base_input(vec![only]));
    assert_eq!(decision.rollback_kind, RollbackKind::Emulated);
}

#[test]
fn p0_arb_003_owner_change_invalidates_stale_arbitration_state() {
    let initial = base_input(vec![candidate("provider-a", 0, true)]);
    let decision_v1 = arbitrate(&initial);

    // Ownership moves to a different provider; the registry's revision for
    // this capability is bumped accordingly (simulated here by constructing
    // a new input at a higher revision -- no transaction machine is
    // exercised).
    let mut moved = base_input(vec![candidate("provider-b", 0, true)]);
    moved.revision = initial.revision + 1;
    let decision_v2 = arbitrate(&moved);

    assert_ne!(decision_v1.revision, decision_v2.revision);
    assert_ne!(
        decision_v1.authoritative_provider,
        decision_v2.authoritative_provider
    );
    // A consumer holding `decision_v1` as a precondition can mechanically
    // detect staleness without any transaction runtime:
    let current_revision = decision_v2.revision;
    assert_ne!(
        decision_v1.revision, current_revision,
        "stale precondition must be detectable"
    );
}

#[test]
fn decision_reason_is_never_an_empty_placeholder() {
    let decision = arbitrate(&base_input(vec![candidate("provider-a", 0, true)]));
    assert!(!decision.decision_reason.is_empty());
    assert!(decision.decision_reason.contains("provider-a"));
}

#[test]
fn ambiguity_is_not_resolved_by_lexicographically_smaller_provider_id() {
    // "provider-a" sorts before "provider-b" lexicographically, but at
    // equal priority this MUST remain a conflict, not a silent
    // first-in-order win.
    let input = base_input(vec![
        candidate("provider-b", 5, true),
        candidate("provider-a", 5, true),
    ]);
    let decision = arbitrate(&input);
    assert!(!decision.write_permitted);
    assert!(matches!(decision.current_owner, Ownership::Conflict));
}

/// §16.1 item 10: arbitration fails closed when write authorization
/// ownership is unknown -- data-model/control-plane only, never proof that
/// any caller was denied real authorization.
#[test]
fn unknown_authorization_ownership_fails_closed_even_with_an_unambiguous_winner() {
    let mut only = candidate("provider-a", 0, true);
    only.authorization_ownership = Knowledge::Unknown;
    let decision = arbitrate(&base_input(vec![only]));
    assert!(!decision.write_permitted);
    assert_eq!(
        decision.authoritative_provider,
        Some(provider("provider-a"))
    );
    assert!(decision.decision_reason.contains("unknown"));
}

#[test]
fn provider_absence_produces_no_writer_not_a_guessed_owner() {
    let decision = arbitrate(&base_input(Vec::new()));
    assert!(!decision.write_permitted);
    assert!(matches!(decision.current_owner, Ownership::NoWriter));
    assert_eq!(decision.authoritative_provider, None);
}

#[test]
fn read_only_observer_is_never_selected_as_writer() {
    let observer = candidate("provider-observer", 0, false);
    let decision = arbitrate(&base_input(vec![observer]));
    assert!(matches!(decision.current_owner, Ownership::NoWriter));
}

#[test]
fn external_writer_is_represented_distinctly_and_denies_write() {
    let mut input = base_input(vec![candidate("provider-a", 0, true)]);
    input.external_writer_present = true;
    let decision = arbitrate(&input);
    assert!(matches!(decision.current_owner, Ownership::ExternalWriter));
    assert!(!decision.write_permitted);
}

#[test]
fn guardian_owned_writer_is_distinguishable_from_provider_owned_writer() {
    let mut guardian_owned = candidate("guardian-helper", 0, true);
    guardian_owned.guardian_owned_writer = true;
    guardian_owned.authorization_ownership =
        Knowledge::Known(AuthorizationMode::GuardianOwnedAuthorization);
    let decision = arbitrate(&base_input(vec![guardian_owned]));
    assert!(matches!(
        decision.current_owner,
        Ownership::GuardianOwnedWriter
    ));
}

#[test]
fn deterministic_regardless_of_candidate_order() {
    let forward = base_input(vec![
        candidate("provider-a", 0, true),
        candidate("provider-b", 1, true),
        candidate("provider-c", 2, false),
    ]);
    let mut reversed = forward.clone();
    reversed.candidates.reverse();

    let decision_forward = arbitrate(&forward);
    let decision_reversed = arbitrate(&reversed);
    assert_eq!(decision_forward, decision_reversed);
}

#[test]
fn deterministic_across_many_construction_orders() {
    use std::collections::HashSet;
    let mut seen = HashSet::new();
    let permutations: [[&str; 3]; 3] = [
        ["provider-a", "provider-b", "provider-c"],
        ["provider-c", "provider-a", "provider-b"],
        ["provider-b", "provider-c", "provider-a"],
    ];
    for order in permutations {
        let candidates = order
            .iter()
            .enumerate()
            .map(|(i, name)| candidate(name, u32::try_from(i).unwrap(), *name == "provider-a"))
            .collect();
        let decision = arbitrate(&base_input(candidates));
        seen.insert(format!("{decision:?}"));
    }
    assert_eq!(
        seen.len(),
        1,
        "arbitration must not depend on construction order"
    );
}

/// G2 boundary: nothing about `ArbitrationDecision`'s public shape can be
/// mistaken for authorization proof -- `write_permitted` is a control-plane
/// policy field, and no field resembles `authorized`/`caller_authorized`.
#[test]
fn arbitration_decision_carries_no_field_resembling_authorization_proof() {
    let decision = arbitrate(&base_input(vec![candidate("provider-a", 0, true)]));
    let debug = format!("{decision:?}");
    assert!(!debug.contains("caller_authorized"));
    assert!(!debug.contains("authorization_passed"));
    assert!(!debug.contains("trusted_caller"));
}
