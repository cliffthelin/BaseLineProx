//! The Diagnostic Budget Manager (TDD contract §19; G5 handoff §4).
//!
//! A **diagnostic-safety** mechanism only: it decides whether a
//! *diagnostic/observational* action may proceed given the host's current
//! pressure state and the action's own declared [`DiagnosticCost`]. It is
//! deliberately, structurally **not**:
//!
//! - an authorization system (it never consults [`crate::authorization`]
//!   or any caller identity -- it answers "is this safe to run right now,"
//!   never "is this caller allowed to run it");
//! - a provider arbitrator (it never touches
//!   [`crate::arbitration`]/ownership/candidate selection -- it has no
//!   concept of "provider" at all);
//! - transaction-state management (see the module doc on the crate root
//!   and G5 handoff §5: this gate's chosen scope, Option A, leaves
//!   [`crate::transaction`] entirely untouched -- `TransactionRecord`/
//!   `engine::apply()` do not appear anywhere in this module);
//! - a general scheduler (there is no queue, no timing, no ordering of
//!   multiple in-flight actions -- every decision here is a pure function
//!   of one action's cost and one pressure snapshot).
//!
//! There is deliberately no depletable "budget pool" to exhaust and reset
//! here: every [`evaluate`] call is a fresh decision against the
//! *current* pressure state, matching the contract's own framing ("deny
//! or downgrade diagnostic escalation when the host is already
//! constrained," §"Governing principles") rather than a cumulative
//! currency this gate's normative tests do not require.

use guardian_provider_api::{CostLevel, DiagnosticCost};

use crate::psi::PressureSeverity;

/// Which resource class triggered a denial -- required so a denial is
/// genuinely *explainable* (P0-DIAG-004), not a single generic "denied"
/// value that happens to type-check.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DenialReason {
    IoPressureCritical,
    MemoryPressureCritical,
    DiskSpaceCritical,
    Other,
}

/// The current, per-resource-class pressure severity the Budget Manager
/// reasons over -- a typed, injectable fixture value (G5 handoff §4.1),
/// never derived from a real host read in this gate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SystemPressureState {
    pub cpu: PressureSeverity,
    pub memory: PressureSeverity,
    pub io: PressureSeverity,
}

impl SystemPressureState {
    #[must_use]
    pub const fn nominal() -> Self {
        Self {
            cpu: PressureSeverity::Nominal,
            memory: PressureSeverity::Nominal,
            io: PressureSeverity::Nominal,
        }
    }
}

/// A typed, injectable free-space fact for the root/recorder-target
/// filesystem (G5 handoff §4.1) -- never a real `statvfs` call in this
/// gate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FreeSpaceState {
    Sufficient,
    Critical,
}

/// The Budget Manager's decision for one diagnostic action. Never a bare
/// `bool` -- `Denied`/`Downgraded` both carry a real [`DenialReason`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BudgetDecision {
    Permitted,
    Denied {
        reason: DenialReason,
    },
    Downgraded {
        alternative: DiagnosticCandidate,
        reason: DenialReason,
    },
}

/// One candidate diagnostic action: an opaque identity plus its declared
/// cost. `identity` is intentionally a plain `String` -- G5 does not need
/// (and must not invent) a new dotted-domain/generated-record identity
/// type; a future gate may promote this if a real need appears.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DiagnosticCandidate {
    pub identity: String,
    pub cost: DiagnosticCost,
}

/// Evaluates one diagnostic action's [`DiagnosticCost`] against the
/// current [`SystemPressureState`]. Pure function -- no state, no
/// caller identity, no provider concept.
///
/// The thresholds implemented are the contract's own floor examples
/// (§19): a `High` I/O-write cost is vetoed under critical I/O pressure
/// (P0-DIAG-001); a `High` memory cost is vetoed under critical memory
/// pressure (P0-DIAG-002). `Moderate`-cost actions are not vetoed by this
/// gate's model -- a stricter production threshold is a deliberate, later
/// decision, not silently assumed here.
#[must_use]
pub fn evaluate(cost: &DiagnosticCost, pressure: SystemPressureState) -> BudgetDecision {
    if cost.io_write_cost == CostLevel::High && pressure.io == PressureSeverity::Critical {
        return BudgetDecision::Denied {
            reason: DenialReason::IoPressureCritical,
        };
    }
    if cost.memory_cost == CostLevel::High && pressure.memory == PressureSeverity::Critical {
        return BudgetDecision::Denied {
            reason: DenialReason::MemoryPressureCritical,
        };
    }
    BudgetDecision::Permitted
}

/// A total, deterministic "cheapness" ranking across every
/// [`DiagnosticCost`] dimension -- sums each dimension's [`CostLevel`]
/// rank. Local to this module: `CostLevel` itself gains no new trait impl
/// (G3's type is not modified by this gate).
const fn cost_level_rank(level: CostLevel) -> u32 {
    match level {
        CostLevel::Negligible => 0,
        CostLevel::Low => 1,
        CostLevel::Moderate => 2,
        CostLevel::High => 3,
    }
}

fn total_cost_rank(cost: &DiagnosticCost) -> u32 {
    cost_level_rank(cost.cpu_cost)
        + cost_level_rank(cost.memory_cost)
        + cost_level_rank(cost.io_read_cost)
        + cost_level_rank(cost.io_write_cost)
        + cost_level_rank(cost.kernel_trace_cost)
}

/// Evaluates a requested diagnostic action; if denied, searches
/// `alternatives` (a real slice of real candidates -- never a hard-coded
/// two-option example) for the cheapest one [`evaluate`] permits under the
/// same pressure state, and returns `Downgraded` if one exists (P0-DIAG-005).
/// If the request itself is permitted, `alternatives` is not consulted at
/// all. If nothing is permitted, returns the original `Denied`.
#[must_use]
pub fn evaluate_with_alternatives(
    requested: &DiagnosticCandidate,
    alternatives: &[DiagnosticCandidate],
    pressure: SystemPressureState,
) -> BudgetDecision {
    let primary = evaluate(&requested.cost, pressure);
    let BudgetDecision::Denied { reason } = primary else {
        return primary;
    };

    alternatives
        .iter()
        .filter(|candidate| {
            matches!(
                evaluate(&candidate.cost, pressure),
                BudgetDecision::Permitted
            )
        })
        .min_by_key(|candidate| total_cost_rank(&candidate.cost))
        .map_or(BudgetDecision::Denied { reason }, |alternative| {
            BudgetDecision::Downgraded {
                alternative: alternative.clone(),
                reason,
            }
        })
}

/// The recorder policy the disk-full-degradation decision produces
/// (P0-DIAG-003) -- a *distinct* outcome from [`BudgetDecision`], since it
/// changes how the recorder itself behaves rather than refusing one
/// action (G5 handoff §4.3).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecorderPolicy {
    Normal,
    MemoryFirst,
}

/// Critical free-space forces the recorder into memory-first policy;
/// sufficient free space leaves it at normal policy. Fail-closed by
/// construction: [`FreeSpaceState`] is a closed two-variant enum with no
/// "unknown, assume fine" state -- a future third state must be added
/// deliberately, and this `match` will then fail to compile until handled.
#[must_use]
pub const fn recorder_policy_for(free_space: FreeSpaceState) -> RecorderPolicy {
    match free_space {
        FreeSpaceState::Sufficient => RecorderPolicy::Normal,
        FreeSpaceState::Critical => RecorderPolicy::MemoryFirst,
    }
}
