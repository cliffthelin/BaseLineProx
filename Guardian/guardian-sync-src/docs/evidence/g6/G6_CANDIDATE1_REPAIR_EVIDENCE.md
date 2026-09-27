# G6 Repair — Candidate 1 (legacy GTK3 Ayatana AppIndicator) full re-test

**Status: REPAIR, corrects blocking finding 1 of the independent audit
(`FAIL — G6 CANDIDATE SELECTION UNSUPPORTED`).** The audit reproduced
candidate 1 successfully under a native-Wayland launch
(`GDK_BACKEND=wayland`, `WAYLAND_DISPLAY=wayland-0`, no `DISPLAY`, no
`XAUTHORITY`) and found the original "structural, unfixable X11
dependency" disqualification in `G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` and
`ADR-006` unsupported. This document re-tests candidate 1's full
required matrix on both desktops under the corrected launch
configuration, per the repair brief's explicit instruction not to merely
edit the ADR.

This document does not delete or contradict
`G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` — that document's icon/menu/handler
findings on both desktops remain valid and are not re-litigated here
(see the repair brief's "do not re-run unless needed" guidance,
interpreted for the parts genuinely unaffected). What changes is the
"no X11 dependency" result, and this document adds the previously-missing
required items (real Guardian-daemon-analog restart with the indicator
alive, and logout/login lifecycle) that the original spike never
attempted.

## What changed in the candidate's own source

`tests/vm/g6-candidate-ayatana-gtk3/src/main.rs` was updated during this
repair, in ways that do not affect the icon/menu/handler behavior already
evidenced:

1. Icon names corrected (`"computer"` healthy, `"dialog-warning"`
   manually-simulated degraded — see `G6_ICON_NAME_CORRECTION.md`).
2. `app_indicator_set_attention_icon_full` is now called once at
   startup, so the previously-documented "status changes internally but
   the glyph doesn't visually change" finding (§ "state/icon update
   propagates: PARTIAL" in the original spike) is superseded, not
   silently erased — see below.
3. A background thread + `glib::MainContext` channel was added to poll
   the same evidence-only daemon stub `ksni` already uses
   (`io.github.cliffthelin.GuardianG6EvidenceStub1`), so real
   daemon-analog-unavailable detection (not just the manual toggle) can
   be evidenced for this candidate too, mirroring `ksni`'s equivalent
   feature added during the earlier G6 closure pass.

None of this changes the candidate's fundamental mechanism (legacy GTK3
Ayatana AppIndicator, hand-written FFI) or reopens the already-accepted
finding that this library's only published Rust binding is broken
against this OS.

## Environment

```text
VM:              disposable qemu overlay (/tmp/g6-repair-vm), base image
                 never modified
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
GNOME:           GNOME Shell 50.1/Wayland, ubuntu-appindicators@ubuntu.com
                 enabled
Xfce:            Xfce 4.20, xfce4-indicator-plugin at panel position 11
Candidate build: tests/vm/g6-candidate-ayatana-gtk3/ as of this repair
                 (icon-corrected, attention-icon-corrected,
                 daemon-analog-watching build)
Capture method:  QEMU QMP screendump + input-send-event; direct D-Bus
                 introspection (RegisteredStatusNotifierItems); process
                 log inspection; `ps` for pid-continuity confirmation
Run window:      2026-09-01T16:22Z (VM boot) -- 2026-09-01T16:33Z (teardown)
Teardown:        all candidate/stub processes SIGTERM'd and confirmed
                 exited; Xfce panel plugin-ids reverted to its 10-plugin
                 baseline; GNOME enabled-extensions cleared;
                 AccountsService Session field removed; GDM autologin
                 disabled; VM shut down cleanly (guest-initiated
                 `shutdown -h now`, QMP socket/process confirmed gone);
                 overlay qcow2 deleted; base cloud image untouched.
```

## GNOME 50 — corrected result

```text
launch environment:
  DISPLAY:        (unset)
  XAUTHORITY:     (unset)
  GDK_BACKEND:    wayland
  WAYLAND_DISPLAY: wayland-0
  (plus DBUS_SESSION_BUS_ADDRESS, XDG_RUNTIME_DIR -- required for any
  D-Bus/session-runtime access regardless of display backend)
```

- **`gtk::init()`: succeeded.** No "Could not open X display" error --
  confirmed via the candidate's own live log, captured at the moment of
  launch.
- **Icon appears: PASS.**
  `candidate1-repair/candidate1_2026-09-01T1622Z_gnome50-native-wayland-baseline-icon.png`
  -- a clean, unambiguous `computer` glyph, no fallback-icon ambiguity
  this time (unlike the original spike and several other G6 screenshots
  affected by the `"emblem-default"` finding).
