//! Stable public error categories and deterministic D-Bus identities.

const ERROR_PREFIX: &str = "io.github.cliffthelin.Guardian1.Error";

/// D-Bus-native Guardian errors exposed at the public IPC boundary.
#[derive(Debug, zbus::DBusError)]
#[zbus(prefix = "io.github.cliffthelin.Guardian1.Error", impl_display = true)]
pub enum GuardianDbusError {
    NotAuthorized(String),
    AuthenticationUnavailable(String),
    Unsupported(String),
    ProviderUnavailable(String),
    ProviderChanged(String),
    PreconditionFailed(String),
    Conflict(String),
    Busy(String),
    TimedOut(String),
    Cancelled(String),
    InvalidRequest(String),
    Unsafe(String),
    ApplyFailed(String),
    ObservationFailed(String),
    RollbackFailed(String),
    PersistenceFailed(String),
    Internal(String),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GuardianErrorCategory {
    NotAuthorized,
    AuthenticationUnavailable,
    Unsupported,
    ProviderUnavailable,
    ProviderChanged,
    PreconditionFailed,
    Conflict,
    Busy,
    TimedOut,
    Cancelled,
    InvalidRequest,
    Unsafe,
    ApplyFailed,
    ObservationFailed,
    RollbackFailed,
    PersistenceFailed,
    Internal,
}

pub const ALL_ERROR_CATEGORIES: [GuardianErrorCategory; 17] = [
    GuardianErrorCategory::NotAuthorized,
    GuardianErrorCategory::AuthenticationUnavailable,
    GuardianErrorCategory::Unsupported,
    GuardianErrorCategory::ProviderUnavailable,
    GuardianErrorCategory::ProviderChanged,
    GuardianErrorCategory::PreconditionFailed,
    GuardianErrorCategory::Conflict,
    GuardianErrorCategory::Busy,
    GuardianErrorCategory::TimedOut,
    GuardianErrorCategory::Cancelled,
    GuardianErrorCategory::InvalidRequest,
    GuardianErrorCategory::Unsafe,
    GuardianErrorCategory::ApplyFailed,
    GuardianErrorCategory::ObservationFailed,
    GuardianErrorCategory::RollbackFailed,
    GuardianErrorCategory::PersistenceFailed,
    GuardianErrorCategory::Internal,
];

impl GuardianErrorCategory {
    /// Creates the corresponding native D-Bus error with human-readable detail.
    #[must_use]
    pub fn with_message(self, message: impl Into<String>) -> GuardianDbusError {
        let message = message.into();
        match self {
            Self::NotAuthorized => GuardianDbusError::NotAuthorized(message),
            Self::AuthenticationUnavailable => {
                GuardianDbusError::AuthenticationUnavailable(message)
            }
            Self::Unsupported => GuardianDbusError::Unsupported(message),
            Self::ProviderUnavailable => GuardianDbusError::ProviderUnavailable(message),
            Self::ProviderChanged => GuardianDbusError::ProviderChanged(message),
            Self::PreconditionFailed => GuardianDbusError::PreconditionFailed(message),
            Self::Conflict => GuardianDbusError::Conflict(message),
            Self::Busy => GuardianDbusError::Busy(message),
            Self::TimedOut => GuardianDbusError::TimedOut(message),
            Self::Cancelled => GuardianDbusError::Cancelled(message),
            Self::InvalidRequest => GuardianDbusError::InvalidRequest(message),
            Self::Unsafe => GuardianDbusError::Unsafe(message),
            Self::ApplyFailed => GuardianDbusError::ApplyFailed(message),
            Self::ObservationFailed => GuardianDbusError::ObservationFailed(message),
            Self::RollbackFailed => GuardianDbusError::RollbackFailed(message),
            Self::PersistenceFailed => GuardianDbusError::PersistenceFailed(message),
            Self::Internal => GuardianDbusError::Internal(message),
        }
    }

    #[must_use]
    pub const fn dbus_error_name(self) -> &'static str {
        match self {
            Self::NotAuthorized => {
                concat!("io.github.cliffthelin.Guardian1.Error", ".NotAuthorized")
            }
            Self::AuthenticationUnavailable => concat!(
                "io.github.cliffthelin.Guardian1.Error",
                ".AuthenticationUnavailable"
            ),
            Self::Unsupported => concat!("io.github.cliffthelin.Guardian1.Error", ".Unsupported"),
            Self::ProviderUnavailable => concat!(
                "io.github.cliffthelin.Guardian1.Error",
                ".ProviderUnavailable"
            ),
            Self::ProviderChanged => {
                concat!("io.github.cliffthelin.Guardian1.Error", ".ProviderChanged")
            }
            Self::PreconditionFailed => concat!(
                "io.github.cliffthelin.Guardian1.Error",
                ".PreconditionFailed"
            ),
            Self::Conflict => concat!("io.github.cliffthelin.Guardian1.Error", ".Conflict"),
            Self::Busy => concat!("io.github.cliffthelin.Guardian1.Error", ".Busy"),
            Self::TimedOut => concat!("io.github.cliffthelin.Guardian1.Error", ".TimedOut"),
            Self::Cancelled => concat!("io.github.cliffthelin.Guardian1.Error", ".Cancelled"),
            Self::InvalidRequest => {
                concat!("io.github.cliffthelin.Guardian1.Error", ".InvalidRequest")
            }
            Self::Unsafe => concat!("io.github.cliffthelin.Guardian1.Error", ".Unsafe"),
            Self::ApplyFailed => concat!("io.github.cliffthelin.Guardian1.Error", ".ApplyFailed"),
            Self::ObservationFailed => concat!(
                "io.github.cliffthelin.Guardian1.Error",
                ".ObservationFailed"
            ),
            Self::RollbackFailed => {
                concat!("io.github.cliffthelin.Guardian1.Error", ".RollbackFailed")
            }
            Self::PersistenceFailed => concat!(
                "io.github.cliffthelin.Guardian1.Error",
                ".PersistenceFailed"
            ),
            Self::Internal => concat!("io.github.cliffthelin.Guardian1.Error", ".Internal"),
        }
    }

    #[must_use]
    pub const fn error_prefix() -> &'static str {
        ERROR_PREFIX
    }
}
