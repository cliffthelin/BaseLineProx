//! G8 `UPower` read provider (`P1-UPW-001..002`). Native
//! `org.freedesktop.UPower` D-Bus only. Treated purely as telemetry — no
//! write capability of any kind exists or is planned for this provider.

use zbus::Connection;
use zbus::zvariant::OwnedValue;

const DESTINATION: &str = "org.freedesktop.UPower";
const MANAGER_PATH: &str = "/org/freedesktop/UPower";
const MANAGER_INTERFACE: &str = "org.freedesktop.UPower";
const DEVICE_INTERFACE: &str = "org.freedesktop.UPower.Device";

/// The display device's normalized read state — `P1-UPW-001`.
#[derive(Clone, Debug, PartialEq)]
pub struct DisplayDeviceState {
    pub kind: u32,
    pub percentage: f64,
    pub state: u32,
    pub is_present: bool,
}

/// A desktop's honest battery-presence fact — `P1-UPW-002`. `NotPresent`
/// is a healthy, real state, never conflated with `Unavailable` (the
/// device category simply does not exist on this machine; the provider
/// itself is working correctly).
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BatteryPresence {
    Present,
    NotPresent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UpowerError {
    ProviderUnavailable(String),
    MalformedResponse(String),
}

impl std::fmt::Display for UpowerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProviderUnavailable(message) => {
                write!(formatter, "UPower unavailable: {message}")
            }
            Self::MalformedResponse(message) => {
                write!(formatter, "malformed UPower response: {message}")
            }
        }
    }
}

impl std::error::Error for UpowerError {}

/// Normalizes an already-fetched `Device` property map (Layer 1
/// testable).
///
/// # Errors
///
/// Returns [`UpowerError::MalformedResponse`] if a required field is
/// missing or the wrong type.
pub fn normalize_display_device<S: ::std::hash::BuildHasher>(
    properties: &std::collections::HashMap<String, OwnedValue, S>,
) -> Result<DisplayDeviceState, UpowerError> {
    let get_u32 = |key: &str| -> Result<u32, UpowerError> {
        properties
            .get(key)
            .and_then(|v| v.downcast_ref::<u32>().ok())
            .ok_or_else(|| UpowerError::MalformedResponse(format!("missing/invalid {key}")))
    };
    let get_f64 = |key: &str| -> Result<f64, UpowerError> {
        properties
            .get(key)
            .and_then(|v| v.downcast_ref::<f64>().ok())
            .ok_or_else(|| UpowerError::MalformedResponse(format!("missing/invalid {key}")))
    };
    let get_bool = |key: &str| -> Result<bool, UpowerError> {
        properties
            .get(key)
            .and_then(|v| v.downcast_ref::<bool>().ok())
            .ok_or_else(|| UpowerError::MalformedResponse(format!("missing/invalid {key}")))
    };
    Ok(DisplayDeviceState {
        kind: get_u32("Type")?,
        percentage: get_f64("Percentage")?,
        state: get_u32("State")?,
        is_present: get_bool("IsPresent")?,
    })
}

pub struct UpowerProvider<'c> {
    connection: &'c Connection,
}

impl<'c> UpowerProvider<'c> {
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

    /// Real `GetDisplayDevice` + property read — `P1-UPW-001`.
    ///
    /// # Errors
    ///
    /// See [`UpowerError`].
    pub async fn display_device(&self) -> Result<DisplayDeviceState, UpowerError> {
        let manager = zbus::Proxy::new(
            self.connection,
            DESTINATION,
            MANAGER_PATH,
            MANAGER_INTERFACE,
        )
        .await
        .map_err(|error| UpowerError::ProviderUnavailable(error.to_string()))?;

        let device_path: zbus::zvariant::OwnedObjectPath = manager
            .call("GetDisplayDevice", &())
            .await
            .map_err(|error| classify_live_call_error(&error))?;

        let properties_proxy = zbus::fdo::PropertiesProxy::builder(self.connection)
            .destination(DESTINATION)
            .map_err(|error| UpowerError::ProviderUnavailable(error.to_string()))?
            .path(device_path)
            .map_err(|error| UpowerError::ProviderUnavailable(error.to_string()))?
            .build()
            .await
            .map_err(|error| UpowerError::ProviderUnavailable(error.to_string()))?;

        let properties: std::collections::HashMap<String, OwnedValue> = properties_proxy
            .get_all(
                zbus::names::InterfaceName::try_from(DEVICE_INTERFACE)
                    .map_err(|error| UpowerError::MalformedResponse(error.to_string()))?,
            )
            .await
            .map_err(|error| UpowerError::MalformedResponse(error.to_string()))?;

        normalize_display_device(&properties)
    }

