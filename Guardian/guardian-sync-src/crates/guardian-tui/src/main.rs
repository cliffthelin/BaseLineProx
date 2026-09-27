//! `guardian-tui` — the G9 TUI shell (contract §33). Runs from a normal
//! terminal or a bare VT (P1-TUI-001), reuses `guardian-client` (ADR-007)
//! exactly as the CLI/GUI do — never a third independent D-Bus/parsing
//! path — and displays the same capability/incident data as the GUI "at
//! a basic level." No provider logic, no safety/arbitration logic, no
//! privileged action of any kind exists in this binary (contract §31).
//!
//! View-model construction (what state to render for a given daemon
//! response) is deliberately pure and unit-tested independently of any
//! rendered terminal buffer — screenshot-style assertions are avoided
//! wherever a deterministic state test suffices (G9 implementation
//! handoff §16).
//!
//! **Text-polkit test action (contract §33's "exercise text polkit in a
//! test action").** Pressing `a` runs a real `CheckAuthorization` call
//! against the real system polkit authority, reusing G1's already-
//! accepted [`guardian_core::authorization::polkit::PolkitAuthorizer`]
//! directly — no new polkit action is defined here (it uses
//! [`PolkitAction::Read`], one of the four `guardian.test.*` actions
//! fixed by contract §9), no new D-Bus method is added anywhere, and no
//! new privileged capability is introduced. This is a **verification
//! path proving terminal authorization works**, not a capability: the
//! call is read-only (`CheckAuthorization` never mutates anything —
//! see the trait doc on [`guardian_core::authorization::Authorizer`]),
//! its result is never wired to any mutation, and it never falls back
//! to `sudo`/a shell if unavailable — an honest "unavailable" is
//! reported instead. Real interactive terminal authentication (when the
//! policy requires it) is obtained the standard way: this binary spawns
//! `pkttyagent` bound to its own process for the duration of the check,
//! never handling credentials itself.

use std::process::{Child, Command};
use std::time::Duration;

use guardian_client::{Capability, ClientError, DaemonConnection, Incident};
use guardian_core::authorization::polkit::PolkitAuthorizer;
use guardian_core::authorization::{
    AuthorizationError, AuthorizationOutcome, AuthorizationRequest, AuthorizationUnavailableReason,
    Authorizer, PolkitAction,
};
use guardian_core::identity::CallerIdentity;
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Direction, Layout};
use ratatui::style::{Color, Style};
use ratatui::text::Line;
use ratatui::widgets::{Block, Borders, List, ListItem, Paragraph};

/// Pure view-model: what the shell has to show, independent of how it
/// is rendered. Real, tested state — not a screenshot fixture.
#[derive(Debug, Clone, PartialEq)]
pub enum ConnectionView {
    Connected {
        contract_version: String,
        service_state: String,
    },
    Unavailable(String),
}

/// Pure projection from a real `ClientError`/`ContractInfo` result —
/// Layer 1 testable with no terminal, no D-Bus.
#[must_use]
pub fn connection_view(
    result: &Result<guardian_client::ContractInfo, ClientError>,
) -> ConnectionView {
    match result {
        Ok(info) => ConnectionView::Connected {
            contract_version: info.contract_version.clone(),
            service_state: info.service_state.clone(),
        },
        Err(error) => ConnectionView::Unavailable(error.to_string()),
    }
}

/// Pure line-per-capability rendering — real `Availability`/`Health`
/// text reported as-is, never collapsed toward a healthier-looking
/// default (AGENTS.md: "Do not convert UNKNOWN into HEALTHY").
#[must_use]
pub fn capability_lines(capabilities: &[Capability]) -> Vec<String> {
    if capabilities.is_empty() {
        return vec!["(no capabilities reported)".to_owned()];
    }
    capabilities
        .iter()
        .map(|capability| {
            format!(
                "{}  availability={} health={} write={}",
                capability.capability_id,
                capability.availability,
                capability.health,
                capability.write_support
            )
        })
        .collect()
}

