//! The one shared Guardian D-Bus client library (ADR-007). CLI, TUI, GUI,
//! and indicator all depend on this crate for every call into
//! `guardian-daemon` — none of them constructs its own D-Bus proxy code,
//! parses Guardian's wire types a second way, or embeds any provider-
//! arbitration/safety logic of its own (contract §31).
//!
//! Every method here is a thin, typed wrapper over exactly the real
//! interfaces `guardian-daemon` serves (`Guardian1`, `Capabilities1`,
//! `Incidents1`, `Transactions1` — `crates/guardian-daemon/src/
//! dbus_surface.rs`). No client-side capability, safety, or arbitration
//! logic exists here — only real IPC and honest error classification.
//!
//! This crate never talks to `GuardianHelper1` — clients are unprivileged
//! and only ever call `guardian-daemon` (contract §31; AGENTS.md
//! privilege rules).

const GUARDIAN_DESTINATION: &str = "io.github.cliffthelin.Guardian1";
const GUARDIAN_OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1";
const GUARDIAN_INTERFACE: &str = "io.github.cliffthelin.Guardian1";
const CAPABILITIES_OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/Capabilities";
const CAPABILITIES_INTERFACE: &str = "io.github.cliffthelin.Guardian.Capabilities1";
const INCIDENTS_OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/Incidents";
const INCIDENTS_INTERFACE: &str = "io.github.cliffthelin.Guardian.Incidents1";
const TRANSACTIONS_OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/Transactions";
const TRANSACTIONS_INTERFACE: &str = "io.github.cliffthelin.Guardian.Transactions1";

/// Real, typed daemon-unavailable vs. malformed-response distinction —
/// the same taxonomy discipline G8 established for provider reads,
/// applied here to Guardian's own public interfaces. A client MUST NOT
/// render "daemon unavailable" as a generic error indistinguishable from
/// "the daemon responded with something unexpected."
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ClientError {
    DaemonUnavailable(String),
    MalformedResponse(String),
}

impl std::fmt::Display for ClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::DaemonUnavailable(message) => {
                write!(formatter, "guardian-daemon unavailable: {message}")
            }
            Self::MalformedResponse(message) => {
                write!(formatter, "malformed guardian-daemon response: {message}")
            }
        }
    }
}

impl std::error::Error for ClientError {}

fn is_absent_error_name(name: &str) -> bool {
    matches!(
        name,
        "org.freedesktop.DBus.Error.ServiceUnknown" | "org.freedesktop.DBus.Error.NameHasNoOwner"
    )
}

