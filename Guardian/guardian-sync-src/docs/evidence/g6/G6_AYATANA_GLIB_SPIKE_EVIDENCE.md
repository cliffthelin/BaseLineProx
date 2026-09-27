# G6 Evidence Spike — Candidate 2 (GLib-only Ayatana AppIndicator 2.x) on GNOME 50 and Xfce 4.20

**Status: CHECKPOINT, part of the ongoing G6 candidate comparison.** Covers
candidate 2 ("GLib-only Ayatana AppIndicator 2.x",
`libayatana-appindicator-glib`) on both required desktop targets in a
single VM pass. Companion documents: `G6_GNOME_KSNI_SPIKE_EVIDENCE.md`,
`G6_XFCE_KSNI_SPIKE_EVIDENCE.md` (candidate 3), `G6_AYATANA_GTK3_SPIKE_EVIDENCE.md`
(candidate 1). Both P0-IND-003 reconnect scenarios and final candidate
selection/ADR-006 remain outstanding.

## Headline result

**Candidate 2 fails icon-appears on both GNOME 50 and Xfce 4.20**, with the
identical root cause captured directly on both desktops: the desktop-side
consumer (GNOME's `ubuntu-appindicators@ubuntu.com` extension; Xfce's
`xfce4-indicator-plugin`) expects the indicator's menu to be exposed over
the legacy `com.canonical.dbusmenu` D-Bus interface (libdbusmenu), and
`libayatana-appindicator-glib`'s `app_indicator_set_menu(GMenu*)` /
`app_indicator_set_actions(GSimpleActionGroup*)` instead export the menu
over the modern GIO `org.gtk.Menus` / `org.gtk.Actions` interfaces. Neither
consumer understands that protocol. This is despite the C library itself
printing a runtime deprecation notice on every run of candidate 1
recommending exactly this library as the replacement (see
`G6_AYATANA_GTK3_SPIKE_EVIDENCE.md`) — a real, disclosed irony: the
"recommended, modern" library is the one candidate that neither required
desktop's indicator consumer can actually render.

The candidate's own implementation is not at fault: SNI registration,
property export, and action wiring were all independently verified correct
(see below) via direct D-Bus interaction bypassing the broken desktop
consumers entirely.

## Environment

```text
VM:              disposable qemu overlay, base image never modified
                 (same base cloud image reused across all G6 spikes)
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
GNOME:           GNOME Shell 50.1, ubuntu-appindicators@ubuntu.com enabled
                 via dconf, gdm3 restarted to load it (Wayland requires a
                 full session restart, established in prior spikes)
Xfce:            Xfce 4.20.4-1, run in the SAME VM instance as the GNOME
                 test via GDM launching a non-GNOME session for the
                 autologin user through AccountsService's `Session=`
                 field (same technique used for candidate 1)
Build:           glib 0.18, gio 0.18, gio-sys 0.18 (safe Rust bindings) +
                 hand-written extern "C" FFI for the 4 AppIndicator entry
                 points -- no Rust binding exists for this library at all
Capture method:  QEMU QMP screendump + input-send-event; D-Bus
                 introspection/Get/Activate calls via SSH for functional
                 verification independent of the desktop-side renderers
Run window:      2026-09-01T07:26Z (VM boot) -- 2026-09-01T07:42Z (teardown)
Teardown:        candidate process SIGTERM'd and confirmed exited on both
                 desktops; Xfce panel plugin-ids reverted to its 10-plugin
                 baseline; AccountsService Session file removed; GDM
                 autologin disabled; VM shut down cleanly (guest-initiated
                 `shutdown -h now`, QMP socket/process confirmed gone);
                 overlay qcow2 deleted; base cloud image untouched.
```

## Candidate

`tests/vm/g6-candidate-ayatana-glib/` — G6 EVIDENCE-ONLY / NOT PRODUCTION
(see its own module doc comment and `build.rs`). Not part of the Cargo
workspace. No `guardian-core` reference. Links directly against
`libayatana-appindicator-glib` via `pkg-config`; no bindgen involved since
no `-sys` crate for this library exists to attempt one. Same 3-item menu
(click counter / degraded-status toggle / exit) as the other two
candidates, built on `gio::Menu` + `gio::SimpleActionGroup` rather than
`GtkMenu`.

Compiled cleanly on the VM on the first try (23.95s, no errors) — notably
easier than candidate 1's build, which required abandoning a broken `-sys`
crate first.

## GNOME 50 results

