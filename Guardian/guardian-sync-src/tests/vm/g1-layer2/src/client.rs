//! G1 Layer 2 real-host harness — client half.
//!
//! Calls the real-system-bus `AuthProbe1` object served by `g1-layer2-server`.
//! Run as different real OS users (`sudo -u <user> ...`) to exercise real,
//! distinct D-Bus caller identities. See `docs/evidence/g1/` for the setup
//! script this is used from.
//!
//! Usage:
//!   g1-layer2-client <action> <interactive: true|false> <claimed_uid> <claimed_username> <claimed_is_admin: true|false>
//!   action: read | low | moderate | high
//!
//! Prints `OK` and exits 0 on success, or `ERROR <dbus-error-name>` and exits
//! 1 on a structured D-Bus error, or `FAIL <message>` and exits 2 on any
//! other failure (never treated as an authorization outcome).

use std::process::ExitCode;

use zbus::blocking::{Connection, Proxy, connection};

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.Guardian1.G1LayerTwoHarness";
const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/G1LayerTwoHarness";
const INTERFACE: &str = "io.github.cliffthelin.AuthProbe1";

fn method_for(action: &str) -> Option<&'static str> {
    match action {
        "read" => Some("AttemptRead"),
        "low" => Some("AttemptLowRiskWrite"),
        "moderate" => Some("AttemptModerateWrite"),
        "high" => Some("AttemptHighRiskWrite"),
        _ => None,
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let [
        _,
        action,
        interactive,
        claimed_uid,
        claimed_username,
        claimed_is_admin,
    ] = args.as_slice()
    else {
        eprintln!(
            "usage: g1-layer2-client <read|low|moderate|high> <true|false interactive> <claimed_uid> <claimed_username> <true|false claimed_is_admin>"
        );
        return ExitCode::from(2);
    };
    let Some(method) = method_for(action) else {
        eprintln!("FAIL unknown action {action}");
        return ExitCode::from(2);
    };
    let interactive: bool = interactive.parse().unwrap_or(false);
    let claimed_uid: u32 = claimed_uid.parse().unwrap_or(0);
    let claimed_is_admin: bool = claimed_is_admin.parse().unwrap_or(false);

    let connection: Connection = match connection::Builder::system().and_then(|b| b.build()) {
        Ok(connection) => connection,
        Err(error) => {
            eprintln!("FAIL could not connect to system bus: {error}");
            return ExitCode::from(2);
        }
    };
    println!(
        "client real unique_name: {}",
        connection.unique_name().map_or("<none>", |n| n.as_str())
    );
    println!(
        "client real uid (from /proc/self/status): {}",
        std::fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|status| status
                .lines()
                .find(|line| line.starts_with("Uid:"))
                .map(str::to_owned))
            .unwrap_or_else(|| "<unknown>".to_owned())
    );

    let proxy = match Proxy::new(&connection, WELL_KNOWN_NAME, OBJECT_PATH, INTERFACE) {
        Ok(proxy) => proxy,
        Err(error) => {
            eprintln!("FAIL could not build proxy: {error}");
            return ExitCode::from(2);
        }
    };

    // Test-only synchronization hook: gives an external `pkttyagent` time to
    // register against this process's PID before the authorization call
    // fires, for P0-AUTH-005 VT text-authentication evidence.
    if let Ok(delay) = std::env::var("G1_DELAY_SECONDS") {
        if let Ok(seconds) = delay.parse::<u64>() {
            println!("client pid: {}", std::process::id());
            std::thread::sleep(std::time::Duration::from_secs(seconds));
        }
    }

    let result: zbus::Result<()> = proxy.call(
        method,
        &(
            interactive,
            claimed_uid,
            0u32,
            claimed_username.as_str(),
            "",
            claimed_is_admin,
        ),
    );

    match result {
        Ok(()) => {
            println!("OK");
            ExitCode::SUCCESS
        }
        Err(zbus::Error::MethodError(name, _, _)) => {
            println!("ERROR {}", name.as_str());
            ExitCode::from(1)
        }
        Err(error) => {
            eprintln!("FAIL non-structured error: {error}");
            ExitCode::from(2)
        }
    }
}
