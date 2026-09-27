//! Layer 1 (private-bus) proof for G1 — Identity & Authorization.
//!
//! Every connection opened here is a *real* D-Bus connection with a *real*,
//! distinct unique bus name assigned by `dbus-daemon` — that part is never
//! mocked. What is mocked is the *authorization decision* itself
//! ([`MockAuthorizer`]), because no real polkit authority exists on a private
//! test bus. See `docs/guardian/30_TDD/GUARDIAN_G1_IMPLEMENTATION_HANDOFF.md`
//! §5 for the Layer 1 / Layer 2 split this file implements the Layer 1 half
//! of.
#![allow(clippy::similar_names)] // claimed_uid/claimed_pid mirror the adversarial-test list on purpose

use std::collections::HashMap;
use std::future::Future;
use std::sync::Mutex;

use guardian_core::authorization::{
    AuthorizationError, AuthorizationOutcome, AuthorizationRequest, AuthorizationUnavailableReason,
    Authorizer, PolkitAction,
};
use guardian_core::error::GuardianDbusError;
use guardian_core::error::GuardianErrorCategory;
use guardian_core::identity::resolve_caller_identity;
use guardian_testkit::PrivateSessionBus;
use zbus::blocking::{Connection, Proxy, connection};

const AUTH_PROBE_INTERFACE: &str = "io.github.cliffthelin.AuthProbe1";
const AUTH_PROBE_PATH: &str = "/io/github/cliffthelin/AuthProbe1";

/// A deterministic, non-real authorization decision source.
///
/// Keyed by the *real* resolved unique bus name of the caller — this type has
/// no way to see any client-supplied claim at all, because
/// [`AuthorizationRequest`] carries no such field.
struct MockAuthorizer {
    grants: Mutex<HashMap<String, Vec<PolkitAction>>>,
    require_interactive: Vec<PolkitAction>,
}

impl MockAuthorizer {
    fn new(require_interactive: Vec<PolkitAction>) -> Self {
        Self {
            grants: Mutex::new(HashMap::new()),
            require_interactive,
        }
    }

    fn grant(&self, unique_name: &str, actions: &[PolkitAction]) {
        self.grants
            .lock()
            .unwrap()
            .insert(unique_name.to_owned(), actions.to_vec());
    }
}

impl Authorizer for MockAuthorizer {
    fn authorize(
        &self,
        request: &AuthorizationRequest,
    ) -> impl Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send {
        let granted = self
            .grants
            .lock()
            .unwrap()
            .get(request.subject().unique_name())
            .is_some_and(|actions| actions.contains(&request.action()));
        let outcome = if !granted {
            AuthorizationOutcome::Denied
        } else if self.require_interactive.contains(&request.action()) && !request.interactive() {
            AuthorizationOutcome::Unavailable(
                AuthorizationUnavailableReason::InteractionRequiredButDisallowed,
            )
        } else {
            AuthorizationOutcome::Authorized
        };
        std::future::ready(Ok(outcome))
    }
}

#[derive(Default, Clone, Copy)]
struct MutationCounts {
    read: u32,
    low: u32,
    moderate: u32,
    high: u32,
}

struct AuthProbe {
    authorizer: MockAuthorizer,
    // Records the exact sequence of steps taken for the *most recent* call,
    // so a test can assert ordering directly rather than only comparing
    // before/after state.
    ordering_log: Mutex<Vec<&'static str>>,
    mutation_counts: Mutex<MutationCounts>,
    last_resolved_identity: Mutex<Option<String>>,
}

impl AuthProbe {
    fn new(authorizer: MockAuthorizer) -> Self {
        Self {
            authorizer,
            ordering_log: Mutex::new(Vec::new()),
            mutation_counts: Mutex::new(MutationCounts::default()),
            last_resolved_identity: Mutex::new(None),
        }
    }