**Real captured stdout/stderr from the candidate process:**

```text
[g6-evidence] G6 EVIDENCE-ONLY ayatana-glib prototype starting, pid=18113
[g6-evidence] app_indicator_new succeeded
[g6-evidence] app_indicator_set_actions + set_menu + set_status(ACTIVE) done, entering main loop
```

No X-display errors occurred — confirming this candidate's export path is
genuinely D-Bus/GMenuModel-based, not X11-based: the process was launched
over SSH with only `DBUS_SESSION_BUS_ADDRESS` set, no `DISPLAY` or
`XAUTHORITY`, unlike candidates 1 and 3, which both require a real
XWayland auth cookie to construct their GTK-backed widgets.

- **Icon appears: FAIL.**
  `gnome50-ayatana-glib/candidate-ayatana-glib_2026-09-01T0736Z_gnome50-topbar-no-icon-fail.png`
  shows the full GNOME top bar (system menu, volume, power) with no new
  icon anywhere, confirmed both by a full-bar screenshot and a zoomed crop
  of the exact region other candidates' icons rendered in.
- **Real root cause, directly captured (not inferred):** `journalctl --user`
  shows GNOME Shell itself threw an exception while trying to build the
  indicator:
  ```text
  Gio.DBusError: GDBus.Error:org.freedesktop.DBus.Error.UnknownMethod: No such interface "com.canonical.dbusmenu" on object at path /org/ayatana/appindicator/guardian_g6_evidence_ayatana_glib
  ```
- **SNI registration independently verified correct**, ruling out a
  candidate-side bug: `org.kde.StatusNotifierWatcher`'s
  `RegisteredStatusNotifierItems` property genuinely listed the candidate
  (`:1.74/org/ayatana/appindicator/guardian_g6_evidence_ayatana_glib`), and
  `gdbus introspect` on that object showed a fully well-formed
  `org.kde.StatusNotifierItem` interface (`Status=Active`,
  `IconName=emblem-default`, correct `Menu` object path) plus the expected
  `org.gtk.Menus`/`org.gtk.Actions` interfaces — but genuinely no
  `com.canonical.dbusmenu` interface at that path, confirming the GNOME
  Shell error is accurate, not a transient glitch.
- **Menu content export independently verified correct via direct D-Bus
  calls** (bypassing the broken GNOME-side consumer entirely):
  ```text
  $ gdbus call ... --method org.gtk.Actions.List
  (['exit', 'click_me', 'degraded'],)
  $ gdbus call ... --method org.gtk.Menus.Start '[0]'
  ([(uint32 0, uint32 0, [{'action': <'app.click_me'>, 'label': <'Click me (see stderr for count)'>},
                           {'action': <'app.degraded'>, 'label': <'Simulate degraded status'>},
                           {'action': <'app.exit'>, 'label': <'Exit'>}])],)
  ```
  This also empirically confirms the `"app.<name>"` detailed-action-name
  prefix convention used in the prototype's `menu.append(..., Some("app.click_me"))`
  calls was correct on the first attempt — no adjustment needed.
- **Action wiring/handler correctness independently verified via direct
  D-Bus `Activate` calls** (again bypassing the broken GUI path):
  ```text
  $ gdbus call ... --method org.gtk.Actions.Activate 'click_me' '[]' '{}'
  $ gdbus call ... --method org.gtk.Actions.Activate 'degraded' '[]' '{}'
  ```
  produced, in the candidate's log:
  ```text
  [g6-evidence] menu item activated, menu_clicks=1
  [g6-evidence] status toggled to Degraded
  ```
  and a follow-up `Properties.Get ... Status` call returned
  `NeedsAttention`, confirming the status change genuinely propagated to
  the SNI `Status` property.

**Conclusion for GNOME:** icon-appears is a hard FAIL for a real,
externally-caused reason (desktop consumer / library protocol mismatch).
Menu-opens, menu-action-invokes-handler, and status-propagation cannot be
tested through the actual GUI (there is no icon to click), but were all
independently confirmed functionally correct via direct D-Bus interaction
with the candidate's own real, running export — the underlying candidate
logic is sound; only the GUI rendering path is blocked.

## Xfce 4.20 results

**Real captured stdout/stderr from the candidate process:**

```text
[g6-evidence] G6 EVIDENCE-ONLY ayatana-glib prototype starting, pid=20395
[g6-evidence] app_indicator_new succeeded
[g6-evidence] app_indicator_set_actions + set_menu + set_status(ACTIVE) done, entering main loop
```

