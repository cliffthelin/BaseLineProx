//! The canonical shared risk taxonomy (TDD contract §10; G3 handoff §33).

use guardian_core::risk::Risk;

#[test]
fn risk_ladder_orders_from_observe_to_very_high() {
    assert!(Risk::Observe < Risk::Low);
    assert!(Risk::Low < Risk::Moderate);
    assert!(Risk::Moderate < Risk::High);
    assert!(Risk::High < Risk::VeryHigh);
}
