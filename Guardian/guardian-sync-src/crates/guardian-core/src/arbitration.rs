//! The Provider Arbitrator (TDD contract §13; G3 handoff §7).
//!
//! Answers: *which provider is authoritative for this capability right now,
//! and is Guardian allowed to write it?* This module is data-model and
//! deterministic-decision logic only -- it is not the G4 transaction engine
//! (no `Apply`/`Observe`/`Commit`/`Rollback` runtime exists here), and its
//! output is never treated as proof that any specific caller passed
//! authorization (G2 boundary, unchanged; see [`ArbitrationDecision`]'s own
//! docs).

use std::fmt;

use guardian_provider_api::{AuthorizationMode, CapabilityId, Knowledge, ProviderId};

use crate::risk::Risk;

/// TDD contract §13. Disclosed as part of every [`ArbitrationDecision`] --
/// P0-ARB-004 requires disclosure only; rollback itself is not implemented
/// until G4.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RollbackKind {
    Native,
    Emulated,
    BestEffort,
    None,
}

/// Who currently holds write authority for a capability -- kept
/// structurally distinct from "a provider exists" (G3 handoff §7/§14): a
/// provider may be a read-only observer without ever being a writer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Ownership {
    NoWriter,
    GuardianOwnedWriter,
    ProviderOwnedWriter(ProviderId),
    /// A write owner outside Guardian's own candidate model entirely (e.g.
    /// a system component Guardian does not yet represent as a provider).
    ExternalWriter,
    /// Two or more candidates ambiguously claim exclusive write ownership.
    Conflict,
}

/// One provider's arbitration input for a single capability.
#[derive(Clone, Debug)]
pub struct CandidateProvider {
    pub provider_id: ProviderId,
    /// Lower is more authoritative. Used only as an explicit, stable
    /// tie-break signal among candidates that are *not* ambiguous with each
    /// other -- it never resolves a genuine write-ownership conflict (see
    /// [`arbitrate`]).
    pub priority: u32,
    pub healthy: bool,
    pub wants_write: bool,
    /// `true` if, when this candidate is selected as writer, Guardian
    /// itself (not the external provider) is the actual write owner --
    /// e.g. a Guardian-owned bounded action realized without a separate
    /// system provider.
    pub guardian_owned_writer: bool,
    pub authorization_ownership: Knowledge<AuthorizationMode>,
    pub rollback_kind: RollbackKind,
}

/// Arbitration input for one capability at one point in time.
#[derive(Clone, Debug)]
pub struct ArbitrationInput {
    pub capability_id: CapabilityId,
    pub candidates: Vec<CandidateProvider>,
    pub write_requested: bool,
    pub risk_class: Risk,
    /// A monotonically increasing generation number bumped whenever the
    /// real ownership/candidate set for `capability_id` changes. Lets a
    /// future consumer (G4) mechanically detect that an
    /// [`ArbitrationDecision`] captured as a precondition is now stale
    /// (P0-ARB-003) by comparing `revision` values -- no transaction state
    /// machine is implemented here.
    pub revision: u64,
    /// Set when Guardian knows a write owner exists entirely outside its
    /// own candidate model (TDD contract §13 "provider absence... but not
    /// guessed write ownership" -- this is the one case where Guardian
    /// asserts an owner without it being one of `candidates`).
    pub external_writer_present: bool,
}

/// TDD contract §13's canonical arbitration output.
///
/// `write_permitted` is a **control-plane policy decision** -- "arbitration
/// permits Guardian to proceed toward this write" -- and is never proof
/// that any specific caller passed real polkit authorization. No field on
/// this type may be read by a privileged helper as evidence of caller
/// identity or authorization (G2 boundary; ADR-002). The privileged helper
/// remains solely and independently responsible for authorizing the real
/// caller immediately before mutation, exactly as G1/G2 established.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArbitrationDecision {
    pub capability_id: CapabilityId,
    /// Sorted by `provider_id` for deterministic, order-independent output.
    pub candidate_providers: Vec<ProviderId>,
    pub authoritative_provider: Option<ProviderId>,
    pub current_owner: Ownership,
    pub ownership_basis: String,
    /// Sorted by `provider_id`.
    pub conflicts: Vec<ProviderId>,
    pub write_permitted: bool,
    pub rollback_kind: RollbackKind,
    pub risk_class: Risk,
    pub decision_reason: String,
    pub revision: u64,
}

impl fmt::Display for RollbackKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Native => "native",
            Self::Emulated => "emulated",
            Self::BestEffort => "best_effort",
            Self::None => "none",
        })
    }
}

/// An unrecognized `RollbackKind` wire token -- there is no `Unknown`
/// variant on this enum, so an unrecognized value fails closed with a typed
/// parse error rather than silently defaulting to any of the four known
/// kinds (added when G4's persistence contract became the first real
/// boundary this type crosses -- TDD contract §23 / G4 handoff NB-3).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RollbackKindParseError;

impl fmt::Display for RollbackKindParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("unrecognized rollback_kind wire token")
    }
}

impl std::error::Error for RollbackKindParseError {}

impl std::str::FromStr for RollbackKind {
    type Err = RollbackKindParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(match value {
            "native" => Self::Native,
            "emulated" => Self::Emulated,
            "best_effort" => Self::BestEffort,
            "none" => Self::None,
            _ => return Err(RollbackKindParseError),
        })
    }
}