    /// Real `EnumerateDevices`, classified for the honest battery-presence
    /// fact — `P1-UPW-002`. `Type == 2` (`Battery`, `UPower`'s own ABI
    /// constant) present in the enumeration means `Present`; an empty or
    /// battery-free enumeration on a real desktop is `NotPresent`, not an
    /// error.
    ///
    /// # Errors
    ///
    /// See [`UpowerError`].
    pub async fn battery_presence(&self) -> Result<BatteryPresence, UpowerError> {
        const UPOWER_DEVICE_TYPE_BATTERY: u32 = 2;
        let manager = zbus::Proxy::new(
            self.connection,
            DESTINATION,
            MANAGER_PATH,
            MANAGER_INTERFACE,
        )
        .await
        .map_err(|error| UpowerError::ProviderUnavailable(error.to_string()))?;

        let device_paths: Vec<zbus::zvariant::OwnedObjectPath> = manager
            .call("EnumerateDevices", &())
            .await
            .map_err(|error| classify_enumerate_devices_error(&error))?;

        for path in device_paths {
            let device_proxy =
                zbus::Proxy::new(self.connection, DESTINATION, path, DEVICE_INTERFACE)
                    .await
                    .map_err(|error| UpowerError::ProviderUnavailable(error.to_string()))?;
            let kind = device_proxy
                .get_property::<u32>("Type")
                .await
                .map_err(|error| classify_live_call_error(&error))?;
            if kind == UPOWER_DEVICE_TYPE_BATTERY {
                return Ok(BatteryPresence::Present);
            }
        }
        Ok(BatteryPresence::NotPresent)
    }
}

/// `EnumerateDevices` is `battery_presence`'s first live call — nothing
/// earlier in this method call chain has confirmed `UPower` is actually
/// present, so any failure here (in particular a real
/// `org.freedesktop.DBus.Error.ServiceUnknown`, confirmed via real-VM
/// evidence: masking `UPower` produces exactly this error) means the
/// provider itself is unreachable, never a malformed *response* — there is
/// no response yet to be malformed. Mirrors `display_device`'s identical
/// treatment of its own first call (`GetDisplayDevice`).
fn classify_enumerate_devices_error(error: &zbus::Error) -> UpowerError {
    classify_live_call_error(error)
}

fn classify_live_call_error(error: &zbus::Error) -> UpowerError {
    if crate::providers::is_provider_absent_error(error) {
        UpowerError::ProviderUnavailable(error.to_string())
    } else {
        UpowerError::MalformedResponse(error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn property_map(
        fields: &[(&str, OwnedValue)],
    ) -> std::collections::HashMap<String, OwnedValue> {
        fields
            .iter()
            .map(|(key, value)| ((*key).to_owned(), value.clone()))
            .collect()
    }

    #[test]
    fn normalizes_a_complete_display_device() {
        let properties = property_map(&[
            ("Type", OwnedValue::from(2u32)),
            ("Percentage", OwnedValue::from(87.5f64)),
            ("State", OwnedValue::from(1u32)),
            ("IsPresent", OwnedValue::from(true)),
        ]);
        let state = normalize_display_device(&properties).unwrap();
        assert_eq!(state.kind, 2);
        assert!((state.percentage - 87.5).abs() < f64::EPSILON);
        assert_eq!(state.state, 1);
        assert!(state.is_present);
    }

    #[test]
    fn missing_field_is_a_real_typed_error() {
        let properties = property_map(&[("Type", OwnedValue::from(2u32))]);
        let result = normalize_display_device(&properties);
        assert!(matches!(result, Err(UpowerError::MalformedResponse(_))));
    }

    /// Real-VM regression (G8 evidence): masking `UPower` produced a real
    /// `ServiceUnknown` error from `EnumerateDevices`, and the production
    /// code originally misclassified it as `MalformedResponse` — a real
    /// provider outage must never be reported as a malformed response.
    #[test]
    fn enumerate_devices_failure_is_provider_unavailable_not_malformed() {
        // Real-VM/dbusmock evidence: a genuinely absent `UPower` makes
        // `zbus::Proxy::call()` surface `Error::MethodError` carrying the
        // D-Bus standard `ServiceUnknown` error name -- not `Error::FDO`,
        // which an earlier version of this classifier assumed and which
        // silently regressed this exact case (caught only by real
        // evidence, not by reasoning about the type alone).
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
        let classified = classify_enumerate_devices_error(&error);
        assert!(matches!(classified, UpowerError::ProviderUnavailable(_)));
    }

    /// Real dbusmock regression (G8 evidence): a live mock returning the
    /// wrong method signature produced a real (non-`ServiceUnknown`)
    /// error — a real, live response with the wrong shape must be
    /// reported as malformed, never conflated with the provider being
    /// absent.
    #[test]
    fn enumerate_devices_signature_mismatch_is_malformed_not_provider_unavailable() {
        let error = zbus::Error::InvalidReply;
        let classified = classify_enumerate_devices_error(&error);
        assert!(matches!(classified, UpowerError::MalformedResponse(_)));
    }

    #[test]
    fn display_device_live_failure_is_malformed_not_provider_unavailable() {
        assert!(matches!(
            classify_live_call_error(&zbus::Error::InvalidReply),
            UpowerError::MalformedResponse(_)
        ));
    }
}
