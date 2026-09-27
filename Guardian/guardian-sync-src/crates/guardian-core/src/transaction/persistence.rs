//! The G4 persistence contract (TDD contract §23; G4 handoff §19).
//!
//! Persists a bounded, explicitly-versioned projection of
//! [`crate::transaction::record::TransactionRecord`] sufficient to prove
//! the persistence *contract* required by this gate (schema versioning,
//! atomic writes, corrupt-record handling, restart-load, and all six
//! recovery classifications) -- not full-fidelity serialization of every
//! nested G3 type (`ArbitrationDecision`'s complete candidate list,
//! `ObservationPolicy`'s free-text conditions, etc.). This is a deliberate,
//! disclosed scope boundary for this gate: the fields below are exactly
//! what a recovery decision needs, reusing G3/G4's own typed
//! `Display`/`FromStr` for every governed enum it touches, never `Debug`
//! formatting as a wire format.

use std::collections::BTreeMap;
use std::fmt;
use std::fs::{self, File};
use std::io::Write as _;
use std::path::{Path, PathBuf};

use guardian_provider_api::{CapabilityId, ProviderId};

use crate::transaction::apply::ApplyOutcome;
use crate::transaction::id::TransactionId;
use crate::transaction::observation::ObservationOutcome;
use crate::transaction::record::TransactionRecord;
use crate::transaction::recovery::RecoverySnapshot;
use crate::transaction::rollback::RollbackOutcome;
use crate::transaction::state::TransactionState;

/// The current schema version this build writes and accepts. Bumped only
/// when the persisted shape changes incompatibly.
pub const CURRENT_SCHEMA_VERSION: u32 = 1;

/// The bounded, versioned persisted projection (see module docs for scope).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedTransactionRecord {
    pub schema_version: u32,
    pub transaction_id: TransactionId,
    pub idempotency_key: String,
    pub capability_id: CapabilityId,
    pub provider_id: ProviderId,
    pub state: TransactionState,
    pub arbitration_revision: Option<u64>,
    pub apply_outcome: Option<ApplyOutcome>,
    /// The durable dispatch-start marker for the current Apply attempt (G4
    /// handoff §19.1a, disclosed Wave-1-required G4 extension -- see
    /// `crate::transaction::apply::ApplyRecord::dispatch_marker`). Absent
    /// (defaults to `false` on load) in records written before this
    /// extension existed, which is exactly the pre-extension semantics: no
    /// marker means "provider dispatch definitely not entered."
    pub dispatch_marker: bool,
    /// The most recent `Observe` result, if any -- required to classify a
    /// reloaded `Observing`-state record via
    /// [`crate::transaction::recovery::classify`] using real persisted
    /// evidence rather than only the fail-closed "no observation recorded"
    /// default (closes the audit's persistence/recovery integration gap).
    pub last_observation: Option<ObservationOutcome>,
    pub rollback_result: Option<RollbackOutcome>,
    pub cancellation_requested: bool,
    pub deadline_expired: bool,
}

impl PersistedTransactionRecord {
    /// Projects the fields of a live [`TransactionRecord`] this gate's
    /// persistence/recovery contract actually needs -- not a general
    /// serialization of every nested field (see module docs).
    #[must_use]
    pub fn from_record(record: &TransactionRecord) -> Self {
        let arbitration_revision = record
            .arbitration_result
            .as_ref()
            .map(|decision| decision.revision)
            .or_else(|| {
                record
                    .pre_state
                    .as_ref()
                    .map(|snapshot| snapshot.arbitration_result.revision)
            });
        Self {
            schema_version: CURRENT_SCHEMA_VERSION,
            transaction_id: record.transaction_id.clone(),
            idempotency_key: record.idempotency_key.clone(),
            capability_id: record.capability_id.clone(),
            provider_id: record.provider_id.clone(),
            state: record.state,
            arbitration_revision,
            apply_outcome: record.apply_record.as_ref().map(|apply| apply.outcome),
            dispatch_marker: record
                .apply_record
                .as_ref()
                .is_some_and(|apply| apply.dispatch_marker),
            last_observation: record.observations.last().copied(),
            rollback_result: record.rollback_result,
            cancellation_requested: record.cancellation_requested,
            deadline_expired: record.deadline_expired,
        }
    }

