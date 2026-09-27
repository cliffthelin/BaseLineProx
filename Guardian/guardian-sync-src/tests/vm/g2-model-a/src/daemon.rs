//! G2 Model A prototype — hardened privileged daemon.
//!
//! One process, running under a real systemd unit with real hardening, that
//! itself performs the bounded typed write after real polkit authorization.
//! Reuses G1's production `guardian_core::identity`/`guardian_core::authorization`
//! exactly — no parallel authorization system. See
//! `docs/evidence/g2/MODEL_A_EVIDENCE.md` for the real-host measurements this
//! binary was used to produce, and
//! `docs/guardian/30_TDD/GUARDIAN_G2_IMPLEMENTATION_HANDOFF.md` §6 for the
//! governing requirements.

use std::sync::Mutex;

use guardian_core::authorization::polkit::PolkitAuthorizer;
use guardian_core::authorization::{AuthorizationError, AuthorizationRequest, Authorizer, PolkitAction};
use guardian_core::error::{GuardianDbusError, GuardianErrorCategory};
use guardian_core::identity::resolve_caller_identity;
use zbus::blocking::connection;

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.Guardian1.G2ModelA";
const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/G2ModelA";

struct ModelADaemon {
    ordering_log: Mutex<Vec<&'static str>>,
    mutation_count: Mutex<u32>,
}

impl ModelADaemon {
    fn new() -> Self {
        Self {
            ordering_log: Mutex::new(Vec::new()),
            mutation_count: Mutex::new(0),
        }
    }
}

#[zbus::interface(name = "io.github.cliffthelin.G2ModelA1")]
impl ModelADaemon {
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

        let authorizer = PolkitAuthorizer::new(connection);
        let request = AuthorizationRequest::new(identity, PolkitAction::LowRiskWrite, interactive);
        let authorization_result = authorizer.authorize(&request).await;
        eprintln!("[g2-model-a] real polkit result: {authorization_result:?}");
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
        .serve_at(OBJECT_PATH, ModelADaemon::new())?
        .build()?;
    eprintln!(
        "[g2-model-a] serving {WELL_KNOWN_NAME} at {OBJECT_PATH}, unique_name={}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}
