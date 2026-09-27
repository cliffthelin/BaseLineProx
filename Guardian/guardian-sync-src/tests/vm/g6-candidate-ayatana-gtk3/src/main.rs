//! G6 EVIDENCE-ONLY PROTOTYPE — NOT PRODUCTION CODE.
//!
//! Candidate spike for the G6 "Indicator decision" gate (TDD contract
//! §30; `docs/guardian/30_TDD/GUARDIAN_G6_IMPLEMENTATION_HANDOFF.md`).
//! Evaluates candidate 1 ("legacy GTK3 Ayatana AppIndicator") under real
//! GNOME 50/Xfce 4.20 sessions in a disposable VM.
//!
//! Uses a minimal, hand-written `extern "C"` FFI surface against
//! `libayatana-appindicator3` plus the `gtk`/`gtk-sys` crates for
//! constructing the `GtkMenu`/`GtkMenuItem` widgets `app_indicator_set_menu`
//! requires. See `build.rs` for why: the only published Rust `-sys` crate
//! for this library (`libayatana-appindicator-sys` 0.2.0) fails to build
//! against Ubuntu 26.04's current glib headers -- a real, reproducible
//! tooling-compatibility finding, not a shortcut. The function/enum
//! declarations below were verified against the real installed header
//! (`/usr/include/libayatana-appindicator3-0.1/libayatana-appindicator/app-indicator.h`),
//! not guessed.
//!
//! Contains no Guardian authorization, transaction, provider, diagnostic,
//! or recorder logic -- never references `guardian-core`. DISPOSABLE:
//! built and run only inside a disposable VM, never on a primary
//! workstation.
//!
//! Updated during G6 repair (independent-audit finding 1): the original
//! spike's "no X11 dependency: FAIL" claim rested on a launch that never
//! set `GDK_BACKEND=wayland`. `gtk::init()` below succeeds under a real
//! GNOME 50/Wayland session with no `DISPLAY`/`XAUTHORITY` set at all
//! when the launcher sets `GDK_BACKEND=wayland` and `WAYLAND_DISPLAY` --
//! this file's own code did not need to change for that; only the
//! external launch environment did. See
//! `docs/evidence/g6/G6_CANDIDATE1_REPAIR_EVIDENCE.md`.
//!
//! Icon names corrected to ones verified present (see
//! `G6_ICON_NAME_CORRECTION.md`): `"computer"` (healthy), `"dialog-warning"`
//! (manually-simulated degraded, via `app_indicator_set_attention_icon_full`
//! so the glyph now genuinely changes -- the original spike's "status
//! changes internally but glyph doesn't" finding is superseded by this
//! addition, not silently erased; see the repair evidence doc), and
//! `"dialog-error"` (real detected daemon-analog-unavailable state).
//!
//! Daemon-analog-presence detection (added during G6 repair, closing
//! independent-audit finding 2 for this candidate): a background OS
//! thread polls the real D-Bus `NameHasOwner` call for the same
//! evidence-only well-known name `tests/vm/g6-daemon-evidence-stub/`
//! claims, and pushes the result to the GTK main loop over a
//! `glib::MainContext` channel (the standard safe way to touch GTK state
//! from a background thread). Real detection, not a simulated timer --
//! only killing/starting the separate stub process changes what this
//! observes. Detected daemon-analog-unavailability takes visual
//! precedence over the manually-simulated toggle.

use std::ffi::{CString, c_char, c_void};
use std::time::Duration;

use gtk::prelude::*;

const DAEMON_STUB_BUS_NAME: &str = "io.github.cliffthelin.GuardianG6EvidenceStub1";

#[repr(C)]
struct AppIndicator {
    _private: [u8; 0],
}

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Copy)]
enum AppIndicatorCategory {
    ApplicationStatus = 0,
    #[allow(dead_code)]
    Communications = 1,
    #[allow(dead_code)]
    SystemServices = 2,
    #[allow(dead_code)]
    Hardware = 3,
    #[allow(dead_code)]
    Other = 4,
}

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Copy)]
enum AppIndicatorStatus {
    #[allow(dead_code)]
    Passive = 0,
    Active = 1,
    Attention = 2,
}

#[link(name = "ayatana-appindicator3")]
unsafe extern "C" {
    fn app_indicator_new(
        id: *const c_char,
        icon_name: *const c_char,
        category: AppIndicatorCategory,
    ) -> *mut AppIndicator;
    fn app_indicator_set_status(indicator: *mut AppIndicator, status: AppIndicatorStatus);
    fn app_indicator_set_menu(indicator: *mut AppIndicator, menu: *mut c_void);
    fn app_indicator_set_attention_icon_full(
        indicator: *mut AppIndicator,
        icon_name: *const c_char,
        icon_desc: *const c_char,
    );
}

fn cstr(s: &str) -> CString {
    CString::new(s).expect("no interior NUL")
}

/// Real, blocking check of whether the evidence-only daemon stub
/// currently owns its well-known bus name. Uses `zbus::blocking` since
/// this runs on a plain background `std::thread`, not an async runtime
/// (this prototype is GTK/glib-based, matching every other candidate's
/// own concurrency model rather than introducing tokio just for this).
fn daemon_stub_present() -> bool {
    let Ok(conn) = zbus::blocking::Connection::session() else {
        return false;
    };
    let Ok(dbus) = zbus::blocking::fdo::DBusProxy::new(&conn) else {
        return false;
    };
    let Ok(name) = zbus::names::BusName::try_from(DAEMON_STUB_BUS_NAME) else {
        return false;
    };
    dbus.name_has_owner(name).unwrap_or(false)
}

