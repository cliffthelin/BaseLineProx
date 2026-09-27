# G6 Evidence Spike — Candidate 1 (legacy GTK3 Ayatana AppIndicator) on GNOME 50 and Xfce 4.20

**Status: CHECKPOINT, part of the ongoing G6 candidate comparison.** Covers
candidate 1 ("legacy GTK3 Ayatana AppIndicator") on both required desktop
targets in a single pass. Companion documents:
`G6_GNOME_KSNI_SPIKE_EVIDENCE.md`, `G6_XFCE_KSNI_SPIKE_EVIDENCE.md`
(candidate 3). Candidate 2 (GLib-only Ayatana AppIndicator) and both
P0-IND-003 reconnect scenarios remain outstanding.

## A real, reproducible tooling finding (read before the environment section)

The only published Rust binding for this library,
[`libayatana-appindicator-sys` 0.2.0](https://crates.io/crates/libayatana-appindicator-sys),
**fails to build against Ubuntu 26.04's current glib headers.** Its
`build.rs` unconditionally regenerates FFI bindings via `bindgen` 0.58
(2020-era) at build time -- there is no pre-generated-bindings fallback
in this specific crate despite its README implying one might exist (that
note applies only to the separate, higher-level `libayatana-appindicator`
crate). `bindgen` 0.58 cannot parse the anonymous union in the currently
installed `gobject/gvalue.h`:

```text
thread 'main' panicked at bindgen-0.58.1/src/ir/context.rs:851:9:
"_GValue_union_(unnamed_at_/usr/include/glib-2_0/gobject/gvalue_h_137_3)" is not a valid Ident
```

This is real, reproduced evidence, not a guess -- confirmed by reading the
crate's actual `build.rs` on the VM and by the exact compiler/bindgen
error above. **This candidate's own prototype (`tests/vm/g6-candidate-ayatana-gtk3/`)
therefore links directly against `libayatana-appindicator3` via a
minimal, hand-written `extern "C"` FFI surface** (function/enum
signatures verified against the real installed header,
`/usr/include/libayatana-appindicator3-0.1/libayatana-appindicator/app-indicator.h`,
not guessed), plus the `gtk`/`gtk-sys` 0.15 crates for constructing the
required `GtkMenu`. This is itself directly relevant comparison evidence:
unlike candidate 3 (`ksni`), which has a fully safe, actively-published,
build-clean Rust API, candidate 1's *only* existing Rust binding is
currently broken against this project's actual target OS.

The library itself also self-reports as legacy:

```text
libayatana-appindicator-WARNING **: libayatana-appindicator is deprecated.
Please use libayatana-appindicator-glib in newly written code.
```

-- a real runtime warning from the C library itself, printed on every
run, recommending exactly the library candidate 2 is built on.

## Environment

```text
VM:              disposable qemu overlay, base image never modified
                 (same base cloud image reused across all G6 spikes)
OS:               Ubuntu 26.04 LTS (Resolute Raccoon)
GNOME:            GNOME Shell 50.1, Ubuntu AppIndicators extension
                  enabled from the start of this run (already established
                  working in the ksni spike)
Xfce:             Xfce 4.20.4-1, run in the SAME VM instance as the GNOME
                  test -- GDM supports launching a non-GNOME session for
                  an autologin user via AccountsService's `Session=`
                  field (`/var/lib/AccountsService/users/ubuntu`), which
                  this run used instead of provisioning an entirely
                  separate VM. xfce4-indicator-plugin added to the panel
                  (same procedure as the ksni Xfce spike).
Build:            libayatana-appindicator3-dev, libgtk-3-dev, clang,
                  libclang-dev, build-essential installed for the
                  bindgen-diagnosis attempt and the final hand-FFI build.
Capture method:   QEMU QMP screendump + input-send-event (same technique
                  as all other G6 spikes)
Run window:       2026-09-01T07:13Z (VM boot) -- 2026-09-01T07:24Z (teardown)
Teardown:         candidate process SIGTERM'd and confirmed exited on
                  both desktops; GNOME's enabled-extensions reverted to
                  empty; Xfce panel plugin-ids reverted to its 10-plugin
                  baseline; AccountsService Session field reverted to
                  empty; overlay disk deleted; qemu process confirmed gone.
```

## Candidate

`tests/vm/g6-candidate-ayatana-gtk3/` -- G6 EVIDENCE-ONLY / NOT
PRODUCTION (see its own module doc comment and `build.rs`). Not part of
the Cargo workspace. No `guardian-core` reference. Uses
`libayatana-appindicator3` (the GTK3-dependent library candidate 1 names)
plus `gtk`/`gtk-sys` 0.15 for `GtkMenu` construction.

## GNOME 50 results

**Real captured stdout/stderr:**

```text
[g6-evidence] G6 EVIDENCE-ONLY ayatana-gtk3 prototype starting, pid=18964
(g6-candidate-ayatana-gtk3:18964): libayatana-appindicator-WARNING **: libayatana-appindicator is deprecated...
[g6-evidence] app_indicator_new succeeded
[g6-evidence] app_indicator_set_menu + set_status(ACTIVE) done, entering gtk::main()
[g6-evidence] menu item activated, menu_clicks=1
[g6-evidence] status toggled to Degraded
```

(A first attempt without `XAUTHORITY` set failed with "Could not open X
display" -- GNOME 50/Wayland requires the real per-session XWayland
auth cookie, not just `DISPLAY=:0`. Corrected and re-run; documented here
for reproducibility, not as a candidate finding.)

- **Icon appears: PASS.** `gnome50-ayatana-gtk3/candidate-ayatana-gtk3_..._icon-visible-pass.png`.
  > **Correction (added during G6 evidence closure): see
  > `G6_ICON_NAME_CORRECTION.md`.** The `"emblem-default"` icon name used
  > here does not exist in the tested Adwaita build; the glyph shown is a
  > generic fallback, not the intended icon -- confirmed by contrast
  > against a true no-candidate baseline from the same VM session. Does
  > not change this PASS: a real, attributable element genuinely
  > appeared, and the menu/click evidence below is unaffected.
- **Menu opens + menu action invokes handler: PASS.** `..._menu-open-pass.png` shows the real menu with the prototype's exact three items; `menu_clicks=1` in the log confirms the click reached the handler.
- **Status/icon-update propagates: PARTIAL, with a real implementation-shape finding.** The status genuinely changed (`status toggled to Degraded` in the log, and `app_indicator_set_status(ATTENTION)` was genuinely called), but the rendered icon glyph did **not** visually change (`..._status-toggled-icon-unchanged.png` is visually identical to the icon-visible screenshot). This is because the AppIndicator C API requires a *separate* explicit call, `app_indicator_set_attention_icon`/`_full`, to change the icon shown for `ATTENTION` status -- this prototype (deliberately kept minimal, mirroring the ksni prototype's scope) never made that call. This is a real, disclosed API-shape difference from candidate 3: `ksni`'s single `icon_name()` method automatically reflects status in the icon, while AppIndicator requires the caller to explicitly wire a second icon for the attention state. Worth recording as a genuine comparison point (candidate 1 needs one more explicit call for equivalent behavior), not silently worked around.

## Xfce 4.20 results

**Real captured stdout/stderr:**

```text
[g6-evidence] G6 EVIDENCE-ONLY ayatana-gtk3 prototype starting, pid=22567
(g6-candidate-ayatana-gtk3:22567): libayatana-appindicator-WARNING **: libayatana-appindicator is deprecated...
[g6-evidence] app_indicator_new succeeded
[g6-evidence] app_indicator_set_menu + set_status(ACTIVE) done, entering gtk::main()
[g6-evidence] menu item activated, menu_clicks=1
```

- **Icon appears: PASS.** `xfce420-ayatana-gtk3/candidate-ayatana-gtk3_..._icon-visible-pass.png`, with `xfce4-indicator-plugin` installed (same requirement the ksni Xfce spike already established -- Xfce's stock panel has no SNI/AppIndicator awareness by default for either candidate tested so far).
  > **Correction (added during G6 evidence closure): see
  > `G6_ICON_NAME_CORRECTION.md`.** Same `"emblem-default"` fallback-glyph
  > finding as the GNOME result above applies here (a green
  > checkmark-in-circle fallback, not the intended icon) -- does not
  > change this PASS.
- **Menu opens + menu action invokes handler: PASS.** `..._menu-open-pass.png` shows the real menu; `menu_clicks=1` confirms the click reached the handler -- using the *exact same* synthetic-click technique (QMP `input-send-event` at the icon's confirmed on-screen coordinates) that produced no menu at all for candidate 3 on Xfce (`G6_XFCE_KSNI_SPIKE_EVIDENCE.md`).

**This directly narrows the ksni-on-Xfce menu-open ambiguity.** Since the
identical technique worked immediately here, the earlier unresolved
finding is now better explained as a genuine candidate-specific
interaction difference between `ksni`'s Rust-native DBusMenu
implementation and `xfce4-indicator-plugin`'s handling of it, rather than
a limitation of the QMP synthetic-click evidence-gathering method itself.
This is not yet fully proven (a definitive root-cause would require
inspecting `ksni`'s DBusMenu registration against
`xfce4-indicator-plugin`'s source), but it meaningfully shifts the
balance of evidence -- recorded here rather than in the ksni document, to
keep each candidate's own evidence file focused on what was actually
observed for that candidate.

## What this run does and does not establish

Established:

- Candidate 1 passes icon-appears and menu-opens/menu-action on both
  GNOME 50 (with the Ubuntu AppIndicators extension) and Xfce 4.20 (with
  `xfce4-indicator-plugin`) -- the same extension/plugin dependency
  candidate 3 also required on both desktops.
- A real, reproducible Rust-tooling gap: the only existing `-sys` crate
  for this library does not build against this project's actual target
  OS's headers.
- A real API-shape difference from candidate 3 regarding attention-state
  icon changes (requires an explicit second call).
- Meaningfully narrows (does not yet fully resolve) the candidate-3
  Xfce-menu-open mystery toward "candidate-specific," not
  "technique-specific."

Not yet established:

- Whether the deprecation warning has any practical maintenance
  implication beyond the message itself (e.g. whether Ubuntu 26.04 still
  ships active security/compatibility updates for this library) --
  worth checking before the final ADR, not undertaken this pass.
- Candidate 2 (GLib-only Ayatana AppIndicator) -- not yet tested.
- Both P0-IND-003 reconnect scenarios, for any candidate.
- A definitive root cause for the candidate-3-specific Xfce menu-open gap.
- Final candidate selection / ADR-006.

## Reproducibility

No dedicated VM setup script was written for this specific run (it reused
the existing `g6-gnome-vm-setup.sh` base-image/GNOME steps, plus the
Xfce/indicator-plugin steps from `g6-xfce-vm-setup.sh`, run manually
against a single shared VM instance for efficiency -- the two setup
scripts remain independently accurate for provisioning either desktop
from scratch). The prototype is `tests/vm/g6-candidate-ayatana-gtk3/`.