/// Pure line-per-incident rendering, at "a basic level" per contract §33 —
/// an honest empty list is a healthy state, never rendered as an error.
#[must_use]
pub fn incident_lines(incidents: &[Incident]) -> Vec<String> {
    if incidents.is_empty() {
        return vec!["(no incidents reported)".to_owned()];
    }
    incidents
        .iter()
        .map(|incident| {
            format!(
                "{}  status={} summary={}",
                incident.incident_id, incident.status, incident.summary
            )
        })
        .collect()
}

/// Pure rendering of the text-polkit test action's result. Every distinct
/// [`AuthorizationOutcome`]/[`AuthorizationError`] case gets its own,
/// honest line — none of them are collapsed into a single generic
/// "authorization failed" message (contract-driven: G1's own error
/// taxonomy already distinguishes these for exactly this reason).
#[must_use]
pub fn authorization_test_line(
    result: &Option<Result<AuthorizationOutcome, AuthorizationError>>,
) -> String {
    match result {
        None => "authorization test: press 'a' to run (guardian.test.read, no capability implied)"
            .to_owned(),
        Some(Ok(AuthorizationOutcome::Authorized)) => {
            "authorization test: AUTHORIZED (verification only — no mutation performed)".to_owned()
        }
        Some(Ok(AuthorizationOutcome::Denied)) => "authorization test: DENIED".to_owned(),
        Some(Ok(AuthorizationOutcome::Unavailable(
            AuthorizationUnavailableReason::InteractionRequiredButDisallowed,
        ))) => "authorization test: unavailable — interaction required but disallowed".to_owned(),
        Some(Ok(AuthorizationOutcome::Unavailable(
            AuthorizationUnavailableReason::NoAuthenticationAgent,
        ))) => "authorization test: unavailable — no authentication agent".to_owned(),
        Some(Err(AuthorizationError::ProviderUnavailable(message))) => {
            format!("authorization test: provider unavailable — {message}")
        }
        Some(Err(AuthorizationError::Internal(message))) => {
            format!("authorization test: internal failure — {message}")
        }
    }
}

/// The generic, testable core of the text-polkit test action: resolves
/// this process's own identity from a live connection and asks `authorizer`
/// to decide. Generic over [`Authorizer`] so it can be proven against a
/// private test bus with a deterministic decision source (see the
/// `check_authorization_with_*` tests below), the same Layer 1 discipline
/// G1's own authorization tests use — the real system polkit authority is
/// only exercised in real-VM evidence (Layer 2), never in this
/// unit-testable core.
async fn check_authorization_with(
    connection: &zbus::Connection,
    authorizer: &impl Authorizer,
) -> Result<AuthorizationOutcome, AuthorizationError> {
    let unique_name = connection.unique_name().ok_or_else(|| {
        AuthorizationError::ProviderUnavailable("connection has no unique bus name".to_owned())
    })?;
    let dbus_proxy = zbus::fdo::DBusProxy::new(connection)
        .await
        .map_err(|error| {
            AuthorizationError::ProviderUnavailable(format!(
                "could not construct DBus proxy: {error}"
            ))
        })?;
    let uid = dbus_proxy
        .get_connection_unix_user(unique_name.clone().into())
        .await
        .ok();
    let subject = CallerIdentity::new(unique_name.to_string(), uid);
    let request = AuthorizationRequest::new(subject, PolkitAction::Read, true);
    authorizer.authorize(&request).await
}

/// Real production entry point for the text-polkit test action: connects
/// to the real system bus, spawns `pkttyagent` bound to this process so a
/// real interactive text-authentication challenge can be answered from
/// this terminal if the policy requires one, runs the real check via
/// [`PolkitAuthorizer`], and always cleans up the spawned agent
/// afterward — never leaves a background process running, never falls
/// back to `sudo` or a shell if any step is unavailable.
async fn run_real_authorization_test() -> Result<AuthorizationOutcome, AuthorizationError> {
    let connection = zbus::Connection::system().await.map_err(|error| {
        AuthorizationError::ProviderUnavailable(format!(
            "could not connect to the system bus: {error}"
        ))
    })?;

    let mut agent = spawn_pkttyagent();
    // A short, fixed wait for the agent to finish registering with polkit
    // before the check is issued — pkttyagent has no synchronous
    // "ready" signal on stdout/stderr, so this mirrors the same
    // short-wait idiom other terminal polkit consumers use.
    std::thread::sleep(Duration::from_millis(300));

    let authorizer = PolkitAuthorizer::new(&connection);
    let result = check_authorization_with(&connection, &authorizer).await;

    if let Some(mut agent) = agent.take() {
        let _ = agent.kill();
        let _ = agent.wait();
    }

    result
}