    /// Shared implementation for all four G1 test actions. This is the exact
    /// ordering the G1 handoff §7 requires:
    /// receive → resolve caller → validate → authorize → only then mutate.
    async fn attempt(
        &self,
        action: PolkitAction,
        interactive: bool,
        header: &zbus::message::Header<'_>,
        connection: &zbus::Connection,
    ) -> Result<(), GuardianDbusError> {
        self.ordering_log.lock().unwrap().clear();
        self.ordering_log.lock().unwrap().push("received");

        let identity = resolve_caller_identity(connection, header)
            .await
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?
            .ok_or_else(|| {
                GuardianErrorCategory::Internal.with_message("message carried no sender")
            })?;
        *self.last_resolved_identity.lock().unwrap() = Some(identity.unique_name().to_owned());
        self.ordering_log.lock().unwrap().push("identity_resolved");

        // No further preconditions for G1's bounded test actions beyond a
        // resolved identity; the step still exists explicitly in the trace
        // so the ordering invariant is visible end to end.
        self.ordering_log.lock().unwrap().push("validated");

        let request = AuthorizationRequest::new(identity, action, interactive);
        let authorization_result = self.authorizer.authorize(&request).await;
        self.ordering_log.lock().unwrap().push("authorized_checked");

        // An infrastructure failure (the authorizer could not even reach a
        // decision) is returned immediately, distinctly from an ordinary
        // denied/unavailable decision — see `AuthorizationError`.
        let outcome = authorization_result.map_err(AuthorizationError::into_dbus_error)?;

        if let Some(error) = outcome.into_dbus_error(action) {
            // Denied/unavailable: return now. Nothing below this line has
            // executed, so no mutation can have occurred.
            return Err(error);
        }

        self.ordering_log.lock().unwrap().push("mutation_applied");
        let mut counts = self.mutation_counts.lock().unwrap();
        match action {
            PolkitAction::Read => counts.read += 1,
            PolkitAction::LowRiskWrite => counts.low += 1,
            PolkitAction::ModerateWrite => counts.moderate += 1,
            PolkitAction::HighRiskWrite => counts.high += 1,
            // G7's action, not exercised by this G1-scoped fixture.
            PolkitAction::GuardianBoundedWrite => {}
        }
        Ok(())
    }
}

