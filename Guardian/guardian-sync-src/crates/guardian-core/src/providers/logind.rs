//! G8 logind read provider (`P1-LGI-001..002`; contract §29). Native
//! `org.freedesktop.login1` D-Bus only.
//!
//! **Read-only, normatively enforced**: this module contains no callable
//! implementation of `Inhibit()` or any other logind mutation — it only
//! lists already-existing inhibitors. Inhibitor state is never treated as
//! an authorization signal.

use zbus::Connection;

const DESTINATION: &str = "org.freedesktop.login1";
const MANAGER_PATH: &str = "/org/freedesktop/login1";
const MANAGER_INTERFACE: &str = "org.freedesktop.login1.Manager";

/// One normalized inhibitor — exactly the fields contract §29 names, no
/// more.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Inhibitor {
    pub what: String,
    pub who: String,
    pub why: String,
    pub mode: String,
    pub uid: u32,
    pub pid: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LogindError {
    /// Contract §29: "A missing logind provider MUST degrade the page/
    /// command without blocking Guardian startup." Callers MUST treat
    /// this as non-fatal.
    ProviderUnavailable(String),
    MalformedResponse(String),
}

impl std::fmt::Display for LogindError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProviderUnavailable(message) => {
                write!(formatter, "login1 unavailable: {message}")
            }
            Self::MalformedResponse(message) => {
                write!(formatter, "malformed login1 response: {message}")
            }
        }
    }
}

impl std::error::Error for LogindError {}

type RawInhibitor = (String, String, String, String, u32, u32);

/// Normalizes an already-fetched `ListInhibitors` reply (Layer 1
/// testable). An empty list is healthy (`P1-LGI-002`), never an error.
#[must_use]
pub fn normalize_inhibitors(raw: &[RawInhibitor]) -> Vec<Inhibitor> {
    raw.iter()
        .map(|(what, who, why, mode, uid, pid)| Inhibitor {
            what: what.clone(),
            who: who.clone(),
            why: why.clone(),
            mode: mode.clone(),
            uid: *uid,
            pid: *pid,
        })
        .collect()
}

pub struct LogindProvider<'c> {
    connection: &'c Connection,
}

impl<'c> LogindProvider<'c> {
    #[must_use]
    pub const fn new(connection: &'c Connection) -> Self {
        Self { connection }
    }

    pub async fn probe(&self) -> bool {
        let Ok(dbus) = zbus::fdo::DBusProxy::new(self.connection).await else {
            return false;
        };
        let Ok(destination) = zbus::names::BusName::try_from(DESTINATION) else {
            return false;
        };
        dbus.name_has_owner(destination).await.unwrap_or(false)
    }

    /// Real `ListInhibitors` — `P1-LGI-001`/`P1-LGI-002`.
    ///
    /// # Errors
    ///
    /// See [`LogindError`].
    pub async fn list_inhibitors(&self) -> Result<Vec<Inhibitor>, LogindError> {
        let manager = zbus::Proxy::new(
            self.connection,
            DESTINATION,
            MANAGER_PATH,
            MANAGER_INTERFACE,
        )
        .await
        .map_err(|error| LogindError::ProviderUnavailable(error.to_string()))?;

        let raw: Vec<RawInhibitor> = manager
            .call("ListInhibitors", &())
            .await
            .map_err(|error| classify_list_inhibitors_error(&error))?;

        Ok(normalize_inhibitors(&raw))
    }
}

/// `ListInhibitors` is `list_inhibitors`' first live call — nothing
/// earlier has confirmed `login1` is actually present, so any failure
/// here (in particular a real `org.freedesktop.DBus.Error.ServiceUnknown`,
/// confirmed via real-VM/dbusmock evidence: a masked/absent `login1`
/// produces exactly this error) means the provider itself is unreachable,
/// never a malformed *response* — there is no response yet to be
/// malformed.
fn classify_list_inhibitors_error(error: &zbus::Error) -> LogindError {
    if crate::providers::is_provider_absent_error(error) {
        LogindError::ProviderUnavailable(error.to_string())
    } else {
        LogindError::MalformedResponse(error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Real dbusmock/VM regression (G8 evidence): an absent `login1`
    /// produced a real `ServiceUnknown` error from `ListInhibitors`, and
    /// the production code originally misclassified it as
    /// `MalformedResponse` — a real provider outage must never be
    /// reported as a malformed response.
    #[test]
    fn list_inhibitors_failure_is_provider_unavailable_not_malformed() {
        // Real-VM/dbusmock evidence: a genuinely absent `login1` makes
        // `zbus::Proxy::call()` surface `Error::MethodError` carrying the
        // D-Bus standard `ServiceUnknown` error name -- not `Error::FDO`,
        // which an earlier version of this classifier assumed and which
        // silently regressed this exact case.
        let name =
            zbus::names::OwnedErrorName::try_from("org.freedesktop.DBus.Error.ServiceUnknown")
                .unwrap();
        let error = zbus::Error::MethodError(
            name,
            None,
            zbus::message::Message::method_call("/", "Ping")
                .unwrap()
                .build(&())
                .unwrap(),
        );
        let classified = classify_list_inhibitors_error(&error);
        assert!(matches!(classified, LogindError::ProviderUnavailable(_)));
    }

    /// Real dbusmock regression (G8 evidence): a live mock returning the
    /// wrong method signature produced a real (non-`ServiceUnknown`)
    /// error — a real, live response with the wrong shape must be
    /// reported as malformed, never conflated with the provider being
    /// absent.
    #[test]
    fn list_inhibitors_signature_mismatch_is_malformed_not_provider_unavailable() {
        let error = zbus::Error::InvalidReply;
        let classified = classify_list_inhibitors_error(&error);
        assert!(matches!(classified, LogindError::MalformedResponse(_)));
    }

    #[test]
    fn empty_inhibitor_list_normalizes_to_empty_and_is_not_an_error() {
        let raw: Vec<RawInhibitor> = vec![];
        let inhibitors = normalize_inhibitors(&raw);
        assert!(inhibitors.is_empty());
    }

    #[test]
    fn one_inhibitor_normalizes_every_required_field() {
        let raw: Vec<RawInhibitor> = vec![(
            "shutdown".to_owned(),
            "guardian-test".to_owned(),
            "test inhibitor".to_owned(),
            "block".to_owned(),
            1000,
            4242,
        )];
        let inhibitors = normalize_inhibitors(&raw);
        assert_eq!(inhibitors.len(), 1);
        assert_eq!(inhibitors[0].what, "shutdown");
        assert_eq!(inhibitors[0].who, "guardian-test");
        assert_eq!(inhibitors[0].why, "test inhibitor");
        assert_eq!(inhibitors[0].mode, "block");
        assert_eq!(inhibitors[0].uid, 1000);
        assert_eq!(inhibitors[0].pid, 4242);
    }

    #[test]
    fn multiple_inhibitors_are_all_preserved_independently() {
        let raw: Vec<RawInhibitor> = vec![
            (
                "shutdown".to_owned(),
                "a".to_owned(),
                "x".to_owned(),
                "block".to_owned(),
                1,
                2,
            ),
            (
                "sleep".to_owned(),
                "b".to_owned(),
                "y".to_owned(),
                "delay".to_owned(),
                3,
                4,
            ),
        ];
        let inhibitors = normalize_inhibitors(&raw);
        assert_eq!(inhibitors.len(), 2);
        assert_eq!(inhibitors[0].what, "shutdown");
        assert_eq!(inhibitors[1].what, "sleep");
    }
}
