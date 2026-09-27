//! `CapabilityRecord` and its governed value types (TDD contract §10/§11/
//! §19/§21; G3 handoff §5).
//!
//! Two dimensions on `CapabilityRecord` are kept structurally separate and
//! must never be collapsed into one field (G3 handoff §5/§10, repaired
//! after an earlier draft conflated them):
//!
//! - **Dimension A** (`authorization_ownership`): *who owns/performs
//!   authorization for this capability, when that is known?* Wraps the
//!   three-value [`AuthorizationMode`] enum in an explicit [`Knowledge`]
//!   state, because G2's own research inventory proved "we have not
//!   established this yet" is a real, distinct state from any of the three
//!   known architectures.
//! - **Dimension B** (`privilege_requirement`): *what OS-level privilege/
//!   access does the operation itself require, independent of who
//!   authorizes it?*
//!
//! Neither dimension may be inferred from the other. See
//! `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md` for the real
//! research fixture both dimensions are tested against.

use std::collections::BTreeSet;
use std::fmt;
use std::str::FromStr;

use crate::ids::{CapabilityId, ProviderId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizationModeParseError(String);

impl fmt::Display for AuthorizationModeParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for AuthorizationModeParseError {}

/// Exactly the three known authorization architectures G2 established
/// (`docs/adr/ADR-002-guardian-privilege-topology.md`). Answers only "who
/// owns/performs authorization?" -- never "is the current caller
/// authorized?" and never "what OS privilege is required?" (G3 handoff
/// §12). In particular, `GuardianOwnedAuthorization` means only "Guardian
/// owns the authorization *mechanism*" for this capability, never "the
/// current caller passed it" -- that remains the privileged helper's own,
/// independent, per-request responsibility (G2 boundary, unchanged).
///
/// This enum deliberately has no `Unknown` variant: whether the
/// architecture is even established yet is a separate, epistemic question,
/// answered by wrapping this type in [`Knowledge`].
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorizationMode {
    NoAuthorizationRequired,
    ProviderOwnedAuthorization,
    GuardianOwnedAuthorization,
}

impl AuthorizationMode {
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::NoAuthorizationRequired => "no_authorization_required",
            Self::ProviderOwnedAuthorization => "provider_owned_authorization",
            Self::GuardianOwnedAuthorization => "guardian_owned_authorization",
        }
    }
}

impl fmt::Display for AuthorizationMode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

/// An unrecognized/future `AuthorizationMode` wire token fails closed with a
/// typed parse error -- it is never folded into one of the three known
/// states (G3 handoff §10 Rule 1).
impl FromStr for AuthorizationMode {
    type Err = AuthorizationModeParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "no_authorization_required" => Ok(Self::NoAuthorizationRequired),
            "provider_owned_authorization" => Ok(Self::ProviderOwnedAuthorization),
            "guardian_owned_authorization" => Ok(Self::GuardianOwnedAuthorization),
            other => Err(AuthorizationModeParseError(format!(
                "unsupported authorization_mode wire token: {other}"
            ))),
        }
    }
}

/// Whether a value of type `T` is actually known yet, kept structurally
/// distinct from any "safe default" value of `T` itself (G3 handoff §5/§9;
/// repaired to stop `Unknown` from being collapsible into a known state).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Knowledge<T> {
    Known(T),
    Unknown,
}

impl<T: fmt::Display> fmt::Display for Knowledge<T> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Known(value) => write!(formatter, "known:{value}"),
            Self::Unknown => formatter.write_str("unknown"),
        }
    }
}

impl Knowledge<AuthorizationMode> {
    /// Parses the wire form produced by [`fmt::Display`]. `"unknown"`
    /// (Rule 2 -- a legitimate, cleanly-deserializing epistemic state)
    /// deserializes to `Self::Unknown` without error. Any other value must
    /// be `"known:<AuthorizationMode wire token>"`; an unrecognized inner
    /// token fails closed through [`AuthorizationMode::from_str`]'s typed
    /// parse error (Rule 1) -- it is never silently accepted as `Unknown`.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorizationModeParseError`] for any value that is
    /// neither `"unknown"` nor `"known:<valid token>"`.
    pub fn parse_wire(value: &str) -> Result<Self, AuthorizationModeParseError> {
        if value == "unknown" {
            return Ok(Self::Unknown);
        }
        let Some(payload) = value.strip_prefix("known:") else {
            return Err(AuthorizationModeParseError(format!(
                "unsupported authorization_ownership wire value: {value}"
            )));
        };
        AuthorizationMode::from_str(payload).map(Self::Known)
    }
}

/// Dimension B: what OS-level privilege/access the capability's operation
/// itself requires, independent of who authorizes it (G3 handoff §5/§9).
/// Reuses the exact category names from
/// `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`. Unlike
/// [`AuthorizationMode`], `Unknown` here *is* a governed runtime variant --
/// the G2 inventory has real rows this pass never researched, and that is
/// legitimate information rather than an error condition, so an
/// unrecognized wire token deserializes cleanly to `Unknown` rather than
/// failing.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrivilegeRequirement {
    NoDirectPrivilege,
    SpecificFileOrDeviceAccess,
    SpecificLinuxCapability,
    RootOrSystemPrivilege,
    Unknown,
}

impl PrivilegeRequirement {
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::NoDirectPrivilege => "no_direct_privilege",
            Self::SpecificFileOrDeviceAccess => "specific_file_or_device_access",
            Self::SpecificLinuxCapability => "specific_linux_capability",
            Self::RootOrSystemPrivilege => "root_or_system_privilege",
            Self::Unknown => "unknown",
        }
    }
}

