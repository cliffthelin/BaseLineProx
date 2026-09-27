# ADR-006: Guardian desktop indicator mechanism

- Status: Accepted
- Date: 2026-09-01
- Governing gate: G6 — Desktop Indicator Decision

## Revision note (preserved history — read before the Decision below)

This ADR has been revised twice since its first version, and both
revisions are preserved here rather than written out of history:

1. **First revision.** An independent audit found an earlier version's
   `Status: Accepted — conditional selection` line functioned as a
   substitute for a required PASS: `ksni`'s Xfce menu-open result was
   UNRESOLVED at the time, and several other required tests were
   untested. A closure pass resolved every one of those items with real
   evidence, and the status was corrected to plain "Accepted."
2. **Second revision (this one).** A further independent audit of that
   closed state found two blocking problems with the evidence itself,
   not just its labeling:
   - **Candidate 1's disqualification was unsupported.** The audit
     reproduced candidate 1 successfully in a fresh disposable GNOME/
     Wayland VM using `GDK_BACKEND=wayland`, `WAYLAND_DISPLAY=wayland-0`,
     no `DISPLAY`, no `XAUTHORITY` — `gtk_init()` succeeded, the
     indicator registered, the icon appeared, the menu opened, the
     handler invoked. The original spike never tried this launch
     configuration, and the "structural, unfixable X11/XWayland
     dependency" language in the prior version of this ADR was
     withdrawn as unsupported.
   - **"Reconnect after daemon restart" was conflated with
     indicator-process restart.** The evidence credited toward that
     required test was killing and relaunching the indicator's own
     process, not a Guardian-daemon analog restarting while the
     indicator stayed alive. Real evidence for the correct scenario
     existed for `ksni` on GNOME but was filed under a different
     heading, and did not exist at all for Xfce.

   **This revision reflects the repair that followed**: candidate 1 was
   re-tested in full, on both desktops, under the corrected launch
   configuration (`docs/evidence/g6/G6_CANDIDATE1_REPAIR_EVIDENCE.md`),
   and the genuinely-correct daemon-analog-restart-while-alive scenario
   was run for `ksni` on Xfce
   (`docs/evidence/g6/G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md`). The
   outcome of that real re-testing, not an assumption that candidate 1
   would obviously win once un-disqualified, is what this ADR's Decision
   section now records.

## Context

G6 is an early decision/spike gate (not a production-implementation
gate — see the §30/§39 ordering resolution recorded in the G6 handoffs)
that must select, with real evidence rather than library-recency
preference, which of three candidate mechanisms Guardian's future
desktop tray indicator should be built on:

1. Legacy GTK3 Ayatana AppIndicator (`libayatana-appindicator3`)
2. GLib-only Ayatana AppIndicator 2.x (`libayatana-appindicator-glib`)
3. Direct Rust SNI + canonical DBusMenu (`ksni`)

All three were built as real, minimal, explicitly non-production
prototypes (`tests/vm/g6-candidate-*/`) and tested against real GNOME
50/Wayland and Xfce 4.20 sessions in disposable qemu VMs, per contract
§30's required-test list. No mocks, headless fixtures, or synthetic D-Bus
sessions were used for any pass/fail determination — see the thirteen
checkpoint evidence documents in `docs/evidence/g6/` for full raw
evidence, and `G6_CANDIDATE_COMPARISON.md` for the consolidated matrix
this ADR is built from.

## Decision

**`ksni` (direct Rust SNI + canonical DBusMenu) is selected** as
Guardian's desktop indicator mechanism.

This is **not** because candidate 1 fails a required test — after
repair, it does not. Both candidate 1 and `ksni` now pass every required
§30 test directly evidenced against them, on both GNOME 50/Wayland and
Xfce 4.20. Candidate 2 remains disqualified.

- The GLib-only Ayatana AppIndicator 2.x candidate is **disqualified** on
  both required desktops by a directly diagnosed, independently
  reproduced protocol incompatibility: it exports its menu via the
  modern `org.gtk.Menus`/`org.gtk.Actions` D-Bus interfaces, which
  neither GNOME's `ubuntu-appindicators@ubuntu.com` extension nor Xfce's
  `xfce4-indicator-plugin` understand — both still expect the legacy
  `com.canonical.dbusmenu` protocol. The candidate's own D-Bus
  registration, menu content, and action wiring were independently
  verified correct via direct D-Bus calls on both desktops; the failure
  is a real ecosystem gap, not an implementation defect, but it is
  disqualifying regardless.
- **Legacy GTK3 Ayatana AppIndicator is not disqualified.** Under the
  corrected launch configuration, it passes icon-appears, menu-opens,
  handler-invokes, visible status/degraded state (now genuinely visible
  after adding one missing API call), no-X11-dependency, both P0-IND-003
  reconnect sub-scenarios (panel/Shell restart and Guardian-daemon-analog
  restart with the indicator confirmed alive throughout, on both
  desktops), no-duplicate-icon, and clean logout/login lifecycle. See
  `G6_CANDIDATE1_REPAIR_EVIDENCE.md`.
- **`ksni` also passes every required test**, on both desktops, with no
  open residuals (the Xfce daemon-unavailable icon, previously an
  undisclosed-but-noted residual, was directly screenshotted during the
  repair — see `G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md`).

**Since both remaining candidates pass all required targets, §30's own
rule resolves the tie on simplicity, using real evidenced facts, not
invented scoring:**

