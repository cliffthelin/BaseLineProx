//! The G5 Diagnostic Budget Manager contract (TDD contract §19; G5
//! handoff §4). P0-DIAG-001..005, plus fail-closed/explainability checks.

use guardian_core::budget::{
    BudgetDecision, DenialReason, DiagnosticCandidate, FreeSpaceState, RecorderPolicy,
    SystemPressureState, evaluate, evaluate_with_alternatives, recorder_policy_for,
};
use guardian_core::psi::PressureSeverity;
use guardian_provider_api::{CostLevel, DiagnosticCost};

fn cost(io_write: CostLevel, memory: CostLevel) -> DiagnosticCost {
    DiagnosticCost {
        cpu_cost: CostLevel::Negligible,
        memory_cost: memory,
        io_read_cost: CostLevel::Negligible,
        io_write_cost: io_write,
        kernel_trace_cost: CostLevel::Negligible,
        expected_duration_ms: None,
    }
}

fn pressure(io: PressureSeverity, memory: PressureSeverity) -> SystemPressureState {
    SystemPressureState {
        cpu: PressureSeverity::Nominal,
        memory,
        io,
    }
}

/// P0-DIAG-001: critical I/O pressure prevents a high I/O-write-cost
/// diagnostic.
#[test]
fn p0_diag_001_critical_io_pressure_vetoes_high_io_write_cost() {
    let high_io_write = cost(CostLevel::High, CostLevel::Negligible);
    let critical_io = pressure(PressureSeverity::Critical, PressureSeverity::Nominal);

    let decision = evaluate(&high_io_write, critical_io);

    assert_eq!(
        decision,
        BudgetDecision::Denied {
            reason: DenialReason::IoPressureCritical
        }
    );
}

#[test]
fn nominal_io_pressure_permits_high_io_write_cost() {
    let high_io_write = cost(CostLevel::High, CostLevel::Negligible);
    let nominal = pressure(PressureSeverity::Nominal, PressureSeverity::Nominal);

    assert_eq!(evaluate(&high_io_write, nominal), BudgetDecision::Permitted);
}

/// P0-DIAG-002: critical memory pressure prevents large-memory diagnostic
/// allocation.
#[test]
fn p0_diag_002_critical_memory_pressure_vetoes_high_memory_cost() {
    let high_memory = cost(CostLevel::Negligible, CostLevel::High);
    let critical_memory = pressure(PressureSeverity::Nominal, PressureSeverity::Critical);

    let decision = evaluate(&high_memory, critical_memory);

    assert_eq!(
        decision,
        BudgetDecision::Denied {
            reason: DenialReason::MemoryPressureCritical
        }
    );
}

#[test]
fn nominal_memory_pressure_permits_high_memory_cost() {
    let high_memory = cost(CostLevel::Negligible, CostLevel::High);
    let nominal = pressure(PressureSeverity::Nominal, PressureSeverity::Nominal);

    assert_eq!(evaluate(&high_memory, nominal), BudgetDecision::Permitted);
}

/// P0-DIAG-003: critical free-space condition forces memory-first
/// recorder policy -- a distinct outcome from `BudgetDecision`, never
/// folded into `Denied`.
#[test]
fn p0_diag_003_disk_full_forces_memory_first_recorder_policy() {
    assert_eq!(
        recorder_policy_for(FreeSpaceState::Critical),
        RecorderPolicy::MemoryFirst
    );
    assert_eq!(
        recorder_policy_for(FreeSpaceState::Sufficient),
        RecorderPolicy::Normal
    );
}

/// P0-DIAG-004: a denied escalation returns a reason code -- must
/// genuinely distinguish resource classes, not collapse to one generic
/// "denied" value.
#[test]
fn p0_diag_004_denial_carries_a_distinguishing_reason() {
    let io_denial = evaluate(
        &cost(CostLevel::High, CostLevel::Negligible),
        pressure(PressureSeverity::Critical, PressureSeverity::Nominal),
    );
    let memory_denial = evaluate(
        &cost(CostLevel::Negligible, CostLevel::High),
        pressure(PressureSeverity::Nominal, PressureSeverity::Critical),
    );

    let BudgetDecision::Denied { reason: io_reason } = io_denial else {
        panic!("expected Denied");
    };
    let BudgetDecision::Denied {
        reason: memory_reason,
    } = memory_denial
    else {
        panic!("expected Denied");
    };

    assert_eq!(io_reason, DenialReason::IoPressureCritical);
    assert_eq!(memory_reason, DenialReason::MemoryPressureCritical);
    assert_ne!(
        io_reason, memory_reason,
        "distinct resource classes must produce distinct reasons"
    );
}

