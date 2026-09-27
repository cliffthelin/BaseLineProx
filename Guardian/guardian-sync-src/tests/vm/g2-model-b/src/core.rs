//! G2 Model B prototype — unprivileged Guardian core.
//!
//! Runs as a dedicated unprivileged system user. Exposes only a read-only
//! bounded operation; never elevated, never in the write path. See
//! `docs/adr/ADR-002-guardian-privilege-topology.md` §"Model B — the relay
//! topology problem" for why this process deliberately does NOT relay
//! privileged writes to the helper.

use std::sync::atomic::{AtomicU32, Ordering};

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.Guardian1.G2ModelBCore";
const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/G2ModelBCore";

struct ModelBCore {
    read_count: AtomicU32,
}

#[zbus::interface(name = "io.github.cliffthelin.G2ModelBCore1")]
impl ModelBCore {
    fn read_status(&self) -> String {
        let n = self.read_count.fetch_add(1, Ordering::SeqCst) + 1;
        format!("core-status-ok reads={n}")
    }
}

fn main() -> zbus::Result<()> {
    let connection = zbus::blocking::connection::Builder::system()?
        .name(WELL_KNOWN_NAME)?
        .serve_at(
            OBJECT_PATH,
            ModelBCore {
                read_count: AtomicU32::new(0),
            },
        )?
        .build()?;
    eprintln!(
        "[g2-model-b-core] serving {WELL_KNOWN_NAME} at {OBJECT_PATH} (unprivileged), unique_name={}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}