impl fmt::Display for PrivilegeRequirement {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

impl FromStr for PrivilegeRequirement {
    type Err = std::convert::Infallible;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(match value {
            "no_direct_privilege" => Self::NoDirectPrivilege,
            "specific_file_or_device_access" => Self::SpecificFileOrDeviceAccess,
            "specific_linux_capability" => Self::SpecificLinuxCapability,
            "root_or_system_privilege" => Self::RootOrSystemPrivilege,
            _ => Self::Unknown,
        })
    }
}

/// TDD contract §11. `Unknown` MUST NOT behave as, or be rendered as,
/// `Available` -- [`Self::is_usable`] makes that a checked behavioral
/// property rather than only a value-equality one.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Availability {
    Available,
    Degraded,
    Unavailable,
    Unsupported,
    Unknown,
}

impl Availability {
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Degraded => "degraded",
            Self::Unavailable => "unavailable",
            Self::Unsupported => "unsupported",
            Self::Unknown => "unknown",
        }
    }

    /// `false` for every state except `Available` -- in particular,
    /// `Unknown` is never treated as usable/healthy (TDD contract §11).
    #[must_use]
    pub const fn is_usable(self) -> bool {
        matches!(self, Self::Available)
    }
}

impl fmt::Display for Availability {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

impl FromStr for Availability {
    type Err = std::convert::Infallible;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(match value {
            "available" => Self::Available,
            "degraded" => Self::Degraded,
            "unavailable" => Self::Unavailable,
            "unsupported" => Self::Unsupported,
            _ => Self::Unknown,
        })
    }
}

/// TDD contract §11 ("Recommended" set) -- preserved in full; no narrowing
/// was found necessary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Health {
    Healthy,
    Warning,
    Error,
    Stale,
    Unknown,
}

impl Health {
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Warning => "warning",
            Self::Error => "error",
            Self::Stale => "stale",
            Self::Unknown => "unknown",
        }
    }
}

impl fmt::Display for Health {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

impl FromStr for Health {
    type Err = std::convert::Infallible;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(match value {
            "healthy" => Self::Healthy,
            "warning" => Self::Warning,
            "error" => Self::Error,
            "stale" => Self::Stale,
            _ => Self::Unknown,
        })
    }
}

/// A provider-level health snapshot -- reuses [`Health`] rather than a
/// second, competing enum (`Provider::health()`, TDD contract §12).
pub type ProviderHealth = Health;

/// TDD contract §21. A capability may become available at more than one
/// lifecycle point, so this is a set, not a single value.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub enum BootAvailability {
    EarlyBoot,
    SystemBus,
    PreLogin,
    UserSession,
    DesktopOnly,
    Optional,
}

impl BootAvailability {
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::EarlyBoot => "early_boot",
            Self::SystemBus => "system_bus",
            Self::PreLogin => "pre_login",
            Self::UserSession => "user_session",
            Self::DesktopOnly => "desktop_only",
            Self::Optional => "optional",
        }
    }
}

impl fmt::Display for BootAvailability {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.wire_token())
    }
}

/// A stable, deterministic (`BTreeSet`-ordered) set of boot-availability
/// levels a capability may declare simultaneously.
pub type BootAvailabilitySet = BTreeSet<BootAvailability>;

/// TDD contract §19 diagnostic cost classes, reused here only as a typed
/// placeholder field on [`CapabilityRecord`] -- G5's Diagnostic Budget
/// Manager owns the veto/scheduling logic; G3 only ensures the field is a
/// real type, not a raw untyped number, so G5 can extend it later without a
/// breaking replacement.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum CostLevel {
    #[default]
    Negligible,
    Low,
    Moderate,
    High,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct DiagnosticCost {
    pub cpu_cost: CostLevel,
    pub memory_cost: CostLevel,
    pub io_read_cost: CostLevel,
    pub io_write_cost: CostLevel,
    pub kernel_trace_cost: CostLevel,
    pub expected_duration_ms: Option<u64>,
}

/// TDD contract §6's source-authority hierarchy, reused as a typed field so
/// `CapabilityRecord.interface_kind` cannot silently become a free-form
/// string. Rank indicates authority/preference, not automatic correctness
/// (governing brief §22) -- a lower-ranked source is not presumed false.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InterfaceKind {
    DBus,
    KernelInterface,
    StructuredCli,
    ScrapedCli,
    Unknown,
}

/// The canonical typed capability representation (TDD contract §11).
///
/// `capability_id` and `provider_id` are independent [`CapabilityId`]/
/// [`ProviderId`] values -- changing which provider realizes a capability
/// must never change `capability_id` (G3 handoff §4/§6/§7).
#[derive(Clone, Debug, PartialEq)]
pub struct CapabilityRecord {
    pub capability_id: CapabilityId,
    pub provider_id: ProviderId,
    pub provider_version: Option<String>,
    pub availability: Availability,
    pub health: Health,
    pub read_support: bool,
    pub write_support: bool,
    pub authorization_ownership: Knowledge<AuthorizationMode>,
    pub privilege_requirement: PrivilegeRequirement,
    pub boot_availability: BootAvailabilitySet,
    pub interface_kind: InterfaceKind,
    pub interface_name: Option<String>,
    pub interface_hash: Option<String>,
    pub diagnostic_cost: DiagnosticCost,
    pub last_observed_at: String,
}

impl CapabilityRecord {
    /// Returns a copy of this record with `provider_id` (and, optionally,
    /// `provider_version`) replaced -- `capability_id` is untouched by
    /// construction, proving the two identities cannot drift together.
    #[must_use]
    pub fn with_provider(&self, provider_id: ProviderId) -> Self {
        Self {
            provider_id,
            ..self.clone()
        }
    }
}
