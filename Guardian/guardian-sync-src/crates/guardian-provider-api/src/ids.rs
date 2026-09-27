//! Stable, structurally distinct identifier types for G3 core data models.
//!
//! `CapabilityId` and `ProviderId` are separate types precisely so a
//! capability's identity can never be confused with, or derived from, the
//! identity of whatever provider currently realizes it (TDD contract §11/
//! §13; G3 handoff §4/§6). Neither type may be constructed from the other,
//! from discovery order, from a UI label, or from a runtime-generated UUID
//! -- construction only accepts an explicit, caller-supplied dotted-domain
//! string.

use std::fmt;
use std::str::FromStr;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IdParseError(String);

impl fmt::Display for IdParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for IdParseError {}

fn validate(kind: &str, value: &str) -> Result<(), IdParseError> {
    if value.is_empty() {
        return Err(IdParseError(format!("{kind} must not be empty")));
    }
    let segments_valid = value.split('.').all(|segment| {
        !segment.is_empty()
            && segment
                .chars()
                .next()
                .is_some_and(|first| first.is_ascii_lowercase())
            && segment
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
    });
    if !segments_valid {
        return Err(IdParseError(format!(
            "{kind} must be lowercase dotted segments starting with a letter, each \
             containing only [a-z0-9-]: {value}"
        )));
    }
    Ok(())
}

macro_rules! stable_id {
    ($name:ident, $kind:literal) => {
        #[doc = concat!("A stable, validated ", $kind, " identifier.")]
        #[derive(Clone, Debug, Eq, PartialEq, Hash, Ord, PartialOrd)]
        pub struct $name(String);

        impl $name {
            /// # Errors
            ///
            /// Returns [`IdParseError`] if `value` is not a lowercase,
            /// dotted, letter-led identifier.
            pub fn new(value: impl Into<String>) -> Result<Self, IdParseError> {
                let value = value.into();
                validate($kind, &value)?;
                Ok(Self(value))
            }

            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }

        impl FromStr for $name {
            type Err = IdParseError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                Self::new(value)
            }
        }
    };
}

stable_id!(CapabilityId, "capability_id");
stable_id!(ProviderId, "provider_id");
stable_id!(EventId, "event_id");
stable_id!(IncidentId, "incident_id");