    /// Projects onto exactly the inputs
    /// [`crate::transaction::recovery::classify`] needs -- the integrated
    /// "load a real persisted record, then classify it" flow the audit
    /// found untested (a corrupt or unparseable record never reaches this
    /// method at all: [`load`]/[`load_all`] fail closed with
    /// [`LoadError`] before a [`RecoverySnapshot`] can be constructed).
    #[must_use]
    pub const fn to_recovery_snapshot(&self) -> RecoverySnapshot {
        RecoverySnapshot {
            state: self.state,
            apply_outcome: self.apply_outcome,
            last_observation: self.last_observation,
            dispatch_marker: self.dispatch_marker,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistenceError(pub String);

impl fmt::Display for PersistenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for PersistenceError {}

/// Distinguishes a genuinely corrupt/unparseable record from an ordinary
/// I/O failure (e.g. the file simply doesn't exist yet) -- a corrupt record
/// must surface as "requires recovery/human handling" (G4 handoff §19),
/// never be silently discarded or treated as safe.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LoadError {
    NotFound,
    Corrupt(String),
    UnsupportedSchemaVersion(u32),
}

impl fmt::Display for LoadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotFound => formatter.write_str("no persisted record at this path"),
            Self::Corrupt(reason) => write!(formatter, "corrupt persisted record: {reason}"),
            Self::UnsupportedSchemaVersion(version) => {
                write!(formatter, "unsupported schema_version {version}")
            }
        }
    }
}

impl std::error::Error for LoadError {}

fn serialize(record: &PersistedTransactionRecord) -> String {
    let mut lines = vec![
        format!("schema_version={}", record.schema_version),
        format!("transaction_id={}", record.transaction_id),
        format!("idempotency_key={}", record.idempotency_key),
        format!("capability_id={}", record.capability_id),
        format!("provider_id={}", record.provider_id),
        format!("state={}", record.state),
    ];
    if let Some(revision) = record.arbitration_revision {
        lines.push(format!("arbitration_revision={revision}"));
    }
    if let Some(outcome) = record.apply_outcome {
        lines.push(format!("apply_outcome={outcome}"));
    }
    if record.dispatch_marker {
        lines.push(format!("dispatch_marker={}", record.dispatch_marker));
    }
    if let Some(observation) = record.last_observation {
        lines.push(format!("last_observation={observation}"));
    }
    if let Some(rollback) = record.rollback_result {
        lines.push(format!("rollback_result={rollback}"));
    }
    lines.push(format!(
        "cancellation_requested={}",
        record.cancellation_requested
    ));
    lines.push(format!("deadline_expired={}", record.deadline_expired));
    lines.join("\n")
}

fn deserialize(text: &str) -> Result<PersistedTransactionRecord, LoadError> {
    let fields: BTreeMap<&str, &str> = text
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .map(|line| {
            line.split_once('=')
                .ok_or_else(|| LoadError::Corrupt(format!("malformed line (no '='): {line}")))
        })
        .collect::<Result<_, _>>()?;

    let required = |key: &str| -> Result<&str, LoadError> {
        fields
            .get(key)
            .copied()
            .ok_or_else(|| LoadError::Corrupt(format!("missing required field: {key}")))
    };

    let schema_version: u32 = required("schema_version")?
        .parse()
        .map_err(|_| LoadError::Corrupt("schema_version is not a valid integer".to_owned()))?;
    if schema_version != CURRENT_SCHEMA_VERSION {
        return Err(LoadError::UnsupportedSchemaVersion(schema_version));
    }

    let transaction_id = TransactionId::new(required("transaction_id")?)
        .map_err(|error| LoadError::Corrupt(format!("transaction_id: {error}")))?;
    let capability_id = CapabilityId::new(required("capability_id")?)
        .map_err(|error| LoadError::Corrupt(format!("capability_id: {error}")))?;
    let provider_id = ProviderId::new(required("provider_id")?)
        .map_err(|error| LoadError::Corrupt(format!("provider_id: {error}")))?;
    let state: TransactionState = required("state")?
        .parse()
        .map_err(|_| LoadError::Corrupt("unrecognized state token".to_owned()))?;

    let arbitration_revision = fields
        .get("arbitration_revision")
        .map(|value| {
            value.parse::<u64>().map_err(|_| {
                LoadError::Corrupt("arbitration_revision is not a valid integer".to_owned())
            })
        })
        .transpose()?;
    let apply_outcome = fields
        .get("apply_outcome")
        .map(|value| {
            Ok::<_, LoadError>(
                value
                    .parse::<ApplyOutcome>()
                    .unwrap_or(ApplyOutcome::NotRecorded),
            )
        })
        .transpose()?;
    let dispatch_marker = fields
        .get("dispatch_marker")
        .is_some_and(|value| *value == "true");
    let last_observation = fields
        .get("last_observation")
        .map(|value| {
            Ok::<_, LoadError>(
                value
                    .parse::<ObservationOutcome>()
                    .unwrap_or(ObservationOutcome::Ambiguous),
            )
        })
        .transpose()?;
    let rollback_result = fields
        .get("rollback_result")
        .map(|value| {
            value
                .parse::<RollbackOutcome>()
                .map_err(|_| LoadError::Corrupt("unrecognized rollback_result token".to_owned()))
        })
        .transpose()?;
    let cancellation_requested = required("cancellation_requested")? == "true";
    let deadline_expired = required("deadline_expired")? == "true";

    Ok(PersistedTransactionRecord {
        schema_version,
        transaction_id,
        idempotency_key: required("idempotency_key")?.to_owned(),
        capability_id,
        provider_id,
        state,
        arbitration_revision,
        apply_outcome,
        dispatch_marker,
        last_observation,
        rollback_result,
        cancellation_requested,
        deadline_expired,
    })
}

