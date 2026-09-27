//! G7 Class B EVIDENCE PROTOTYPE — NON-PRODUCTION. DISPOSABLE.
//! Trivial real D-Bus caller for `g7-class-b-daemon`, evidence use only.

fn main() -> zbus::Result<()> {
    let connection = zbus::blocking::Connection::system()?;
    let proxy = zbus::blocking::Proxy::new(
        &connection,
        "io.github.cliffthelin.G7ClassBPrototype1",
        "/io/github/cliffthelin/G7ClassBPrototype1",
        "io.github.cliffthelin.G7ClassBPrototype1",
    )?;
    let result: u64 = proxy.call("AttemptProviderDelegatedWrite", &())?;
    println!("{result}");
    Ok(())
}