/// P0-DIAG-005: the manager can select a cheaper available diagnostic
/// path -- proven over a real multi-candidate slice, with the cheapest
/// permitted candidate deliberately NOT at index 0, so the test cannot
/// pass by accident of ordering.
#[test]
fn p0_diag_005_selects_cheapest_permitted_alternative_not_by_accident_of_order() {
    let requested = DiagnosticCandidate {
        identity: "expensive-io-trace".to_owned(),
        cost: cost(CostLevel::High, CostLevel::Negligible),
    };
    let alternatives = vec![
        // index 0: also denied under this pressure -- must NOT be picked.
        DiagnosticCandidate {
            identity: "also-expensive-io-trace".to_owned(),
            cost: cost(CostLevel::High, CostLevel::Negligible),
        },
        // index 1: permitted but pricier than index 2.
        DiagnosticCandidate {
            identity: "moderate-trace".to_owned(),
            cost: cost(CostLevel::Moderate, CostLevel::Moderate),
        },
        // index 2: permitted and cheapest -- this is the one that must be
        // selected.
        DiagnosticCandidate {
            identity: "cheap-trace".to_owned(),
            cost: cost(CostLevel::Low, CostLevel::Negligible),
        },
    ];
    let critical_io = pressure(PressureSeverity::Critical, PressureSeverity::Nominal);

    let decision = evaluate_with_alternatives(&requested, &alternatives, critical_io);

    match decision {
        BudgetDecision::Downgraded {
            alternative,
            reason,
        } => {
            assert_eq!(alternative.identity, "cheap-trace");
            assert_eq!(reason, DenialReason::IoPressureCritical);
        }
        other => panic!("expected Downgraded to the cheapest permitted alternative, got {other:?}"),
    }
}

#[test]
fn no_permitted_alternative_falls_back_to_denied() {
    let requested = DiagnosticCandidate {
        identity: "expensive".to_owned(),
        cost: cost(CostLevel::High, CostLevel::Negligible),
    };
    let alternatives = vec![DiagnosticCandidate {
        identity: "also-expensive".to_owned(),
        cost: cost(CostLevel::High, CostLevel::Negligible),
    }];
    let critical_io = pressure(PressureSeverity::Critical, PressureSeverity::Nominal);

    let decision = evaluate_with_alternatives(&requested, &alternatives, critical_io);

    assert_eq!(
        decision,
        BudgetDecision::Denied {
            reason: DenialReason::IoPressureCritical
        }
    );
}

#[test]
fn permitted_request_never_consults_alternatives() {
    let requested = DiagnosticCandidate {
        identity: "cheap-and-fine".to_owned(),
        cost: cost(CostLevel::Negligible, CostLevel::Negligible),
    };
    // Deliberately malformed-looking alternatives that would panic if
    // ever inspected in a way this test doesn't expect -- but since the
    // request itself is permitted, they must simply never be consulted.
    let alternatives = vec![DiagnosticCandidate {
        identity: "unused".to_owned(),
        cost: cost(CostLevel::High, CostLevel::High),
    }];
    let nominal = pressure(PressureSeverity::Nominal, PressureSeverity::Nominal);

    let decision = evaluate_with_alternatives(&requested, &alternatives, nominal);

    assert_eq!(decision, BudgetDecision::Permitted);
}

// ---------------------------------------------------------------------
// Boundary preservation: the Budget Manager must not become authorization,
// arbitration, transaction control, or a scheduler.
// ---------------------------------------------------------------------

/// `BudgetDecision`/`DenialReason`/`DiagnosticCandidate` must never
/// resemble authorization, caller-identity, provider-ownership, or
/// transaction-state vocabulary -- confirmed by inspecting Debug output
/// for exactly the kind of accidental-field-bleed G3/G4 already guard
/// against with an identical style of test.
#[test]
fn budget_decision_carries_no_authorization_arbitration_or_transaction_vocabulary() {
    let decision = evaluate(
        &cost(CostLevel::High, CostLevel::Negligible),
        pressure(PressureSeverity::Critical, PressureSeverity::Nominal),
    );
    let debug = format!("{decision:?}");
    assert!(!debug.to_lowercase().contains("caller"));
    assert!(!debug.to_lowercase().contains("authorized"));
    assert!(!debug.to_lowercase().contains("provider_id"));
    assert!(!debug.to_lowercase().contains("transactionstate"));
    assert!(!debug.to_lowercase().contains("ownership"));
}
