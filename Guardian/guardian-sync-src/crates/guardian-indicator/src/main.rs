//! `guardian-indicator` — the G9 production indicator (contract §30's
//! required tests, now proven against real `guardian-daemon` data
//! instead of G6's disposable stub — P1-IND-001/002). Built on `ksni`
//! per G6's accepted decision (ADR-006) — this binary does **not**
//! re-litigate that choice, and is real production code informed by
//! (never copy-pasted wholesale from) the disposable
//! `tests/vm/g6-candidate-ksni/` prototype.
//!
//! Reuses `guardian-client` (ADR-007) for every daemon read — no second
//! D-Bus parsing path, no provider/arbitration logic of its own. Real
//! daemon presence is detected via a real, periodic `ListCapabilities`
//! call (not a raw `NameHasOwner` poll), so a "healthy" icon reflects a
//! real, live, successful read, not merely that the bus name currently
//! has an owner.
//!
//! **Session-scoped launch (ADR-008 §5, forward constraint from
//! ADR-006):** this binary must be launched via a real desktop
//! autostart mechanism — the packaged
//! `/etc/xdg/autostart/guardian-indicator.desktop` entry — so it is a
//! normal child of the user's login session and is cleaned up by
//! `systemd-logind` on logout. It must never be launched as a detached
//! background process (`nohup ... &`) in production or in evidence
//! gathering.
//!
//! `ksni` pulls in `zbus`; this crate selects `ksni`'s `async-io`
//! feature rather than its default `tokio` feature. `zbus`'s Cargo
//! features are unified across the whole workspace by `cargo test
//! --workspace`/`cargo build --workspace`, so enabling `zbus/tokio`
//! here would silently switch every other crate's `zbus` connections
//! (including `guardian-daemon`'s) onto a process-wide tokio runtime
//! too, mismatching their own `async-io`-based executors and causing
//! reactor panics unrelated to this binary. This crate's own `tokio`
//! runtime (for signal handling and the poll timer) is unaffected —
//! it never touches `zbus`'s internal executor choice.

use std::time::Duration;

use guardian_client::{Capability, ClientError, DaemonConnection};
use ksni::TrayMethods;
use ksni::menu::StandardItem;

/// Pure aggregation over real capability state — never fabricated, never
/// a manual "simulate degraded" toggle (unlike the G6 evidence-only
/// prototype, which deliberately included one for spike-testing
/// purposes only).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum IndicatorState {
    Healthy,
    Degraded,
    DaemonUnavailable,
}

/// Pure, Layer-1-testable projection from a real capability-list result.
#[must_use]
fn indicator_state(result: &Result<Vec<Capability>, ClientError>) -> IndicatorState {
    match result {
        Err(_) => IndicatorState::DaemonUnavailable,
        Ok(capabilities) => {
            let any_unhealthy = capabilities
                .iter()
                .any(|capability| capability.health != "healthy");
            if any_unhealthy {
                IndicatorState::Degraded
            } else {
                IndicatorState::Healthy
            }
        }
    }
}

fn icon_for(state: IndicatorState) -> &'static str {
    match state {
        IndicatorState::Healthy => "computer",
        IndicatorState::Degraded => "dialog-warning",
        IndicatorState::DaemonUnavailable => "dialog-error",
    }
}

fn title_for(state: IndicatorState) -> &'static str {
    match state {
        IndicatorState::Healthy => "Guardian — Healthy",
        IndicatorState::Degraded => "Guardian — Degraded",
        IndicatorState::DaemonUnavailable => "Guardian — Daemon Unavailable",
    }
}

#[derive(Debug, Clone)]
struct GuardianTray {
    state: IndicatorState,
    capability_count: usize,
}

impl ksni::Tray for GuardianTray {
    fn id(&self) -> String {
        "guardian-indicator".into()
    }

    fn icon_name(&self) -> String {
        icon_for(self.state).into()
    }

    fn title(&self) -> String {
        title_for(self.state).into()
    }

    fn tool_tip(&self) -> ksni::ToolTip {
        ksni::ToolTip {
            title: title_for(self.state).into(),
            description: format!("{} real capabilities observed", self.capability_count),
            ..Default::default()
        }
    }

