# G6 Evidence Closure — ksni-on-Xfce menu-open resolution

**Status: CLOSURE, resolves the UNRESOLVED finding in `G6_XFCE_KSNI_SPIKE_EVIDENCE.md`.**
That document reported "menu opens" as UNRESOLVED for `ksni` on Xfce 4.20
after three real synthetic-click attempts produced no visible menu and
zero `com.canonical.dbusmenu` D-Bus traffic. This closure re-tests the
same claim, on a fresh disposable VM, with a fuller package set and a
corrected icon name (see `G6_ICON_NAME_CORRECTION.md`), and reaches a
definitive result: **PASS.**

Per the independent audit's instruction not to leave this UNRESOLVED
without a genuine further attempt, and not to infer menu functionality
from SNI registration or icon visibility alone: the evidence below
follows the full required chain (icon visible → click performed → menu
visibly opens → expected items visible → item clicked → handler
invocation recorded in the candidate's own log), not a partial subset.

## Environment

```text
VM:              disposable qemu overlay, base image never modified
                 (same base cloud image reused across all G6 spikes)
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
Desktop:         Xfce 4.20, xfce4-indicator-plugin added to panel
                 position 11 (same technique as the original spike)
Candidate build: tests/vm/g6-candidate-ksni/ as of this closure pass --
                 icon names corrected (see G6_ICON_NAME_CORRECTION.md),
                 daemon-presence watching added (see
                 G6_DAEMON_UNAVAILABLE_EVIDENCE.md); menu structure
                 (3 items: click counter, degraded-status toggle, exit)
                 unchanged from the original spike
Capture method:  QEMU QMP screendump + input-send-event; xfce4-indicator-
                 plugin's own debug log
                 (~/.cache/xfce4-indicator-plugin.log) read directly
Run window:      2026-09-01T10:51Z -- 2026-09-01T10:56Z (this segment;
                 full VM run window covers the whole closure pass, see
                 G6_DAEMON_UNAVAILABLE_EVIDENCE.md for the shared
                 environment block)
Teardown:        covered under the shared VM teardown recorded in
                 G6_DAEMON_UNAVAILABLE_EVIDENCE.md and
                 G6_XFCE_RECONNECT_EVIDENCE.md (same VM session)
```

## Required evidence chain

1. **Icon visible.**
   `gnome50-xfce420-closure/candidate-ksni_2026-09-01T1052Z_xfce420-baseline-icon-visible.png`
   -- icon present next to the "ubuntu" username label, using the
   corrected `"computer"` icon name.
2. **Real click performed.** QMP `input-send-event` synthetic
   absolute-mouse move + left-button down/up at the icon's confirmed
   on-screen coordinates (computed from a zoomed crop of the baseline
   screenshot, not guessed).
3. **Menu visibly opens.**
   `candidate-ksni_2026-09-01T1052Z_xfce420-menu-open-PASS.png` -- a real
   popup menu is visible immediately below/left of the icon.
4. **Expected menu items visible.** The screenshot shows all three items
   exactly as declared in the prototype: "Click me (clicks so far: 0)",
   "Simulate degraded status" (with checkbox), "Exit" (with icon).
5. **Menu item clicked.** A second real click on "Click me", at the
   item's on-screen position within the now-open menu.
6. **Handler invocation recorded.** The candidate's own log
   (`g6-ksni-xfce.log`, captured live during the run) shows:
   ```text
   [g6-evidence] menu item activated, menu_clicks=1
   ```
   -- not inferred from the screenshot alone.
7. **Re-open confirms persisted state, not a one-off.** The icon was
   clicked a second time to re-open the menu; the screenshot
   (`candidate-ksni_2026-09-01T1053Z_xfce420-menu-reopen-state-persisted.png`)
   shows "Click me (clicks so far: 1)" -- proving the same running
   process handled both interactions, not a coincidental one-time render.
8. **Status-toggle bonus check.** "Simulate degraded status" was also
   clicked; the icon visibly changed to a warning-triangle glyph
   (`candidate-ksni_2026-09-01T1053Z_xfce420-degraded-warning-icon.png`),
   confirming "state/icon update propagates" also holds on Xfce, not
   only GNOME as previously evidenced.

## What changed since the original UNRESOLVED finding

The `xfce4-indicator-plugin` debug log for this run
(`xfce4-indicator-plugin-ksni-menu-resolution.log`) shows a clean
registration with **no error at any point** -- distinct from candidate
2's log on the same plugin, which showed a `LIBDBUSMENU-GLIB Getting
layout failed` error. This was checked specifically because that log
file (`~/.cache/xfce4-indicator-plugin.log`) had not yet been discovered
as a diagnostic source at the time of the original ksni-on-Xfce spike --
it was found later, during candidate 2's investigation. Re-checking it
for `ksni` this time shows no equivalent failure signature.

The most likely explanation, consistent with all available evidence
(without overclaiming a definitive root cause the evidence does not
establish): the original UNRESOLVED result was a synthetic-click
targeting/timing issue specific to that run, not a genuine `ksni`/
`xfce4-indicator-plugin` incompatibility -- consistent with the original
document's own candidate-1-vs-candidate-3 comparison note, which already
observed the identical click technique working immediately for candidate
1 on the same plugin. This closure directly confirms the same technique
now also works for `ksni`, on a fresh VM, across two independent click
attempts (initial open, re-open) plus one item-click, with no anomaly.

## Classification

Per the audit's required classification (PASS / FAIL -- candidate
incompatibility / FAIL -- environment/plugin limitation): **PASS.** The
full required chain was demonstrated with real, log-confirmed handler
invocation, not inferred. The original UNRESOLVED finding in
`G6_XFCE_KSNI_SPIKE_EVIDENCE.md` is preserved as-written (per the
instruction not to rewrite prior observations) -- this document
supersedes it for the purposes of the required-test matrix and G6
candidate selection, and is cross-referenced from that document.

## §30 required tests now closed for ksni-on-Xfce

```text
icon appears                    PASS (already established; reconfirmed)
menu opens                      PASS (this closure)
menu actions invoke handler     PASS (this closure, log-confirmed)
state/icon update propagates    PASS (this closure, bonus check)
```