/// Pure, Layer-1-testable classification — mirrors
/// `guardian_core::providers::is_provider_absent_error`'s real-evidence-
/// grounded distinction between a genuine absence and a live-but-
/// unexpected response, applied here to the daemon itself rather than an
/// external provider.
#[must_use]
pub fn classify_call_error(error: &zbus::Error) -> ClientError {
    let is_absent = match error {
        zbus::Error::FDO(fdo_error) => matches!(
            fdo_error.as_ref(),
            zbus::fdo::Error::ServiceUnknown(_) | zbus::fdo::Error::NameHasNoOwner(_)
        ),
        zbus::Error::MethodError(name, _, _) => is_absent_error_name(name.as_str()),
        zbus::Error::InputOutput(_) => true,
        _ => false,
    };
    if is_absent {
        ClientError::DaemonUnavailable(error.to_string())
    } else {
        ClientError::MalformedResponse(error.to_string())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractInfo {
    pub contract_version: String,
    pub service_state: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Capability {
    pub capability_id: String,
    pub provider_id: String,
    pub provider_version: String,
    pub availability: String,
    pub health: String,
    pub read_support: bool,
    pub write_support: bool,
    pub authorization_ownership: String,
    pub privilege_requirement: String,
    pub interface_kind: String,
    pub last_observed_at: String,
}

type CapabilityWire = (
    String,
    String,
    String,
    String,
    String,
    bool,
    bool,
    String,
    String,
    String,
    String,
);

impl From<CapabilityWire> for Capability {
    fn from(wire: CapabilityWire) -> Self {
        Self {
            capability_id: wire.0,
            provider_id: wire.1,
            provider_version: wire.2,
            availability: wire.3,
            health: wire.4,
            read_support: wire.5,
            write_support: wire.6,
            authorization_ownership: wire.7,
            privilege_requirement: wire.8,
            interface_kind: wire.9,
            last_observed_at: wire.10,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct PsiSummary {
    pub kind: String,
    pub avg10: f64,
    pub avg60: f64,
    pub avg300: f64,
    pub available: bool,
}

type PsiSummaryWire = (String, f64, f64, f64, bool);

impl From<PsiSummaryWire> for PsiSummary {
    fn from(wire: PsiSummaryWire) -> Self {
        Self {
            kind: wire.0,
            avg10: wire.1,
            avg60: wire.2,
            avg300: wire.3,
            available: wire.4,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Blocker {
    pub what: String,
    pub who: String,
    pub why: String,
    pub mode: String,
    pub uid: u32,
    pub pid: u32,
}

type BlockerWire = (String, String, String, String, u32, u32);

impl From<BlockerWire> for Blocker {
    fn from(wire: BlockerWire) -> Self {
        Self {
            what: wire.0,
            who: wire.1,
            why: wire.2,
            mode: wire.3,
            uid: wire.4,
            pid: wire.5,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Incident {
    pub incident_id: String,
    pub opened_at: String,
    pub closed_at: String,
    pub status: String,
    pub summary: String,
    pub confidence: String,
    pub primary_resource: String,
}

type IncidentWire = (String, String, String, String, String, String, String);

impl From<IncidentWire> for Incident {
    fn from(wire: IncidentWire) -> Self {
        Self {
            incident_id: wire.0,
            opened_at: wire.1,
            closed_at: wire.2,
            status: wire.3,
            summary: wire.4,
            confidence: wire.5,
            primary_resource: wire.6,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Transaction {
    pub transaction_id: String,
    pub state: String,
    pub created_at: String,
}

type TransactionWire = (String, String, String);

impl From<TransactionWire> for Transaction {
    fn from(wire: TransactionWire) -> Self {
        Self {
            transaction_id: wire.0,
            state: wire.1,
            created_at: wire.2,
        }
    }
}

/// A real, live connection to `guardian-daemon`'s public interfaces —
/// never to `guardian-helper`, never a second parsing path per surface.
pub struct DaemonConnection {
    connection: zbus::Connection,
}

impl DaemonConnection {
    /// Real system-bus connection. Daemon-absence at this stage is the
    /// same `DaemonUnavailable` taxonomy every subsequent call uses.
    ///
    /// # Errors
    ///
    /// Returns [`ClientError::DaemonUnavailable`] if the system bus
    /// itself cannot be reached.
    pub async fn connect() -> Result<Self, ClientError> {
        let connection = zbus::Connection::system()
            .await
            .map_err(|error| ClientError::DaemonUnavailable(error.to_string()))?;
        Ok(Self { connection })
    }

    async fn call<T>(&self, path: &str, interface: &str, method: &str) -> Result<T, ClientError>
    where
        T: for<'de> zbus::zvariant::DynamicDeserialize<'de> + zbus::zvariant::Type,
    {
        let proxy = zbus::Proxy::new(&self.connection, GUARDIAN_DESTINATION, path, interface)
            .await
            .map_err(|error| ClientError::DaemonUnavailable(error.to_string()))?;
        proxy
            .call(method, &())
            .await
            .map_err(|error| classify_call_error(&error))
    }

    /// Real `Guardian1.ContractVersion`/`ServiceState` — the frozen G0
    /// contract, unchanged since G0.
    ///
    /// # Errors
    ///
    /// See [`ClientError`].
    pub async fn contract_info(&self) -> Result<ContractInfo, ClientError> {
        let proxy = zbus::Proxy::new(
            &self.connection,
            GUARDIAN_DESTINATION,
            GUARDIAN_OBJECT_PATH,
            GUARDIAN_INTERFACE,
        )
        .await
        .map_err(|error| ClientError::DaemonUnavailable(error.to_string()))?;
        let contract_version: String = proxy
            .call("ContractVersion", &())
            .await
            .map_err(|error| classify_call_error(&error))?;
        let service_state: String = proxy
            .call("ServiceState", &())
            .await
            .map_err(|error| classify_call_error(&error))?;
        Ok(ContractInfo {
            contract_version,
            service_state,
        })
    }

    /// Real `Capabilities1.ListCapabilities` — the live G8 Capability
    /// Registry snapshot.
    ///
    /// # Errors
    ///
    /// See [`ClientError`].
    pub async fn capabilities(&self) -> Result<Vec<Capability>, ClientError> {
        let wire: Vec<CapabilityWire> = self
            .call(
                CAPABILITIES_OBJECT_PATH,
                CAPABILITIES_INTERFACE,
                "ListCapabilities",
            )
            .await?;
        Ok(wire.into_iter().map(Capability::from).collect())
    }

    /// Real `Capabilities1.PsiSummary` — live `/proc/pressure` reads.
    ///
    /// # Errors
    ///
    /// See [`ClientError`].
    pub async fn psi_summary(&self) -> Result<Vec<PsiSummary>, ClientError> {
        let wire: Vec<PsiSummaryWire> = self
            .call(
                CAPABILITIES_OBJECT_PATH,
                CAPABILITIES_INTERFACE,
                "PsiSummary",
            )
            .await?;
        Ok(wire.into_iter().map(PsiSummary::from).collect())
    }

    /// Real `Capabilities1.ListBlockers` — live `logind` inhibitors.
    ///
    /// # Errors
    ///
    /// See [`ClientError`].
    pub async fn blockers(&self) -> Result<Vec<Blocker>, ClientError> {
        let wire: Vec<BlockerWire> = self
            .call(
                CAPABILITIES_OBJECT_PATH,
                CAPABILITIES_INTERFACE,
                "ListBlockers",
            )
            .await?;
        Ok(wire.into_iter().map(Blocker::from).collect())
    }

    /// Real `Incidents1.ListIncidents` — genuinely empty in this gate
    /// (no incident producer exists yet); see `dbus_surface`'s own doc
    /// comment.
    ///
    /// # Errors
    ///
    /// See [`ClientError`].
    pub async fn incidents(&self) -> Result<Vec<Incident>, ClientError> {
        let wire: Vec<IncidentWire> = self
            .call(INCIDENTS_OBJECT_PATH, INCIDENTS_INTERFACE, "ListIncidents")
            .await?;
        Ok(wire.into_iter().map(Incident::from).collect())
    }

    /// Real `Transactions1.ListTransactions` — genuinely empty in this
    /// gate (the daemon holds no transaction store); see
    /// `dbus_surface`'s own doc comment.
    ///
    /// # Errors
    ///
    /// See [`ClientError`].
    pub async fn transactions(&self) -> Result<Vec<Transaction>, ClientError> {
        let wire: Vec<TransactionWire> = self
            .call(
                TRANSACTIONS_OBJECT_PATH,
                TRANSACTIONS_INTERFACE,
                "ListTransactions",
            )
            .await?;
        Ok(wire.into_iter().map(Transaction::from).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn method_error_with_service_unknown_name_is_daemon_unavailable() {
        let name =
            zbus::names::OwnedErrorName::try_from("org.freedesktop.DBus.Error.ServiceUnknown")
                .unwrap();
        let message = zbus::message::Message::method_call("/", "Ping")
            .unwrap()
            .build(&())
            .unwrap();
        let error = zbus::Error::MethodError(name, None, message);
        assert!(matches!(
            classify_call_error(&error),
            ClientError::DaemonUnavailable(_)
        ));
    }

    #[test]
    fn invalid_reply_is_malformed_not_daemon_unavailable() {
        let classified = classify_call_error(&zbus::Error::InvalidReply);
        assert!(matches!(classified, ClientError::MalformedResponse(_)));
    }

    #[test]
    fn capability_wire_projection_preserves_every_field() {
        let wire: CapabilityWire = (
            "systemd.unit.state".to_owned(),
            "guardian.g8.systemd".to_owned(),
            String::new(),
            "available".to_owned(),
            "healthy".to_owned(),
            true,
            false,
            "unknown".to_owned(),
            "no_direct_privilege".to_owned(),
            "dbus".to_owned(),
            "2026-09-02T00:00:00Z".to_owned(),
        );
        let capability = Capability::from(wire);
        assert_eq!(capability.capability_id, "systemd.unit.state");
        assert!(capability.read_support);
        assert!(!capability.write_support);
    }
}
