# G6 Evidence Spike — P0-IND-003 (reconnect scenarios) on GNOME 50

> **Correction (added during G6 repair, blocking finding 2 of the
> independent audit): "Scenario 2" below is mislabeled.** It tests
> killing and relaunching the **candidate's own process**, not the
> Guardian-daemon analog. This is real, valuable evidence (kept as-is,
> not deleted) but it is **indicator-process restart**, a distinct thing
> from "reconnect after daemon restart" as the contract and the G6
> handoff's own stub-justification language use that phrase (a
> Guardian-daemon-analog restarting while the indicator process itself
> stays alive). The genuinely-correct "daemon restart, indicator alive"
> scenario for `ksni` on GNOME is `G6_DAEMON_UNAVAILABLE_EVIDENCE.md`
> (real evidence, indicator pid unchanged throughout); the Xfce
> equivalent is `G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md`. For candidate 1,
> see `G6_CANDIDATE1_REPAIR_EVIDENCE.md`'s "Scenario B" on both desktops.
> The original text below is preserved unchanged, not rewritten, per the
> repair brief's history-preservation instruction.

**Status: CHECKPOINT, part of the ongoing G6 candidate comparison.** Covers
both required P0-IND-003 reconnect sub-scenarios — panel/Shell (watcher)
restart, and candidate/daemon restart — for the two candidates that pass
icon-appears (candidate 3 "ksni" and candidate 1 "legacy GTK3 Ayatana
AppIndicator"). Candidate 2 ("GLib-only Ayatana AppIndicator") is excluded
here: it already fails icon-appears on both required desktops for a
directly-diagnosed reason (see `G6_AYATANA_GLIB_SPIKE_EVIDENCE.md`), so a
reconnect test on top of a candidate that never renders would add no new
information.

**Scope decision, stated explicitly:** this pass tests GNOME 50 only, not
Xfce. Reconnect behavior for a StatusNotifierItem-based candidate is
governed almost entirely by the *candidate's own* D-Bus registration
lifecycle (does it clean up on the old connection dying, does it get
rediscovered by whatever's watching `org.kde.StatusNotifierWatcher`) — a
property of the candidate and the generic SNI protocol, not of the
specific desktop consuming it. Testing once per candidate, on the desktop
where the icon-appears baseline is cleanest, follows the same "prove the
mechanism once, don't multiply desktop x scenario combinations without
new information" principle already used to scope earlier passes in this
gate. If the final comparison surfaces a reason to doubt this
desktop-independence assumption, Xfce reconnect testing should be added
before selection.

## A real finding surfaced while establishing the baseline (read first)

Getting a clean baseline for this pass required resolving a genuine,
initially confusing false negative, worth recording in full since it
could otherwise cause a real candidate to be mis-scored as failing
icon-appears in a future run:

1. On a freshly-provisioned VM (same base image, same provisioning
   pattern as every other G6 spike, but a narrower explicit package list
   than earlier sessions used), `ksni` registered correctly
   (`org.kde.StatusNotifierWatcher`'s `RegisteredStatusNotifierItems`
   listed it, `StatusNotifierItemRegistered` fired correctly per a
   `dbus-monitor` capture, `ubuntu-appindicators@ubuntu.com` showed
   `State: ACTIVE`) — yet **no icon rendered**, with **zero errors logged
   anywhere** (`journalctl --user`, the extension's own debug output).
   This is a different failure signature than candidate 2's: no
   exception, just silence.
2. Root-caused by reading the extension's own source
   (`indicatorStatusIcon.js`, `statusNotifierWatcher.js`) and directly
   checking the icon theme on disk:
   `find /usr/share/icons/Adwaita /usr/share/icons/hicolor -iname '*emblem-default*'`
   returned **nothing**. The icon name `"emblem-default"`, hardcoded in
   all three G6 candidate prototypes, does not exist as an icon anywhere
   in this VM's installed Adwaita build (GNOME 50-era Adwaita dropped
   several regular-color `emblem-*` icons in favor of symbolic-only
   variants). The entire D-Bus/registration/panel-widget-creation chain
   executes without error; the icon widget itself is simply built from a
   name that resolves to nothing, so it paints as an invisible/zero-content
   actor. Switching the icon name to `"computer"` (confirmed present via
   the same `find`) made the icon render immediately, on the same running
   session, with no other change.
3. **This does not overturn any previously recorded finding in this
   gate.** Candidate 2's GNOME/Xfce FAIL is independently and directly
   evidenced by a thrown exception
   (`No such interface "com.canonical.dbusmenu"`) and a plugin debug log
   showing the identical failure on Xfce — a real protocol mismatch,
   unrelated to icon-name resolution, and reproduced on two independent
   consumer implementations. It is reported here because it is a real,
   reproducible environment hazard (icon-theme drift between separately
   provisioned VMs, or between GNOME versions) that a production Guardian
   indicator implementation must not be vulnerable to: **the eventual G7+
   implementation must use an icon name verified present in the target
   icon theme (or ship its own icon), not assume a specific
   freedesktop-icon-naming-spec name is universally available.** This is
   being flagged as exactly the kind of "candidate-evaluation gate should
   surface this now" finding G6 exists for, even though it's a
   packaging/theme concern rather than a candidate-protocol concern.
4. A second, unrelated false-start during the same session: idle-timeout
   locked the session mid-investigation, producing several screenshots of
   the **lock curtain** (a near-blank blue screen) that were briefly
   mistaken for a persistently blank desktop. Resolved via
   `org.gnome.ScreenSaver.SetActive false` (same technique used
   successfully in the candidate-2 spike) and confirmed via
   `loginctl show-session ... -p LockedHint` before continuing;
   `idle-delay`/`lock-enabled` were then disabled for the remainder of
   the session to prevent recurrence. Recorded for completeness, not as a
   candidate finding.

All reconnect testing below happened after both issues were resolved and
a clean, icon-visible baseline was independently reconfirmed for each
candidate immediately before testing.

## Environment

```text
VM:              disposable qemu overlay, base image never modified
                 (same base cloud image reused across all G6 spikes)
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
GNOME:           GNOME Shell 50.1, ubuntu-appindicators@ubuntu.com enabled
                 via dconf, gdm3 restarted to load it
Candidates:      tests/vm/g6-candidate-ksni/, tests/vm/g6-candidate-ayatana-gtk3/
                 -- unmodified except for the icon-name substitution
                 described above, applied only to the on-VM working copy
                 used for this test, NOT committed to either prototype's
                 source in this repo (see note at the end of this
                 document on why).
Capture method:  QEMU QMP screendump + input-send-event; D-Bus
                 introspection for registration-state confirmation
Run window:      2026-09-01T07:44Z (VM boot) -- 2026-09-01T08:04Z (teardown)
Teardown:        both candidate processes SIGTERM'd and confirmed exited;
                 VM shut down cleanly (guest-initiated `shutdown -h now`,
                 QMP socket/process confirmed gone); overlay qcow2
                 deleted; base cloud image untouched.
```

## Candidate 3 (ksni) results

**Scenario 1 — panel/Shell (watcher) restart.** GNOME Wayland sessions
cannot restart `gnome-shell` in place the way X11 sessions historically
could (that "Restart Shell" path is X11-only and was deliberately removed
under Wayland — restarting the compositor mid-session isn't supported).
The correct GNOME-Wayland analog, used here, is disabling then
re-enabling the `ubuntu-appindicators@ubuntu.com` extension itself: its
own `enable()`/`disable()` methods construct and destroy the
`StatusNotifierWatcher` D-Bus object directly (confirmed by reading
`extension.js`), which is the same object Xfce's `xfce4-indicator-plugin`
loses and regains when its panel process restarts. This is therefore a
faithful reconnect test of "the thing that hosts the tray icon goes away
and comes back", even though the mechanism differs from Xfce's.

- Candidate process was **not** touched (same pid throughout).
- `gnome-extensions disable/enable ubuntu-appindicators@ubuntu.com` →
  `State: ACTIVE` confirmed after re-enable.
- **PASS.**
  `gnome50-reconnect/candidate-ksni_2026-09-01T0801Z_p0-ind-003-panel-watcher-restart-reconnect-pass.png`
  shows the icon present again with no manual intervention on the
  candidate side.
- `RegisteredStatusNotifierItems` after the cycle still showed exactly
  one entry, same pid as before -- **no duplicate icon.**
- Mechanism note, real and worth carrying into the final comparison:
  ksni's own D-Bus connection to the *bus* never dropped (only the
  *watcher object on the shell side* was destroyed and recreated), so
  ksni itself did nothing to reconnect. Recovery here depended on the
  extension's own `_seekStatusNotifierItems` fallback bus-scan --
  explicitly written, per its own source comment, for "indicators that
  do not re-register... when the plugin is enabled/disabled" (its
  comment specifically calls out Dropbox as a known example of this
  category). ksni apparently falls into the same category: it does not
  proactively re-announce itself on `NameOwnerChanged` for the watcher
  name. This is not a failure -- the scenario still passes, end to end
  -- but it is a real dependency on GNOME-extension-side recovery logic
  that a different desktop environment might not implement.

**Scenario 2 — indicator-process restart (NOT Guardian-daemon restart — see correction notice at top of this document).**

- `kill -TERM` on the candidate pid: `RegisteredStatusNotifierItems`
  immediately returned `[]` -- **clean deregistration, no stale entry.**
  `gnome50-reconnect/candidate-ksni_2026-09-01T0801Z_p0-ind-003-daemon-killed-icon-removed-clean.png`
  confirms the icon vanished from the panel at the same moment.
- Candidate relaunched (fresh process, new pid) with no other
  environment change.
- **PASS.**
  `gnome50-reconnect/candidate-ksni_2026-09-01T0802Z_p0-ind-003-daemon-restart-reconnect-pass.png`
  shows the icon reappeared; a follow-up click
  (`..._daemon-restart-menu-still-functional.png`) confirmed the menu
  still opens correctly with the same three items, i.e. the new process
  instance is genuinely serving the request end to end, not a stale
  cached panel entry.
- No duplicate icon at any point during this scenario.

## Candidate 1 (legacy GTK3 Ayatana AppIndicator) results

Same two scenarios, same VM, same technique.

**Scenario 1 — panel/Shell (watcher) restart.**
- **PASS**, identical shape to ksni's result:
  `gnome50-reconnect/candidate-ayatana-gtk3_2026-09-01T0803Z_p0-ind-003-panel-watcher-restart-reconnect-pass.png`
  shows the icon present again after the extension disable/enable cycle,
  candidate process untouched, no duplicate.

**Scenario 2 — indicator-process restart (NOT Guardian-daemon restart — see correction notice at top of this document).**
- `kill -TERM` produced the same clean `RegisteredStatusNotifierItems: []`
  deregistration as ksni.
- Relaunched candidate (fresh pid): **PASS.**
  `gnome50-reconnect/candidate-ayatana-gtk3_2026-09-01T0803Z_p0-ind-003-daemon-restart-reconnect-pass.png`
  shows the icon back; a follow-up click
  (`..._daemon-restart-menu-still-functional.png`) confirmed the menu
  reopens with the same three items via the new process instance.
- No duplicate icon at any point.

## What this run does and does not establish

Established:

- Panel/watcher restart **PASS on GNOME 50 for both candidates that pass
  icon-appears** (ksni, legacy GTK3 Ayatana AppIndicator). What this
  document labels "Scenario 2" is real, valuable indicator-process-
  restart evidence (also PASS, no duplicate icon, no stale registration,
  no broken menu) but is **not** "reconnect after daemon restart" as the
  contract means it -- see the correction notice at the top of this
  document and `G6_DAEMON_UNAVAILABLE_EVIDENCE.md` /
  `G6_CANDIDATE1_REPAIR_EVIDENCE.md` for the genuinely-correct
  Guardian-daemon-analog-restart-while-alive evidence (added during G6
  repair).
- The GNOME "panel restart" analog genuinely differs from Xfce's (no
  in-place Wayland shell restart exists) and required the
  extension-disable/enable substitution documented above -- worth
  carrying into the final ADR as a platform-specific reconnect-testing
  caveat.
