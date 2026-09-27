//! G2 Model B prototype — narrow privileged helper.
//!
//! Reuses G1's production `guardian_core::identity`/`guardian_core::authorization`
//! exactly, identically to Model A. Clients call this process **directly**
//! for the bounded write — it never receives, and never trusts, an identity
//! claim relayed by `g2-model-b-core`. It resolves the real caller from its
//! own inbound D-Bus connection and performs its own real
//! `CheckAuthorization`, closing the confused-deputy risk by construction
//! rather than by convention. See `docs/adr/ADR-002-guardian-privilege-topology.md`.

use std::sync::Mutex;

use guardian_core::authorization::polkit::PolkitAuthorizer;
use guardian_core::authorization::{AuthorizationError, AuthorizationRequest, Authorizer, PolkitAction};
use guardian_core::error::{GuardianDbusError, GuardianErrorCategory};
use guardian_core::identity::resolve_caller_identity;
use zbus::blocking::connection;

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.Guardian1.G2ModelBHelper";
const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/G2ModelBHelper";

struct ModelBHelper {
    ordering_log: Mutex<Vec<&'static str>>,
    mutation_count: Mutex<u32>,
}

impl ModelBHelper {
    fn new() -> Self {
        Self {
            ordering_log: Mutex::new(Vec::new()),
            mutation_count: Mutex::new(0),
        }
    }
}

#[zbus::interface(name = "io.github.cliffthelin.G2ModelBHelper1")]
impl ModelBHelper {
    async fn attempt_bounded_write(
        &self,
        interactive: bool,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> Result<(), GuardianDbusError> {
        self.ordering_log.lock().unwrap().clear();
        self.ordering_log.lock().unwrap().push("received");

        // Real caller identity, resolved from THIS connection's own inbound
        // message header. This is deliberately the only identity source:
        // there is no "claimed_uid"/"claimed_identity" parameter anywhere
        // in this method's signature for a relaying core to populate, and
        // no code path here ever reads anything from a would-be core
        // process's own claims. Whoever's D-Bus connection this message
        // arrived on is the caller, full stop.
        let identity = resolve_caller_identity(connection, &header)
            .await
            .map_err(|error| GuardianErrorCategory::Internal.with_message(error.to_string()))?
            .ok_or_else(|| {
                GuardianErrorCategory::Internal.with_message("message carried no sender")
            })?;
        self.ordering_log.lock().unwrap().push("identity_resolved");
        self.ordering_log.lock().unwrap().push("validated");

        // Real, independent CheckAuthorization -- not a decision forwarded
        // by g2-model-b-core, which this process never even connects to.
        let authorizer = PolkitAuthorizer::new(connection);
        let request = AuthorizationRequest::new(identity, PolkitAction::LowRiskWrite, interactive);
        let authorization_result = authorizer.authorize(&request).await;
        eprintln!("[g2-model-b-helper] real polkit result: {authorization_result:?}");
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

fn main() -> zbus::Result<()> {
    let connection = connection::Builder::system()?
        .name(WELL_KNOWN_NAME)?
        .serve_at(OBJECT_PATH, ModelBHelper::new())?
        .build()?;
    eprintln!(
        "[g2-model-b-helper] serving {WELL_KNOWN_NAME} at {OBJECT_PATH} (privileged), unique_name={}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}