#[zbus::interface(name = "io.github.cliffthelin.AuthProbe1")]
impl AuthProbe {
    #[allow(clippy::too_many_arguments)] // mirrors the five adversarial identity-claim fields individually
    async fn attempt_read(
        &self,
        interactive: bool,
        claimed_uid: u32,
        claimed_pid: u32,
        claimed_username: String,
        claimed_role: String,
        claimed_is_admin: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<(), GuardianDbusError> {
        // Received, and deliberately never consulted below: this is the
        // literal proof that client-supplied identity claims cannot
        // influence the outcome, not merely a promise in a comment.
        let _ = (
            claimed_uid,
            claimed_pid,
            &claimed_username,
            &claimed_role,
            claimed_is_admin,
        );
        self.attempt(PolkitAction::Read, interactive, &header, connection)
            .await
    }

    #[allow(clippy::too_many_arguments)] // mirrors the five adversarial identity-claim fields individually
    async fn attempt_low_risk_write(
        &self,
        interactive: bool,
        claimed_uid: u32,
        claimed_pid: u32,
        claimed_username: String,
        claimed_role: String,
        claimed_is_admin: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<(), GuardianDbusError> {
        let _ = (
            claimed_uid,
            claimed_pid,
            &claimed_username,
            &claimed_role,
            claimed_is_admin,
        );
        self.attempt(PolkitAction::LowRiskWrite, interactive, &header, connection)
            .await
    }

    #[allow(clippy::too_many_arguments)] // mirrors the five adversarial identity-claim fields individually
    async fn attempt_moderate_write(
        &self,
        interactive: bool,
        claimed_uid: u32,
        claimed_pid: u32,
        claimed_username: String,
        claimed_role: String,
        claimed_is_admin: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<(), GuardianDbusError> {
        let _ = (
            claimed_uid,
            claimed_pid,
            &claimed_username,
            &claimed_role,
            claimed_is_admin,
        );
        self.attempt(
            PolkitAction::ModerateWrite,
            interactive,
            &header,
            connection,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)] // mirrors the five adversarial identity-claim fields individually
    async fn attempt_high_risk_write(
        &self,
        interactive: bool,
        claimed_uid: u32,
        claimed_pid: u32,
        claimed_username: String,
        claimed_role: String,
        claimed_is_admin: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<(), GuardianDbusError> {
        let _ = (
            claimed_uid,
            claimed_pid,
            &claimed_username,
            &claimed_role,
            claimed_is_admin,
        );
        self.attempt(
            PolkitAction::HighRiskWrite,
            interactive,
            &header,
            connection,
        )
        .await
    }

    fn mutation_counts(&self) -> (u32, u32, u32, u32) {
        let counts = self.mutation_counts.lock().unwrap();
        (counts.read, counts.low, counts.moderate, counts.high)
    }

    fn last_ordering_trace(&self) -> Vec<String> {
        self.ordering_log
            .lock()
            .unwrap()
            .iter()
            .map(|event| (*event).to_owned())
            .collect()
    }

    fn last_resolved_identity(&self) -> String {
        self.last_resolved_identity
            .lock()
            .unwrap()
            .clone()
            .unwrap_or_default()
    }
}

fn client_call(
    proxy: &Proxy<'_>,
    method: &str,
    interactive: bool,
    claimed_uid: u32,
    claimed_username: &str,
    claimed_is_admin: bool,
) -> zbus::Result<()> {
    proxy.call(
        method,
        &(
            interactive,
            claimed_uid,
            0u32,
            claimed_username,
            "",
            claimed_is_admin,
        ),
    )
}

fn method_error_name(error: &zbus::Error) -> &str {
    match error {
        zbus::Error::MethodError(name, _, _) => name.as_str(),
        other => panic!("expected structured D-Bus method error, got {other:?}"),
    }
}

fn client_connection(bus: &PrivateSessionBus) -> Connection {
    connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect client to private D-Bus")
}

fn probe_proxy<'c>(client: &'c Connection, server: &'c Connection) -> Proxy<'c> {
    Proxy::new(
        client,
        server.unique_name().expect("server unique name").as_str(),
        AUTH_PROBE_PATH,
        AUTH_PROBE_INTERFACE,
    )
    .expect("create AuthProbe1 proxy")
}

/// P0-AUTH-001 (Layer 1 half) — caller identity cannot be spoofed.
///
/// Two *real*, distinct D-Bus connections (`client_a`, `client_b`) each get a
/// real unique bus name from `dbus-daemon` — that identity is never mocked.
/// The authorizer is configured to grant `LowRiskWrite` to `client_a`'s real
/// identity only, before the object is even registered. `client_a` then
/// claims to be an unprivileged stranger; `client_b` claims to be root with
/// `is_admin = true`. The outcome tracks only the real identity in both
/// directions: `client_a` succeeds despite its modest claim, `client_b` is
/// denied despite its inflated one.
#[test]
fn p0_auth_001_caller_identity_cannot_be_spoofed() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    let authorizer = MockAuthorizer::new(Vec::new());

    let client_a = client_connection(&bus);
    let client_b = client_connection(&bus);
    let name_a = client_a.unique_name().unwrap().to_string();
    let name_b = client_b.unique_name().unwrap().to_string();
    assert_ne!(name_a, name_b);

    // Grant only client_a's real, already-known unique name before the
    // object is even registered — this is legitimate because the test
    // controls both the real bus names (via the client connections opened
    // above) and the authorizer configuration; production code never has
    // this foreknowledge and must rely solely on resolve_caller_identity.
    authorizer.grant(&name_a, &[PolkitAction::LowRiskWrite]);

    server
        .object_server()
        .at(AUTH_PROBE_PATH, AuthProbe::new(authorizer))
        .expect("register AuthProbe1 test object");

    let proxy_a = probe_proxy(&client_a, &server);
    let proxy_b = probe_proxy(&client_b, &server);

    // client_a: real identity granted, but claims to be an unprivileged
    // stranger. Must still succeed — the claim is irrelevant.
    let result_a = client_call(
        &proxy_a,
        "AttemptLowRiskWrite",
        false,
        1000,
        "nobody",
        false,
    );
    assert!(
        result_a.is_ok(),
        "real-identity grant must apply regardless of claim: {result_a:?}"
    );

    // client_b: real identity never granted, but claims to be root/admin.
    // Must still be denied — the claim is irrelevant.
    let result_b = client_call(&proxy_b, "AttemptLowRiskWrite", false, 0, "root", true);
    assert!(result_b.is_err());
    assert_eq!(
        method_error_name(&result_b.unwrap_err()),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );

    let mutation_proxy = Proxy::new(
        &client_a,
        server.unique_name().unwrap().as_str(),
        AUTH_PROBE_PATH,
        AUTH_PROBE_INTERFACE,
    )
    .unwrap();
    let counts: (u32, u32, u32, u32) = mutation_proxy.call("MutationCounts", &()).unwrap();
    assert_eq!(
        counts,
        (0, 1, 0, 0),
        "only the real-identity-granted call mutated state"
    );
}

/// P0-AUTH-002 (Layer 1 half) — denied action does not apply, proven via the
/// exact execution ordering, not only via before/after state.
#[test]
fn p0_auth_002_denied_action_never_reaches_the_mutation_step() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    server
        .object_server()
        .at(
            AUTH_PROBE_PATH,
            AuthProbe::new(MockAuthorizer::new(Vec::new())),
        )
        .expect("register AuthProbe1 test object");

    let client = client_connection(&bus);
    let proxy = probe_proxy(&client, &server);

    let result = client_call(&proxy, "AttemptHighRiskWrite", false, 0, "root", true);
    assert!(result.is_err());
    assert_eq!(
        method_error_name(&result.unwrap_err()),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );

    let trace: Vec<String> = proxy.call("LastOrderingTrace", &()).unwrap();
    assert_eq!(
        trace,
        vec![
            "received",
            "identity_resolved",
            "validated",
            "authorized_checked"
        ],
        "denial must stop the ordering trace before mutation_applied"
    );

    let counts: (u32, u32, u32, u32) = proxy.call("MutationCounts", &()).unwrap();
    assert_eq!(counts, (0, 0, 0, 0), "zero mutation on denial");
}

/// P0-AUTH-003 (Layer 1 half) — a non-interactive request cannot succeed for
/// an action that requires interaction, and fails closed rather than
/// prompting. There is no interactive-authentication code path reachable
/// from this test at all (the mock authorizer performs no I/O and shows no
/// prompt of any kind), which is itself the structural proof that background
/// requests cannot trigger one: the only component in this repository able
/// to initiate a real prompt is `guardian_core::authorization::polkit::PolkitAuthorizer`,
/// and it is never constructed in this test.
#[test]
fn p0_auth_003_background_request_fails_closed_without_prompting() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    let authorizer = MockAuthorizer::new(vec![PolkitAction::ModerateWrite]);

    let client = client_connection(&bus);
    let name = client.unique_name().unwrap().to_string();
    authorizer.grant(&name, &[PolkitAction::ModerateWrite]);

    server
        .object_server()
        .at(AUTH_PROBE_PATH, AuthProbe::new(authorizer))
        .expect("register AuthProbe1 test object");

    let proxy = probe_proxy(&client, &server);

    // Granted, but non-interactive, and the action requires interaction.
    let result = client_call(&proxy, "AttemptModerateWrite", false, 1000, "nobody", false);
    assert!(result.is_err());
    assert_eq!(
        method_error_name(&result.unwrap_err()),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );
    let counts: (u32, u32, u32, u32) = proxy.call("MutationCounts", &()).unwrap();
    assert_eq!(counts, (0, 0, 0, 0), "background request must not mutate");
}

/// P0-AUTH-004 (Layer 1 half) — the identical request, marked as an explicit
/// user-initiated action (`interactive = true`), may proceed once granted.
#[test]
fn p0_auth_004_explicit_interactive_request_may_proceed_once_granted() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    let authorizer = MockAuthorizer::new(vec![PolkitAction::ModerateWrite]);

