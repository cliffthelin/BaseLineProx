//! G8 systemd read provider (`P1-SYS-001..003`). Native
//! `org.freedesktop.systemd1` D-Bus only — no `systemctl` shell-out
//! (contract §40's forbidden-shortcuts list forbids exactly this where a
//! stable D-Bus API is already selected).
//!
//! **Read-only, normatively enforced**: this module contains no callable
//! implementation of `StartUnit`/`StopUnit`/`RestartUnit` or any other
//! systemd mutation. It exposes exactly one typed read
//! ([`SystemdProvider::unit_state`]) for an explicitly-named allowed unit
//! — never a generic "call any method on any unit" broker.

use zbus::Connection;
use zbus::zvariant::OwnedValue;

const DESTINATION: &str = "org.freedesktop.systemd1";
const MANAGER_PATH: &str = "/org/freedesktop/systemd1";
const MANAGER_INTERFACE: &str = "org.freedesktop.systemd1.Manager";
const UNIT_INTERFACE: &str = "org.freedesktop.systemd1.Unit";

/// A real unit's normalized read state — `P1-SYS-001`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnitState {
    pub load_state: String,
    pub active_state: String,
    pub sub_state: String,
    pub description: String,
}

/// Typed systemd read-provider failures — never collapsed into a generic
/// error, and never mapped to `NotAuthorized`/`AuthenticationUnavailable`
/// (this module performs no authorization operation at all).
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SystemdError {
    /// `systemd1` is not reachable on the bus at all.
    ProviderUnavailable(String),
    /// The named unit does not exist — `P1-SYS-002`, a real, distinct,
    /// typed "not found," never conflated with a provider outage.
    UnitNotFound(String),
    /// A real property response was malformed/incomplete.
    MalformedResponse(String),
}

impl std::fmt::Display for SystemdError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProviderUnavailable(message) => {
                write!(formatter, "systemd1 unavailable: {message}")
            }
            Self::UnitNotFound(unit) => write!(formatter, "unit not found: {unit}"),
            Self::MalformedResponse(message) => {
                write!(formatter, "malformed systemd1 response: {message}")
            }
        }
    }
}

impl std::error::Error for SystemdError {}

/// Normalizes an already-fetched `org.freedesktop.systemd1.Unit`
/// property map (Layer 1 testable — no D-Bus involved). Every field is
/// required; a missing field is a real [`SystemdError::MalformedResponse`],
/// never a silently-defaulted empty string.
///
/// # Errors
///
/// See [`SystemdError::MalformedResponse`].
pub fn normalize_unit_state<S: ::std::hash::BuildHasher>(
    properties: &std::collections::HashMap<String, OwnedValue, S>,
) -> Result<UnitState, SystemdError> {
    let string_field = |key: &str| -> Result<String, SystemdError> {
        properties
            .get(key)
            .and_then(|value| value.downcast_ref::<zbus::zvariant::Str>().ok())
            .map(|s| s.as_str().to_owned())
            .ok_or_else(|| SystemdError::MalformedResponse(format!("missing/invalid {key}")))
    };
    Ok(UnitState {
        load_state: string_field("LoadState")?,
        active_state: string_field("ActiveState")?,
        sub_state: string_field("SubState")?,
        description: string_field("Description")?,
    })
}

/// A real, live connection to `org.freedesktop.systemd1`. `unit_name`
/// must be an allowlisted, Guardian-known unit string — this type never
/// accepts an arbitrary caller-supplied unit as a trust boundary (the
/// allowlist itself is a `guardian-daemon` concern, not this adapter's).
pub struct SystemdProvider<'c> {
    connection: &'c Connection,
}

impl<'c> SystemdProvider<'c> {
    #[must_use]
    pub const fn new(connection: &'c Connection) -> Self {
        Self { connection }
    }

    /// Real probe: does `systemd1`'s well-known name currently have a
    /// real owner on this bus.
    pub async fn probe(&self) -> bool {
        let Ok(dbus) = zbus::fdo::DBusProxy::new(self.connection).await else {
            return false;
        };
        let Ok(destination) = zbus::names::BusName::try_from(DESTINATION) else {
            return false;
        };
        dbus.name_has_owner(destination).await.unwrap_or(false)
    }

