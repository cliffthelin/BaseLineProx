//! G6 EVIDENCE-ONLY PROTOTYPE — NOT PRODUCTION CODE.
//!
//! Candidate spike for the G6 "Indicator decision" gate (TDD contract
//! §30; `docs/guardian/30_TDD/GUARDIAN_G6_IMPLEMENTATION_HANDOFF.md`).
//! Evaluates candidate 3 ("direct Rust SNI + canonical DBusMenu, e.g.
//! `ksni`") under real GNOME 50/Xfce 4.20 sessions in a disposable VM.
//!
//! This is deliberately the *simplest possible* StatusNotifierItem tray
//! icon plus a small usable menu -- just enough to exercise §30's
//! required-test list (icon appears, menu opens, menu action invokes a
//! handler, status/icon can change, degraded state is representable). It
//! contains no Guardian authorization, transaction, provider, diagnostic,
//! or recorder logic -- it never talks to `guardian-core` at all, per the
//! G6 handoff's thin-client-boundary requirement (§ "Thin-client
//! boundary" in the task brief; contract §31).
//!
//! DISPOSABLE: built and run only inside a disposable VM, never on a
//! primary workstation. Not wired into `guardian-daemon`, not part of
//! any production build, not referenced by the Cargo workspace at
//! `/home/Cliff/SysProjects/Guardian/Cargo.toml`.
//!
//! Icon names (updated during G6 evidence closure): the original
//! `"emblem-default"` icon name does not exist in this project's tested
//! Adwaita builds (see `docs/evidence/g6/G6_P0_IND_003_RECONNECT_EVIDENCE.md`
//! and `docs/evidence/g6/G6_ICON_NAME_CORRECTION.md`) -- it was replaced
//! with names directly verified present via
//! `find /usr/share/icons/{Adwaita,hicolor,Humanity} -iname '<name>.*'`
//! on the VM used for this closure pass, recorded in the accompanying
//! evidence document. `"computer"` (healthy), `"dialog-warning"`
//! (manually simulated degraded), `"dialog-error"` (real, detected
//! daemon-unavailable state), `"application-exit"` (menu item icon) were
//! all confirmed present before use.
//!
//! Daemon-unavailable detection (added during G6 evidence closure, for
//! §30's "daemon unavailable shows degraded state" required test): this
//! candidate watches, via a background task using the real D-Bus
//! `org.freedesktop.DBus.NameHasOwner` call, whether the well-known name
//! `io.github.cliffthelin.GuardianG6EvidenceStub1` currently has an
//! owner. That name is claimed only by
//! `tests/vm/g6-daemon-evidence-stub/` -- a separate, explicitly
//! NON-PRODUCTION / G6 EVIDENCE-ONLY / DISPOSABLE / NOT-A-G7-DAEMON-
//! SKELETON binary that does nothing but own the name (see that crate's
//! own module doc comment). This is real detection of a real absent/
//! present D-Bus name, not a simulated toggle -- distinct from the
//! pre-existing "Simulate degraded status" menu item, which remains for
//! manual/interactive testing. Detected daemon-unavailability takes
//! visual precedence over the manually-simulated degraded state.

use std::time::Duration;

use ksni::TrayMethods;
use ksni::menu::{CheckmarkItem, StandardItem};

const DAEMON_STUB_BUS_NAME: &str = "io.github.cliffthelin.GuardianG6EvidenceStub1";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ManualStatus {
    Healthy,
    Degraded,
}

#[derive(Debug)]
struct EvidenceTray {
    manual_status: ManualStatus,
    daemon_present: bool,
    menu_clicks: u64,
}

impl EvidenceTray {
    /// Real detected daemon-absence always takes visual precedence over
    /// the manually-simulated degraded toggle -- per the G6 handoff's
    /// fail-closed/degraded-state checklist ("must be a real, distinct,
    /// observable state").
    fn effective_icon(&self) -> &'static str {
        if !self.daemon_present {
            "dialog-error"
        } else {
            match self.manual_status {
                ManualStatus::Healthy => "computer",
                ManualStatus::Degraded => "dialog-warning",
            }
        }
    }

    fn effective_title(&self) -> String {
        if !self.daemon_present {
            "Guardian G6 evidence (DAEMON UNAVAILABLE)".into()
        } else {
            match self.manual_status {
                ManualStatus::Healthy => "Guardian G6 evidence (healthy)".into(),
                ManualStatus::Degraded => "Guardian G6 evidence (DEGRADED)".into(),
            }
        }
    }
}