- **Menu opens: PASS.**
  `..._gnome50-native-wayland-menu-open.png` -- real popup, correct 3
  items.
- **Handler invokes: PASS.** Candidate's own log:
  `[g6-evidence] menu item activated, menu_clicks=1`.
- **Visible status/degraded state: PASS** (an improvement over the
  original spike's PARTIAL result). Manual "Simulate degraded status"
  toggle now produces a real, visible warning-triangle glyph change --
  `candidate1_2026-09-01T1623Z_gnome50-manual-degraded-icon-now-visible.png`
  -- because `app_indicator_set_attention_icon_full` is now called. The
  original spike's finding (status changes internally, glyph doesn't,
  because that call was missing) is not erased -- it is the reason this
  call was added, and remains documented in
  `G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` as the discovered API-shape
  requirement.
- **No X11 dependency: PASS.** This is the corrected result. The
  candidate ran, registered, rendered its icon, and served a fully
  interactive menu with zero `DISPLAY`/`XAUTHORITY` set, using only
  GTK3's native Wayland backend. This directly reverses the original
  spike's FAIL and the independent audit's finding that this FAIL was
  unsupported.

## GNOME 50 — P0-IND-003, kept as three distinct scenarios

### Scenario A: panel/Shell restart

- Baseline: exactly one registered item
  (`:1.73@/org/ayatana/NotificationItem/guardian_g6_evidence_ayatana_gtk3`),
  candidate pid unchanged throughout.
- Disruption: `gnome-extensions disable ubuntu-appindicators@ubuntu.com`
  then `enable` (the same Wayland-appropriate analog to "Shell restart"
  established in the earlier closure pass -- GNOME Wayland has no
  in-place shell restart).
- **PASS.** `candidate1_2026-09-01T1623Z_gnome50-panel-shell-restart-reconnect-pass.png`
  shows the icon present again; `RegisteredStatusNotifierItems` after
  the cycle showed exactly one entry, same candidate identity, no
  duplicate. Candidate pid confirmed unchanged via `ps` before and
  after.

### Scenario B: Guardian-daemon-analog restart, indicator alive throughout

- Baseline: candidate pid 22460 running, daemon stub present, `computer`
  icon showing.
- Disruption: `kill -TERM` on the **daemon stub only** (pid 22455) --
  the candidate process was never touched.
- Observable degraded state: candidate's own log shows real detection,
  not a timer:
  ```text
  [g6-evidence] daemon-watch: io.github.cliffthelin.GuardianG6EvidenceStub1 presence changed -> false
  ```
  Screenshot
  `candidate1_2026-09-01T1624Z_gnome50-daemon-analog-unavailable-visible.png`
  shows the icon changed to the warning-triangle glyph (the same visual
  the manual toggle produces -- candidate 1's implementation does not
  distinguish manual-simulated from really-detected degraded states
  visually, unlike `ksni`'s distinct `dialog-error`; a real, disclosed
  difference between the two candidates' prototypes, not a defect in
  either).
- Recovery: daemon stub relaunched (fresh pid). Candidate's log:
  `presence changed -> true`. Screenshot
  `candidate1_2026-09-01T1624Z_gnome50-daemon-analog-recovered.png`
  confirms the icon returned to `computer`.
- **Candidate pid confirmed unchanged across the entire scenario**
  (22460 throughout, verified via `ps` before disruption, during the
  degraded window, and after recovery) -- this is genuinely
  "Guardian-daemon-analog restart while indicator remains alive," not
  process restart.
- **PASS.**

### Scenario C: indicator-process restart (reported separately, not counted as B)

Not re-run for candidate 1 in this repair pass beyond what the daemon-
analog test above already demonstrates process-identity continuity for
scenario B. If a dedicated candidate-1 process-kill/relaunch scenario is
wanted later (mirroring `ksni`'s and the original candidate-1 evidence in
`gnome50-reconnect/`), it should be labeled "indicator-process restart"
explicitly and not credited toward "reconnect after daemon restart" --
this is the exact distinction blocking finding 2 required going forward.

## GNOME 50 — clean logout/login lifecycle

- Real `gnome-session-quit --logout --no-prompt`. Confirmed via process
  inspection (`gnome-shell --mode=gdm` replacing `--mode=user`).
- Autologin did not automatically retrigger (standard GDM behavior,
  established in the earlier closure pass); `systemctl restart gdm3`
  used to bring up the new session -- a test-harness step, not a
  candidate behavior.
