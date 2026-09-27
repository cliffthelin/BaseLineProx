//! Layer 1 (pure, no bus required) proof for Wave 1's provider-authorization
//! addition to `authorization.rs` (`GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md`
//! §7/§10/§12; TDD contract §50).
//!
//! Covers: `ProviderAuthorizationRequest::SystemdRestart`'s exact `action_id`/
//! `details` derivation (W1-AUTH-007), that it is disjoint from
//! `PolkitAction` and carries no caller-suppliable field (W1-AUTH-005/006),
//! and the error-category mapping for the mediated provider check
//! (handoff §11).

use std::collections::HashMap;

use guardian_core::authorization::polkit::PolkitAuthorizer;
use guardian_core::authorization::{
    AuthorizationError, AuthorizationOutcome, AuthorizationUnavailableReason, PolkitAction,
    ProviderAuthorizationRequest, ProviderAuthorizer, RestartCapability,
};
use guardian_core::identity::CallerIdentity;
use guardian_testkit::PrivateSessionBus;
use zbus::DBusError;
use zbus::connection as async_connection;

fn cups_request() -> ProviderAuthorizationRequest {
    ProviderAuthorizationRequest::SystemdRestart {
        capability: RestartCapability::new("cups.service"),
    }
}

#[test]
fn action_id_is_the_real_already_shipped_systemd_manage_units_action() {
    assert_eq!(
        cups_request().action_id(),
        "org.freedesktop.systemd1.manage-units"
    );
}

/// W1-AUTH-007/W1-VM-007 correction: `polkit.message` is systemd's own
/// literal, unsubstituted `$(unit)` template -- a fresh runtime capture of
/// the real `CheckAuthorization` request established this (earlier
/// evidence/planning had recorded the interpolated `'cups.service'` form;
/// see `docs/evidence/wave1/` and the governing handoff's correction note).
/// Runtime systemd behavior is authoritative for Wave 1 parity.
#[test]
fn details_carry_exactly_the_four_evidenced_fields_with_evidenced_values() {
    let details = cups_request().details();
    let expected: HashMap<&str, String> = HashMap::from([
        ("unit", "cups.service".to_owned()),
        ("verb", "restart".to_owned()),
        (
            "polkit.message",
            "Authentication is required to restart '$(unit)'.".to_owned(),
        ),
        ("polkit.gettext_domain", "systemd".to_owned()),
    ]);
    assert_eq!(details, expected);
    assert_eq!(
        details.len(),
        4,
        "must be exactly four fields, no more, no fewer"
    );
}

#[test]
fn details_are_derived_only_from_the_capability_unit_name_changes_with_it() {
    let request = ProviderAuthorizationRequest::SystemdRestart {
        capability: RestartCapability::new("other.service"),
    };
    let details = request.details();
    assert_eq!(details.get("unit"), Some(&"other.service".to_owned()));
    // `polkit.message` is the literal, unsubstituted `$(unit)` template
    // (W1-AUTH-007/W1-VM-007 correction, above) -- it is systemd's own
    // fixed wire text, not a Guardian-side interpolation, so it does NOT
    // change with the unit name, unlike `unit` itself.
    assert_eq!(
        details.get("polkit.message"),
        Some(&"Authentication is required to restart '$(unit)'.".to_owned())
    );
    // verb/gettext_domain are fixed regardless of which unit -- the request
    // always represents a restart of *some* governed unit, never another verb.
    assert_eq!(details.get("verb"), Some(&"restart".to_owned()));
    assert_eq!(
        details.get("polkit.gettext_domain"),
        Some(&"systemd".to_owned())
    );
}

/// W1-AUTH-005: source-level, mechanically checkable — no Guardian-owned
/// replacement action for systemd restart exists. `PolkitAction`'s own
/// variant list is unchanged (five variants, none named for systemd).
#[test]
fn polkit_action_gains_no_systemd_restart_variant() {
    let variants = [
        PolkitAction::Read,
        PolkitAction::LowRiskWrite,
        PolkitAction::ModerateWrite,
        PolkitAction::HighRiskWrite,
        PolkitAction::GuardianBoundedWrite,
    ];
    for action in variants {
        assert!(
            !action.action_id().contains("systemd"),
            "no PolkitAction variant may reference systemd: {}",
            action.action_id()
        );
    }
}