| Factor | Candidate 1 | `ksni` |
|---|---|---|
| Rust binding | Only published binding is broken against this OS (reproduced `bindgen` failure) — requires a hand-written, unsafe FFI layer to maintain indefinitely | Published, actively-maintained, safe binding; compiled cleanly on every fresh build in this gate |
| Toolkit dependency | Requires linking GTK3 in full merely to build a `GtkMenu` structure, though no GTK window is ever shown | No GTK dependency — pure Rust + `zbus` |
| Launch environment | Requires an explicit, non-default `GDK_BACKEND=wayland` setting under GNOME/Wayland — confirmed by direct reproduction that omitting it causes a real failure | No special launch environment required on either desktop, confirmed across every test in this gate |
| Status-icon API completeness | Requires an additional explicit `app_indicator_set_attention_icon_full` call for a visible state change | A single `icon_name()` method automatically reflects state |
| Upstream signal | The C library prints a runtime deprecation warning on every launch, recommending the library candidate 2 is built on (itself independently disqualified in this gate) | No such signal |

`ksni` is selected on these concrete grounds — not because it is "the
pure-Rust option" as a preference. That it happens to be pure Rust is a
consequence of this comparison (every row above is a real dependency/
toolkit/environment fact), not the reason for it. Full table and
reasoning: `G6_CANDIDATE_COMPARISON.md`.

## Why not the others, restated plainly

- Legacy GTK3 Ayatana AppIndicator: passes every required test once
  launched correctly, but carries a real, evidenced complexity burden
  (broken upstream Rust binding, GTK3 dependency, non-default launch
  environment requirement, an extra API call for correct status
  visuals) that `ksni` does not.
- GLib-only Ayatana AppIndicator 2.x: despite being the library its own
  predecessor's runtime deprecation warning recommends switching to, it
  is the only candidate that fails to render on either required desktop
  out of the box, because neither desktop's actual indicator-consuming
  code understands its modern menu-export protocol. Real irony, real
  disqualification.

## Real findings carried forward for G7+ (not this ADR's scope to act on)

- The `ubuntu-appindicators@ubuntu.com` / `xfce4-indicator-plugin`
  dependency `ksni` requires on both desktops is not a Guardian-authored
  component and is not guaranteed present on every real Ubuntu 26.04
  install. A production Guardian indicator should detect and clearly
  report the absence of a working `StatusNotifierWatcher`, not silently
  show nothing.
- Icon names must be verified present in the target icon theme before
  use, or Guardian should ship its own icon asset — see
  `G6_ICON_NAME_CORRECTION.md`.
- The production indicator must be launched via proper desktop session
  autostart (cleaned up by `systemd-logind` on logout), not as a
  detached background process — see
  `G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`'s stale-registration finding
  on Xfce.
- `ksni`'s reconnect-after-panel-restart behavior on both desktops
  depends on the host desktop's own recovery mechanism (GNOME extension
  fallback bus-scan; Xfce's persistent indicator-application service),
  not on `ksni` proactively re-announcing itself. This dependency should
  be understood by whoever builds G7's production indicator on top of
  `ksni`.
- If a future gate ever needs to reconsider this decision, note that
  candidate 1 is a real, evidenced, working fallback (not merely a
  rejected idea) — its own complexity costs, not a functional failure,
  are why it was not selected.

## What this ADR does not do

Consistent with this gate's explicit scope: **G6 selects an indicator
mechanism. It does not certify a production guardian-indicator
implementation.** This ADR does not authorize building the G7+ production
indicator daemon, expanding Guardian's public D-Bus surface, or beginning
any implementation work beyond this gate's own evidence prototypes. The
`ksni`-based prototype in `tests/vm/g6-candidate-ksni/`, the candidate 1
prototype in `tests/vm/g6-candidate-ayatana-gtk3/`, and the minimal
`tests/vm/g6-daemon-evidence-stub/` used to evidence the
daemon-unavailable/daemon-restart required tests are all evidence-only
artifacts (each explicitly marked as such in its own module doc comment)
and are not the basis for G7's actual code — G7 must build its own
production indicator daemon using `ksni` as a library dependency,
subject to normal G7 TDD discipline, not by promoting any spike artifact
directly.

## Evidence

Full raw evidence, including screenshots with explicit provenance
labeling, VM setup/teardown records, and D-Bus introspection captures:

- `docs/evidence/g6/G6_GNOME_KSNI_SPIKE_EVIDENCE.md`
- `docs/evidence/g6/G6_XFCE_KSNI_SPIKE_EVIDENCE.md`
- `docs/evidence/g6/G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` (original spike;
  see correction notices and `G6_CANDIDATE1_REPAIR_EVIDENCE.md` for the
  corrected no-X11-dependency and status-visibility results)
- `docs/evidence/g6/G6_AYATANA_GLIB_SPIKE_EVIDENCE.md`
- `docs/evidence/g6/G6_P0_IND_003_RECONNECT_EVIDENCE.md` (GNOME; see
  correction notice regarding "Scenario 2" labeling)
- `docs/evidence/g6/G6_XFCE_KSNI_MENU_RESOLUTION.md`
- `docs/evidence/g6/G6_XFCE_RECONNECT_EVIDENCE.md` (see correction
  notice regarding "Scenario B" labeling)
- `docs/evidence/g6/G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`
- `docs/evidence/g6/G6_DAEMON_UNAVAILABLE_EVIDENCE.md`
- `docs/evidence/g6/G6_ICON_NAME_CORRECTION.md`
- `docs/evidence/g6/G6_CANDIDATE1_REPAIR_EVIDENCE.md` (repair: corrected
  no-X11-dependency result, full re-tested matrix on both desktops)
- `docs/evidence/g6/G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md` (repair:
  closes the Xfce Guardian-daemon-analog-restart gap)
- `docs/evidence/g6/G6_CANDIDATE_COMPARISON.md` (consolidated matrix and
  the simplicity comparison this ADR's decision is drawn from)