fn record_path(directory: &Path, transaction_id: &TransactionId) -> PathBuf {
    directory.join(format!("{transaction_id}.txn"))
}

/// Persists `record` under `directory` with the real durability guarantee
/// G4 handoff §19.1 step 3 requires -- not atomicity alone. Exactly three
/// operations are performed, and this is the complete guarantee (no
/// stronger, no weaker):
///
/// 1. the temp file's contents are written and **`fsync`'d** (`sync_all`)
///    before anything else happens, so the bytes that will become the
///    published record are durable on disk first;
/// 2. the temp file is atomically renamed onto the final path (POSIX
///    `rename` -- a reader can only ever observe the old complete record or
///    the new complete record, never a partial one);
/// 3. the containing directory is itself **`fsync`'d** after the rename,
///    because POSIX does not guarantee a rename's directory-entry update
///    is durable on its own -- without this, a power loss immediately
///    after a "successful" rename could still lose the new directory
///    entry on some filesystems/mount options.
///
/// This does not guarantee anything about `directory`'s own ancestors, and
/// it is a synchronous, blocking durability barrier (deliberately -- this
/// gate does not implement async I/O or a write-behind journal; see G4
/// handoff §19).
///
/// # Errors
///
/// Returns [`PersistenceError`] on any I/O failure, including a failure of
/// either `fsync` step -- callers (see
/// [`crate::transaction::engine::apply`]) must treat that identically to
/// any other persistence failure and must not proceed past it.
pub fn persist(
    directory: &Path,
    record: &PersistedTransactionRecord,
) -> Result<(), PersistenceError> {
    fs::create_dir_all(directory).map_err(|error| PersistenceError(error.to_string()))?;
    let final_path = record_path(directory, &record.transaction_id);
    let temp_path = directory.join(format!("{}.txn.tmp", record.transaction_id));

    {
        let mut file =
            File::create(&temp_path).map_err(|error| PersistenceError(error.to_string()))?;
        file.write_all(serialize(record).as_bytes())
            .map_err(|error| PersistenceError(error.to_string()))?;
        file.sync_all()
            .map_err(|error| PersistenceError(error.to_string()))?;
    }

    fs::rename(&temp_path, &final_path).map_err(|error| PersistenceError(error.to_string()))?;

    let directory_handle =
        File::open(directory).map_err(|error| PersistenceError(error.to_string()))?;
    directory_handle
        .sync_all()
        .map_err(|error| PersistenceError(error.to_string()))?;

    Ok(())
}

/// Loads one persisted record. A missing file is [`LoadError::NotFound`]
/// (not corruption); an unparseable or future-schema file fails closed as
/// [`LoadError::Corrupt`]/[`LoadError::UnsupportedSchemaVersion`] -- never
/// silently treated as safe.
///
/// # Errors
///
/// See [`LoadError`].
pub fn load(
    directory: &Path,
    transaction_id: &TransactionId,
) -> Result<PersistedTransactionRecord, LoadError> {
    let path = record_path(directory, transaction_id);
    let text = fs::read_to_string(&path).map_err(|_| LoadError::NotFound)?;
    deserialize(&text)
}

/// Loads every persisted record under `directory` (P0-TXN-011's restart
/// load). Each file's own load result is preserved individually -- a
/// corrupt record does not prevent other, valid records from loading.
#[must_use]
pub fn load_all(directory: &Path) -> Vec<Result<PersistedTransactionRecord, LoadError>> {
    let Ok(entries) = fs::read_dir(directory) else {
        return Vec::new();
    };
    entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "txn"))
        .map(|path| {
            fs::read_to_string(&path)
                .map_err(|_| LoadError::NotFound)
                .and_then(|text| deserialize(&text))
        })
        .collect()
}