    let client = client_connection(&bus);
    let name = client.unique_name().unwrap().to_string();
    authorizer.grant(&name, &[PolkitAction::ModerateWrite]);

    server
        .object_server()
        .at(AUTH_PROBE_PATH, AuthProbe::new(authorizer))
        .expect("register AuthProbe1 test object");

    let proxy = probe_proxy(&client, &server);

    let result = client_call(&proxy, "AttemptModerateWrite", true, 1000, "nobody", false);
    assert!(
        result.is_ok(),
        "interactive + granted must succeed: {result:?}"
    );
    let counts: (u32, u32, u32, u32) = proxy.call("MutationCounts", &()).unwrap();
    assert_eq!(counts, (0, 0, 1, 0));
}

/// Granting a low-risk action must not implicitly authorize a high-risk one
/// (TDD contract §9, last line).
#[test]
fn granting_low_risk_does_not_authorize_high_risk() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    let authorizer = MockAuthorizer::new(Vec::new());

    let client = client_connection(&bus);
    let name = client.unique_name().unwrap().to_string();
    authorizer.grant(&name, &[PolkitAction::LowRiskWrite]);

    server
        .object_server()
        .at(AUTH_PROBE_PATH, AuthProbe::new(authorizer))
        .expect("register AuthProbe1 test object");

    let proxy = probe_proxy(&client, &server);

    let low = client_call(&proxy, "AttemptLowRiskWrite", false, 1000, "nobody", false);
    let high = client_call(&proxy, "AttemptHighRiskWrite", false, 1000, "nobody", false);
    assert!(low.is_ok());
    assert!(high.is_err());
    let counts: (u32, u32, u32, u32) = proxy.call("MutationCounts", &()).unwrap();
    assert_eq!(counts, (0, 1, 0, 0));
}