/// Spawns `pkttyagent` bound to this process, or returns `None` if it
/// could not be started (e.g. not installed) — an honest "no agent"
/// outcome then flows naturally from `CheckAuthorization` itself, never
/// a fallback to `sudo`/a shell.
fn spawn_pkttyagent() -> Option<Child> {
    Command::new("pkttyagent")
        .arg("--process")
        .arg(std::process::id().to_string())
        .spawn()
        .ok()
}

fn main() -> std::io::Result<()> {
    let (connection_view, capability_lines, incident_lines) = async_io::block_on(gather_state());
    let mut authorization_result: Option<Result<AuthorizationOutcome, AuthorizationError>> = None;

    crossterm::terminal::enable_raw_mode()?;
    let mut stdout = std::io::stdout();
    crossterm::execute!(stdout, crossterm::terminal::EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    loop {
        terminal.draw(|frame| {
            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(3),
                    Constraint::Min(1),
                    Constraint::Min(1),
                    Constraint::Length(3),
                ])
                .split(frame.area());

            let status_text = match &connection_view {
                ConnectionView::Connected {
                    contract_version,
                    service_state,
                } => format!(
                    "Guardian daemon: connected (contract {contract_version}, state {service_state})"
                ),
                ConnectionView::Unavailable(message) => {
                    format!("Guardian daemon: unavailable — {message}")
                }
            };
            let status_style = match &connection_view {
                ConnectionView::Connected { .. } => Style::default().fg(Color::Green),
                ConnectionView::Unavailable(_) => Style::default().fg(Color::Red),
            };
            frame.render_widget(
                Paragraph::new(Line::styled(status_text, status_style))
                    .block(Block::default().borders(Borders::ALL).title("Guardian")),
                chunks[0],
            );

            let capability_items: Vec<ListItem> = capability_lines
                .iter()
                .map(|line| ListItem::new(line.as_str()))
                .collect();
            frame.render_widget(
                List::new(capability_items)
                    .block(Block::default().borders(Borders::ALL).title("Capabilities")),
                chunks[1],
            );

            let incident_items: Vec<ListItem> = incident_lines
                .iter()
                .map(|line| ListItem::new(line.as_str()))
                .collect();
            frame.render_widget(
                List::new(incident_items)
                    .block(Block::default().borders(Borders::ALL).title("Incidents")),
                chunks[2],
            );

            frame.render_widget(
                Paragraph::new(authorization_test_line(&authorization_result)).block(
                    Block::default()
                        .borders(Borders::ALL)
                        .title("Authorization test ('a' to run, 'q' to quit)"),
                ),
                chunks[3],
            );
        })?;

        if crossterm::event::poll(Duration::from_millis(250))? {
            if let crossterm::event::Event::Key(key) = crossterm::event::read()? {
                match key.code {
                    crossterm::event::KeyCode::Char('a' | 'A') => {
                        authorization_result =
                            Some(async_io::block_on(run_real_authorization_test()));
                    }
                    crossterm::event::KeyCode::Char('q' | 'Q') | crossterm::event::KeyCode::Esc => {
                        break;
                    }
                    _ => {}
                }
            }
        }
    }

    crossterm::execute!(
        terminal.backend_mut(),
        crossterm::terminal::LeaveAlternateScreen
    )?;
    crossterm::terminal::disable_raw_mode()?;
    Ok(())
}

