//! Layer 1 (private-bus) proof for G2 — Privilege Topology.
//!
//! Both prototypes (`tests/vm/g2-model-a/`, `tests/vm/g2-model-b/`) reuse
//! this exact production code — `guardian_core::identity`/
//! `guardian_core::authorization` — unchanged from G1. This file proves the
//! plumbing that matters for the topology comparison without a real bus,
//! root, or VM. Real-host measurement is `docs/evidence/g2/MODEL_A_EVIDENCE.md`
//! and `docs/evidence/g2/MODEL_B_EVIDENCE.md`.

use std::collections::HashMap;
use std::future::Future;
use std::sync::Mutex;

use guardian_core::authorization::{
    AuthorizationError, AuthorizationOutcome, AuthorizationRequest, Authorizer, PolkitAction,
};
use guardian_core::error::GuardianDbusError;
use guardian_core::error::GuardianErrorCategory;
use guardian_core::identity::resolve_caller_identity;
use guardian_testkit::PrivateSessionBus;
use zbus::blocking::{Connection, Proxy, connection};

const HELPER_INTERFACE: &str = "io.github.cliffthelin.G2HelperProbe1";
const HELPER_PATH: &str = "/io/github/cliffthelin/G2HelperProbe1";

/// Same deterministic test double pattern as G1's `MockAuthorizer` — real
/// polkit is exercised only in the VM (Layer 2); here the *plumbing* is
/// what's under test.
struct MockAuthorizer {
    grants: Mutex<Vec<String>>,
}

impl MockAuthorizer {
    fn new() -> Self {
        Self {
            grants: Mutex::new(Vec::new()),
        }
    }

    fn grant(&self, unique_name: &str) {
        self.grants.lock().unwrap().push(unique_name.to_owned());
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
            .iter()
            .any(|name| name == request.subject().unique_name());
        let outcome = if granted {
            AuthorizationOutcome::Authorized
        } else {
            AuthorizationOutcome::Denied
        };
        std::future::ready(Ok(outcome))
    }
}

/// Stands in for **either** Model A's single daemon **or** Model B's
/// directly-callable helper: the object's own resolved caller is the only
/// identity source, exactly matching both prototypes' real `daemon.rs`/
/// `helper.rs`. There is deliberately no constructor parameter or method
/// argument through which a "core" process (or anything else) could inject
/// a claimed identity — this is the structural confused-deputy proof for
/// Model B, since the helper's real implementation has the identical shape.
struct HelperProbe {
    authorizer: MockAuthorizer,
    ordering_log: Mutex<Vec<&'static str>>,
    mutation_count: Mutex<u32>,
}

impl HelperProbe {
    fn new(authorizer: MockAuthorizer) -> Self {
        Self {
            authorizer,
            ordering_log: Mutex::new(Vec::new()),
            mutation_count: Mutex::new(0),
        }
    }
}

#[zbus::interface(name = "io.github.cliffthelin.G2HelperProbe1")]
impl HelperProbe {
    /// Mirrors `daemon.rs`/`helper.rs`'s `attempt_bounded_write` exactly:
    /// receive -> resolve real caller -> validate -> authorize -> only then
    /// mutate. No `claimed_uid`/`claimed_identity`/`from_core` parameter
    /// exists here, matching the real prototypes' signatures precisely.
    async fn attempt_bounded_write(
        &self,
        interactive: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<(), GuardianDbusError> {
        self.ordering_log.lock().unwrap().clear();
        self.ordering_log.lock().unwrap().push("received");

        let identity = resolve_caller_identity(connection, &header)
            .await
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?
            .ok_or_else(|| {
                GuardianErrorCategory::Internal.with_message("message carried no sender")
            })?;
        self.ordering_log.lock().unwrap().push("identity_resolved");
        self.ordering_log.lock().unwrap().push("validated");

        let request = AuthorizationRequest::new(identity, PolkitAction::LowRiskWrite, interactive);
        let authorization_result = self.authorizer.authorize(&request).await;
        self.ordering_log.lock().unwrap().push("authorized_checked");

        let outcome = authorization_result.map_err(AuthorizationError::into_dbus_error)?;
        if let Some(error) = outcome.into_dbus_error(PolkitAction::LowRiskWrite) {
            return Err(error);
        }

        self.ordering_log.lock().unwrap().push("mutation_applied");
        *self.mutation_count.lock().unwrap() += 1;
        Ok(())
    }

    fn mutation_count(&self) -> u32 {
        *self.mutation_count.lock().unwrap()
    }

    fn last_ordering_trace(&self) -> Vec<String> {
        self.ordering_log
            .lock()
            .unwrap()
            .iter()
            .map(|event| (*event).to_owned())
            .collect()
    }
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
        HELPER_PATH,
        HELPER_INTERFACE,
    )
    .expect("create G2HelperProbe1 proxy")
}

