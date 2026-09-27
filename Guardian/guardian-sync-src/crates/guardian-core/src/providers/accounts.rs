//! G8 `AccountsService` read/validation provider (`P1-ACC-001..003`;
//! contract §28). Native `org.freedesktop.Accounts` D-Bus for provider/
//! user discovery; installed-session enumeration is a real filesystem
//! scan of `/usr/share/{xsessions,wayland-sessions}/*.desktop` — the
//! correct next layer down the accepted hierarchy, since no D-Bus
//! enumeration API for *available* session types exists on any Guardian
//! target desktop (this is the same mechanism GDM/LightDM/SDDM
//! themselves use).
//!
//! **Read-only, normatively enforced**: this module contains no callable
//! implementation of `SetSession()` or `SetXSession()` — not "untested,"
//! genuinely absent from the codebase. It implements only discovery,
//! enumeration, and validation/rejection-before-write
//! (`P1-ACC-003`). Any future evidence-only session-write experiment
//! belongs in a disposable prototype, never here.

use std::fs;
use std::path::PathBuf;

use zbus::Connection;

const DESTINATION: &str = "org.freedesktop.Accounts";
const MANAGER_PATH: &str = "/org/freedesktop/Accounts";
const MANAGER_INTERFACE: &str = "org.freedesktop.Accounts";

/// One installed, selectable session — `P1-ACC-002`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SessionDescriptor {
    /// The `.desktop` file's stem — the real, stable identity
    /// `SetSession()` would eventually take, per contract §28's
    /// preference for `SetSession()` over `.dmrc`.
    pub id: String,
    pub display_name: String,
    pub is_wayland: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AccountsError {
    ProviderUnavailable(String),
    MalformedResponse(String),
}

impl std::fmt::Display for AccountsError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProviderUnavailable(message) => {
                write!(formatter, "AccountsService unavailable: {message}")
            }
            Self::MalformedResponse(message) => {
                write!(formatter, "malformed AccountsService response: {message}")
            }
        }
    }
}

impl std::error::Error for AccountsError {}

/// `P1-ACC-003`: a requested session identifier that does not match any
/// real installed session. Rejected **before** any write — and since no
/// write exists in this gate's production code at all, this is the
/// terminal outcome for an invalid request, not a precondition for one.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InvalidSession(pub String);

impl std::fmt::Display for InvalidSession {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "invalid session identifier: {}", self.0)
    }
}

impl std::error::Error for InvalidSession {}

/// Real filesystem scan for installed sessions (Layer 1 testable via
/// injectable directories). A `.desktop` file with no readable `Name=`
/// field is skipped, not fabricated.
#[must_use]
pub fn scan_installed_sessions(directories: &[(PathBuf, bool)]) -> Vec<SessionDescriptor> {
    let mut sessions = Vec::new();
    for (directory, is_wayland) in directories {
        let Ok(entries) = fs::read_dir(directory) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("desktop") {
                continue;
            }
            let Some(id) = path.file_stem().and_then(|stem| stem.to_str()) else {
                continue;
            };
            let Ok(contents) = fs::read_to_string(&path) else {
                continue;
            };
            if let Some(display_name) = parse_desktop_entry_name(&contents) {
                sessions.push(SessionDescriptor {
                    id: id.to_owned(),
                    display_name,
                    is_wayland: *is_wayland,
                });
            }
        }
    }
    sessions
}

fn parse_desktop_entry_name(contents: &str) -> Option<String> {
    contents
        .lines()
        .find_map(|line| line.strip_prefix("Name=").map(str::to_owned))
}

/// The real, standard installed-session directories.
#[must_use]
pub fn real_session_directories() -> Vec<(PathBuf, bool)> {
    vec![
        (PathBuf::from("/usr/share/xsessions"), false),
        (PathBuf::from("/usr/share/wayland-sessions"), true),
    ]
}

/// `P1-ACC-003` — pure validation logic, no write anywhere near it.
///
/// # Errors
///
/// Returns [`InvalidSession`] if `requested` does not match any installed
/// session's `id`.
pub fn validate_session_id(
    requested: &str,
    installed: &[SessionDescriptor],
) -> Result<SessionDescriptor, InvalidSession> {
    installed
        .iter()
        .find(|session| session.id == requested)
        .cloned()
        .ok_or_else(|| InvalidSession(requested.to_owned()))
}

pub struct AccountsProvider<'c> {
    connection: &'c Connection,
}

impl<'c> AccountsProvider<'c> {
    #[must_use]
    pub const fn new(connection: &'c Connection) -> Self {
        Self { connection }
    }

    /// Real probe — `P1-ACC-001`.
    pub async fn probe(&self) -> bool {
        let Ok(dbus) = zbus::fdo::DBusProxy::new(self.connection).await else {
            return false;
        };
        let Ok(destination) = zbus::names::BusName::try_from(DESTINATION) else {
            return false;
        };
        dbus.name_has_owner(destination).await.unwrap_or(false)
    }

