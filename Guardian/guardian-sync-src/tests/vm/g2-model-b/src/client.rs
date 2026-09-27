//! G2 Model B prototype — client. Calls the core for reads and the helper
//! directly for the bounded write, demonstrating that the client itself
//! chooses which process to talk to; the core is never in the write path.

use std::process::ExitCode;

use zbus::blocking::{Connection, Proxy, connection};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mode = args.get(1).map(String::as_str).unwrap_or("write");
    let interactive: bool = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(false);

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

    if mode == "read" {
        let proxy = match Proxy::new(
            &connection,
            "io.github.cliffthelin.Guardian1.G2ModelBCore",
            "/io/github/cliffthelin/Guardian1/G2ModelBCore",
            "io.github.cliffthelin.G2ModelBCore1",
        ) {
            Ok(proxy) => proxy,
            Err(error) => {
                eprintln!("FAIL could not build core proxy: {error}");
                return ExitCode::from(2);
            }
        };
        match proxy.call::<_, _, String>("ReadStatus", &()) {
            Ok(status) => {
                println!("OK {status}");
                return ExitCode::SUCCESS;
            }
            Err(error) => {
                eprintln!("FAIL {error}");
                return ExitCode::from(2);
            }
        }
    }

    let proxy = match Proxy::new(
        &connection,
        "io.github.cliffthelin.Guardian1.G2ModelBHelper",
        "/io/github/cliffthelin/Guardian1/G2ModelBHelper",
        "io.github.cliffthelin.G2ModelBHelper1",
    ) {
        Ok(proxy) => proxy,
        Err(error) => {
            eprintln!("FAIL could not build helper proxy: {error}");
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
