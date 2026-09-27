//! `TransactionId` — a generated *record* identity, deliberately distinct
//! from `guardian_provider_api`'s dotted-domain *semantic* identity macro
//! (G3 NB-4; G4 handoff §8). A transaction ID answers "which specific
//! attempt is this," not "what capability/provider concept does this
//! name" -- so it is never constructed via `CapabilityId`'s validator.

use std::fmt;
use std::str::FromStr;
use std::sync::atomic::{AtomicU64, Ordering};

static COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransactionIdParseError(String);

impl fmt::Display for TransactionIdParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for TransactionIdParseError {}

/// A `UUIDv4`-*shaped* generated record identity (chosen over a ULID because
/// this gate has no host-clock-ordering requirement for transaction IDs
/// themselves -- ordering is carried by `created_at`/`attempt_started_at`
/// instead, and a UUID avoids any dependency on monotonic clock behavior
/// across restarts). Unique, persistent, stable once created, serializable,
/// never derived from `Vec` position or discovery order.
#[derive(Clone, Debug, Eq, PartialEq, Hash, Ord, PartialOrd)]
pub struct TransactionId(String);

impl TransactionId {
    /// Generates a new, unique `TransactionId`. Not cryptographically
    /// random -- this gate only needs process-local uniqueness, achieved by
    /// mixing a monotonic counter, the process ID, and wall-clock
    /// nanoseconds, which is sufficient for a fixture-only transaction
    /// engine with no concurrent-process identity-collision requirement.
    #[must_use]
    pub fn generate() -> Self {
        let counter = u128::from(COUNTER.fetch_add(1, Ordering::Relaxed));
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |duration| duration.as_nanos());
        let pid = u128::from(std::process::id());
        let mixed =
            nanos ^ (counter << 64) ^ (pid << 32) ^ 0x4000_8000_0000_0000_0000_0000_0000_0000;
        Self(format_uuid_shape(mixed))
    }

    /// # Errors
    ///
    /// Returns [`TransactionIdParseError`] if `value` is not a lowercase
    /// `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` hex-grouped string.
    pub fn new(value: impl Into<String>) -> Result<Self, TransactionIdParseError> {
        let value = value.into();
        validate_uuid_shape(&value)?;
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for TransactionId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl FromStr for TransactionId {
    type Err = TransactionIdParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

fn hex_group(slice: &[u8], out: &mut String) {
    use std::fmt::Write as _;
    for byte in slice {
        let _ = write!(out, "{byte:02x}");
    }
}

fn format_uuid_shape(value: u128) -> String {
    let bytes = value.to_be_bytes();
    let mut out = String::with_capacity(36);
    hex_group(&bytes[0..4], &mut out);
    out.push('-');
    hex_group(&bytes[4..6], &mut out);
    out.push('-');
    hex_group(&bytes[6..8], &mut out);
    out.push('-');
    hex_group(&bytes[8..10], &mut out);
    out.push('-');
    hex_group(&bytes[10..16], &mut out);
    out
}

fn validate_uuid_shape(value: &str) -> Result<(), TransactionIdParseError> {
    let groups: Vec<&str> = value.split('-').collect();
    let expected_lengths = [8usize, 4, 4, 4, 12];
    if groups.len() != expected_lengths.len() {
        return Err(TransactionIdParseError(format!(
            "transaction_id must have 5 hyphen-separated groups: {value}"
        )));
    }
    for (group, expected_len) in groups.iter().zip(expected_lengths) {
        if group.len() != expected_len
            || !group
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        {
            return Err(TransactionIdParseError(format!(
                "transaction_id group {group:?} must be {expected_len} lowercase hex digits"
            )));
        }
    }
    Ok(())
}
