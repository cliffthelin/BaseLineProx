use guardian_core::error::{GuardianDbusError, GuardianErrorCategory};
use std::collections::HashSet;
use zbus::DBusError;

const EXPECTED_ERROR_NAMES: [(GuardianErrorCategory, &str); 17] = [
    (
        GuardianErrorCategory::NotAuthorized,
        "io.github.cliffthelin.Guardian1.Error.NotAuthorized",
    ),
    (
        GuardianErrorCategory::AuthenticationUnavailable,
        "io.github.cliffthelin.Guardian1.Error.AuthenticationUnavailable",
    ),
    (
        GuardianErrorCategory::Unsupported,
        "io.github.cliffthelin.Guardian1.Error.Unsupported",
    ),
    (
        GuardianErrorCategory::ProviderUnavailable,
        "io.github.cliffthelin.Guardian1.Error.ProviderUnavailable",
    ),
    (
        GuardianErrorCategory::ProviderChanged,
        "io.github.cliffthelin.Guardian1.Error.ProviderChanged",
    ),
    (
        GuardianErrorCategory::PreconditionFailed,
        "io.github.cliffthelin.Guardian1.Error.PreconditionFailed",
    ),
    (
        GuardianErrorCategory::Conflict,
        "io.github.cliffthelin.Guardian1.Error.Conflict",
    ),
    (
        GuardianErrorCategory::Busy,
        "io.github.cliffthelin.Guardian1.Error.Busy",
    ),
    (
        GuardianErrorCategory::TimedOut,
        "io.github.cliffthelin.Guardian1.Error.TimedOut",
    ),
    (
        GuardianErrorCategory::Cancelled,
        "io.github.cliffthelin.Guardian1.Error.Cancelled",
    ),
    (
        GuardianErrorCategory::InvalidRequest,
        "io.github.cliffthelin.Guardian1.Error.InvalidRequest",
    ),
    (
        GuardianErrorCategory::Unsafe,
        "io.github.cliffthelin.Guardian1.Error.Unsafe",
    ),
    (
        GuardianErrorCategory::ApplyFailed,
        "io.github.cliffthelin.Guardian1.Error.ApplyFailed",
    ),
    (
        GuardianErrorCategory::ObservationFailed,
        "io.github.cliffthelin.Guardian1.Error.ObservationFailed",
    ),
    (
        GuardianErrorCategory::RollbackFailed,
        "io.github.cliffthelin.Guardian1.Error.RollbackFailed",
    ),
    (
        GuardianErrorCategory::PersistenceFailed,
        "io.github.cliffthelin.Guardian1.Error.PersistenceFailed",
    ),
    (
        GuardianErrorCategory::Internal,
        "io.github.cliffthelin.Guardian1.Error.Internal",
    ),
];

#[test]
fn p0_dbus_004_every_error_has_the_exact_native_dbus_identity() {
    let mut identities = HashSet::new();

    for (category, expected_name) in EXPECTED_ERROR_NAMES {
        assert_eq!(category.dbus_error_name(), expected_name);
        let native_error: GuardianDbusError = category.with_message("contract test");
        assert_eq!(native_error.name().as_str(), expected_name);
        assert!(identities.insert(expected_name));
    }

    assert_eq!(identities.len(), EXPECTED_ERROR_NAMES.len());
}
