//! G2 Model A prototype — client for the hardened privileged daemon.

use std::process::ExitCode;

use zbus::blocking::{Connection, Proxy, connection};

const WELL_KNOWN_NAME: &str = "io.github.cliffthelin.Guardian1.G2ModelA";
const OBJECT_PATH: &str = "/io/github/cliffthelin/Guardian1/G2ModelA";
const INTERFACE: &str = "io.github.cliffthelin.G2ModelA1";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let interactive: bool = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(false);

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

    let proxy = match Proxy::new(&connection, WELL_KNOWN_NAME, OBJECT_PATH, INTERFACE) {
        Ok(proxy) => proxy,
        Err(error) => {
            eprintln!("FAIL could not build proxy: {error}");
            return ExitCode::from(2);
        }
    };

    let result: zbus::Result<()> = proxy.call("AttemptBoundedWrite", &(interactive,));
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
