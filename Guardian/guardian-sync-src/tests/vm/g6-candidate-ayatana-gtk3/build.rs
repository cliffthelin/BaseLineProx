//! G6 EVIDENCE-ONLY build script -- NOT PRODUCTION.
//!
//! `libayatana-appindicator-sys` (crates.io 0.2.0) always regenerates its
//! bindings via `bindgen` 0.58 at build time (its own build.rs has no
//! pre-generated-bindings fallback despite the crate's README implying
//! one exists -- confirmed by reading that crate's actual build.rs).
//! That old bindgen version cannot parse Ubuntu 26.04's current
//! `glib-object.h` (`"_GValue_union_(...)" is not a valid Ident` --
//! a real, reproducible tooling incompatibility, itself valuable G6
//! evidence about this candidate's current Rust-ecosystem viability).
//!
//! This candidate therefore links directly against the same C library
//! via a minimal, hand-written FFI surface in `src/main.rs` (verified
//! against the real installed header,
//! `/usr/include/libayatana-appindicator3-0.1/libayatana-appindicator/app-indicator.h`)
//! instead of depending on that broken sys crate.
fn main() {
    let library = pkg_config::probe_library("ayatana-appindicator3-0.1")
        .expect("ayatana-appindicator3-0.1 not found via pkg-config");
    for path in library.link_paths {
        println!("cargo:rustc-link-search=native={}", path.display());
    }
    println!("cargo:rustc-link-lib=ayatana-appindicator3");
}