/// Caller-identity lifetime (G1 handoff §8): identity is resolved fresh from
/// the connection on every call. There is no cache anywhere in
/// `resolve_caller_identity` or `AuthProbe` (structurally: neither type has a
/// field capable of holding one), so a second, distinct real connection is
/// never confused with an earlier one — proven here by two sequential real
/// connections producing two different resolved identities from the same
/// object, in sequence, with the first connection dropped before the second
/// opens.
#[test]
fn caller_identity_is_re_resolved_fresh_never_cached_across_connections() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    server
        .object_server()
        .at(
            AUTH_PROBE_PATH,
            AuthProbe::new(MockAuthorizer::new(Vec::new())),
        )
        .expect("register AuthProbe1 test object");

    let first = client_connection(&bus);
    let first_name = first.unique_name().unwrap().to_string();
    let proxy_first = probe_proxy(&first, &server);
    let _ = client_call(&proxy_first, "AttemptRead", false, 0, "root", true);
    let resolved_first: String = proxy_first.call("LastResolvedIdentity", &()).unwrap();
    assert_eq!(resolved_first, first_name);
    drop(proxy_first);
    drop(first);

    let second = client_connection(&bus);
    let second_name = second.unique_name().unwrap().to_string();
    assert_ne!(
        first_name, second_name,
        "dbus-daemon must not reuse the unique name after disconnect for this test to be meaningful"
    );
    let proxy_second = probe_proxy(&second, &server);
    let _ = client_call(&proxy_second, "AttemptRead", false, 0, "root", true);
    let resolved_second: String = proxy_second.call("LastResolvedIdentity", &()).unwrap();
    assert_eq!(
        resolved_second, second_name,
        "identity must be re-resolved fresh, never left over from the disconnected first connection"
    );
    assert_ne!(resolved_first, resolved_second);
}