- A real, reproducible icon-theme-drift hazard: a hardcoded icon name
  that renders fine in one provisioned VM can silently fail to render
  (with zero errors) in another, due to icon-theme content differing
  between otherwise-equivalent Ubuntu 26.04 installations. This is
  relevant to G7+ implementation, not just this spike.
- Both candidates deregister cleanly on process death (no orphaned D-Bus
  names, no stale panel entries) -- a real point in favor of the SNI
  protocol's own design, independent of which candidate library is used.

Not yet established:

- Xfce reconnect behavior for either candidate (deliberately out of scope
  for this pass; see the scope-decision note above).
- Final candidate comparison / selection / ADR-006 -- this was the last
  outstanding required-test category before that comparison can be
  written.

## Reproducibility

No dedicated VM setup script was written for this specific run (reused
the established GNOME provisioning steps from prior spikes, with a
narrower explicit apt package list -- itself the proximate cause of the
icon-theme finding above, and worth using the *fuller* package list from
`g6-gnome-vm-setup.sh` in any future re-run to avoid re-diagnosing the
same false negative). The candidates are
`tests/vm/g6-candidate-ksni/` and `tests/vm/g6-candidate-ayatana-gtk3/`,
both committed with their original `"emblem-default"` icon name intact --
the `"computer"` substitution used to unblock this specific VM's baseline
was made only in the on-VM working copy and was never committed, since
changing a G6 evidence-only prototype's icon name has no bearing on the
protocol-level questions this gate is evaluating, and preserving the
original committed source keeps every prior spike's evidence
directly reproducible against the code as committed.
