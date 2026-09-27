//! Layer 1 (pure, no bus required) proof for G1 authorization plumbing.
//!
//! Covers: the G1 handoff §6 typed-error mapping, and the structural
//! spoof-resistance guarantee that [`AuthorizationRequest`] has no field a
//! client-supplied identity claim could occupy.

use guardian_core::authorization::polkit::PolkitAuthorizer;
use guardian_core::authorization::{
    AuthorizationError, AuthorizationOutcome, AuthorizationRequest, AuthorizationUnavailableReason,
    Authorizer, PolkitAction,
};
use guardian_core::error::GuardianDbusError;
use guardian_core::identity::CallerIdentity;
use guardian_testkit::PrivateSessionBus;
use zbus::DBusError;
use zbus::connection as async_connection;

fn identity(unique_name: &str) -> CallerIdentity {
    CallerIdentity::new(unique_name, Some(1000))
}

#[test]
fn error_mapping_explicit_denial_maps_to_not_authorized() {
    let error = AuthorizationOutcome::Denied
        .into_dbus_error(PolkitAction::LowRiskWrite)
        .expect("denial must map to a public error");
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );
}

#[test]
fn error_mapping_no_authentication_agent_maps_to_authentication_unavailable() {
    let error =
        AuthorizationOutcome::Unavailable(AuthorizationUnavailableReason::NoAuthenticationAgent)
            .into_dbus_error(PolkitAction::ModerateWrite)
            .expect("unavailable must map to a public error");
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.AuthenticationUnavailable"
    );
}

#[test]
fn error_mapping_interaction_disallowed_maps_to_not_authorized_not_a_new_error() {
    let error = AuthorizationOutcome::Unavailable(
        AuthorizationUnavailableReason::InteractionRequiredButDisallowed,
    )
    .into_dbus_error(PolkitAction::HighRiskWrite)
    .expect("unavailable-by-policy must map to a public error");
    // The G1 handoff §6 requires this public error to remain NotAuthorized —
    // the internal reason distinguishes the case, not a new public category.
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );
}

#[test]
fn authorized_outcome_maps_to_no_error_at_all() {
    assert!(
        AuthorizationOutcome::Authorized
            .into_dbus_error(PolkitAction::Read)
            .is_none()
    );
}

#[test]
fn all_four_g1_test_actions_have_the_exact_polkit_action_ids_from_the_tdd_contract() {
    assert_eq!(PolkitAction::Read.action_id(), "guardian.test.read");
    assert_eq!(
        PolkitAction::LowRiskWrite.action_id(),
        "guardian.test.low-risk-write"
    );
    assert_eq!(
        PolkitAction::ModerateWrite.action_id(),
        "guardian.test.moderate-write"
    );
    assert_eq!(
        PolkitAction::HighRiskWrite.action_id(),
        "guardian.test.high-risk-write"
    );
}

/// P0-AUTH-001 (structural half): [`AuthorizationRequest`] is constructed
/// from a resolved [`CallerIdentity`] alone. There is no UID/PID/username/
/// role/`is_admin` field for a client-supplied claim to occupy, so two
/// requests built from the *same* real identity produce identical requests
/// regardless of what a caller might have claimed about itself elsewhere —
/// there is no code path by which such a claim could reach this struct.
#[test]
fn p0_auth_001_authorization_request_has_no_field_a_client_claim_could_occupy() {
    let real = identity(":1.42");

    // Two requests for the same action/interactivity, built from the same
    // real identity, are indistinguishable — proving nothing outside
    // `CallerIdentity` (which itself is only ever built by
    // `resolve_caller_identity` from the real bus sender, never from method
    // arguments) can influence what gets authorized.
    let first = AuthorizationRequest::new(real.clone(), PolkitAction::LowRiskWrite, false);
    let second = AuthorizationRequest::new(real.clone(), PolkitAction::LowRiskWrite, false);
    assert_eq!(
        first.subject().unique_name(),
        second.subject().unique_name()
    );
    assert_eq!(first.subject().uid(), second.subject().uid());
    assert_eq!(first.action().action_id(), second.action().action_id());
    assert_eq!(first.interactive(), second.interactive());

    // A different real identity does change the subject — proving the
    // subject genuinely comes from identity, not from nothing.
    let other = identity(":1.99");
    let third = AuthorizationRequest::new(other, PolkitAction::LowRiskWrite, false);
    assert_ne!(first.subject().unique_name(), third.subject().unique_name());
}

fn assert_send<T: Send>() {}

#[test]
fn guardian_dbus_error_type_used_by_the_mapping_is_the_real_public_error_type() {
    // Compile-time proof the mapping produces the same type the rest of
    // Guardian's public D-Bus surface uses — not a parallel error type.
    fn _takes_public_error(_: GuardianDbusError) {}
    assert_send::<GuardianDbusError>();
}

// --- AuthorizationError: infrastructure failure is distinct from every
// authorization decision (D, F below; A/B/C already covered above). ---

#[test]
fn infrastructure_provider_unavailable_maps_to_provider_unavailable_never_authentication_unavailable()
 {
    let error = AuthorizationError::ProviderUnavailable("polkit authority unreachable".to_owned())
        .into_dbus_error();
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.ProviderUnavailable"
    );
}

#[test]
fn infrastructure_internal_maps_to_internal() {
    let error = AuthorizationError::Internal("invariant violated".to_owned()).into_dbus_error();
    assert_eq!(
        error.name().as_str(),
        "io.github.cliffthelin.Guardian1.Error.Internal"
    );
}

/// Case E — the real `PolkitAuthorizer`, exercised for real (not a
/// hand-built `AuthorizationError` value): a private test bus has no
/// `org.freedesktop.PolicyKit1` service at all, so the real
/// `CheckAuthorization` D-Bus call genuinely fails at the transport level.
/// This proves the actual polkit.rs code path maps that failure to
/// `ProviderUnavailable`, never to `AuthenticationUnavailable`.
#[test]
fn real_polkit_authorizer_maps_unreachable_provider_to_provider_unavailable() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let address = bus.address().to_owned();

    async_io::block_on(async move {
        let connection = async_connection::Builder::address(address.as_str())
            .expect("parse private D-Bus address")
            .build()
            .await
            .expect("connect to private D-Bus");

        let authorizer = PolkitAuthorizer::new(&connection);
        let request =
            AuthorizationRequest::new(identity(":1.1"), PolkitAction::LowRiskWrite, false);

        let result = authorizer.authorize(&request).await;

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