async fn gather_state() -> (ConnectionView, Vec<String>, Vec<String>) {
    let Ok(connection) = DaemonConnection::connect().await else {
        return (
            ConnectionView::Unavailable("could not connect to the system bus".to_owned()),
            vec!["(daemon unavailable)".to_owned()],
            vec!["(daemon unavailable)".to_owned()],
        );
    };
    let contract_result = connection.contract_info().await;
    let view = connection_view(&contract_result);
    let capability_lines = match connection.capabilities().await {
        Ok(capabilities) => capability_lines(&capabilities),
        Err(error) => vec![format!("(capabilities unavailable: {error})")],
    };
    let incident_lines = match connection.incidents().await {
        Ok(incidents) => incident_lines(&incidents),
        Err(error) => vec![format!("(incidents unavailable: {error})")],
    };
    (view, capability_lines, incident_lines)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn connected_result_produces_connected_view() {
        let result = Ok(guardian_client::ContractInfo {
            contract_version: "1.0".to_owned(),
            service_state: "contract-only".to_owned(),
        });
        let view = connection_view(&result);
        assert_eq!(
            view,
            ConnectionView::Connected {
                contract_version: "1.0".to_owned(),
                service_state: "contract-only".to_owned(),
            }
        );
    }

    #[test]
    fn daemon_unavailable_error_produces_unavailable_view_not_a_panic() {
        let result = Err(ClientError::DaemonUnavailable("gone".to_owned()));
        let view = connection_view(&result);
        assert!(matches!(view, ConnectionView::Unavailable(_)));
    }

    #[test]
    fn empty_capability_list_renders_an_honest_placeholder_not_nothing() {
        let lines = capability_lines(&[]);
        assert_eq!(lines, vec!["(no capabilities reported)".to_owned()]);
    }

    #[test]
    fn write_support_true_is_visible_in_the_rendered_line() {
        let capability = Capability {
            capability_id: "test.cap".to_owned(),
            provider_id: "test.provider".to_owned(),
            provider_version: String::new(),
            availability: "available".to_owned(),
            health: "healthy".to_owned(),
            read_support: true,
            write_support: true,
            authorization_ownership: "unknown".to_owned(),
            privilege_requirement: "no_direct_privilege".to_owned(),
            interface_kind: "dbus".to_owned(),
            last_observed_at: String::new(),
        };
        let lines = capability_lines(&[capability]);
        assert!(lines[0].contains("write=true"));
    }

    #[test]
    fn empty_incident_list_renders_as_a_healthy_state_not_an_error() {
        let lines = incident_lines(&[]);
        assert_eq!(lines, vec!["(no incidents reported)".to_owned()]);
        assert!(!lines[0].to_lowercase().contains("error"));
    }

    #[test]
    fn real_incident_renders_its_status_and_summary() {
        let incident = Incident {
            incident_id: "inc-1".to_owned(),
            opened_at: String::new(),
            closed_at: String::new(),
            status: "open".to_owned(),
            summary: "disk pressure".to_owned(),
            confidence: "high".to_owned(),
            primary_resource: "sda".to_owned(),
        };
        let lines = incident_lines(&[incident]);
        assert!(lines[0].contains("status=open"));
        assert!(lines[0].contains("summary=disk pressure"));
    }

    #[test]
    fn capabilities_and_incidents_render_independently_when_both_present() {
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
        let incident = Incident {
            incident_id: "inc-1".to_owned(),
            opened_at: String::new(),
            closed_at: String::new(),
            status: "open".to_owned(),
            summary: "disk pressure".to_owned(),
            confidence: "high".to_owned(),
            primary_resource: "sda".to_owned(),
        };
        let capability_lines = capability_lines(&[capability]);
        let incident_lines = incident_lines(&[incident]);
        assert!(capability_lines[0].contains("test.cap"));
        assert!(incident_lines[0].contains("inc-1"));
    }

    #[test]
    fn authorization_test_not_yet_run_is_distinct_from_every_outcome() {
        let line = authorization_test_line(&None);
        assert!(line.contains("press 'a'"));
        assert!(!line.contains("AUTHORIZED"));
        assert!(!line.contains("DENIED"));
    }

    #[test]
    fn authorization_test_authorized_never_implies_a_mutation() {
        let line = authorization_test_line(&Some(Ok(AuthorizationOutcome::Authorized)));
        assert!(line.contains("AUTHORIZED"));
        assert!(line.contains("no mutation performed"));
    }

    #[test]
    fn authorization_test_denied_is_distinct_from_authorized() {
        let line = authorization_test_line(&Some(Ok(AuthorizationOutcome::Denied)));
        assert!(line.contains("DENIED"));
        assert!(!line.contains("AUTHORIZED"));
    }

    #[test]
    fn authorization_test_no_agent_is_distinct_from_denied() {
        let line = authorization_test_line(&Some(Ok(AuthorizationOutcome::Unavailable(
            AuthorizationUnavailableReason::NoAuthenticationAgent,
        ))));
        assert!(line.contains("no authentication agent"));
        assert!(!line.contains("DENIED"));
    }

    #[test]
    fn authorization_test_interaction_disallowed_is_distinct_from_no_agent() {
        let line = authorization_test_line(&Some(Ok(AuthorizationOutcome::Unavailable(
            AuthorizationUnavailableReason::InteractionRequiredButDisallowed,
        ))));
        assert!(line.contains("interaction required but disallowed"));
        assert!(!line.contains("no authentication agent"));
    }

    #[test]
    fn authorization_test_provider_failure_is_distinct_from_a_denial() {
        let line = authorization_test_line(&Some(Err(AuthorizationError::ProviderUnavailable(
            "polkit is not reachable".to_owned(),
        ))));
        assert!(line.contains("provider unavailable"));
        assert!(line.contains("polkit is not reachable"));
        assert!(!line.contains("DENIED"));
    }

    #[test]
    fn authorization_test_internal_failure_is_distinct_from_provider_unavailable() {
        let line = authorization_test_line(&Some(Err(AuthorizationError::Internal(
            "invariant violated".to_owned(),
        ))));
        assert!(line.contains("internal failure"));
        assert!(!line.contains("provider unavailable"));
    }

    // Real-bus, mocked-decision tests for `check_authorization_with` — the
    // same Layer 1 discipline G1's own authorization tests use (a genuine
    // private D-Bus connection with a genuine, distinct unique bus name;
    // only the *decision source* is a deterministic test double, since no
    // real polkit authority exists on a private test bus). This proves the
    // TUI's own identity-resolution-from-a-live-connection logic works
    // against a real connection, not just that a hand-rolled TUI mock
    // returns what it's told to return.

    struct RecordingAuthorizer {
        outcome: AuthorizationOutcome,
        seen_unique_name: std::sync::Mutex<Option<String>>,
    }

    impl RecordingAuthorizer {
        fn new(outcome: AuthorizationOutcome) -> Self {
            Self {
                outcome,
                seen_unique_name: std::sync::Mutex::new(None),
            }
        }
    }

    impl Authorizer for RecordingAuthorizer {
        fn authorize(
            &self,
            request: &AuthorizationRequest,
        ) -> impl std::future::Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send
        {
            *self.seen_unique_name.lock().unwrap() =
                Some(request.subject().unique_name().to_owned());
            let outcome = self.outcome;
            async move { Ok(outcome) }
        }
    }

    #[test]
    fn check_authorization_with_resolves_a_real_unique_bus_name_and_relays_authorized() {
        async_io::block_on(async {
            let bus =
                guardian_testkit::PrivateSessionBus::launch().expect("private D-Bus must launch");
            let connection = zbus::connection::Builder::address(bus.address())
                .expect("parse private D-Bus address")
                .build()
                .await
                .expect("connect to private D-Bus");

            let authorizer = RecordingAuthorizer::new(AuthorizationOutcome::Authorized);
            let result = check_authorization_with(&connection, &authorizer).await;

            assert!(matches!(result, Ok(AuthorizationOutcome::Authorized)));
            let seen = authorizer.seen_unique_name.lock().unwrap().clone();
            let seen = seen.expect("authorizer must have been called with a real subject");
            // A real D-Bus unique connection name always starts with ':'.
            assert!(
                seen.starts_with(':'),
                "expected a real unique name, got {seen}"
            );
            assert_eq!(seen, connection.unique_name().unwrap().to_string());
        });
    }

    #[test]
    fn check_authorization_with_relays_denied_without_reinterpreting_it() {
        async_io::block_on(async {
            let bus =
                guardian_testkit::PrivateSessionBus::launch().expect("private D-Bus must launch");
            let connection = zbus::connection::Builder::address(bus.address())
                .expect("parse private D-Bus address")
                .build()
                .await
                .expect("connect to private D-Bus");

            let authorizer = RecordingAuthorizer::new(AuthorizationOutcome::Denied);
            let result = check_authorization_with(&connection, &authorizer).await;

            assert!(matches!(result, Ok(AuthorizationOutcome::Denied)));
        });
    }
}