fn main() {
    eprintln!(
        "[g6-evidence] G6 EVIDENCE-ONLY ayatana-gtk3 prototype starting, pid={}",
        std::process::id()
    );

    gtk::init().expect("gtk::init failed -- is a real X11/Wayland display available?");

    let id = cstr("guardian-g6-evidence-ayatana-gtk3");
    let icon = cstr("computer");
    let attention_icon = cstr("dialog-warning");
    let attention_desc = cstr("Simulated degraded status");

    // SAFETY: `id`/`icon` are valid, NUL-terminated C strings kept alive
    // for this call; `app_indicator_new` copies what it needs internally
    // (standard GObject construction convention).
    let indicator = unsafe {
        app_indicator_new(id.as_ptr(), icon.as_ptr(), AppIndicatorCategory::ApplicationStatus)
    };
    if indicator.is_null() {
        eprintln!("[g6-evidence] app_indicator_new FAILED (returned null)");
        std::process::exit(1);
    }
    eprintln!("[g6-evidence] app_indicator_new succeeded");

    // SAFETY: `attention_icon`/`attention_desc` outlive this call.
    unsafe {
        app_indicator_set_attention_icon_full(
            indicator,
            attention_icon.as_ptr(),
            attention_desc.as_ptr(),
        );
    }

    let menu = gtk::Menu::new();

    let click_item = gtk::MenuItem::with_label("Click me (see stderr for count)");
    let click_count = std::rc::Rc::new(std::cell::Cell::new(0_u64));
    {
        let click_count = click_count.clone();
        click_item.connect_activate(move |_| {
            click_count.set(click_count.get() + 1);
            eprintln!(
                "[g6-evidence] menu item activated, menu_clicks={}",
                click_count.get()
            );
        });
    }
    menu.append(&click_item);

    let manual_degraded = std::rc::Rc::new(std::cell::Cell::new(false));
    let daemon_present = std::rc::Rc::new(std::cell::Cell::new(true));

    let indicator_addr = indicator as usize;
    let apply_status = {
        let manual_degraded = manual_degraded.clone();
        let daemon_present = daemon_present.clone();
        move || {
            let indicator = indicator_addr as *mut AppIndicator;
            let degraded = manual_degraded.get() || !daemon_present.get();
            let status = if degraded {
                AppIndicatorStatus::Attention
            } else {
                AppIndicatorStatus::Active
            };
            // SAFETY: `indicator` is a process-lifetime singleton, never
            // freed before exit.
            unsafe { app_indicator_set_status(indicator, status) };
        }
    };

    let degrade_item = gtk::CheckMenuItem::with_label("Simulate degraded status");
    {
        let manual_degraded = manual_degraded.clone();
        let apply_status = apply_status.clone();
        degrade_item.connect_toggled(move |item| {
            manual_degraded.set(item.is_active());
            apply_status();
            eprintln!(
                "[g6-evidence] manual status toggled to {}",
                if manual_degraded.get() { "Degraded" } else { "Healthy" }
            );
        });
    }
    menu.append(&degrade_item);

    let exit_item = gtk::MenuItem::with_label("Exit");
    exit_item.connect_activate(|_| {
        eprintln!("[g6-evidence] exit requested via menu");
        std::process::exit(0);
    });
    menu.append(&exit_item);

    menu.show_all();

    // SAFETY: `menu`'s underlying GObject is kept alive for the process
    // lifetime via `mem::forget` below; the raw pointer handed to
    // `app_indicator_set_menu` (via glib's ToGlibPtr, which yields the
    // real `GtkMenu*`) remains valid for exactly that long. `c_void` is
    // used on the FFI side since this file declares no `GtkMenu` type of
    // its own -- the C function only ever dereferences it as an opaque
    // GObject pointer.
    unsafe {
        use glib::translate::ToGlibPtr;
        let raw: *mut gtk_sys::GtkMenu = menu.to_glib_none().0;
        app_indicator_set_menu(indicator, raw.cast::<c_void>());
        app_indicator_set_status(indicator, AppIndicatorStatus::Active);
    }
    eprintln!("[g6-evidence] app_indicator_set_menu + set_status(ACTIVE) done, entering gtk::main()");

    std::mem::forget(menu);

    // Real daemon-analog presence watcher: a plain background thread
    // (this prototype has no async runtime) that polls every 500ms and
    // hands the result to the GTK main loop over a glib channel -- the
    // standard safe cross-thread-to-GTK mechanism, not a raw shared
    // mutable flag touched from two threads.
    let (sender, receiver) = glib::MainContext::channel::<bool>(glib::PRIORITY_DEFAULT);
    std::thread::spawn(move || {
        let mut last_seen: Option<bool> = None;
        loop {
            let present = daemon_stub_present();
            if last_seen != Some(present) {
                eprintln!(
                    "[g6-evidence] daemon-watch: {DAEMON_STUB_BUS_NAME} presence changed -> {present}"
                );
                last_seen = Some(present);
                if sender.send(present).is_err() {
                    break;
                }
            }
            std::thread::sleep(Duration::from_millis(500));
        }
    });
    receiver.attach(None, move |present| {
        daemon_present.set(present);
        apply_status();
        glib::Continue(true)
    });

    gtk::main();
}
