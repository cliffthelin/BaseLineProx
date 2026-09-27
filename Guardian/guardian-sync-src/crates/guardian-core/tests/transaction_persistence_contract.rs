//! The G4 persistence contract (TDD contract §23; G4 handoff §19): schema
//! versioning, atomic writes, corrupt-record handling, unknown-version
//! fail-closed, restart load (P0-TXN-011).

use guardian_core::arbitration::RollbackKind;
use guardian_core::transaction::persistence::{
    CURRENT_SCHEMA_VERSION, LoadError, PersistedTransactionRecord, load, load_all, persist,
};
use guardian_core::transaction::{ApplyOutcome, RollbackOutcome, TransactionId, TransactionState};
use guardian_provider_api::{CapabilityId, ProviderId};

fn base_record() -> PersistedTransactionRecord {
    PersistedTransactionRecord {
        schema_version: CURRENT_SCHEMA_VERSION,
        transaction_id: TransactionId::generate(),
        idempotency_key: "idem-0001".to_owned(),
        capability_id: CapabilityId::new("storage.device.poweroff").unwrap(),
        provider_id: ProviderId::new("fixture-provider-a").unwrap(),
        state: TransactionState::Applying,
        arbitration_revision: Some(3),
        apply_outcome: Some(ApplyOutcome::ConfirmedSuccess),
        dispatch_marker: false,
        last_observation: None,
        rollback_result: None,
        cancellation_requested: false,
        deadline_expired: false,
    }
}

fn temp_dir(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "guardian-g4-persistence-{name}-{}",
        std::process::id()
    ))
}

#[test]
fn atomic_persist_then_load_round_trips() {
    let dir = temp_dir("round-trip");
    let record = base_record();
    persist(&dir, &record).unwrap();
    let loaded = load(&dir, &record.transaction_id).unwrap();
    assert_eq!(loaded, record);
    std::fs::remove_dir_all(&dir).ok();
}

/// G4 extension (G4 handoff §19.1a): `dispatch_marker` round-trips through
/// a real persist/load cycle exactly like every other field, both when
/// `true` and when absent from an older-shaped record on disk (backward
/// compatibility for evidence/records written before this extension).
#[test]
fn dispatch_marker_round_trips_through_persistence() {
    let dir = temp_dir("dispatch-marker-round-trip");
    let mut record = base_record();
    record.apply_outcome = Some(ApplyOutcome::NotRecorded);
    record.dispatch_marker = true;
    persist(&dir, &record).unwrap();
    let loaded = load(&dir, &record.transaction_id).unwrap();
    assert_eq!(loaded, record);
    assert!(loaded.dispatch_marker);
    std::fs::remove_dir_all(&dir).ok();
}