    /// Real `LoadUnit` + real property read for one explicitly-named
    /// unit — `P1-SYS-001`/`P1-SYS-002`.
    ///
    /// # Errors
    ///
    /// See [`SystemdError`].
    pub async fn unit_state(&self, unit_name: &str) -> Result<UnitState, SystemdError> {
        let manager = zbus::Proxy::new(
            self.connection,
            DESTINATION,
            MANAGER_PATH,
            MANAGER_INTERFACE,
        )
        .await
        .map_err(|error| SystemdError::ProviderUnavailable(error.to_string()))?;

        let unit_path: zbus::zvariant::OwnedObjectPath = manager
            .call("LoadUnit", &(unit_name,))
            .await
            .map_err(|error| classify_load_unit_error(unit_name, &error))?;

        let properties_proxy = zbus::fdo::PropertiesProxy::builder(self.connection)
            .destination(DESTINATION)
            .map_err(|error| SystemdError::ProviderUnavailable(error.to_string()))?
            .path(unit_path)
            .map_err(|error| SystemdError::ProviderUnavailable(error.to_string()))?
            .build()
            .await
            .map_err(|error| SystemdError::ProviderUnavailable(error.to_string()))?;

        let properties: std::collections::HashMap<String, OwnedValue> = properties_proxy
            .get_all(
                zbus::names::InterfaceName::try_from(UNIT_INTERFACE)
                    .map_err(|error| SystemdError::MalformedResponse(error.to_string()))?,
            )
            .await
            .map_err(|error| SystemdError::MalformedResponse(error.to_string()))?;

        let state = normalize_unit_state(&properties)?;
        if state.load_state == "not-found" {
            return Err(SystemdError::UnitNotFound(unit_name.to_owned()));
        }
        Ok(state)
    }
}

fn classify_load_unit_error(unit_name: &str, error: &zbus::Error) -> SystemdError {
    if crate::providers::is_provider_absent_error(error) {
        return SystemdError::ProviderUnavailable(error.to_string());
    }
    if let zbus::Error::MethodError(name, _, _) = error {
        if name.as_str() == "org.freedesktop.systemd1.NoSuchUnit" {
            return SystemdError::UnitNotFound(unit_name.to_owned());
        }
    }
    SystemdError::MalformedResponse(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use zbus::zvariant::Str;

    fn property_map(fields: &[(&str, &str)]) -> HashMap<String, OwnedValue> {
        fields
            .iter()
            .map(|(key, value)| ((*key).to_owned(), OwnedValue::from(Str::from(*value))))
            .collect()
    }

    #[test]
    fn normalizes_a_complete_real_property_map() {
        let properties = property_map(&[
            ("LoadState", "loaded"),
            ("ActiveState", "active"),
            ("SubState", "running"),
            ("Description", "A Test Unit"),
        ]);
        let state = normalize_unit_state(&properties).unwrap();
        assert_eq!(state.load_state, "loaded");
        assert_eq!(state.active_state, "active");
        assert_eq!(state.sub_state, "running");
        assert_eq!(state.description, "A Test Unit");
    }

    #[test]
    fn missing_field_is_a_real_typed_error_not_a_default() {
        let properties = property_map(&[("LoadState", "loaded"), ("ActiveState", "active")]);
        let result = normalize_unit_state(&properties);
        assert!(matches!(result, Err(SystemdError::MalformedResponse(_))));
    }

    #[test]
    fn classify_load_unit_error_recognizes_no_such_unit() {
        let name =
            zbus::names::OwnedErrorName::try_from("org.freedesktop.systemd1.NoSuchUnit").unwrap();
        let error = zbus::Error::MethodError(name, None, dummy_message());
        let classified = classify_load_unit_error("nonexistent.service", &error);
        assert!(
            matches!(classified, SystemdError::UnitNotFound(unit) if unit == "nonexistent.service")
        );
    }

    #[test]
    fn classify_load_unit_error_treats_live_failures_as_malformed() {
        let error = zbus::Error::InvalidReply;
        let classified = classify_load_unit_error("some.service", &error);
        assert!(matches!(classified, SystemdError::MalformedResponse(_)));
    }

    #[test]
    fn classify_load_unit_error_treats_absent_provider_as_unavailable() {
        let name =
            zbus::names::OwnedErrorName::try_from("org.freedesktop.DBus.Error.ServiceUnknown")
                .unwrap();
        let error = zbus::Error::MethodError(name, None, dummy_message());
        let classified = classify_load_unit_error("some.service", &error);
        assert!(matches!(classified, SystemdError::ProviderUnavailable(_)));
    }

    fn dummy_message() -> zbus::message::Message {
        zbus::message::Message::method_call("/", "Ping")
            .unwrap()
            .build(&())
            .unwrap()
    }
}