/// Model A / Model B shared plumbing: the bounded operation is typed
/// (`interactive: bool` only — no path/argv/payload parameter), authorization
/// happens strictly before mutation (ordering trace), and denial produces
/// zero mutation. This is the Layer 1 evidence for
/// TDD contract §36 "Model A: bounded operation remains typed; no generic
/// execution surface appears; authorization failure prevents mutation."
#[test]
fn bounded_write_is_typed_ordered_and_denies_cleanly() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    server
        .object_server()
        .at(HELPER_PATH, HelperProbe::new(MockAuthorizer::new()))
        .expect("register G2HelperProbe1 test object");

    let client = client_connection(&bus);
    let proxy = probe_proxy(&client, &server);

    // Denied (never granted): zero mutation, ordering stops before
    // mutation_applied.
    let denied: zbus::Result<()> = proxy.call("AttemptBoundedWrite", &(false,));
    assert!(denied.is_err());
    assert_eq!(
        method_error_name(&denied.unwrap_err()),
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
        "denial must stop before mutation_applied"
    );
    let count: u32 = proxy.call("MutationCount", &()).unwrap();
    assert_eq!(count, 0);
}

/// This is the confused-deputy structural proof for Model B. `client_a`'s
/// real identity is granted; `client_b`'s is not. Neither connection's
/// method call carries any identity-claim argument at all — the D-Bus
/// method signature (`interactive: bool`) has no such field, matching the
/// real `helper.rs` exactly. There is no code path here (or in the real
/// helper) through which a would-be relaying "core" process could ever
/// inject an identity, because none exists to inject.
#[test]
fn model_b_helper_cannot_be_influenced_by_a_relaying_process_because_no_claim_field_exists() {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let server = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect server to private D-Bus");
    let authorizer = MockAuthorizer::new();

    let client_a = client_connection(&bus);
    let client_b = client_connection(&bus);
    let name_a = client_a.unique_name().unwrap().to_string();
    let name_b = client_b.unique_name().unwrap().to_string();
    assert_ne!(name_a, name_b);
    authorizer.grant(&name_a);

    server
        .object_server()
        .at(HELPER_PATH, HelperProbe::new(authorizer))
        .expect("register G2HelperProbe1 test object");

    let proxy_a = probe_proxy(&client_a, &server);
    let proxy_b = probe_proxy(&client_b, &server);

    let result_a: zbus::Result<()> = proxy_a.call("AttemptBoundedWrite", &(false,));
    assert!(
        result_a.is_ok(),
        "granted real connection must succeed: {result_a:?}"
    );

    let result_b: zbus::Result<()> = proxy_b.call("AttemptBoundedWrite", &(false,));
    assert!(
        result_b.is_err(),
        "ungranted real connection must be denied"
    );
    assert_eq!(
        method_error_name(&result_b.unwrap_err()),
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized"
    );

    let count: u32 = proxy_a.call("MutationCount", &()).unwrap();
    assert_eq!(
        count, 1,
        "only the real granted connection's call mutated state"
    );
}

/// Adversarial demonstration of the design this repository does **not**
/// build: a hypothetical relaying helper that trusts a `claimed_identity`
/// map forwarded by a core process. This function is never called from
/// production or from the prototypes — it exists solely so the test below
/// can show the vulnerability the real design avoids by never having this
/// code path at all.
#[allow(dead_code)]
fn vulnerable_relay_authorize_would_trust_forwarded_claim(
    claimed_identity: &HashMap<&str, &str>,
) -> bool {
    // This is exactly the forbidden pattern: trusting a claim instead of
    // resolving the real connection's own sender.
    claimed_identity.get("authorized") == Some(&"true")
}

/// Proves the vulnerable pattern above really would be exploitable if it
/// existed, by construction (not by running it against the real helper,
/// which has no such code path to exploit) — establishing, by contrast,
/// why the real `helper.rs`'s complete absence of a claim parameter is the
/// safety property, not merely a convention that happens to be followed.
#[test]
fn adversarial_forged_claim_would_succeed_against_the_pattern_g2_deliberately_avoids() {
    let mut forged = HashMap::new();
    forged.insert("uid", "0");
    forged.insert("authorized", "true");
    assert!(
        vulnerable_relay_authorize_would_trust_forwarded_claim(&forged),
        "a claim-trusting relay would be fooled by this forged map"
    );
    // The real HelperProbe/helper.rs `attempt_bounded_write` has no
    // equivalent function to call with this map at all -- there is no
    // argument of this shape anywhere in its signature. That absence, not
    // a runtime check, is what closes this attack for Model B.
}
