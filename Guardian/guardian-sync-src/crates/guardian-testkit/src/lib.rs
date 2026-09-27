//! Test support that never touches the host system bus.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};

pub struct PrivateSessionBus {
    child: Child,
    address: String,
}

impl PrivateSessionBus {
    /// Starts a private, non-system D-Bus daemon and captures its address.
    ///
    /// # Errors
    ///
    /// Returns an I/O error when `dbus-daemon` cannot be started or its address
    /// cannot be read.
    pub fn launch() -> std::io::Result<Self> {
        let mut child = Command::new("dbus-daemon")
            .args(["--session", "--nofork", "--print-address=1"])
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()?;
        let stdout = child.stdout.take().ok_or_else(|| {
            std::io::Error::other("dbus-daemon stdout was not available after piping")
        })?;
        let mut address = String::new();
        BufReader::new(stdout).read_line(&mut address)?;
        Ok(Self {
            child,
            address: address.trim().to_owned(),
        })
    }

    #[must_use]
    pub fn address(&self) -> &str {
        &self.address
    }
}

impl Drop for PrivateSessionBus {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
