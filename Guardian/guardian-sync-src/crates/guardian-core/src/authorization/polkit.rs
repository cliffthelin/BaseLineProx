//! Real polkit-backed [`Authorizer`], calling `org.freedesktop.PolicyKit1.Authority`
//! over whatever [`zbus::Connection`] it is given.
//!
//! This is genuine production code, not a placeholder: it performs the real
//! `CheckAuthorization` D-Bus call. Whether it observes *real* polkit
//! behavior depends on which connection it is given — a private test bus has
//! no polkit authority service to answer it, so this authorizer is only
//! meaningfully exercised against the real system bus (Layer 2).

use std::collections::HashMap;

use zbus::Connection;
use zbus::zvariant::Value;

use super::{
    AuthorizationError, AuthorizationOutcome, AuthorizationRequest, AuthorizationUnavailableReason,
    Authorizer, ProviderAuthorizationRequest, ProviderAuthorizer,
};
use crate::identity::CallerIdentity;

const ALLOW_USER_INTERACTION: u32 = 0x01;

#[zbus::proxy(
    default_service = "org.freedesktop.PolicyKit1",
    default_path = "/org/freedesktop/PolicyKit1/Authority",
    interface = "org.freedesktop.PolicyKit1.Authority",
    gen_blocking = false
)]
trait PolicyKitAuthority {
    #[zbus(name = "CheckAuthorization")]
    #[allow(clippy::too_many_arguments)]
    fn check_authorization(
        &self,
        subject: (&str, HashMap<&str, Value<'_>>),
        action_id: &str,
        details: HashMap<&str, &str>,
        flags: u32,
        cancellation_id: &str,
    ) -> zbus::Result<(bool, bool, HashMap<String, String>)>;
}

/// Authorizes G1 test actions against the real system polkit authority on
/// `connection`.
pub struct PolkitAuthorizer<'c> {
    connection: &'c Connection,
}

impl<'c> PolkitAuthorizer<'c> {
    #[must_use]
    pub const fn new(connection: &'c Connection) -> Self {
        Self { connection }
    }
}

impl PolkitAuthorizer<'_> {
    /// Private, low-level `CheckAuthorization` transport shared by both
    /// public entry points ([`Authorizer::authorize`] and
    /// [`ProviderAuthorizer::authorize_provider_request`]). This is
    /// deliberately **not** part of this module's public API — it is not a
    /// trusted callable boundary and must never become one: both callers
    /// above construct `action_id`/`details` entirely from their own closed,
    /// typed inputs (a fixed [`crate::authorization::PolkitAction`]
    /// action-id constant with an empty map, or
    /// [`ProviderAuthorizationRequest`]'s own internally-derived action
    /// id/details) before this function ever sees them — nothing here
    /// accepts a caller-supplied action id or detail map from outside this
    /// module (handoff §7/§10).
    async fn check_authorization_raw(
        &self,
        subject: &CallerIdentity,
        action_id: &str,
        details: HashMap<&str, &str>,
        interactive: bool,
    ) -> Result<AuthorizationOutcome, AuthorizationError> {
        // Failing to even construct the proxy means Guardian cannot reach
        // the polkit authority at all — an infrastructure failure, never an
        // authorization decision about the caller.
        let proxy = PolicyKitAuthorityProxy::new(self.connection)
            .await
            .map_err(|error| {
                AuthorizationError::ProviderUnavailable(format!(
                    "could not construct PolicyKit1 Authority proxy: {error}"
                ))
            })?;

        let mut subject_details = HashMap::new();
        subject_details.insert("name", Value::from(subject.unique_name()));
        let flags = if interactive {
            ALLOW_USER_INTERACTION
        } else {
            0
        };

        let result = proxy
            .check_authorization(
                ("system-bus-name", subject_details),
                action_id,
                details,
                flags,
                "",
            )
            .await;

        // `is_challenge` means polkit determined interactive authentication
        // is required to decide this action, and could not be resolved
        // within this call. Which typed outcome that maps to depends on
        // which flag *we* asked for: a non-interactive request that hits a
        // challenge is exactly P0-AUTH-003's "background action cannot
        // prompt" case; an interactive request that still comes back as a
        // challenge means no agent completed it (not registered, or the
        // call returned before the agent could answer).
        //
        // A transport-level `Err` here is not a decision about the caller
        // at all — CheckAuthorization itself could not be completed (the
        // service went away, the call timed out, the response could not be
        // parsed). That is the same class of failure as the proxy failing
        // to construct above, so it maps to the same `ProviderUnavailable`
        // infrastructure error, never to `AuthenticationUnavailable`.
        match result {
            Ok((true, _, _)) => Ok(AuthorizationOutcome::Authorized),
            Ok((false, true, _)) if !interactive => Ok(AuthorizationOutcome::Unavailable(
                AuthorizationUnavailableReason::InteractionRequiredButDisallowed,
            )),
            Ok((false, true, _)) => Ok(AuthorizationOutcome::Unavailable(
                AuthorizationUnavailableReason::NoAuthenticationAgent,
            )),
            Ok((false, false, _)) => Ok(AuthorizationOutcome::Denied),
            Err(error) => Err(AuthorizationError::ProviderUnavailable(format!(
                "CheckAuthorization failed: {error}"
            ))),
        }
    }
}

impl Authorizer for PolkitAuthorizer<'_> {
    async fn authorize(
        &self,
        request: &AuthorizationRequest,
    ) -> Result<AuthorizationOutcome, AuthorizationError> {
        // Every existing `PolkitAction` call site keeps its current
        // empty-details behavior, unchanged (handoff §7/§10).
        self.check_authorization_raw(
            request.subject(),
            request.action().action_id(),
            HashMap::new(),
            request.interactive(),
        )
        .await
    }
}

impl ProviderAuthorizer for PolkitAuthorizer<'_> {
    async fn authorize_provider_request(
        &self,
        subject: &CallerIdentity,
        request: &ProviderAuthorizationRequest,
        interactive: bool,
    ) -> Result<AuthorizationOutcome, AuthorizationError> {
        let owned_details = request.details();
        let details: HashMap<&str, &str> = owned_details
            .iter()
            .map(|(key, value)| (*key, value.as_str()))
            .collect();
        self.check_authorization_raw(subject, request.action_id(), details, interactive)
            .await
    }
}
