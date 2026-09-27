//! Authorization request/decision abstractions for G1 — Identity & Authorization.
//!
//! Every authorization outcome maps to one of the 17 existing
//! [`crate::error::GuardianDbusError`] categories
//! (`docs/guardian/30_TDD/GUARDIAN_G1_IMPLEMENTATION_HANDOFF.md` §6). No new
//! public error category is introduced here.

pub mod polkit;

use std::collections::HashMap;
use std::future::Future;

use crate::error::{GuardianDbusError, GuardianErrorCategory};
use crate::identity::CallerIdentity;

/// The four G1 test-only polkit actions (TDD contract §9), plus G7's one
/// real production Class A action (`guardian-helper`'s sole bounded write —
/// ADR-002's Privilege Requirement Inventory: "1 is Guardian's own bounded
/// polkit-gated action"). Each later gate that adds a genuinely new
/// polkit-gated operation gets its own variant here; this enum does not
/// become a generic action-name carrier.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolkitAction {
    Read,
    LowRiskWrite,
    ModerateWrite,
    HighRiskWrite,
    /// G7's Class A Guardian-owned privileged mutation, authorized entirely
    /// inside `guardian-helper` (G7 implementation handoff §2.3/§2.5).
    GuardianBoundedWrite,
}

impl PolkitAction {
    /// The exact polkit action identifier, as fixed by TDD contract §9 (the
    /// four `guardian.test.*` actions) and by the G7 implementation handoff
    /// §9 for `GuardianBoundedWrite`.
    #[must_use]
    pub const fn action_id(self) -> &'static str {
        match self {
            Self::Read => "guardian.test.read",
            Self::LowRiskWrite => "guardian.test.low-risk-write",
            Self::ModerateWrite => "guardian.test.moderate-write",
            Self::HighRiskWrite => "guardian.test.high-risk-write",
            Self::GuardianBoundedWrite => "io.github.cliffthelin.guardian.g7.bounded-write",
        }
    }
}

/// A bounded authorization request.
///
/// Carries only the real, resolved caller identity and the action/interactive
/// flag Guardian itself determined — there is no field here for a
/// client-supplied UID, PID, username, role, or `is_admin` claim to occupy.
/// This is a structural (type-level) guarantee, not merely a runtime check:
/// nothing a client sends as method arguments can reach this struct except
/// through [`CallerIdentity`], which is itself only constructed by
/// [`crate::identity::resolve_caller_identity`] from the real bus sender.
#[derive(Clone, Debug)]
pub struct AuthorizationRequest {
    subject: CallerIdentity,
    action: PolkitAction,
    interactive: bool,
}

impl AuthorizationRequest {
    #[must_use]
    pub const fn new(subject: CallerIdentity, action: PolkitAction, interactive: bool) -> Self {
        Self {
            subject,
            action,
            interactive,
        }
    }

    #[must_use]
    pub const fn subject(&self) -> &CallerIdentity {
        &self.subject
    }

    #[must_use]
    pub const fn action(&self) -> PolkitAction {
        self.action
    }

    /// Whether this request came from an explicit, user-initiated action and
    /// may therefore enter an interactive authentication flow. A background
    /// or automated code path must always construct this as `false`
    /// (TDD contract §8.3; P0-AUTH-003).
    #[must_use]
    pub const fn interactive(&self) -> bool {
        self.interactive
    }
}

/// Why an [`AuthorizationOutcome::Unavailable`] result occurred.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorizationUnavailableReason {
    /// The request was non-interactive but the action requires interactive
    /// authentication to proceed. The request fails closed rather than
    /// prompting (P0-AUTH-003).
    InteractionRequiredButDisallowed,
    /// Interactive authentication was allowed for this request, but no usable
    /// authentication mechanism/agent is available to complete it.
    NoAuthenticationAgent,
}

/// The internal authorization result, before mapping to the public typed
/// error a caller actually receives.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorizationOutcome {
    /// The action is authorized; the caller may proceed.
    Authorized,
    /// The action was explicitly denied.
    Denied,
    /// Authorization could not be completed for a reason unrelated to an
    /// explicit denial — see [`AuthorizationUnavailableReason`].
    Unavailable(AuthorizationUnavailableReason),
}

impl AuthorizationOutcome {
    /// Maps this outcome to the public typed error a denied/unavailable
    /// caller receives, per the G1 handoff §6 mapping. Returns `None` when
    /// authorized — callers proceed to the bounded action in that case.
    #[must_use]
    pub fn into_dbus_error(self, action: PolkitAction) -> Option<GuardianDbusError> {
        match self {
            Self::Authorized => None,
            Self::Denied => Some(
                GuardianErrorCategory::NotAuthorized
                    .with_message(format!("authorization denied for {}", action.action_id())),
            ),
            Self::Unavailable(AuthorizationUnavailableReason::InteractionRequiredButDisallowed) => {
                Some(GuardianErrorCategory::NotAuthorized.with_message(format!(
                    "interaction-required-but-disallowed for {}",
                    action.action_id()
                )))
            }
            Self::Unavailable(AuthorizationUnavailableReason::NoAuthenticationAgent) => Some(
                GuardianErrorCategory::AuthenticationUnavailable.with_message(format!(
                    "no authentication mechanism available for {}",
                    action.action_id()
                )),
            ),
        }
    }

