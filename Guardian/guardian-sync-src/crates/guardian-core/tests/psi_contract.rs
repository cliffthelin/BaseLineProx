//! The G5 PSI fixture/parsing contract (TDD contract §20; G5 handoff §6).
//! Fixture-driven and deterministic -- no real `/proc/pressure/*` read
//! anywhere in this file.
//!
//! Float comparisons below are intentional exact-parse-round-trip checks
//! (literal decimal text parsed into `f64`, both sides fully controlled by
//! this file) -- not a tolerance-requiring numeric computation.
#![allow(clippy::float_cmp)]

use guardian_core::psi::{
    MonotonicTotalCheck, PressureSeverity, PsiParseError, PsiReading, PsiResourceKind,
    SeverityThresholds, ThresholdMonitor, classify, parse_resource, read_resource,
};

const THRESHOLDS: SeverityThresholds = SeverityThresholds::new(10.0, 60.0);

#[test]
fn valid_some_and_full_parse() {
    let text = "some avg10=5.00 avg60=2.00 avg300=1.00 total=1234\nfull avg10=1.00 avg60=0.50 avg300=0.10 total=567\n";
    let resource = parse_resource(text, PsiResourceKind::Memory).unwrap();
    assert_eq!(resource.some.avg10, 5.00);
    assert_eq!(resource.some.total, 1234);
    let full = resource.full.expect("full line must be present for memory");
    assert_eq!(full.avg10, 1.00);
    assert_eq!(full.total, 567);
}

/// §20's explicitly named required test: CPU legitimately has no `full`
/// line on some kernels -- this must parse successfully into a distinct,
/// non-error state, not incidentally pass because the parser happens to
/// be lenient.
#[test]
fn cpu_lacking_a_full_line_parses_as_a_legitimate_distinct_state() {
    let text = "some avg10=12.50 avg60=8.00 avg300=3.00 total=99\n";
    let resource = parse_resource(text, PsiResourceKind::Cpu).unwrap();
    assert_eq!(resource.some.avg10, 12.50);
    assert_eq!(
        resource.full, None,
        "CPU's missing full line must be None, not an error"
    );
}

#[test]
fn malformed_line_is_a_typed_error_never_a_panic_never_zero_pressure() {
    let text = "this is not a psi line at all\n";
    let result = parse_resource(text, PsiResourceKind::Io);
    assert!(matches!(result, Err(PsiParseError(_))));
}

/// Adversarial: a genuinely malformed line must be rejected even when a
/// valid `some` line is *also* present in the same input -- proves the
/// parser doesn't fail-open by silently skipping unrecognized lines once
/// it has already satisfied the "some" requirement.
#[test]
fn malformed_line_alongside_an_otherwise_valid_some_line_is_still_rejected() {
    let text = "some avg10=5.00 avg60=2.00 avg300=1.00 total=1\nthis line is garbage\n";
    let result = parse_resource(text, PsiResourceKind::Cpu);
    assert!(
        result.is_err(),
        "a malformed line must not be silently skipped just because 'some' already parsed"
    );
}

#[test]
fn malformed_field_within_an_otherwise_valid_line_is_a_typed_error() {
    let text = "some avg10=not-a-number avg60=2.00 avg300=1.00 total=1\n";
    let result = parse_resource(text, PsiResourceKind::Cpu);
    assert!(result.is_err());
}

#[test]
fn missing_required_field_is_a_typed_error() {
    let text = "some avg10=5.00 avg60=2.00 total=1\n"; // missing avg300
    let result = parse_resource(text, PsiResourceKind::Cpu);
    assert!(result.is_err());
}

/// §6.2: an entirely absent source is a distinct, explicit state from a
/// present-but-malformed one -- never silently "zero pressure."
#[test]
fn unavailable_source_is_distinct_from_present_text() {
    let unavailable = read_resource(None, PsiResourceKind::Io).unwrap();
    assert_eq!(unavailable, PsiReading::Unavailable);

    let present = read_resource(
        Some("some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"),
        PsiResourceKind::Io,
    )
    .unwrap();
    assert!(matches!(present, PsiReading::Present(_)));
}

#[test]
fn present_but_malformed_source_still_surfaces_a_real_parse_error() {
    let result = read_resource(Some("garbage"), PsiResourceKind::Memory);
    assert!(result.is_err());
}

// ---------------------------------------------------------------------
// Counter monotonicity
// ---------------------------------------------------------------------