/// A persisted record written before this extension existed (no
/// `dispatch_marker=` line at all) must load with `dispatch_marker: false`
/// -- exactly the pre-extension semantics ("no marker means dispatch
/// definitely not entered"), never a load failure and never a silent
/// `true`.
#[test]
fn absent_dispatch_marker_field_defaults_to_false_for_backward_compatibility() {
    let dir = temp_dir("dispatch-marker-absent");
    std::fs::create_dir_all(&dir).unwrap();
    let id = TransactionId::generate();
    let text = format!(
        "schema_version={CURRENT_SCHEMA_VERSION}\n\
         transaction_id={id}\n\
         idempotency_key=idem-legacy-0001\n\
         capability_id=storage.device.poweroff\n\
         provider_id=fixture-provider-a\n\
         state=applying\n\
         apply_outcome=not_recorded\n\
         cancellation_requested=false\n\
         deadline_expired=false\n"
    );
    std::fs::write(dir.join(format!("{id}.txn")), text).unwrap();

    let loaded = load(&dir, &id).unwrap();
    assert!(!loaded.dispatch_marker);

    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn missing_record_is_not_found_not_corrupt() {
    let dir = temp_dir("missing");
    let id = TransactionId::generate();
    let result = load(&dir, &id);
    assert_eq!(result, Err(LoadError::NotFound));
}

/// Schema/version: an unrecognized future schema version fails closed --
/// typed error, never silently misinterpreted.
#[test]
fn unsupported_schema_version_fails_closed_not_misinterpreted() {
    let dir = temp_dir("schema");
    std::fs::create_dir_all(&dir).unwrap();
    let id = TransactionId::generate();
    let path = dir.join(format!("{id}.txn"));
    std::fs::write(
        &path,
        "schema_version=999\ntransaction_id=deadbeef-dead-dead-dead-deaddeadbeef\n",
    )
    .unwrap();
    let result = load(&dir, &id);
    assert_eq!(result, Err(LoadError::UnsupportedSchemaVersion(999)));
    std::fs::remove_dir_all(&dir).ok();
}

/// Corrupt-record behavior: a genuinely unparseable record surfaces as
/// corrupt -- never silently discarded, never treated as safe.
#[test]
fn corrupt_record_surfaces_as_corrupt_never_silently_safe() {
    let dir = temp_dir("corrupt");
    std::fs::create_dir_all(&dir).unwrap();
    let id = TransactionId::generate();
    let path = dir.join(format!("{id}.txn"));
    std::fs::write(&path, "this is not a valid persisted record at all").unwrap();
    let result = load(&dir, &id);
    assert!(matches!(result, Err(LoadError::Corrupt(_))));
    std::fs::remove_dir_all(&dir).ok();
}

/// Partial-write behavior is covered by atomicity: a record written via the
/// real `persist()` function is never observable half-written, because
/// `persist()` writes to a temp file and renames -- a reader can only ever
/// see the old complete file or the new complete file, never a partial one.
#[test]
fn persist_never_leaves_a_partial_file_at_the_final_path() {
    let dir = temp_dir("atomic");
    let record = base_record();
    persist(&dir, &record).unwrap();
    // The temp file must not remain after a successful persist.
    let temp_path = dir.join(format!("{}.txn.tmp", record.transaction_id));
    assert!(!temp_path.exists());
    let final_path = dir.join(format!("{}.txn", record.transaction_id));
    assert!(final_path.exists());
    std::fs::remove_dir_all(&dir).ok();
}

/// P0-TXN-011: restart load reads back every persisted nonterminal
/// transaction; one corrupt record does not prevent others from loading.
#[test]
fn p0_txn_011_restart_load_reads_back_all_records_corrupt_one_does_not_block_others() {
    let dir = temp_dir("restart-load");
    let good_a = base_record();
    let mut good_b = base_record();
    good_b.transaction_id = TransactionId::generate();
    good_b.state = TransactionState::Observing;
    persist(&dir, &good_a).unwrap();
    persist(&dir, &good_b).unwrap();

    let corrupt_id = TransactionId::generate();
    std::fs::write(
        dir.join(format!("{corrupt_id}.txn")),
        "garbage, not parseable",
    )
    .unwrap();

    let all = load_all(&dir);
    assert_eq!(all.len(), 3);
    let ok_count = all.iter().filter(|r| r.is_ok()).count();
    let corrupt_count = all
        .iter()
        .filter(|r| matches!(r, Err(LoadError::Corrupt(_))))
        .count();
    assert_eq!(ok_count, 2);
    assert_eq!(corrupt_count, 1);
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn rollback_outcome_and_rollback_kind_round_trip_through_persistence() {
    let dir = temp_dir("rollback-fields");
    let mut record = base_record();
    record.rollback_result = Some(RollbackOutcome::AttemptedUnconfirmed);
    persist(&dir, &record).unwrap();
    let loaded = load(&dir, &record.transaction_id).unwrap();
    assert_eq!(
        loaded.rollback_result,
        Some(RollbackOutcome::AttemptedUnconfirmed)
    );

    // RollbackKind itself (G3's enum, closed for NB-3 by this gate) also
    // round-trips through Display/FromStr now that persistence is a real
    // boundary it crosses.
    for kind in [
        RollbackKind::Native,
        RollbackKind::Emulated,
        RollbackKind::BestEffort,
        RollbackKind::None,
    ] {
        let wire = kind.to_string();
        let parsed: RollbackKind = wire.parse().unwrap();
        assert_eq!(parsed, kind);
    }
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn unrecognized_rollback_kind_wire_token_is_a_typed_parse_failure() {
    assert!("future_kind_xyz".parse::<RollbackKind>().is_err());
}
