//! G6 EVIDENCE-ONLY PROTOTYPE — NOT PRODUCTION CODE.
//!
//! Candidate spike for the G6 "Indicator decision" gate (TDD contract
//! §30; `docs/guardian/30_TDD/GUARDIAN_G6_IMPLEMENTATION_HANDOFF.md`).
//! Evaluates candidate 2 ("GLib-only Ayatana AppIndicator 2.x") under
//! real GNOME 50/Xfce 4.20 sessions in a disposable VM.
//!
//! This library (`libayatana-appindicator-glib`) has genuinely no GTK
//! dependency at all -- its menu API is the modern `GMenu`/
//! `GSimpleActionGroup` (GIO action-model) shape, not `GtkMenu`/
//! libdbusmenu the way candidate 1 requires. There is no published Rust
//! binding for this library at all (candidate 1's only binding exists
//! but is broken against this OS -- see
//! `tests/vm/g6-candidate-ayatana-gtk3/build.rs`); this candidate uses a
//! minimal hand-written `extern "C"` FFI surface verified against the
//! real installed header
//! (`/usr/include/libayatana-appindicator-glib/ayatana-appindicator.h`),
//! plus the safe `gio`/`glib` crates for the `GMenu`/`GSimpleActionGroup`
//! construction this library's own API actually wants.
//!
//! Contains no Guardian authorization, transaction, provider, diagnostic,
//! or recorder logic -- never references `guardian-core`. DISPOSABLE:
//! built and run only inside a disposable VM, never on a primary
//! workstation.

use std::cell::Cell;
use std::ffi::{CString, c_char, c_void};
use std::rc::Rc;

use gio::prelude::*;

#[repr(C)]
struct AppIndicator {
    _private: [u8; 0],
}

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Copy)]
enum AppIndicatorCategory {
    ApplicationStatus = 0,
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

#[link(name = "ayatana-appindicator-glib")]
unsafe extern "C" {
    fn app_indicator_new(
        id: *const c_char,
        icon_name: *const c_char,
        category: AppIndicatorCategory,
    ) -> *mut AppIndicator;
    fn app_indicator_set_status(indicator: *mut AppIndicator, status: AppIndicatorStatus);
    fn app_indicator_set_menu(indicator: *mut AppIndicator, menu: *mut c_void);
    fn app_indicator_set_actions(indicator: *mut AppIndicator, actions: *mut c_void);
}

fn cstr(s: &str) -> CString {
    CString::new(s).expect("no interior NUL")
}

fn main() {
    eprintln!(
        "[g6-evidence] G6 EVIDENCE-ONLY ayatana-glib prototype starting, pid={}",
        std::process::id()
    );

    let id = cstr("guardian-g6-evidence-ayatana-glib");
    let icon = cstr("emblem-default");

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

    // GAction-model menu: build a GSimpleActionGroup under the "app"
    // prefix (the conventional GMenuModel prefix for this kind of
    // export) and a GMenu whose items reference those actions by
    // "app.<name>" detailed action names.
    let action_group = gio::SimpleActionGroup::new();

    let click_count = Rc::new(Cell::new(0_u64));
    let click_action = gio::SimpleAction::new("click_me", None);
    {
        let click_count = click_count.clone();
        click_action.connect_activate(move |_, _| {
            click_count.set(click_count.get() + 1);
            eprintln!(
                "[g6-evidence] menu item activated, menu_clicks={}",
                click_count.get()
            );
        });
    }
    action_group.add_action(&click_action);

    let degrade_action = gio::SimpleAction::new_stateful("degraded", None, &false.to_variant());
    {
        let indicator_addr = indicator as usize;
        degrade_action.connect_activate(move |action, _| {
            let indicator = indicator_addr as *mut AppIndicator;
            let was_degraded = action
                .state()
                .and_then(|v| v.get::<bool>())
                .unwrap_or(false);
            let now_degraded = !was_degraded;
            action.set_state(&now_degraded.to_variant());
            let status = if now_degraded {
                AppIndicatorStatus::Attention
            } else {
                AppIndicatorStatus::Active
            };
            // SAFETY: `indicator` is a process-lifetime singleton, never
            // freed before exit.
            unsafe { app_indicator_set_status(indicator, status) };
            eprintln!(
                "[g6-evidence] status toggled to {}",
                if now_degraded { "Degraded" } else { "Healthy" }
            );
        });
    }
    action_group.add_action(&degrade_action);

    let exit_action = gio::SimpleAction::new("exit", None);
    exit_action.connect_activate(|_, _| {
        eprintln!("[g6-evidence] exit requested via menu");
        std::process::exit(0);
    });
    action_group.add_action(&exit_action);

    let menu = gio::Menu::new();
    menu.append(Some("Click me (see stderr for count)"), Some("app.click_me"));
    menu.append(Some("Simulate degraded status"), Some("app.degraded"));
    menu.append(Some("Exit"), Some("app.exit"));

    // SAFETY: both `menu` and `action_group`'s underlying GObjects are
    // kept alive for the process lifetime via `mem::forget` below; the
    // raw pointers handed to the C API remain valid for exactly that
    // long. `c_void` is used on the FFI side since this file declares no
    // `GMenu`/`GSimpleActionGroup` type of its own -- the C function only
    // ever dereferences these as opaque GObject pointers.
    unsafe {
        use glib::translate::ToGlibPtr;
        let menu_raw: *mut gio_sys::GMenu = menu.to_glib_none().0;
        let actions_raw: *mut gio_sys::GSimpleActionGroup = action_group.to_glib_none().0;
        app_indicator_set_actions(indicator, actions_raw.cast::<c_void>());
        app_indicator_set_menu(indicator, menu_raw.cast::<c_void>());
        app_indicator_set_status(indicator, AppIndicatorStatus::Active);
    }
    eprintln!(
        "[g6-evidence] app_indicator_set_actions + set_menu + set_status(ACTIVE) done, entering main loop"
    );

    std::mem::forget(menu);
    std::mem::forget(action_group);

    let main_loop = glib::MainLoop::new(None, false);
    main_loop.run();
}