/// W1-AUTH-006: source-level check that the disjointness is real, not
/// merely by convention -- the production module text contains no
/// conversion between the two enums.
#[test]
fn no_conversion_exists_between_provider_authorization_request_and_polkit_action() {
    let source = include_str!("../src/authorization.rs");
    assert!(
        !source.contains("impl From<ProviderAuthorizationRequest> for PolkitAction"),
        "ProviderAuthorizationRequest must never convert into a PolkitAction"
    );
    assert!(
        !source.contains("impl From<PolkitAction> for ProviderAuthorizationRequest"),
        "PolkitAction must never convert into a ProviderAuthorizationRequest"
    );
}

/// W1-AUTH-005/007: mechanically checkable — `authorization.rs`'s own
/// source never constructs a `ProviderAuthorizationRequest::details()` or
/// `action_id()` from a `HashMap` parameter reachable from outside this
/// module's own match arms (no generic `details: HashMap<...>` parameter
/// exists anywhere in the enum's public API surface).
#[test]
fn action_id_and_details_take_no_external_parameter() {
    let source = include_str!("../src/authorization.rs");
    // The only place `HashMap` appears as a function *parameter* in this
    // file must be nowhere -- `details()` takes `&self` only.
    assert!(
        source.contains("pub fn action_id(&self) -> &'static str"),
        "action_id must be a pure, parameterless (besides &self) function"
    );
    assert!(
        source.contains("pub fn details(&self) -> HashMap<&'static str, String>"),
        "details must be a pure, parameterless (besides &self) function"
    );
    assert!(
        !source.contains("pub fn authorize_provider(action_id"),
        "no generic authorize_provider(action_id, details, ...) surface may exist"
    );
}

#[test]
fn denied_maps_to_not_authorized_via_provider_request_mapping() {
    let error = AuthorizationOutcome::Denied
        .into_provider_dbus_error(&cups_request())
        .expect("denial must map to a public error");
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );
}

#[test]
fn no_authentication_agent_maps_to_authentication_unavailable_via_provider_request_mapping() {
    let error =
        AuthorizationOutcome::Unavailable(AuthorizationUnavailableReason::NoAuthenticationAgent)
            .into_provider_dbus_error(&cups_request())
            .expect("unavailable must map to a public error");
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.AuthenticationUnavailable"
    );
}

#[test]
fn interaction_disallowed_maps_to_not_authorized_via_provider_request_mapping() {
    let error = AuthorizationOutcome::Unavailable(
        AuthorizationUnavailableReason::InteractionRequiredButDisallowed,
    )
    .into_provider_dbus_error(&cups_request())
    .expect("unavailable-by-policy must map to a public error");
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );
}

#[test]
fn authorized_maps_to_no_error() {
    assert!(
        AuthorizationOutcome::Authorized
            .into_provider_dbus_error(&cups_request())
            .is_none()
    );
}

// --- Layer 2: the real `PolkitAuthorizer::authorize_provider_request`,
// exercised for real against a private test bus with no polkit authority
// service, proving the real production code path (not a hand-built
// `AuthorizationError`) maps an unreachable provider to `ProviderUnavailable`
// -- same discipline as `authorization_contract.rs`'s existing
// `real_polkit_authorizer_maps_unreachable_provider_to_provider_unavailable`. ---

