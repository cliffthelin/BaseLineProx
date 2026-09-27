# G6 Candidate Comparison — Desktop Indicator Decision Gate

**Status: final comparison record for G6, built from real evidence
gathered across fourteen checkpoint documents in this directory.** This
document does not introduce new evidence; it consolidates
`G6_GNOME_KSNI_SPIKE_EVIDENCE.md`, `G6_XFCE_KSNI_SPIKE_EVIDENCE.md`,
`G6_AYATANA_GTK3_SPIKE_EVIDENCE.md`, `G6_AYATANA_GLIB_SPIKE_EVIDENCE.md`,
`G6_P0_IND_003_RECONNECT_EVIDENCE.md`, `G6_XFCE_KSNI_MENU_RESOLUTION.md`,
`G6_XFCE_RECONNECT_EVIDENCE.md`, `G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`,
`G6_DAEMON_UNAVAILABLE_EVIDENCE.md`, `G6_ICON_NAME_CORRECTION.md`,
`G6_CANDIDATE1_REPAIR_EVIDENCE.md`, and
`G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md` against the contract's own
10-item required-test list (§30) and applies its selection rule. The
selection this document reaches is recorded formally in
`docs/adr/ADR-006-guardian-indicator-mechanism.md`.

**Revision history (preserved, not erased):**

1. An early version of this document (and `ADR-006`) recorded `ksni` as
   "Accepted — conditional selection" while the Xfce menu-open result
   was UNRESOLVED and several other required tests were untested. A
   closure pass resolved every one of those items with real evidence.
2. **An independent audit of that closure then found two blocking
   problems.** First, live re-execution showed candidate 1's stated
   disqualification ("structural, unfixable X11/XWayland dependency")
   did not hold up: the candidate ran fully functionally with zero X11
   involvement once `GDK_BACKEND=wayland` was set — a launch
   configuration the original spike never tried. Second, the evidence
   labeled "reconnect after daemon restart" for `ksni` actually tested
   killing and relaunching the indicator's own process, not a
   Guardian-daemon analog restarting while the indicator stayed alive —
   real evidence for the correct scenario existed for `ksni` on GNOME
   but was filed under a different heading, and did not exist at all
   for Xfce.
3. **This revision reflects the repair that followed that audit**:
   candidate 1 was re-tested in full under the corrected native-Wayland
   launch on both desktops (`G6_CANDIDATE1_REPAIR_EVIDENCE.md`), and the
   genuinely-correct daemon-analog-restart-while-alive scenario was run
   for `ksni` on Xfce (`G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md`). The
   original mislabeled evidence remains in place with correction notices
   pointing to the real scenario, per the repair brief's explicit
   instruction to preserve history rather than rewrite it away.

## The rule being applied

> "The winning implementation is the simplest candidate that passes all
> required targets. The test result, not library recency, selects the
> implementation." (§30, verbatim)

Applied honestly, this rule requires checking all ten required tests
against both target environments for every candidate, and disqualifying
any candidate that fails even one, "regardless of how idiomatic or
modern it is." It also means: **when more than one candidate passes all
required targets, the selection between them must rest on real,
evidenced complexity/dependency facts, not arbitrary scoring or a
preference for one implementation style over another.**

## Comparison matrix

Legend: **PASS** (directly evidenced), **FAIL** (directly evidenced),
**N/A** (test does not apply to this target as designed).

### Candidate 1 — legacy GTK3 Ayatana AppIndicator

*(Re-tested during G6 repair — see `G6_CANDIDATE1_REPAIR_EVIDENCE.md`
for full evidence. Not re-litigated from scratch; the icon/menu/handler
findings from the original spike were unaffected and are cited as-is.)*

