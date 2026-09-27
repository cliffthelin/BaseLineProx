//! G6 EVIDENCE-ONLY build script -- NOT PRODUCTION.
//!
//! Links against `libayatana-appindicator-glib` (candidate 2, "GLib-only
//! Ayatana AppIndicator 2.x") via a minimal hand-written FFI surface in
//! `src/main.rs` -- there is no published Rust binding for this library
//! at all (unlike candidate 1, which has a broken one; see
//! `tests/vm/g6-candidate-ayatana-gtk3/build.rs` for that finding).
fn main() {
    let library = pkg_config::probe_library("ayatana-appindicator-glib")
        .expect("ayatana-appindicator-glib not found via pkg-config");
    for path in library.link_paths {
        println!("cargo:rustc-link-search=native={}", path.display());
    }
    println!("cargo:rustc-link-lib=ayatana-appindicator-glib");
}