#[test]
fn monotonic_total_sequence_is_accepted() {
    let mut check = MonotonicTotalCheck::new();
    for total in [0_u64, 5, 5, 100, 100_000] {
        check.observe(total).unwrap();
    }
}

/// A real, forced non-monotonicity -- proving the invariant is actually
/// checked, not merely assumed true by construction.
#[test]
fn non_monotonic_total_is_detected_not_assumed() {
    let mut check = MonotonicTotalCheck::new();
    check.observe(100).unwrap();
    let result = check.observe(50);
    assert!(result.is_err());
    let error = result.unwrap_err();
    assert_eq!(error.previous, 100);
    assert_eq!(error.observed, 50);
}

// ---------------------------------------------------------------------
// Severity classification
// ---------------------------------------------------------------------

#[test]
fn severity_classification_thresholds() {
    use guardian_core::psi::PsiLine;

    let nominal = PsiLine {
        avg10: 5.0,
        avg60: 0.0,
        avg300: 0.0,
        total: 0,
    };
    let elevated = PsiLine {
        avg10: 15.0,
        avg60: 0.0,
        avg300: 0.0,
        total: 0,
    };
    let critical = PsiLine {
        avg10: 75.0,
        avg60: 0.0,
        avg300: 0.0,
        total: 0,
    };

    assert_eq!(classify(nominal, THRESHOLDS), PressureSeverity::Nominal);
    assert_eq!(classify(elevated, THRESHOLDS), PressureSeverity::Elevated);
    assert_eq!(classify(critical, THRESHOLDS), PressureSeverity::Critical);
}

// ---------------------------------------------------------------------
// Threshold event triggering + teardown
// ---------------------------------------------------------------------

#[test]
fn threshold_event_triggers_exactly_on_crossing() {
    let mut monitor = ThresholdMonitor::new(PsiResourceKind::Io, PressureSeverity::Critical);

    // First observation never produces an event (no prior sample to
    // compare against).
    assert_eq!(monitor.observe(PressureSeverity::Nominal), None);
    // Still below threshold -- no event.
    assert_eq!(monitor.observe(PressureSeverity::Elevated), None);
    // Crosses into Critical -- exactly one event.
    let event = monitor
        .observe(PressureSeverity::Critical)
        .expect("crossing into Critical must produce an event");
    assert_eq!(event.from, PressureSeverity::Elevated);
    assert_eq!(event.to, PressureSeverity::Critical);
    assert_eq!(event.resource, PsiResourceKind::Io);
    // Staying at Critical -- no further event (already crossed).
    assert_eq!(monitor.observe(PressureSeverity::Critical), None);
    // Dropping back below -- a real reverse-crossing event.
    let reverse = monitor
        .observe(PressureSeverity::Nominal)
        .expect("crossing back below threshold must also produce an event");
    assert_eq!(reverse.from, PressureSeverity::Critical);
    assert_eq!(reverse.to, PressureSeverity::Nominal);
}

#[test]
fn threshold_monitor_teardown_stops_further_events() {
    let mut monitor = ThresholdMonitor::new(PsiResourceKind::Memory, PressureSeverity::Elevated);
    monitor.observe(PressureSeverity::Nominal);
    monitor.teardown();
    assert!(monitor.is_torn_down());

    // Would have crossed the threshold, but teardown must suppress it.
    let after_teardown = monitor.observe(PressureSeverity::Critical);
    assert_eq!(
        after_teardown, None,
        "no event may be produced after teardown"
    );
}

/// "No busy-loop when there is no event" is proven structurally here: the
/// only way to learn anything from `ThresholdMonitor` is a caller-driven
/// `observe(value)` call -- there is no method on this type that spins,
/// polls, or blocks waiting for a real kernel event. This test does not
/// (and cannot, without a real kernel) prove real `poll`/`epoll` timing
/// behavior -- it proves the fixture-driven state machine's public API
/// shape has no such method to call in the first place.
#[test]
fn threshold_monitor_api_has_no_polling_method_only_push_based_observe() {
    let mut monitor = ThresholdMonitor::new(PsiResourceKind::Cpu, PressureSeverity::Critical);
    // The only public methods are observe/teardown/is_torn_down -- this
    // test exercises exactly that surface, evidencing the claim above by
    // construction rather than by inspecting a timing trace.
    assert_eq!(monitor.observe(PressureSeverity::Nominal), None);
    assert!(!monitor.is_torn_down());
}