| Required test | GNOME 50 | Xfce 4.20 |
|---|---|---|
| icon appears | PASS | PASS |
| menu opens | PASS | PASS |
| menu actions invoke handler | PASS | PASS |
| state/icon update propagates | **PASS** (repaired — `app_indicator_set_attention_icon_full` added; glyph now genuinely changes) | **PASS** (repaired, same mechanism) |
| no X11 dependency | **PASS** (repaired — `GDK_BACKEND=wayland`/`WAYLAND_DISPLAY` launch confirmed zero X11/XWayland involvement; the original FAIL was a launch-configuration gap, not a structural property) | N/A — Xfce is X11 by design |
| reconnect after panel/Shell restart | PASS (extension disable/enable, candidate pid unchanged) | PASS (real `xfce4-panel -r`, candidate pid unchanged) |
| reconnect after daemon restart (Guardian-daemon-analog, indicator alive) | **PASS** — real evidence-only stub killed/relaunched, candidate pid confirmed unchanged throughout, real detected degraded state, real recovery | **PASS** — same mechanism, candidate pid confirmed unchanged throughout |
| daemon unavailable shows degraded state | PASS (same mechanism as the row above — real detection, visible warning-triangle glyph, not visually distinct from the manual toggle, a disclosed difference from `ksni`) | PASS (same mechanism) |
| no duplicate icon | PASS (confirmed across both reconnect scenarios) | PASS (confirmed across both reconnect scenarios) |
| clean user logout/login lifecycle | PASS (candidate process did not survive logout — a real, clean deregistration; fresh relaunch showed exactly one item) | PASS (same pattern) |

**Verdict: candidate 1 now passes every required §30 test directly
evidenced against it, on both target environments.** The original "no
X11 dependency: FAIL" and "state/icon update propagates: PARTIAL"
findings are superseded by the repair, not erased — both remain
documented in `G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` and
`G6_CANDIDATE1_REPAIR_EVIDENCE.md` as real findings about the original
launch configuration and the API surface, respectively.

### Candidate 2 — GLib-only Ayatana AppIndicator 2.x

*(Unreopened — no new evidence contradicts this candidate's
disqualification; the audit accepted this disqualification as sound and
the repair brief explicitly did not require re-testing it.)*

| Required test | GNOME 50 | Xfce 4.20 |
|---|---|---|
| icon appears | **FAIL** — `com.canonical.dbusmenu` interface not found, directly thrown by GNOME Shell | **FAIL** — identical root cause, directly captured in `xfce4-indicator-plugin`'s own debug log |
| all other tests | N/T — blocked by icon-appears failure | N/T |

**Verdict: disqualified**, unchanged, on both required desktops, for a
directly diagnosed, reproduced-on-two-independent-consumers reason: this
library's modern `org.gtk.Menus`/`org.gtk.Actions` menu export is not
understood by either required desktop's actual indicator-rendering code.
The candidate's own D-Bus registration, menu content, and action
handling were independently verified correct via direct D-Bus calls on
both desktops — the failure is a real ecosystem gap, not an
implementation defect, but it is disqualifying regardless.

### Candidate 3 — direct Rust SNI + canonical DBusMenu (`ksni`)

| Required test | GNOME 50 | Xfce 4.20 |
|---|---|---|
| icon appears | PASS | PASS |
| menu opens | PASS | PASS — closed via `G6_XFCE_KSNI_MENU_RESOLUTION.md`; full click → menu → item-click → log-confirmed-handler chain demonstrated |
| menu actions invoke handler | PASS | PASS |
| state/icon update propagates | PASS | PASS — glyph visibly changes to warning-triangle on status toggle |
| no X11 dependency | PASS — empirically confirmed, no `DISPLAY`/`XAUTHORITY` set | N/A — Xfce is X11 by design |
| reconnect after panel/Shell restart | PASS | PASS — real `xfce4-panel -r`, recovery via the persistent `ayatana-indicator-application-service`, not candidate-side re-registration |
| reconnect after daemon restart (Guardian-daemon-analog, indicator alive) | **PASS** — `G6_DAEMON_UNAVAILABLE_EVIDENCE.md`; indicator pid confirmed unchanged throughout, real detected degraded state (`dialog-error`), real recovery | **PASS** — `G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md` (closed during G6 repair); same pattern, indicator pid confirmed unchanged throughout |
| daemon unavailable shows degraded state | PASS — real detection of a real evidence-only D-Bus stub's presence/absence, distinct `dialog-error` icon, not a simulated toggle | PASS — same mechanism, now directly screenshotted on Xfce as part of the daemon-restart repair (closes the prior "minor residual" note) |
| no duplicate icon | PASS | PASS — confirmed across reconnect scenarios and the logout/login stale-registration check |
| clean user logout/login lifecycle | PASS | PASS — includes a disclosed, non-candidate finding about stale registrations surviving logout when a process is launched outside proper session scoping (relevant to G7+ launch-mechanism design, not a `ksni` defect) |

**Verdict: `ksni` passes every required §30 test directly evidenced
against it, on both target environments, with no open residuals
remaining.**

## Applying the selection rule

