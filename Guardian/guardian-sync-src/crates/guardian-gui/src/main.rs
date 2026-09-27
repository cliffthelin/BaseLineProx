//! `guardian-gui` — the G9 GUI shell (contract §32). Explicitly a shell,
//! not the finished Guardian dashboard: daemon connection state, overall
//! Guardian state, capabilities list, provider ownership details,
//! incidents list, current system blockers, read-only PSI summary,
//! transaction history view, graceful provider-unavailable state — no
//! more than this list (G9 implementation handoff §7.3).
//!
//! Built on GTK4 + libadwaita via `gtk4-rs`, per ADR-007 (accepted
//! before this code was written, not chosen ad hoc here). Reuses
//! `guardian-client` (ADR-007) for every daemon read — no second D-Bus
//! client, no provider-arbitration/safety logic of its own (contract
//! §31).

use adw::prelude::*;
use gtk::glib;
use guardian_client::{Capability, ClientError, ContractInfo, DaemonConnection};

const APP_ID: &str = "io.github.cliffthelin.GuardianGui";

/// Pure, Layer-1-testable rendering text — independent of any real GTK
/// widget, so the honest-rendering rules (never collapse `Unknown`
/// toward `Healthy`, never render empty as an error) are checked without
/// a running display server.
#[must_use]
fn connection_line(result: &Result<ContractInfo, ClientError>) -> String {
    match result {
        Ok(info) => format!(
            "Connected — contract {}, state {}",
            info.contract_version, info.service_state
        ),
        Err(ClientError::DaemonUnavailable(message)) => format!("Daemon unavailable: {message}"),
        Err(ClientError::MalformedResponse(message)) => {
            format!("Daemon responded unexpectedly: {message}")
        }
    }
}

/// Real capability rows — `write_support`/`authorization_ownership` are
/// always shown, never omitted for a friendlier-looking default (G9
/// implementation handoff §9's forward-constraint requirement).
#[must_use]
fn capability_row_text(capability: &Capability) -> String {
    format!(
        "{}  ({})  availability={} health={} read={} write={} authz={} priv={}",
        capability.capability_id,
        capability.provider_id,
        capability.availability,
        capability.health,
        capability.read_support,
        capability.write_support,
        capability.authorization_ownership,
        capability.privilege_requirement,
    )
}

#[must_use]
fn empty_state_text(label: &str) -> String {
    format!("(no {label})")
}

/// The five read-only panes (contract §32/G9 handoff §7.3's fixed list).
struct Panes {
    capabilities: gtk::ListBox,
    blockers: gtk::ListBox,
    incidents: gtk::ListBox,
    transactions: gtk::ListBox,
    psi: gtk::ListBox,
}

fn build_panes(notebook: &gtk::Notebook) -> Panes {
    let capabilities = gtk::ListBox::new();
    notebook.append_page(
        &scrolled(&capabilities),
        Some(&gtk::Label::new(Some("Capabilities"))),
    );

    let blockers = gtk::ListBox::new();
    notebook.append_page(
        &scrolled(&blockers),
        Some(&gtk::Label::new(Some("Blockers"))),
    );

    let incidents = gtk::ListBox::new();
    notebook.append_page(
        &scrolled(&incidents),
        Some(&gtk::Label::new(Some("Incidents"))),
    );

    let transactions = gtk::ListBox::new();
    notebook.append_page(
        &scrolled(&transactions),
        Some(&gtk::Label::new(Some("Transactions"))),
    );

    let psi = gtk::ListBox::new();
    notebook.append_page(&scrolled(&psi), Some(&gtk::Label::new(Some("PSI summary"))));

    Panes {
        capabilities,
        blockers,
        incidents,
        transactions,
        psi,
    }
}

/// Real, live population of every pane from one daemon connection — a
/// connection failure degrades every pane to an honest
/// "daemon unavailable" label, never a silent empty list.
async fn populate_panes(status_label: &gtk::Label, panes: &Panes) {
    let connection = match DaemonConnection::connect().await {
        Ok(connection) => connection,
        Err(error) => {
            status_label.set_label(&connection_line(&Err(error)));
            for (list, label) in [
                (&panes.capabilities, "capabilities"),
                (&panes.blockers, "blockers"),
                (&panes.incidents, "incidents"),
                (&panes.transactions, "transactions"),
                (&panes.psi, "PSI resources"),
            ] {
                list.append(&gtk::Label::new(Some(&format!(
                    "(daemon unavailable — {label} not shown)"
                ))));
            }
            return;
        }
    };

    let contract = connection.contract_info().await;
    status_label.set_label(&connection_line(&contract));

    populate(
        &panes.capabilities,
        connection.capabilities().await,
        "capabilities",
        capability_row_text,
    );
    populate(
        &panes.blockers,
        connection.blockers().await,
        "blockers",
        |blocker| {
            format!(
                "{} by {} ({}): {}",
                blocker.what, blocker.who, blocker.mode, blocker.why
            )
        },
    );
    populate(
        &panes.incidents,
        connection.incidents().await,
        "incidents",
        |incident| {
            format!(
                "{}  {}  {}",
                incident.incident_id, incident.status, incident.summary
            )
        },
    );
    populate(
        &panes.transactions,
        connection.transactions().await,
        "transactions",
        |transaction| format!("{}  {}", transaction.transaction_id, transaction.state),
    );
    populate(
        &panes.psi,
        connection.psi_summary().await,
        "PSI resources",
        |entry| {
            if entry.available {
                format!(
                    "{}: avg10={:.2} avg60={:.2} avg300={:.2}",
                    entry.kind, entry.avg10, entry.avg60, entry.avg300
                )
            } else {
                format!("{}: unavailable", entry.kind)
            }
        },
    );
}