/// Arbitrates a single capability's write ownership. Deterministic:
/// identical `input` (regardless of `input.candidates` order) always
/// produces an identical [`ArbitrationDecision`] -- resolution depends only
/// on explicit `priority`/`provider_id` values, never on iteration order.
#[must_use]
pub fn arbitrate(input: &ArbitrationInput) -> ArbitrationDecision {
    let mut candidates = input.candidates.clone();
    candidates.sort_by(|a, b| a.provider_id.cmp(&b.provider_id));

    let mut candidate_providers: Vec<ProviderId> =
        candidates.iter().map(|c| c.provider_id.clone()).collect();
    candidate_providers.sort();

    if input.external_writer_present {
        return external_writer_decision(input, candidate_providers);
    }

    let healthy_writers: Vec<&CandidateProvider> = candidates
        .iter()
        .filter(|c| c.healthy && c.wants_write)
        .collect();

    let Some(min_priority) = healthy_writers.iter().map(|c| c.priority).min() else {
        return no_writer_decision(input, candidate_providers);
    };

    let mut top_tier: Vec<&CandidateProvider> = healthy_writers
        .into_iter()
        .filter(|c| c.priority == min_priority)
        .collect();
    top_tier.sort_by(|a, b| a.provider_id.cmp(&b.provider_id));

    if let [winner] = top_tier.as_slice() {
        winner_decision(input, candidate_providers, winner)
    } else {
        conflict_decision(input, candidate_providers, &top_tier)
    }
}

fn external_writer_decision(
    input: &ArbitrationInput,
    candidate_providers: Vec<ProviderId>,
) -> ArbitrationDecision {
    ArbitrationDecision {
        capability_id: input.capability_id.clone(),
        candidate_providers,
        authoritative_provider: None,
        current_owner: Ownership::ExternalWriter,
        ownership_basis: "an external, non-candidate writer is known to hold ownership".to_owned(),
        conflicts: Vec::new(),
        write_permitted: false,
        rollback_kind: RollbackKind::None,
        risk_class: input.risk_class,
        decision_reason:
            "write denied: an external writer outside Guardian's candidate model owns this capability"
                .to_owned(),
        revision: input.revision,
    }
}

fn no_writer_decision(
    input: &ArbitrationInput,
    candidate_providers: Vec<ProviderId>,
) -> ArbitrationDecision {
    ArbitrationDecision {
        capability_id: input.capability_id.clone(),
        candidate_providers,
        authoritative_provider: None,
        current_owner: Ownership::NoWriter,
        ownership_basis: "no healthy candidate currently claims write ownership".to_owned(),
        conflicts: Vec::new(),
        write_permitted: false,
        rollback_kind: RollbackKind::None,
        risk_class: input.risk_class,
        decision_reason:
            "write denied: no candidate provider is available to write this capability".to_owned(),
        revision: input.revision,
    }
}

fn conflict_decision(
    input: &ArbitrationInput,
    candidate_providers: Vec<ProviderId>,
    top_tier: &[&CandidateProvider],
) -> ArbitrationDecision {
    let conflicts: Vec<ProviderId> = top_tier.iter().map(|c| c.provider_id.clone()).collect();
    ArbitrationDecision {
        capability_id: input.capability_id.clone(),
        candidate_providers,
        authoritative_provider: None,
        current_owner: Ownership::Conflict,
        ownership_basis: format!(
            "{} candidates ambiguously claim exclusive write ownership at equal priority",
            conflicts.len()
        ),
        conflicts,
        write_permitted: false,
        rollback_kind: RollbackKind::None,
        risk_class: input.risk_class,
        decision_reason:
            "write denied: ownership is ambiguous between multiple equally-prioritized candidates"
                .to_owned(),
        revision: input.revision,
    }
}

fn winner_decision(
    input: &ArbitrationInput,
    candidate_providers: Vec<ProviderId>,
    winner: &CandidateProvider,
) -> ArbitrationDecision {
    let current_owner = if winner.guardian_owned_writer {
        Ownership::GuardianOwnedWriter
    } else {
        Ownership::ProviderOwnedWriter(winner.provider_id.clone())
    };

    if input.write_requested && matches!(winner.authorization_ownership, Knowledge::Unknown) {
        return ArbitrationDecision {
            capability_id: input.capability_id.clone(),
            candidate_providers,
            authoritative_provider: Some(winner.provider_id.clone()),
            current_owner,
            ownership_basis: "an unambiguous candidate was selected, but its authorization \
                               architecture has not been established"
                .to_owned(),
            conflicts: Vec::new(),
            write_permitted: false,
            rollback_kind: winner.rollback_kind,
            risk_class: input.risk_class,
            decision_reason: "write denied: authorization ownership for this capability is \
                               unknown -- this is a control-plane policy decision, not proof \
                               that any caller was denied real authorization"
                .to_owned(),
            revision: input.revision,
        };
    }

    ArbitrationDecision {
        capability_id: input.capability_id.clone(),
        candidate_providers,
        authoritative_provider: Some(winner.provider_id.clone()),
        current_owner,
        ownership_basis: format!(
            "{} is the sole unambiguous top-priority candidate",
            winner.provider_id
        ),
        conflicts: Vec::new(),
        write_permitted: input.write_requested,
        rollback_kind: winner.rollback_kind,
        risk_class: input.risk_class,
        decision_reason: if input.write_requested {
            format!(
                "write permitted: {} is the authoritative writer",
                winner.provider_id
            )
        } else {
            "no write requested; arbitration performed for observation only".to_owned()
        },
        revision: input.revision,
    }
}