Both candidate 1 and `ksni` now pass every required §30 test on both
target environments. Candidate 2 remains disqualified. Per the rule's
own text, the tie between the two passing candidates must be broken on
**simplicity**, using real, evidenced complexity/dependency facts:

| Factor | Candidate 1 | `ksni` |
|---|---|---|
| Rust binding availability | The only published binding (`libayatana-appindicator-sys` 0.2.0) fails to build against this project's target OS (a real, reproduced `bindgen` failure) — a hand-written, unsafe `extern "C"` FFI layer is required as a substitute and must be maintained going forward. | Published, actively-maintained, safe binding (`ksni` 0.3.6) that compiled cleanly on every fresh build attempted in this gate, with no FFI workaround needed. |
| Toolkit dependency | Requires linking GTK3 in full merely to construct a `GtkMenu` structure for the indicator library's menu API, even though no GTK window is ever displayed. | No GTK dependency at all — pure Rust plus `zbus` for D-Bus. |
| Launch environment | Requires an explicit, non-default `GDK_BACKEND=wayland` setting under GNOME/Wayland to avoid falling back to XWayland — confirmed via direct reproduction that omitting this setting causes a real failure. A production launcher/session-integration must know to set this correctly. | Works correctly under GNOME and Xfce with no special launch environment beyond the ordinary session bus address — confirmed across every test in this gate. |
| Status/icon-update API completeness | Requires an additional explicit `app_indicator_set_attention_icon_full` call, made once at startup, to get a visually distinct state icon; without it, status changes are invisible (the original spike's own finding). | A single `icon_name()` method automatically reflects state; no extra call needed. |
| Desktop dependency | Requires the same external consumer package on each desktop (`ubuntu-appindicators@ubuntu.com` / `xfce4-indicator-plugin`) as `ksni` — no difference here. | Same. |
| Upstream signal | The C library itself prints a runtime deprecation warning on every launch, recommending `libayatana-appindicator-glib` (candidate 2, independently disqualified in this same gate) as its replacement. | No such signal. |

**`ksni` is selected as the simpler candidate on these concrete,
evidenced grounds — not because it is "the pure-Rust option," which is
a consequence of this comparison, not its basis.** Every row above is a
real, disclosed fact established in this gate's own evidence, not an
invented scoring dimension.

`ksni` is selected as Guardian's indicator mechanism under §30's own
rule: both remaining candidates pass all required targets, and `ksni` is
the simpler of the two on the evidenced dependency/complexity grounds
above. This is recorded in `ADR-006` as a final selection.

## Caveats and follow-ups for the record

- The `ubuntu-appindicators@ubuntu.com` / `xfce4-indicator-plugin`
  dependency `ksni` requires on both desktops is not a Guardian-authored
  component and is not guaranteed present on every real Ubuntu 26.04
  install. A production Guardian indicator should detect and clearly
  report the absence of a working `StatusNotifierWatcher`, not silently
  show nothing.
- The icon-name/icon-theme fragility documented in
  `G6_ICON_NAME_CORRECTION.md` (a hardcoded icon name that resolves as a
  generic fallback in one VM and as fully invisible in another) applies
  to whatever production icon name Guardian eventually chooses. It must
  be verified against the target theme or shipped as Guardian's own icon
  asset.
- The stale-registration finding in `G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`
  (a non-session-scoped process can leave a stale icon visible after
  logout, because Xfce's watcher service is per-user, not per-session)
  is a real launch-mechanism design constraint for G7+: the production
  indicator must be launched via proper desktop session autostart
  (killed cleanly by `systemd-logind` on logout), not as a detached
  background process.
- `ksni`'s reconnect-after-panel-restart behavior on both desktops
  depends on the host desktop's own recovery mechanism (GNOME extension
  fallback bus-scan; Xfce's persistent indicator-application service),
  not on `ksni` proactively re-announcing itself. This dependency should
  be understood by whoever builds G7's production indicator.

## What this document does not do

Per this gate's explicit scope: **G6 selects an indicator mechanism. It
does not certify a production guardian-indicator implementation.**
Nothing in this document, or in `ADR-006`, authorizes building the G7+
production indicator daemon, expanding Guardian's public D-Bus surface,
or beginning any implementation work beyond this gate's own evidence
prototypes. The prototypes in `tests/vm/g6-candidate-*/` and
`tests/vm/g6-daemon-evidence-stub/` remain evidence-only artifacts,
explicitly marked non-production, and are not the basis for G7's actual
code.
