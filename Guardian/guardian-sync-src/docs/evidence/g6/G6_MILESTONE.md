# Guardian Phase 0 — G6 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Gate shape — read before comparing to G0-G5's milestone records

G6 is a **decision/spike gate** (§30, "Desktop indicator decision gate"),
not an implementation gate. It has no `guardian-core` module and no
normative test IDs implemented as `cargo test` assertions — its three
normative IDs (P0-IND-001..003) are evidenced entirely through real
GNOME/Xfce desktop execution, not Rust unit tests. Its deliverable is a
real-evidence-backed decision (recorded in
`docs/adr/ADR-006-guardian-indicator-mechanism.md`), not a merged
production code change. The evidence prototypes in
`tests/vm/g6-candidate-*/` are explicitly marked non-production and are
excluded from the Cargo workspace; they do not affect `cargo test
--workspace`, which remains unchanged at 189 passed throughout this gate.
Unlike the earlier expectation that spike gates go untagged, G6 **is
tagged** following its accepted independent re-audit — see Decision
below.

## Decision

```text
Gate:               G6 — Desktop Indicator Decision
Accepted commit:    985a04d9a9af24cf9201d9dbeb1ebbbea762a139
G6 tag:              phase0-g6-indicator-decision (annotated, points to
                     985a04d9a9af24cf9201d9dbeb1ebbbea762a139)
Selected mechanism: ksni (direct Rust SNI + canonical DBusMenu)
Decision record:    docs/adr/ADR-006-guardian-indicator-mechanism.md
Status:             Accepted — PASS on independent re-audit
```

```text
P0-IND-001 (GNOME compatibility)  PASS
P0-IND-002 (Xfce compatibility)   PASS
P0-IND-003 (reconnect)            PASS -- panel/Shell restart and
                                   Guardian-daemon-analog restart (with
                                   the indicator confirmed alive
                                   throughout) both evidenced separately
                                   on both desktops; indicator-process
                                   restart evidence retained as a
                                   distinct, non-substituting scenario
                                   (see "Real findings" below)
```