- **Icon appears: FAIL.**
  `xfce420-ayatana-glib/candidate-ayatana-glib_2026-09-01T0741Z_xfce420-desktop-with-indicator-plugin-no-icon-fail.png`
  (full desktop) and the accompanying topbar zoom crop show the Xfce panel
  with `xfce4-indicator-plugin` installed and active, but no candidate
  icon anywhere in it.
- **Real root cause, directly captured from the plugin's own debug log**
  (`xfce420-ayatana-glib/xfce4-indicator-plugin.log`, read from
  `/home/ubuntu/.cache/xfce4-indicator-plugin.log` via its open fd) — the
  exact same interface mismatch as GNOME, independently reproduced by a
  completely different consumer implementation:
  ```text
  DEBUG   Ayatana-Indicator-Application Connected to Application Indicator Service.
  DEBUG   Ayatana-Indicator-Application Building new application entry: :1.60  with icon: emblem-default at position 0
  DEBUG   libindicator-plugin       Entry added for io=libayatana-application.so
  WARNING LIBDBUSMENU-GLIB          Getting layout failed: GDBus.Error:org.freedesktop.DBus.Error.UnknownMethod: No such interface "com.canonical.dbusmenu" on object at path /org/ayatana/appindicator/guardian_g6_evidence_ayatana_glib
  ```
  This is a materially stronger piece of evidence than the GNOME finding
  alone: it shows the plugin genuinely discovered and began building a
  panel entry for the candidate (via `ayatana-indicator-application-service`,
  which itself watches `org.kde.StatusNotifierWatcher` — the same
  watcher GNOME's extension and candidate 3 both used), then aborted
  specifically at the `com.canonical.dbusmenu` layout-fetch step. Two
  independent consumer implementations, on two different desktops, fail at
  the exact same protocol boundary — strong evidence this is a genuine
  ecosystem gap around this specific library's menu export format, not an
  environment fluke.
- **Action wiring re-confirmed independently correct on Xfce too** via the
  same direct D-Bus `Activate` technique used on GNOME:
  ```text
  $ gdbus call --dest :1.60 ... --method org.gtk.Actions.Activate 'click_me' '[]' '{}'
  ```
  produced `[g6-evidence] menu item activated, menu_clicks=1` in the
  candidate's Xfce-session log, matching the GNOME result.

**Conclusion for Xfce:** icon-appears is a hard FAIL, with a directly
captured, unambiguous root cause matching GNOME's failure exactly. As on
GNOME, the candidate's own action/menu export is independently verified
correct; only the desktop-side rendering path is blocked.

## What this run does and does not establish

Established:

- Candidate 2 fails icon-appears on **both** required desktops, with the
  identical, directly-captured root cause on each: the desktop consumer
  wants `com.canonical.dbusmenu`, the library exports `org.gtk.Menus`/`org.gtk.Actions`.
- This is not a flaw in the candidate's Rust implementation or FFI
  surface — every other required behavior (SNI registration, menu
  content, action list, click-invokes-handler, status propagation) was
  independently verified correct via direct D-Bus interaction, bypassing
  the broken GUI consumers entirely.
- A real irony worth carrying into the final comparison: this is the
  library the deprecated candidate-1 library's own runtime warning
  recommends switching to, yet it is the only one of the three candidates
  that fails to render on either required desktop out of the box.
- No published Rust binding exists for this library at all (same finding
  category as candidate 1, which at least has a *broken* one) — this
  candidate's FFI surface, though small, is entirely hand-written and
  unverified by any upstream crate.
- The `"app.<name>"` detailed-action-name convention used in the
  prototype's menu construction was correct on the first attempt, per the
  direct `org.gtk.Menus.Start` D-Bus response.

Not yet established:

- Whether GNOME's or Xfce's indicator consumers could be made to
  understand `org.gtk.Menus`/`org.gtk.Actions` menus via some
  configuration or newer package version not present in this Ubuntu
  26.04 snapshot -- not investigated; would be out of scope for a G6
  spike regardless, since Guardian cannot control users' desktop-extension
  versions.
- Both P0-IND-003 reconnect scenarios, for any candidate.
- Final candidate selection / ADR-006.

## Reproducibility

No dedicated VM setup script was written for this specific run (reused the
established GNOME/Xfce provisioning steps from prior spikes' setup
scripts, run manually against a single shared VM instance for efficiency).
The prototype is `tests/vm/g6-candidate-ayatana-glib/`.
