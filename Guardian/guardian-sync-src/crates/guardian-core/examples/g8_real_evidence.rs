//! G8 Layer 4 real-system evidence gathering. Exercises all six real
//! provider adapters against whatever system bus/kernel this binary runs
//! on. Intended to run only inside a disposable VM (never the primary
//! workstation) — see `docs/evidence/g8/`. Read-only by construction: this
//! binary performs no write, and calls no method named or semantically
//! equivalent to `PowerOff`, `SetSession`, `StartUnit`/`StopUnit`/
//! `RestartUnit`, or `Inhibit`.

use guardian_core::providers::accounts::{self, AccountsProvider};
use guardian_core::providers::logind::LogindProvider;
use guardian_core::providers::psi::PsiFileSource;
use guardian_core::providers::registry;
use guardian_core::providers::systemd::SystemdProvider;
use guardian_core::providers::udisks::{self, UdisksProvider};
use guardian_core::providers::upower::UpowerProvider;
use guardian_core::psi::PsiResourceKind;
use zbus::Connection;

fn section(title: &str) {
    println!("\n=== {title} ===");
}

fn psi_evidence() {
    section("PSI (P1-PSI-001..005) — production crate::psi reuse, kernel files");
    let psi = PsiFileSource::real();
    for (kind, name) in [
        (PsiResourceKind::Cpu, "cpu"),
        (PsiResourceKind::Memory, "memory"),
        (PsiResourceKind::Io, "io"),
    ] {
        println!("  path({name}) = {}", psi.path(kind).display());
        println!("  read({name}) = {:?}", psi.read(kind));
    }
}

async fn systemd_evidence(connection: &Connection) {
    section("systemd (P1-SYS-001..003)");
    let systemd = SystemdProvider::new(connection);
    println!("  probe() = {}", systemd.probe().await);
    for unit in ["systemd-logind.service", "cron.service"] {
        println!(
            "  unit_state({unit}) = {:?}",
            systemd.unit_state(unit).await
        );
    }
    println!(
        "  unit_state(nonexistent) = {:?}",
        systemd
            .unit_state("guardian-g8-nonexistent-unit-evidence.service")
            .await
    );
}

async fn logind_evidence(connection: &Connection) {
    section("logind (P1-LGI-001..002)");
    let logind = LogindProvider::new(connection);
    println!("  probe() = {}", logind.probe().await);
    println!("  list_inhibitors() = {:?}", logind.list_inhibitors().await);
}

async fn upower_evidence(connection: &Connection) {
    section("UPower (P1-UPW-001..002)");
    let upower = UpowerProvider::new(connection);
    println!("  probe() = {}", upower.probe().await);
    println!("  display_device() = {:?}", upower.display_device().await);
    println!(
        "  battery_presence() = {:?}",
        upower.battery_presence().await
    );
}

async fn accounts_evidence(connection: &Connection) {
    section("AccountsService (P1-ACC-001..003)");
    let accounts_provider = AccountsProvider::new(connection);
    println!("  probe() = {}", accounts_provider.probe().await);
    println!(
        "  list_cached_users() = {:?}",
        accounts_provider.list_cached_users().await
    );
    let installed = accounts::scan_installed_sessions(&accounts::real_session_directories());
    println!("  scan_installed_sessions() = {installed:?}");
    println!(
        "  validate_session_id(\"nonexistent\") = {:?}",
        accounts::validate_session_id("nonexistent-session-id", &installed)
    );
    if let Some(first) = installed.first() {
        println!(
            "  validate_session_id({:?}) = {:?}",
            first.id,
            accounts::validate_session_id(&first.id, &installed)
        );
    }
}

async fn udisks_evidence(connection: &Connection) {
    section("UDisks2 (P1-UDS-001..004)");
    let udisks_provider = UdisksProvider::new(connection);
    println!("  probe() = {}", udisks_provider.probe().await);
    match udisks_provider.topology().await {
        Ok(topology) => {
            println!(
                "  topology(): {} drives, {} blocks",
                topology.drives.len(),
                topology.blocks.len()
            );
            for drive in &topology.drives {
                println!("    drive: {drive:?}");
                let siblings = topology.siblings_of_drive(&drive.object_path);
                println!(
                    "      siblings ({}): {:?}",
                    siblings.len(),
                    siblings.iter().map(|b| &b.device_node).collect::<Vec<_>>()
                );
                let result = udisks::validate_power_off_preconditions(&topology, &drive.id, true);
                println!(
                    "      validate_power_off_preconditions(user_initiated=true) = {result:?}"
                );
                let result_not_user =
                    udisks::validate_power_off_preconditions(&topology, &drive.id, false);
                println!(
                    "      validate_power_off_preconditions(user_initiated=false) = {result_not_user:?}"
                );
            }
            let stale = udisks::validate_power_off_preconditions(
                &topology,
                "guardian-g8-nonexistent-drive-evidence",
                true,
            );
            println!("  validate_power_off_preconditions(stale id) = {stale:?}");
        }
        Err(error) => println!("  topology() = Err({error:?})"),
    }
}

async fn registry_evidence(connection: &Connection) {
    section("Capability Registry (handoff §11)");
    let records = registry::populate_registry(connection).await;
    for record in &records {
        println!(
            "  {} <- {} availability={:?} health={:?} read={} write={} authz={:?} priv={:?} iface={:?}",
            record.capability_id,
            record.provider_id,
            record.availability,
            record.health,
            record.read_support,
            record.write_support,
            record.authorization_ownership,
            record.privilege_requirement,
            record.interface_kind,
        );
    }
}

async fn run() {
    let connection = Connection::system()
        .await
        .expect("real system bus connection");

    psi_evidence();
    systemd_evidence(&connection).await;
    logind_evidence(&connection).await;
    upower_evidence(&connection).await;
    accounts_evidence(&connection).await;
    udisks_evidence(&connection).await;
    registry_evidence(&connection).await;
}

fn main() {
    async_io::block_on(run());
}