fn build_ui(app: &adw::Application) {
    let window = adw::ApplicationWindow::builder()
        .application(app)
        .title("Guardian")
        .default_width(720)
        .default_height(560)
        .build();

    let toolbar_view = adw::ToolbarView::new();
    toolbar_view.add_top_bar(&adw::HeaderBar::new());

    let root = gtk::Box::new(gtk::Orientation::Vertical, 8);
    root.set_margin_top(12);
    root.set_margin_bottom(12);
    root.set_margin_start(12);
    root.set_margin_end(12);

    let status_label = gtk::Label::new(Some("Connecting..."));
    status_label.set_halign(gtk::Align::Start);
    root.append(&status_label);

    let notebook = gtk::Notebook::new();
    let panes = build_panes(&notebook);

    root.append(&notebook);
    toolbar_view.set_content(Some(&root));
    window.set_content(Some(&toolbar_view));
    window.present();

    glib::spawn_future_local(async move {
        populate_panes(&status_label, &panes).await;
    });
}

fn scrolled(widget: &impl IsA<gtk::Widget>) -> gtk::ScrolledWindow {
    let scrolled = gtk::ScrolledWindow::new();
    scrolled.set_child(Some(widget));
    scrolled.set_vexpand(true);
    scrolled
}

fn populate<T>(
    list: &gtk::ListBox,
    result: Result<Vec<T>, ClientError>,
    label: &str,
    render: impl Fn(&T) -> String,
) {
    match result {
        Ok(items) if items.is_empty() => {
            list.append(&gtk::Label::new(Some(&empty_state_text(label))));
        }
        Ok(items) => {
            for item in &items {
                list.append(&gtk::Label::new(Some(&render(item))));
            }
        }
        Err(error) => {
            list.append(&gtk::Label::new(Some(&format!(
                "({label} unavailable: {error})"
            ))));
        }
    }
}

fn main() -> glib::ExitCode {
    let app = adw::Application::builder().application_id(APP_ID).build();
    app.connect_activate(build_ui);
    app.run()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn connected_result_renders_contract_and_state() {
        let result = Ok(ContractInfo {
            contract_version: "1.0".to_owned(),
            service_state: "contract-only".to_owned(),
        });
        assert_eq!(
            connection_line(&result),
            "Connected — contract 1.0, state contract-only"
        );
    }

    #[test]
    fn daemon_unavailable_is_distinct_from_malformed_response() {
        let unavailable = connection_line(&Err(ClientError::DaemonUnavailable("gone".to_owned())));
        let malformed = connection_line(&Err(ClientError::MalformedResponse("bad".to_owned())));
        assert!(unavailable.starts_with("Daemon unavailable"));
        assert!(malformed.starts_with("Daemon responded unexpectedly"));
        assert_ne!(unavailable, malformed);
    }

    #[test]
    fn empty_state_text_is_never_rendered_as_an_error() {
        let text = empty_state_text("incidents");
        assert_eq!(text, "(no incidents)");
        assert!(!text.to_lowercase().contains("error"));
    }

    #[test]
    fn capability_row_always_shows_write_support_and_authorization() {
        let capability = Capability {
            capability_id: "test.cap".to_owned(),
            provider_id: "test.provider".to_owned(),
            provider_version: String::new(),
            availability: "available".to_owned(),
            health: "healthy".to_owned(),
            read_support: true,
            write_support: false,
            authorization_ownership: "unknown".to_owned(),
            privilege_requirement: "no_direct_privilege".to_owned(),
            interface_kind: "dbus".to_owned(),
            last_observed_at: String::new(),
        };
        let text = capability_row_text(&capability);
        assert!(text.contains("write=false"));
        assert!(text.contains("authz=unknown"));
    }
}