#[test]
fn real_polkit_authorizer_provider_request_maps_unreachable_provider_to_provider_unavailable() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let address = bus.address().to_owned();

    async_io::block_on(async move {
        let connection = async_connection::Builder::address(address.as_str())
            .expect("parse private D-Bus address")
            .build()
            .await
            .expect("connect to private D-Bus");

        let authorizer = PolkitAuthorizer::new(&connection);
        let subject = CallerIdentity::new(":1.1", Some(1000));
        let request = cups_request();

        let result = authorizer
            .authorize_provider_request(&subject, &request, false)
            .await;

        let error = match result {
            Err(error) => error,
            Ok(outcome) => panic!(
                "expected an infrastructure failure against a bus with no polkit service, got {outcome:?}"
            ),
        };
        let dbus_error = error.into_dbus_error();
        assert_eq!(
            dbus_error.name().as_str(),
            "io.github.cliffthelin.Guardian1.Error.ProviderUnavailable",
            "a real unreachable-provider failure must never surface as AuthenticationUnavailable"
        );
    });
}

// --- A deterministic mock `ProviderAuthorizer`, capable of asserting on the
// exact action id/details map it received -- required by the handoff's
// evidence ladder ("a mock capable of asserting on the exact details map it
// received, to catch a future regression to empty/partial details") and
// used to prove the Denied/AuthenticationUnavailable paths deterministically
// without a real bus. ---

struct RecordingMockAuthorizer {
    outcome: AuthorizationOutcome,
    seen_action_id: std::sync::Mutex<Option<String>>,
    seen_details: std::sync::Mutex<Option<HashMap<String, String>>>,
}

impl RecordingMockAuthorizer {
    fn new(outcome: AuthorizationOutcome) -> Self {
        Self {
            outcome,
            seen_action_id: std::sync::Mutex::new(None),
            seen_details: std::sync::Mutex::new(None),
        }
    }
}

impl ProviderAuthorizer for RecordingMockAuthorizer {
    fn authorize_provider_request(
        &self,
        _subject: &CallerIdentity,
        request: &ProviderAuthorizationRequest,
        _interactive: bool,
    ) -> impl std::future::Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send
    {
        *self.seen_action_id.lock().unwrap() = Some(request.action_id().to_owned());
        *self.seen_details.lock().unwrap() = Some(
            request
                .details()
                .into_iter()
                .map(|(k, v)| (k.to_owned(), v))
                .collect(),
        );
        std::future::ready(Ok(self.outcome))
    }
}

#[test]
fn mock_authorizer_observes_the_exact_action_id_and_complete_details() {
    let mock = RecordingMockAuthorizer::new(AuthorizationOutcome::Authorized);
    let subject = CallerIdentity::new(":1.1", Some(1000));
    async_io::block_on(async {
        let outcome = mock
            .authorize_provider_request(&subject, &cups_request(), false)
            .await
            .unwrap();
        assert_eq!(outcome, AuthorizationOutcome::Authorized);
    });

    assert_eq!(
        mock.seen_action_id.lock().unwrap().as_deref(),
        Some("org.freedesktop.systemd1.manage-units")
    );
    let details = mock.seen_details.lock().unwrap().clone().unwrap();
    assert_eq!(
        details.len(),
        4,
        "a future regression to empty/partial details must fail this assertion"
    );
    assert_eq!(details.get("unit"), Some(&"cups.service".to_owned()));
    assert_eq!(details.get("verb"), Some(&"restart".to_owned()));
}

#[test]
fn mock_authorizer_can_deterministically_simulate_denied() {
    let mock = RecordingMockAuthorizer::new(AuthorizationOutcome::Denied);
    let subject = CallerIdentity::new(":1.2", Some(1001));
    let outcome =
        async_io::block_on(mock.authorize_provider_request(&subject, &cups_request(), false))
            .unwrap();
    assert_eq!(outcome, AuthorizationOutcome::Denied);
}

#[test]
fn mock_authorizer_can_deterministically_simulate_authentication_unavailable() {
    let mock = RecordingMockAuthorizer::new(AuthorizationOutcome::Unavailable(
        AuthorizationUnavailableReason::NoAuthenticationAgent,
    ));
    let subject = CallerIdentity::new(":1.3", Some(1002));
    let outcome =
        async_io::block_on(mock.authorize_provider_request(&subject, &cups_request(), true))
            .unwrap();
    assert_eq!(
        outcome,
        AuthorizationOutcome::Unavailable(AuthorizationUnavailableReason::NoAuthenticationAgent)
    );
}