    fn menu(&self) -> Vec<ksni::MenuItem<Self>> {
        vec![
            StandardItem {
                label: title_for(self.state).into(),
                enabled: false,
                ..Default::default()
            }
            .into(),
            StandardItem {
                label: "Quit".into(),
                icon_name: "application-exit".into(),
                activate: Box::new(|_: &mut Self| std::process::exit(0)),
                ..Default::default()
            }
            .into(),
        ]
    }
}

/// Real, periodic daemon poll — never a cached/simulated toggle. Reuses
/// the exact same `guardian-client` call the CLI/GUI/TUI use.
async fn watch_daemon(handle: ksni::Handle<GuardianTray>) {
    loop {
        let result = match DaemonConnection::connect().await {
            Ok(connection) => connection.capabilities().await,
            Err(error) => Err(error),
        };
        let state = indicator_state(&result);
        let count = result.as_ref().map_or(0, Vec::len);
        handle
            .update(|tray: &mut GuardianTray| {
                tray.state = state;
                tray.capability_count = count;
            })
            .await;
        tokio::time::sleep(Duration::from_secs(30)).await;
    }
}

/// Real desktop sessions launch many autostart apps in parallel; the
/// `org.kde.StatusNotifierWatcher` provider (a GNOME Shell extension, or
/// a separate ayatana process on other desktops) is not guaranteed to
/// have registered yet when this binary starts (observed directly: a
/// GNOME 50 autologin session where `tray.spawn()` failed with
/// `ServiceUnknown` on first attempt because the watcher registered a
/// moment later). A bounded, logged retry with backoff handles that
/// real startup race; it is not a silent infinite retry, and gives up
/// with a real error after `MAX_SPAWN_ATTEMPTS` if the watcher never
/// appears.
const MAX_SPAWN_ATTEMPTS: u32 = 15;
const SPAWN_RETRY_DELAY: Duration = Duration::from_secs(2);

async fn spawn_tray_with_retry(tray: GuardianTray) -> ksni::Handle<GuardianTray> {
    let mut last_error = None;
    for attempt in 1..=MAX_SPAWN_ATTEMPTS {
        match tray.clone().spawn().await {
            Ok(handle) => return handle,
            Err(error) => {
                eprintln!(
                    "[guardian-indicator] tray.spawn() attempt {attempt}/{MAX_SPAWN_ATTEMPTS} failed: {error:?}"
                );
                last_error = Some(error);
                tokio::time::sleep(SPAWN_RETRY_DELAY).await;
            }
        }
    }
    eprintln!("[guardian-indicator] giving up after {MAX_SPAWN_ATTEMPTS} attempts: {last_error:?}");
    std::process::exit(1);
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let tray = GuardianTray {
        state: IndicatorState::DaemonUnavailable,
        capability_count: 0,
    };
    let handle = spawn_tray_with_retry(tray).await;

    let watcher_handle = handle.clone();
    tokio::spawn(watch_daemon(watcher_handle));

    let _ = handle;
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .expect("install SIGTERM handler");
    term.recv().await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn daemon_error_produces_daemon_unavailable_state() {
        let result = Err(ClientError::DaemonUnavailable("gone".to_owned()));
        assert_eq!(indicator_state(&result), IndicatorState::DaemonUnavailable);
    }

    #[test]
    fn all_healthy_capabilities_produce_healthy_state() {
        let result = Ok(vec![sample_capability("healthy")]);
        assert_eq!(indicator_state(&result), IndicatorState::Healthy);
    }

    #[test]
    fn any_unhealthy_capability_produces_degraded_state() {
        let result = Ok(vec![
            sample_capability("healthy"),
            sample_capability("error"),
        ]);
        assert_eq!(indicator_state(&result), IndicatorState::Degraded);
    }

    #[test]
    fn empty_capability_list_is_healthy_not_degraded() {
        let result: Result<Vec<Capability>, ClientError> = Ok(Vec::new());
        assert_eq!(indicator_state(&result), IndicatorState::Healthy);
    }

    fn sample_capability(health: &str) -> Capability {
        Capability {
            capability_id: "test.cap".to_owned(),
            provider_id: "test.provider".to_owned(),
            provider_version: String::new(),
            availability: "available".to_owned(),
            health: health.to_owned(),
            read_support: true,
            write_support: false,
            authorization_ownership: "unknown".to_owned(),
            privilege_requirement: "no_direct_privilege".to_owned(),
            interface_kind: "dbus".to_owned(),
            last_observed_at: String::new(),
        }
    }
}
