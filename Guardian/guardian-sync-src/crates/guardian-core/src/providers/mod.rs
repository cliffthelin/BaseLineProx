//! G8 — Initial Providers (`P1-SYS/PSI/LGI/UDS/UPW/ACC-*`). Every module
//! here is **read-only**: discovery, normalization, availability
//! detection, topology, and validation/rejection-before-write logic only.
//! No module in this tree contains a callable implementation of any
//! Guardian-owned or provider-owned privileged mutation — see each
//! module's own doc comment for the specific normative prohibition.

pub mod accounts;
pub mod health;
pub mod logind;
pub mod psi;
pub mod registry;
pub mod systemd;
pub mod udisks;
pub mod upower;

/// Shared "is this D-Bus failure a genuine provider-absence, or something
/// else" check for a `*Provider`'s first live call (`P1-*` read adapters
/// in `accounts`, `logind`, `upower`) — extracted here once three
/// independent modules needed the identical rule (real-VM/dbusmock
/// evidence: `zbus::Proxy::call()` surfaces a real absent well-known name
/// as `Error::MethodError` with the D-Bus standard `ServiceUnknown`/
/// `NameHasNoOwner` error name, not as `Error::FDO` — a first attempt at
/// this classifier matched only `Error::FDO` and silently misclassified
/// every raw-`Proxy::call()`-based provider's real outage as
/// `MalformedResponse`; caught only because real-VM evidence exercised the
/// actual wire shape, not an assumption about it). `udisks`'s own
/// `GetManagedObjects()` call already receives a `zbus::fdo::Error`
/// directly (via the typed `ObjectManagerProxy`) and matches its two
/// variants inline — it never routes through this helper.
#[must_use]
pub(crate) fn is_provider_absent_error(error: &zbus::Error) -> bool {
    fn is_absent_error_name(name: &str) -> bool {
        matches!(
            name,
            "org.freedesktop.DBus.Error.ServiceUnknown"
                | "org.freedesktop.DBus.Error.NameHasNoOwner"
        )
    }
    match error {
        zbus::Error::FDO(fdo_error) => matches!(
            fdo_error.as_ref(),
            zbus::fdo::Error::ServiceUnknown(_) | zbus::fdo::Error::NameHasNoOwner(_)
        ),
        zbus::Error::MethodError(name, _, _) => is_absent_error_name(name.as_str()),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::is_provider_absent_error;

    #[test]
    fn method_error_with_service_unknown_name_is_provider_absent() {
        let name =
            zbus::names::OwnedErrorName::try_from("org.freedesktop.DBus.Error.ServiceUnknown")
                .unwrap();
        let error = zbus::Error::MethodError(name, None, dummy_message());
        assert!(is_provider_absent_error(&error));
    }

    #[test]
    fn method_error_with_unrelated_name_is_not_provider_absent() {
        let name =
            zbus::names::OwnedErrorName::try_from("org.freedesktop.DBus.Error.UnknownMethod")
                .unwrap();
        let error = zbus::Error::MethodError(name, None, dummy_message());
        assert!(!is_provider_absent_error(&error));
    }

    #[test]
    fn fdo_service_unknown_is_provider_absent() {
        let error = zbus::Error::FDO(Box::new(zbus::fdo::Error::ServiceUnknown(
            "gone".to_owned(),
        )));
        assert!(is_provider_absent_error(&error));
    }

    #[test]
    fn invalid_reply_is_not_provider_absent() {
        assert!(!is_provider_absent_error(&zbus::Error::InvalidReply));
    }

    fn dummy_message() -> zbus::message::Message {
        zbus::message::Message::method_call("/", "Ping")
            .unwrap()
            .build(&())
            .unwrap()
    }
}