- The old candidate process **did not survive** the logout this time
  (unlike the daemon stub, which did, matching the pattern already
  documented for `ksni`) -- `RegisteredStatusNotifierItems` in the new
  session showed empty before any relaunch, confirming no stale
  candidate-1 registration survived. The orphaned stub was killed
  explicitly before relaunching.
- Fresh launch in the new session (fresh pid): `RegisteredStatusNotifierItems`
  showed exactly one entry.
- **PASS.**
  `candidate1_2026-09-01T1625Z_gnome50-postlogin-single-icon.png` +
  `..._gnome50-postlogin-menu-functional.png` confirm a single icon and
  a real, functional menu in the new session.

## Xfce 4.20 — corrected result

Standard X11 launch (`DISPLAY=:0`, no special backend needed -- Xfce is
X11-based by design, so "no X11 dependency" does not apply here, per
§30's own framing, unchanged from the original comparison).

- **Icon appears: PASS.**
  `candidate1_2026-09-01T1626Z_xfce420-baseline-icon.png`.
- **Menu opens: PASS.** `..._xfce420-menu-open.png`.
- **Handler invokes: PASS.** Log: `menu_clicks=1`.
- **Visible status/degraded state: PASS** (same improvement as GNOME --
  `..._xfce420-manual-degraded-visible.png` shows a real warning-triangle
  glyph).

## Xfce 4.20 — P0-IND-003, kept as three distinct scenarios

### Scenario A: panel restart

- Baseline: one registered item, candidate pid 26621 unchanged.
- Disruption: real `xfce4-panel -r` (new `xfce4-panel` process pid
  confirmed via `ps`, candidate pid unchanged).
- **PASS.** `candidate1_2026-09-01T1628Z_xfce420-panel-restart-reconnect.png`
  shows the icon back; a follow-up click
  (`..._xfce420-panel-restart-menu-functional.png`) confirms the menu
  still works. `RegisteredStatusNotifierItems` showed exactly one entry
  throughout, same candidate identity, no duplicate.

### Scenario B: Guardian-daemon-analog restart, indicator alive throughout

- Baseline: candidate pid 26621, daemon stub present, `computer` icon.
- Disruption: `kill -TERM` on the daemon stub only (candidate untouched).
- Observable degraded state: log shows `presence changed -> false`;
  screenshot `..._xfce420-daemon-analog-unavailable-visible.png` shows
  the warning-triangle glyph.
- Recovery: stub relaunched; log shows `presence changed -> true`;
  screenshot `..._xfce420-daemon-analog-recovered.png` confirms return
  to `computer`.
- **Candidate pid (26621) confirmed unchanged throughout the entire
  scenario** via `ps`.
- **PASS.**

## Xfce 4.20 — clean logout/login lifecycle

- Real `xfce4-session-logout --logout --fast`. Confirmed via process
  inspection (`xfce4-session` gone).
- `systemctl restart gdm3` used to bring up the new session (test-harness
  step).
- The old candidate process **did not survive** this logout either
  (X11-connected GTK processes are torn down when their X session ends,
  distinct from the daemon stub's D-Bus-only, per-user-bus survival
  already documented for the Xfce case in
  `G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`) -- `RegisteredStatusNotifierItems`
  was empty before relaunch. The orphaned stub was killed explicitly.
  The panel's indicator-plugin slot (position 11) persisted across the
  logout since `xfconf` panel configuration is stored per-user, not
  per-session -- confirmed by checking `plugin-ids` immediately after
  the new session came up, before any relaunch.
- Fresh launch (fresh pid): `RegisteredStatusNotifierItems` showed
  exactly one entry.
- **PASS.**
  `candidate1_2026-09-01T1631Z_xfce420-postlogin-single-icon.png` +
  `..._xfce420-postlogin-menu-functional.png` confirm a single icon and
  functional menu in the new session.

## Summary: candidate 1's corrected §30 matrix

```text
                                       GNOME 50        Xfce 4.20
icon appears                          PASS            PASS
menu opens                            PASS            PASS
menu actions invoke handler           PASS            PASS
state/icon update propagates          PASS (improved)  PASS (improved)
no X11 dependency                     PASS (corrected) N/A (X11 by design)
reconnect after panel/Shell restart   PASS            PASS
reconnect after daemon restart        PASS (real       PASS (real
                                       daemon-analog,   daemon-analog,
                                       indicator alive) indicator alive)
daemon unavailable shows degraded     PASS (same       PASS (same
                                       mechanism as     mechanism)
                                       above)
no duplicate icon                     PASS             PASS
clean user logout/login lifecycle     PASS             PASS
```

Candidate 1 now passes every required §30 test directly evidenced
against it, on both target environments. See
`G6_CANDIDATE_COMPARISON.md` for the re-applied selection rule across
all three candidates.