impl ksni::Tray for EvidenceTray {
    fn id(&self) -> String {
        "guardian-g6-evidence-ksni".into()
    }

    fn icon_name(&self) -> String {
        self.effective_icon().into()
    }

    fn title(&self) -> String {
        self.effective_title()
    }

    fn tool_tip(&self) -> ksni::ToolTip {
        ksni::ToolTip {
            title: self.effective_title(),
            description: format!(
                "menu_clicks={} daemon_present={}",
                self.menu_clicks, self.daemon_present
            ),
            ..Default::default()
        }
    }

    fn menu(&self) -> Vec<ksni::MenuItem<Self>> {
        vec![
            StandardItem {
                label: format!("Click me (clicks so far: {})", self.menu_clicks),
                activate: Box::new(|this: &mut Self| {
                    this.menu_clicks += 1;
                    eprintln!(
                        "[g6-evidence] menu item activated, menu_clicks={}",
                        this.menu_clicks
                    );
                }),
                ..Default::default()
            }
            .into(),
            CheckmarkItem {
                label: "Simulate degraded status".into(),
                checked: self.manual_status == ManualStatus::Degraded,
                activate: Box::new(|this: &mut Self| {
                    this.manual_status = match this.manual_status {
                        ManualStatus::Healthy => ManualStatus::Degraded,
                        ManualStatus::Degraded => ManualStatus::Healthy,
                    };
                    eprintln!(
                        "[g6-evidence] manual status toggled to {:?}",
                        this.manual_status
                    );
                }),
                ..Default::default()
            }
            .into(),
            StandardItem {
                label: "Exit".into(),
                icon_name: "application-exit".into(),
                activate: Box::new(|_| {
                    eprintln!("[g6-evidence] exit requested via menu");
                    std::process::exit(0);
                }),
                ..Default::default()
            }
            .into(),
        ]
    }
}

/// Polls the real D-Bus session bus for whether the evidence-only daemon
/// stub currently owns `DAEMON_STUB_BUS_NAME`, and pushes the result into
/// the tray via `ksni::Handle::update`. Real detection, not a timer-based
/// simulation -- killing/starting `g6-daemon-evidence-stub` is what
/// actually changes what this task observes.
async fn watch_daemon_presence(handle: ksni::Handle<EvidenceTray>) {
    let conn = match zbus::Connection::session().await {
        Ok(c) => c,
        Err(error) => {
            eprintln!("[g6-evidence] daemon-watch: session bus connect FAILED: {error:?}");
            return;
        }
    };
    let dbus = match zbus::fdo::DBusProxy::new(&conn).await {
        Ok(p) => p,
        Err(error) => {
            eprintln!("[g6-evidence] daemon-watch: DBusProxy FAILED: {error:?}");
            return;
        }
    };

    let mut last_seen: Option<bool> = None;
    loop {
        let present = dbus
            .name_has_owner(zbus::names::BusName::try_from(DAEMON_STUB_BUS_NAME).unwrap())
            .await
            .unwrap_or(false);

        if last_seen != Some(present) {
            eprintln!(
                "[g6-evidence] daemon-watch: {} presence changed -> {}",
                DAEMON_STUB_BUS_NAME, present
            );
            last_seen = Some(present);
        }

        handle
            .update(|tray: &mut EvidenceTray| {
                tray.daemon_present = present;
            })
            .await;

        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    eprintln!(
        "[g6-evidence] G6 EVIDENCE-ONLY ksni prototype starting, pid={}",
        std::process::id()
    );
    let tray = EvidenceTray {
        manual_status: ManualStatus::Healthy,
        // Assume present until the first real poll completes, to avoid a
        // guaranteed-false initial flash before the watcher task has run
        // even once.
        daemon_present: true,
        menu_clicks: 0,
    };
    let handle = match tray.spawn().await {
        Ok(h) => {
            eprintln!("[g6-evidence] tray.spawn() succeeded, StatusNotifierItem registered");
            h
        }
        Err(error) => {
            eprintln!("[g6-evidence] tray.spawn() FAILED: {error:?}");
            std::process::exit(1);
        }
    };

    let watcher_handle = handle.clone();
    tokio::spawn(watch_daemon_presence(watcher_handle));

    // Keep the process alive; allow SIGTERM for clean teardown from the
    // evidence-gathering harness.
    let _ = handle;
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .expect("install SIGTERM handler");
    term.recv().await;
    eprintln!("[g6-evidence] SIGTERM received, exiting");
}
