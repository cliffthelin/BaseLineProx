//! Minimal, read-only G0 D-Bus contract export.

pub mod dbus_surface;

pub const INTERFACE_NAME: &str = "io.github.cliffthelin.Guardian1";
pub const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1";

pub struct GuardianContract {
    contract_version: &'static str,
    service_state: &'static str,
}

impl Default for GuardianContract {
    fn default() -> Self {
        Self {
            contract_version: "1.0",
            service_state: "contract-only",
        }
    }
}

#[zbus::interface(name = "io.github.cliffthelin.Guardian1")]
impl GuardianContract {
    /// The additive API contract version within interface major 1.
    fn contract_version(&self) -> &str {
        self.contract_version
    }

    /// Explicitly communicates that this G0 skeleton performs no system writes.
    fn service_state(&self) -> &str {
        self.service_state
    }
}
