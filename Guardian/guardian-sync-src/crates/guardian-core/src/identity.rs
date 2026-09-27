//! Caller identity resolved from the real D-Bus connection.
//!
//! Guardian authorizes callers using only the sender recorded by the D-Bus
//! daemon on the message that carried the request, plus a live query of that
//! sender's real OS credentials. Client-supplied method arguments never
//! contribute to a [`CallerIdentity`] — there is no field here for them to
//! occupy (TDD contract §8.1; P0-AUTH-001).

use zbus::Connection;
use zbus::fdo::DBusProxy;
use zbus::message::Header;
use zbus::names::BusName;

/// Identity of the real D-Bus caller, resolved from the connection a request
/// arrived on.
///
/// This type is deliberately constructible only from [`resolve_caller_identity`]
/// in production code paths; nothing here is ever populated from a method
/// argument supplied by the calling client.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CallerIdentity {
    unique_name: String,
    uid: Option<u32>,
}

impl CallerIdentity {
    /// Constructs a caller identity from an already-resolved unique bus name
    /// and, where available, the real OS user id of the connecting process.
    #[must_use]
    pub fn new(unique_name: impl Into<String>, uid: Option<u32>) -> Self {
        Self {
            unique_name: unique_name.into(),
            uid,
        }
    }

    /// The real D-Bus unique connection name of the caller (e.g. `:1.42`).
    #[must_use]
    pub fn unique_name(&self) -> &str {
        &self.unique_name
    }

    /// The real OS user id of the caller, when the underlying transport and
    /// bus daemon could report it. `None` is an honest "unknown", never a
    /// fabricated default.
    #[must_use]
    pub const fn uid(&self) -> Option<u32> {
        self.uid
    }
}

/// Resolves the real caller identity of `header`'s sender on `connection`.
///
/// Uses only the D-Bus message header's `sender` field (set by the bus daemon
/// itself, not by the client) and a live
/// `org.freedesktop.DBus.GetConnectionUnixUser` query against that sender.
/// Client-supplied method arguments are never consulted.
///
/// Returns `Ok(None)` only if the header carries no sender at all, which does
/// not happen for ordinary method-call dispatch on a bus that enforces sender
/// tagging (every bus Guardian targets).
///
/// # Errors
///
/// Returns an error if the connection itself fails while resolving identity
/// (a structural failure, not an authorization outcome). An unavailable UID
/// query is represented as `uid: None` on the returned identity, not as an
/// error — TDD contract's registry rule against converting `UNKNOWN` into a
/// fabricated value applies here too.
pub async fn resolve_caller_identity(
    connection: &Connection,
    header: &Header<'_>,
) -> zbus::Result<Option<CallerIdentity>> {
    let Some(sender) = header.sender() else {
        return Ok(None);
    };
    let unique_name = sender.to_string();
    let dbus_proxy = DBusProxy::new(connection).await?;
    let bus_name: BusName<'_> = sender.clone().into();
    let uid = dbus_proxy.get_connection_unix_user(bus_name).await.ok();
    Ok(Some(CallerIdentity::new(unique_name, uid)))
}