    /// Real `ListCachedUsers` — user/session context discovery.
    ///
    /// # Errors
    ///
    /// See [`AccountsError`].
    pub async fn list_cached_users(
        &self,
    ) -> Result<Vec<zbus::zvariant::OwnedObjectPath>, AccountsError> {
        let manager = zbus::Proxy::new(
            self.connection,
            DESTINATION,
            MANAGER_PATH,
            MANAGER_INTERFACE,
        )
        .await
        .map_err(|error| AccountsError::ProviderUnavailable(error.to_string()))?;

        manager
            .call("ListCachedUsers", &())
            .await
            .map_err(|error| classify_list_cached_users_error(&error))
    }
}

/// `ListCachedUsers` is `list_cached_users`' first live call — nothing
/// earlier has confirmed `Accounts` is actually present. `ServiceUnknown`/
/// `NameHasNoOwner` (confirmed via real-VM evidence: masking `Accounts`
/// produces exactly `ServiceUnknown`) mean the provider itself is
/// unreachable — `ProviderUnavailable`. Any other failure means a real
/// response interaction happened at all (confirmed via dbusmock evidence:
/// a live mock returning the wrong signature produces a real
/// `InvalidReply`-shaped error here, not `ServiceUnknown`) — that is a
/// malformed response, never conflated with the provider being absent.
fn classify_list_cached_users_error(error: &zbus::Error) -> AccountsError {
    if crate::providers::is_provider_absent_error(error) {
        AccountsError::ProviderUnavailable(error.to_string())
    } else {
        AccountsError::MalformedResponse(error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("accounts-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn scans_valid_desktop_files_and_skips_unreadable_ones() {
        let dir = temp_dir("scan-valid");
        fs::write(
            dir.join("ubuntu.desktop"),
            "[Desktop Entry]\nName=Ubuntu\nType=XSession\n",
        )
        .unwrap();
        fs::write(dir.join("not-a-session.txt"), "irrelevant").unwrap();
        fs::write(
            dir.join("broken.desktop"),
            "[Desktop Entry]\nType=XSession\n",
        )
        .unwrap();

        let sessions = scan_installed_sessions(&[(dir, false)]);
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions[0].id, "ubuntu");
        assert_eq!(sessions[0].display_name, "Ubuntu");
        assert!(!sessions[0].is_wayland);
    }

    #[test]
    fn wayland_directory_is_marked_correctly() {
        let dir = temp_dir("wayland");
        fs::write(
            dir.join("ubuntu-wayland.desktop"),
            "[Desktop Entry]\nName=Ubuntu (Wayland)\n",
        )
        .unwrap();
        let sessions = scan_installed_sessions(&[(dir, true)]);
        assert_eq!(sessions.len(), 1);
        assert!(sessions[0].is_wayland);
    }

    #[test]
    fn valid_session_id_validates_successfully() {
        let installed = vec![SessionDescriptor {
            id: "ubuntu".to_owned(),
            display_name: "Ubuntu".to_owned(),
            is_wayland: false,
        }];
        let result = validate_session_id("ubuntu", &installed);
        assert!(result.is_ok());
    }

    #[test]
    fn invalid_session_id_is_rejected_before_any_write() {
        let installed = vec![SessionDescriptor {
            id: "ubuntu".to_owned(),
            display_name: "Ubuntu".to_owned(),
            is_wayland: false,
        }];
        let result = validate_session_id("not-a-real-session", &installed);
        assert_eq!(result, Err(InvalidSession("not-a-real-session".to_owned())));
    }

    #[test]
    fn nonexistent_directory_yields_empty_not_an_error() {
        let sessions = scan_installed_sessions(&[(PathBuf::from("/nonexistent/path/xyz"), false)]);
        assert!(sessions.is_empty());
    }

    /// Real-VM regression (G8 evidence): masking `Accounts` produced a
    /// real `ServiceUnknown` error from `ListCachedUsers`, and the
    /// production code originally misclassified it as `MalformedResponse`
    /// — a real provider outage must never be reported as a malformed
    /// response.
    #[test]
    fn list_cached_users_failure_is_provider_unavailable_not_malformed() {
        // Real-VM/dbusmock evidence: a genuinely absent `Accounts` makes
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
        let classified = classify_list_cached_users_error(&error);
        assert!(matches!(classified, AccountsError::ProviderUnavailable(_)));
    }

    /// Real dbusmock regression (G8 evidence): a live mock returning the
    /// wrong method signature produced a real (non-`ServiceUnknown`)
    /// error, and the production code originally misclassified it as
    /// `ProviderUnavailable` too — a real, live response with the wrong
    /// shape must be reported as malformed, never conflated with the
    /// provider being absent.
    #[test]
    fn list_cached_users_signature_mismatch_is_malformed_not_provider_unavailable() {
        let error = zbus::Error::InvalidReply;
        let classified = classify_list_cached_users_error(&error);
        assert!(matches!(classified, AccountsError::MalformedResponse(_)));
    }
}
