//! Provider-facing public contract records for G0 and G3.

pub mod capability;
pub mod ids;
pub mod provider;

pub use capability::{
    AuthorizationMode, AuthorizationModeParseError, Availability, BootAvailability,
    BootAvailabilitySet, CapabilityRecord, CostLevel, DiagnosticCost, Health, InterfaceKind,
    Knowledge, PrivilegeRequirement, ProviderHealth,
};
pub use ids::{CapabilityId, EventId, IdParseError, IncidentId, ProviderId};
pub use provider::{
    ActionRequest, ApplyOutcome, InspectionSnapshot, MutableCapabilityAdapter,
    ObservationExpectation, ObservationOutcome, ProbeResult, Provider, ProviderIdentity,
    RawProviderEvent, RollbackOutcome, StateSnapshot, Unsupported, ValidationResult,
};

use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fmt;
use std::str::FromStr;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderProvenance {
    pub provider_id: String,
    pub package_name: Option<String>,
    pub package_version: Option<String>,
    pub interface_name: Option<String>,
    pub interface_version: Option<String>,
    pub introspection_hash: Option<String>,
    pub policy_hash: Option<String>,
    pub observed_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProvenanceParseError(String);

impl fmt::Display for ProvenanceParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for ProvenanceParseError {}

impl FromStr for ProviderProvenance {
    type Err = ProvenanceParseError;

    fn from_str(manifest: &str) -> Result<Self, Self::Err> {
        let fields: HashMap<_, _> = manifest
            .lines()
            .map(str::trim)
            .filter(|line| !line.is_empty() && !line.starts_with('#'))
            .map(|line| {
                line.split_once('=')
                    .map(|(key, value)| (key.trim(), value.trim()))
                    .ok_or_else(|| ProvenanceParseError(format!("invalid provenance line: {line}")))
            })
            .collect::<Result<_, _>>()?;
        let required = |key: &str| {
            fields
                .get(key)
                .copied()
                .ok_or_else(|| ProvenanceParseError(format!("missing provenance field: {key}")))
        };
        let optional = |key: &str| -> Result<Option<String>, ProvenanceParseError> {
            let value = required(key)?;
            Ok((value != "unknown").then(|| value.to_owned()))
        };

        Ok(Self {
            provider_id: required("provider_id")?.to_owned(),
            package_name: optional("package_name")?,
            package_version: optional("package_version")?,
            interface_name: optional("interface_name")?,
            interface_version: optional("interface_version")?,
            introspection_hash: optional("introspection_hash")?,
            policy_hash: optional("policy_hash")?,
            observed_at: required("observed_at")?.to_owned(),
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriftStatus {
    Match,
    Drift,
    Missing,
    Invalid,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriftResult {
    pub provider_id: String,
    pub status: DriftStatus,
    pub expected_hash: String,
    pub observed_hash: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractSnapshot {
    provider_id: String,
    expected_hash: String,
}

impl ContractSnapshot {
    #[must_use]
    pub fn from_bytes(provider_id: impl Into<String>, contract: &[u8]) -> Self {
        Self::from_hash(provider_id, Self::sha256(contract))
    }

    #[must_use]
    pub fn from_hash(provider_id: impl Into<String>, expected_hash: impl Into<String>) -> Self {
        Self {
            provider_id: provider_id.into(),
            expected_hash: expected_hash.into(),
        }
    }

    #[must_use]
    pub fn sha256(contract: &[u8]) -> String {
        format!("{:x}", Sha256::digest(contract))
    }

    #[must_use]
    pub fn compare(&self, observed: Option<&[u8]>) -> DriftResult {
        if !is_sha256(&self.expected_hash) {
            return self.result(DriftStatus::Invalid, None);
        }
        let Some(observed) = observed else {
            return self.result(DriftStatus::Missing, None);
        };
        let observed_hash = Self::sha256(observed);
        let status = if observed_hash == self.expected_hash {
            DriftStatus::Match
        } else {
            DriftStatus::Drift
        };
        self.result(status, Some(observed_hash))
    }

    fn result(&self, status: DriftStatus, observed_hash: Option<String>) -> DriftResult {
        DriftResult {
            provider_id: self.provider_id.clone(),
            status,
            expected_hash: self.expected_hash.clone(),
            observed_hash,
        }
    }
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
