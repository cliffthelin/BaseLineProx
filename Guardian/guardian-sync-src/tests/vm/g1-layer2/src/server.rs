//! G1 Layer 2 real-host harness — server half.
//!
//! Registers a G1 test-only authorization probe on the *real* system D-Bus,
//! backed by the *real* `guardian_core::authorization::polkit::PolkitAuthorizer`
//! — no mock. Only for use inside the disposable Ubuntu 26.04.1 VM described
//! in `docs/guardian/30_TDD/GUARDIAN_G1_IMPLEMENTATION_HANDOFF.md` §5.2.
//! Never run on a primary development workstation: this process requires a
//! temporary D-Bus system-bus policy file and real polkit action/rule
//! definitions installed alongside it (see `docs/evidence/g1/` for the setup
//! script used to produce that evidence).

use std::sync::Mutex;

use guardian_core::authorization::polkit::PolkitAuthorizer;
use guardian_core::authorization::{
    AuthorizationError, AuthorizationRequest, Authorizer, PolkitAction,
};
use guardian_core::error::{GuardianDbusError, GuardianErrorCategory};
use guardian_core::identity::resolve_caller_identity;
use zbus::blocking::connection;

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.Guardian1.G1LayerTwoHarness";
const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/G1LayerTwoHarness";

#[derive(Default, Clone, Copy)]
struct MutationCounts {
    read: u32,
    low: u32,
    moderate: u32,
    high: u32,
}

struct AuthProbe {
    ordering_log: Mutex<Vec<&'static str>>,
    mutation_counts: Mutex<MutationCounts>,
    last_resolved_identity: Mutex<Option<String>>,
}

impl AuthProbe {
    fn new() -> Self {
        Self {
            ordering_log: Mutex::new(Vec::new()),
            mutation_counts: Mutex::new(MutationCounts::default()),
            last_resolved_identity: Mutex::new(None),
        }
    }

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
        eprintln!(
            "[g1-layer2-server] resolved caller: unique_name={} uid={:?}",
            identity.unique_name(),
            identity.uid()
        );
        *self.last_resolved_identity.lock().unwrap() = Some(format!(
            "{}|{}",
            identity.unique_name(),
            identity
                .uid()
                .map_or_else(|| "unknown".to_owned(), |uid| uid.to_string())
        ));
        self.ordering_log.lock().unwrap().push("identity_resolved");
        self.ordering_log.lock().unwrap().push("validated");

        // The real, production polkit-backed authorizer — not a mock.
        let authorizer = PolkitAuthorizer::new(connection);
        let request = AuthorizationRequest::new(identity, action, interactive);
        let authorization_result = authorizer.authorize(&request).await;
        eprintln!("[g1-layer2-server] real polkit result: {authorization_result:?}");
        self.ordering_log.lock().unwrap().push("authorized_checked");

        let outcome = authorization_result.map_err(AuthorizationError::into_dbus_error)?;

        if let Some(error) = outcome.into_dbus_error(action) {
            return Err(error);
        }

        self.ordering_log.lock().unwrap().push("mutation_applied");
        let mut counts = self.mutation_counts.lock().unwrap();
        match action {
            PolkitAction::Read => counts.read += 1,
            PolkitAction::LowRiskWrite => counts.low += 1,
            PolkitAction::ModerateWrite => counts.moderate += 1,
            PolkitAction::HighRiskWrite => counts.high += 1,
        }
        Ok(())
    }
}

#[zbus::interface(name = "io.github.cliffthelin.AuthProbe1")]
impl AuthProbe {
    #[allow(clippy::too_many_arguments)]
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

    #[allow(clippy::too_many_arguments)]
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

    #[allow(clippy::too_many_arguments)]
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

    #[allow(clippy::too_many_arguments)]
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

fn main() -> zbus::Result<()> {
    let connection = connection::Builder::system()?
        .name(WELL_KNOWN_NAME)?
        .serve_at(OBJECT_PATH, AuthProbe::new())?
        .build()?;
    eprintln!(
        "[g1-layer2-server] serving {WELL_KNOWN_NAME} at {OBJECT_PATH}, unique_name={}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}