    /// The [`ProviderAuthorizationRequest`] counterpart to
    /// [`Self::into_dbus_error`] — identical mapping (G1's 17-category
    /// taxonomy is reused unmodified; handoff §11), keyed on the mediated
    /// provider action id rather than a [`PolkitAction`].
    #[must_use]
    pub fn into_provider_dbus_error(
        self,
        request: &ProviderAuthorizationRequest,
    ) -> Option<GuardianDbusError> {
        match self {
            Self::Authorized => None,
            Self::Denied => Some(
                GuardianErrorCategory::NotAuthorized
                    .with_message(format!("authorization denied for {}", request.action_id())),
            ),
            Self::Unavailable(AuthorizationUnavailableReason::InteractionRequiredButDisallowed) => {
                Some(GuardianErrorCategory::NotAuthorized.with_message(format!(
                    "interaction-required-but-disallowed for {}",
                    request.action_id()
                )))
            }
            Self::Unavailable(AuthorizationUnavailableReason::NoAuthenticationAgent) => Some(
                GuardianErrorCategory::AuthenticationUnavailable.with_message(format!(
                    "no authentication mechanism available for {}",
                    request.action_id()
                )),
            ),
        }
    }
}

/// A failure to *obtain* an authorization decision at all — deliberately
/// distinct from every [`AuthorizationOutcome`] variant, none of which
/// represent a failure of the authorization mechanism itself.
///
/// This is the type that keeps "the provider couldn't be reached" from ever
/// being silently reinterpreted as "no authentication agent is available"
/// (a real [`AuthorizationOutcome::Unavailable`]) or any other decision —
/// the two are different in kind, not just in severity, and mixing them
/// would let a real polkit/D-Bus outage present itself to a caller as an
/// ordinary authentication-related outcome.
#[derive(Debug)]
pub enum AuthorizationError {
    /// The authorization provider (real polkit, for [`polkit::PolkitAuthorizer`])
    /// could not be reached or used to obtain a decision: the service is
    /// unavailable, the D-Bus transport failed, the proxy could not be
    /// constructed, or the provider's response could not be interpreted.
    /// This is never a decision about the caller — it is Guardian being
    /// unable to ask the question at all.
    ProviderUnavailable(String),
    /// A genuine internal Guardian invariant or programming failure, not a
    /// provider-availability problem. Reserved for authorizer implementations
    /// that can distinguish "my own logic is broken" from "the provider is
    /// unreachable" — [`polkit::PolkitAuthorizer`] does not currently produce
    /// this variant, since every failure mode it can observe is a provider
    /// problem, not an internal one.
    Internal(String),
}

impl AuthorizationError {
    /// Maps this infrastructure failure to the corresponding existing typed
    /// error. Always produces an error — an [`AuthorizationError`] is never
    /// a "proceed" case, unlike [`AuthorizationOutcome`].
    #[must_use]
    pub fn into_dbus_error(self) -> GuardianDbusError {
        match self {
            Self::ProviderUnavailable(message) => {
                GuardianErrorCategory::ProviderUnavailable.with_message(message)
            }
            Self::Internal(message) => GuardianErrorCategory::Internal.with_message(message),
        }
    }
}

/// A pluggable authorization decision source.
///
/// Production code uses [`polkit::PolkitAuthorizer`], backed by the real
/// system polkit authority. Tests use a deterministic test double to prove
/// the surrounding plumbing (ordering, error mapping, interactive-flag
/// routing) without requiring a real bus or root.
pub trait Authorizer {
    /// Decides the outcome for `request`, or reports that no decision could
    /// be obtained at all (see [`AuthorizationError`]). Must not have any
    /// observable side effect on Guardian's own state either way — only the
    /// caller, after inspecting `Ok(AuthorizationOutcome::Authorized)`, may
    /// cause a mutation (TDD contract GP-05/GP-06; G1 handoff §7).
    fn authorize(
        &self,
        request: &AuthorizationRequest,
    ) -> impl Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send;
}

// ---------------------------------------------------------------------------
// Wave 1 (TDD contract §50; `GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md` §7/§10)
// ---------------------------------------------------------------------------
//
// `PolkitAction` above remains reserved for Guardian-owned decisions only —
// nothing below adds a variant to it, and nothing below is a generic
// action-id/detail-map broker. `ProviderAuthorizationRequest` is a closed,
// disjoint representation of a *provider-owned* policy decision Guardian
// mediates on a resolved caller's behalf: each variant derives both its
// action id and its complete authorization details internally, from an
// already-resolved, Guardian-controlled capability row — never from caller
// input, and never as an open `details: HashMap<String, String>`-shaped
// parameter reachable from outside this module's own construction of the
// request.