Candidate 2 (GLib-only Ayatana AppIndicator 2.x) was disqualified by a
real, directly-evidenced menu-protocol incompatibility with both
required desktops' actual indicator-rendering code. **Candidate 1
(legacy GTK3 Ayatana AppIndicator) is not disqualified** — after repair
(see revision note below), it passes every required §30 test on both
desktops. `ksni` was selected over candidate 1 not because candidate 1
fails a required test, but on evidenced simplicity grounds (no broken
upstream Rust binding, no GTK3 dependency, no non-default launch
environment requirement, no extra API call needed for status visuals —
see `G6_CANDIDATE_COMPARISON.md`'s comparison table).

## Independent audit history (preserved in full, not collapsed)

This gate went through **two independent audits**, and both verdicts —
including the failing one — are recorded here deliberately rather than
smoothed into a single clean narrative:

```text
Round 0 -- premature selection (self-caught before external audit):
  ksni recorded as "Accepted -- conditional selection" while the Xfce
  menu-open result was UNRESOLVED and several other required tests were
  untested. Closed with real evidence (Xfce menu-open resolution, Xfce
  reconnect, logout/login lifecycle, daemon-unavailable degraded state).

Round 1 -- first independent audit:
  Verdict: FAIL -- G6 CANDIDATE SELECTION UNSUPPORTED.
  Findings:
    1. Candidate 1's "structural, unfixable X11/XWayland dependency"
       disqualification did not hold up under live re-execution
       (GDK_BACKEND=wayland was never tried in the original spike).
    2. "Reconnect after daemon restart" evidence for ksni actually
       tested indicator-process restart, not a Guardian-daemon analog
       restarting while the indicator stayed alive -- conflated on
       GNOME, entirely untested on Xfce.

Round 2 -- repair + second independent audit:
  Candidate 1 re-tested in full, both desktops, under the corrected
  native-Wayland launch (G6_CANDIDATE1_REPAIR_EVIDENCE.md). The
  genuinely-correct daemon-analog-restart-while-alive scenario run for
  ksni on Xfce (G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md). Mislabeled
  original evidence preserved in place with correction notices, not
  deleted or rewritten.
  Verdict: PASS -- G6 REPAIR ACCEPTED.
```

Full reasoning for each round: `ADR-006`.

## Real-desktop environments (requirement satisfied)

```text
GNOME:  GNOME Shell 50.1, Wayland session, gdm3, Ubuntu 26.04 LTS
        (Resolute Raccoon), ubuntu-appindicators@ubuntu.com extension
Xfce:   Xfce 4.20.4-1, xfce4-session, lightdm/gdm3-launched, Ubuntu
        26.04 LTS, xfce4-indicator-plugin
```

No mocks, unit-test-only claims, or headless GTK construction were used
to evidence P0-IND-001..003 anywhere in this gate -- every icon/menu/
handler/status/reconnect/lifecycle claim traces to a real disposable-VM
screenshot, D-Bus introspection call, or process log captured during
real execution.

## P0-IND-003 evidence, kept as three distinct scenarios (not collapsed)

```text
1. Panel/Shell restart:
   GNOME -- ubuntu-appindicators extension disable/enable cycle (no
   in-place Wayland shell restart exists); Xfce -- real xfce4-panel -r.
   Both candidates, both desktops: PASS, candidate pid unchanged,
   registration recovered, no duplicate, menu functional afterward.

2. Guardian-daemon-analog restart, indicator alive throughout:
   The evidence-only daemon stub (tests/vm/g6-daemon-evidence-stub/)
   killed and relaunched while the indicator's own process was left
   untouched -- pid confirmed unchanged before, during, and after, on
   both candidates, both desktops. Real detected degraded state, real
   recovery to healthy. See G6_DAEMON_UNAVAILABLE_EVIDENCE.md,
   G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md, G6_CANDIDATE1_REPAIR_EVIDENCE.md.

3. Indicator-process restart (kept separate, NOT credited as scenario 2):
   The indicator's own process killed and relaunched (fresh pid). Real,
   valuable evidence of clean deregistration/re-registration and no
   stale entries -- retained in G6_P0_IND_003_RECONNECT_EVIDENCE.md and
   G6_XFCE_RECONNECT_EVIDENCE.md with explicit correction notices
   marking it distinct from Guardian-daemon restart, after an
   independent audit found the two conflated in an earlier version of
   this evidence.
```

## Evidence-gathering method

All evidence was gathered against real, disposable GNOME 50 and Xfce
4.20 sessions in qemu VMs (bare `qemu-system-x86_64` + QMP
`screendump`/`input-send-event`, no VNC client, no mocks, no headless
fixtures) — never against the primary workstation, and never inferred
from library documentation alone. Every VM was torn down and its overlay
disk destroyed after evidence capture; base cloud images were never
written to. Thirteen checkpoint documents record this work in full, each
with explicit environment details, real captured process output, and
provenance-labeled screenshots:

```text
docs/evidence/g6/G6_GNOME_KSNI_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_XFCE_KSNI_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_AYATANA_GTK3_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_AYATANA_GLIB_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_P0_IND_003_RECONNECT_EVIDENCE.md
docs/evidence/g6/G6_XFCE_KSNI_MENU_RESOLUTION.md
docs/evidence/g6/G6_XFCE_RECONNECT_EVIDENCE.md
docs/evidence/g6/G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md
docs/evidence/g6/G6_DAEMON_UNAVAILABLE_EVIDENCE.md
docs/evidence/g6/G6_ICON_NAME_CORRECTION.md
docs/evidence/g6/G6_CANDIDATE1_REPAIR_EVIDENCE.md
docs/evidence/g6/G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md
docs/evidence/g6/G6_CANDIDATE_COMPARISON.md   (consolidated matrix)
```

## Required-test status (§30), consolidated

See `G6_CANDIDATE_COMPARISON.md` for the full per-candidate,
per-desktop matrix. Summary for the selected mechanism (`ksni`):

```text
icon appears                          GNOME PASS / Xfce PASS
menu opens                            GNOME PASS / Xfce PASS
menu actions invoke handler           GNOME PASS / Xfce PASS
state/icon update propagates          GNOME PASS / Xfce PASS
no X11 dependency                     GNOME PASS / Xfce N/A (X11 by design)
reconnect after panel/Shell restart   GNOME PASS / Xfce PASS
reconnect after daemon restart        GNOME PASS / Xfce PASS
daemon unavailable shows degraded     GNOME PASS / Xfce PASS (real
                                       stub-based detection, both desktops)
no duplicate icon                     GNOME PASS / Xfce PASS
clean user logout/login lifecycle     GNOME PASS / Xfce PASS
```

## Real findings this gate surfaced, worth preserving for G7+

Findings that materially affect how the eventual production indicator
must be built, not just this gate's own scoring:

- **candidate 1's original "structural X11/XWayland dependency" finding
  was corrected during repair** — the real cause was a launch that never
  set `GDK_BACKEND=wayland`; under that setting, candidate 1 runs with
  zero X11/XWayland involvement, confirmed by live reproduction. `ksni`
  still requires no special launch environment at all on either desktop,
  which remains a real, evidenced simplicity advantage — but it is not
  candidate 1's sole disqualifier the way earlier versions of this
  record stated. See `G6_CANDIDATE1_REPAIR_EVIDENCE.md`.
- **candidate 2's ecosystem gap is real and ironic** — the library its
  own predecessor's runtime deprecation warning recommends is the one
  candidate that fails to render on either required desktop, because
  neither desktop's actual indicator-consuming code understands its
  modern `org.gtk.Menus`/`org.gtk.Actions` menu export. Both GNOME's
  extension and Xfce's plugin independently fail at the identical
  `com.canonical.dbusmenu`-interface boundary — verified via GNOME
  Shell's own exception log and Xfce's indicator-plugin debug log
  respectively.
- **icon-name/icon-theme fragility is a real production hazard**,
  discovered while establishing a reconnect-testing baseline: a
  hardcoded icon name (`"emblem-default"`) that renders correctly in one
  provisioned VM can silently fail to render — zero errors, full
  successful D-Bus registration, just an invisible icon — in another,
  because current Adwaita dropped that specific icon. The eventual
  production indicator must verify its icon name against the actual
  target theme (or ship its own icon asset), not assume a
  freedesktop-icon-naming-spec name is universally present.
- **GNOME Wayland has no in-place shell/panel restart** — the "panel
  restart" reconnect scenario required substituting an
  `ubuntu-appindicators` extension disable/enable cycle, since GNOME's
  historical X11-only "Restart Shell" mechanism does not exist under
  Wayland. This is a real platform difference the eventual production
  reconnect-handling logic (and its own test suite, whenever G7+ builds
  one) must account for.
- **`ksni`'s reconnect-after-panel-restart success depends on
  GNOME-extension-side recovery logic**, not proactive re-announcement
  by `ksni` itself — the extension's own `_seekStatusNotifierItems`
  fallback bus-scan (explicitly written for indicators that "do not
  re-register... when the plugin is enabled/disabled") is what recovers
  the icon. A production indicator relying on this should not assume
  every StatusNotifierWatcher implementation provides an equivalent
  fallback.

## Open items closed during evidence closure and repair

- Xfce menu-open, Xfce reconnect, logout/login lifecycle, and
  daemon-unavailable degraded state (first closure pass) — see
  `G6_XFCE_KSNI_MENU_RESOLUTION.md`, `G6_XFCE_RECONNECT_EVIDENCE.md`,
  `G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`, and
  `G6_DAEMON_UNAVAILABLE_EVIDENCE.md`.
- Candidate 1's no-X11-dependency result, and `ksni`'s Xfce
  Guardian-daemon-analog-restart evidence, plus the Xfce
  daemon-unavailable icon screenshot (second, audit-driven repair pass)
  — see `G6_CANDIDATE1_REPAIR_EVIDENCE.md` and
  `G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md`.

No residual items remain open from either pass as of this record.

## Residual items for G7+ (design work, not evidence gaps)

```text
1. "Daemon unavailable shows degraded state" was evidenced against a
   minimal, explicitly non-production evidence-only D-Bus stub (per the
   G6 handoff's own explicit permission for this) -- wiring the same
   mechanism against the real Guardian daemon's own eventual health
   signal is G7+ protocol-design work.
2. A stale-registration hazard was found on Xfce (see
   G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md): a non-session-scoped
   indicator process can leave a stale icon visible after logout,
   because Xfce's watcher service is per-user, not per-session. G7's
   production indicator must be launched via proper desktop session
   autostart, not as a detached process.
3. Candidate 1 is a real, evidenced, working fallback if `ksni` is ever
   reconsidered -- its own complexity costs (broken upstream binding,
   GTK3 dependency, non-default launch environment), not a functional
   failure, are why it was not selected.
```

## Forward constraints for G7+

### FC-G6-1 — "simplest" is underspecified

§30 selects "the simplest candidate that passes all required targets"
but defines no formal simplicity metric. For this gate, `ksni` was
accepted over candidate 1 (both passed every required test) using
concrete, evidenced factors: a working, actively-maintained Rust
binding vs. a broken one requiring hand-written FFI; no GTK3 dependency
vs. a full GTK3 toolkit dependency; no special launch environment vs. a
required non-default `GDK_BACKEND=wayland` setting; and no extra API
call needed for correct status visuals vs. one required call. **Do not
retroactively present those four factors as a universal, normative
scoring formula** — they were the concrete, disclosed facts available
in this specific comparison, not a general-purpose rubric. If a future
gate uses similar "simplest passing candidate" language to choose
between multiple qualifying options, clarify the contract's own
simplicity criteria before relying on a similarly ad hoc, if honestly
evidenced, tie-break.

### FC-G6-2 — session-scoped production launch required

G6's evidence-gathering harness launched candidates as detached
background processes over SSH, not through real desktop session
autostart. This uncovered a real Xfce hazard
(`G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`): a candidate launched outside
proper graphical-session lifecycle management can leave a stale
registration visible after logout, because Xfce's indicator-watcher
service is per-user, not per-session, and does not get cleaned up by
`systemd-logind` the way a properly session-scoped autostart entry
would. **Production indicator work in G7+ must use a correctly
session-scoped launch mechanism** (desktop autostart entry or
equivalent, tied to the user's graphical session lifecycle) and must
not reuse G6's detached evidence-harness launch model as a production
pattern.

## Scope boundary (restated)

Per this gate's explicit instructions: **G6 selects an indicator
mechanism. It does not certify a production guardian-indicator
implementation.** No G7 production daemon work, no G8 provider work, no
G9 client/packaging work, no public D-Bus expansion, and no privileged-
helper changes were performed or authorized as part of this gate. The
evidence prototypes in `tests/vm/g6-candidate-*/` remain non-production
artifacts; G7 must build its own production indicator using `ksni` as a
library dependency, under normal G7 TDD discipline.

## Evidence index (referenced, not duplicated here)

```text
docs/guardian/30_TDD/GUARDIAN_G6_IMPLEMENTATION_HANDOFF.md
docs/guardian/30_TDD/GUARDIAN_G6_INDEPENDENT_REVIEW_HANDOFF.md
docs/adr/ADR-006-guardian-indicator-mechanism.md
docs/evidence/g6/G6_GNOME_KSNI_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_XFCE_KSNI_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_AYATANA_GTK3_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_AYATANA_GLIB_SPIKE_EVIDENCE.md
docs/evidence/g6/G6_P0_IND_003_RECONNECT_EVIDENCE.md
docs/evidence/g6/G6_XFCE_KSNI_MENU_RESOLUTION.md
docs/evidence/g6/G6_XFCE_RECONNECT_EVIDENCE.md
docs/evidence/g6/G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md
docs/evidence/g6/G6_DAEMON_UNAVAILABLE_EVIDENCE.md
docs/evidence/g6/G6_ICON_NAME_CORRECTION.md
docs/evidence/g6/G6_CANDIDATE1_REPAIR_EVIDENCE.md
docs/evidence/g6/G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md
docs/evidence/g6/G6_CANDIDATE_COMPARISON.md
tests/vm/g6-candidate-ksni/
tests/vm/g6-candidate-ayatana-gtk3/
tests/vm/g6-candidate-ayatana-glib/
tests/vm/g6-daemon-evidence-stub/
```