/// A resolved, already-validated Wave 1 restart-capability row.
///
/// Carries only the canonical systemd unit name a Guardian-compiled/
/// configured capability table (`guardian-helper`'s own, §10) has already
/// resolved from a `capability_id` — this type is never constructed from a
/// caller-supplied unit name, and nothing here accepts one. It exists here,
/// in `authorization.rs`, only because [`ProviderAuthorizationRequest`]
/// needs a concrete, typed field to derive its action id/details from.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RestartCapability {
    unit_name: String,
}

impl RestartCapability {
    /// Constructs a resolved capability row from an already-governed unit
    /// name (e.g. the single `cups-restart` → `cups.service` row in
    /// `guardian-helper`'s own compiled/configured capability table).
    #[must_use]
    pub fn new(unit_name: impl Into<String>) -> Self {
        Self {
            unit_name: unit_name.into(),
        }
    }

    #[must_use]
    pub fn unit_name(&self) -> &str {
        &self.unit_name
    }
}

/// A provider-owned authorization request Guardian mediates on a resolved
/// caller's behalf — disjoint from [`PolkitAction`], which is reserved for
/// Guardian-owned decisions only. Each variant represents one real,
/// already-shipped provider operation; both its action id and its complete
/// authorization details are derived entirely from the already-resolved,
/// Guardian-controlled capability carried inside it — never from caller
/// input, and never as an open detail map (handoff §7, corrected four
/// times; TDD contract §50's relay-authorization rule).
#[derive(Clone, Debug)]
pub enum ProviderAuthorizationRequest {
    /// systemd's own real `manage-units` request for a Wave 1
    /// `RestartCapability` row.
    SystemdRestart { capability: RestartCapability },
}

impl ProviderAuthorizationRequest {
    /// The provider's own real, already-shipped polkit action id — never a
    /// caller-supplied or otherwise dynamically constructed string
    /// (W1-AUTH-005/W1-AUTH-007).
    #[must_use]
    pub fn action_id(&self) -> &'static str {
        match self {
            Self::SystemdRestart { .. } => "org.freedesktop.systemd1.manage-units",
        }
    }

    /// The complete, real authorization details systemd itself sends for
    /// this exact request — all four evidenced fields (handoff §7's
    /// "fidelity floor, not ceiling"), derived from `capability` alone, with
    /// no other parameter available to influence them (W1-AUTH-007).
    ///
    /// **Correction (W1-AUTH-007/W1-VM-007 re-capture)**: `polkit.message`
    /// is systemd's own literal, unsubstituted `"Authentication is required
    /// to restart '$(unit)'."` template — not a Guardian-side interpolation
    /// of the unit name. A fresh runtime interception of systemd's real
    /// `CheckAuthorization` request for `manage-units` established this;
    /// earlier Wave 1 evidence/planning had recorded the interpolated form
    /// (e.g. `'cups.service'`), which this corrects. Runtime systemd
    /// behavior is authoritative for Wave 1 parity — see
    /// `docs/evidence/wave1/` and the governing handoff/contract text for
    /// the full correction note. Guardian must reproduce the literal
    /// template unchanged; substituting `$(unit)` is polkit's own job (its
    /// agent performs the substitution when displaying the prompt), not
    /// something any caller of this mediated path may do.
    #[must_use]
    pub fn details(&self) -> HashMap<&'static str, String> {
        match self {
            Self::SystemdRestart { capability } => HashMap::from([
                ("unit", capability.unit_name().to_owned()),
                ("verb", "restart".to_owned()),
                (
                    "polkit.message",
                    "Authentication is required to restart '$(unit)'.".to_owned(),
                ),
                ("polkit.gettext_domain", "systemd".to_owned()),
            ]),
        }
    }
}

/// A pluggable provider-authorization decision source — the
/// [`ProviderAuthorizationRequest`] counterpart to [`Authorizer`]. Kept as a
/// separate trait (rather than a new [`Authorizer`] method) so
/// [`Authorizer::authorize`]'s existing signature, and every existing
/// [`PolkitAction`] call site's empty-details behavior, remains completely
/// untouched.
///
/// Production code uses [`polkit::PolkitAuthorizer`]. Tests use a
/// deterministic test double capable of asserting on the exact action
/// id/details map it received, to catch a future regression to empty or
/// partial details.
pub trait ProviderAuthorizer {
    /// Decides the outcome of mediating `request` for `subject` — the real,
    /// resolved original caller, never `guardian-helper`'s own identity
    /// (W1-AUTH-001/W1-AUTH-004).
    fn authorize_provider_request(
        &self,
        subject: &CallerIdentity,
        request: &ProviderAuthorizationRequest,
        interactive: bool,
    ) -> impl Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send;
}
