# G6 Evidence Closure — P0-IND-003 reconnect on Xfce 4.20

> **Correction (added during G6 repair, blocking finding 2 of the
> independent audit): "Scenario B" below is mislabeled.** It tests
> killing and relaunching `ksni`'s own process, which is
> **indicator-process restart**, not "Guardian-daemon restart" (a
> Guardian-daemon analog restarting while the indicator process itself
> stays alive). The genuinely-correct scenario for `ksni` on Xfce is
> `G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md` (real evidence, indicator pid
> unchanged throughout the daemon-stub kill/relaunch cycle). Original
> text below preserved unchanged.

**Status: CLOSURE.** Extends `G6_P0_IND_003_RECONNECT_EVIDENCE.md`
(GNOME-only) to Xfce 4.20, per the independent audit's finding that §30
lists Xfce as a target environment for the required-test list without a
per-test carve-out. Both required sub-scenarios -- panel/watcher restart,
daemon/candidate restart -- are covered for `ksni`, the only candidate
with a passing icon-appears result on Xfce (candidates 1 and 2 remain
disqualified per their existing, unreopened findings).

## Environment

```text
VM:              disposable qemu overlay (/tmp/g6-evidence-vm-closure),
                 base image never modified
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
Desktop:         Xfce 4.20, xfce4-indicator-plugin at panel position 11
Candidate build: tests/vm/g6-candidate-ksni/ (icon names corrected,
                 daemon-presence watching added -- see
                 G6_ICON_NAME_CORRECTION.md, G6_DAEMON_UNAVAILABLE_EVIDENCE.md)
Capture method:  QEMU QMP screendump + input-send-event; direct D-Bus
                 introspection (org.kde.StatusNotifierWatcher
                 RegisteredStatusNotifierItems) for registration-state
                 confirmation; process log inspection
Run window:      2026-09-01T10:54Z -- 2026-09-01T10:56Z
Teardown:        candidate + daemon-stub processes SIGTERM'd and
                 confirmed exited; Xfce panel plugin-ids reverted to its
                 10-plugin baseline (xfce4-panel -r applied);
                 AccountsService Session field removed; GDM autologin
                 disabled; VM shut down cleanly (guest-initiated
                 `shutdown -h now`, QMP socket/process confirmed gone);
                 overlay qcow2 deleted; base cloud image untouched.
```

## Scenario A -- panel/watcher restart

On Xfce, unlike GNOME's Wayland session, `xfce4-panel -r` is a real,
literal restart of the panel process itself, and does destroy/recreate
the indicator plugin's widget. This is the actual mechanism the
contract's "panel/Shell restart" language describes for this desktop --
no substitution was needed here (contrast with GNOME, where no in-place
shell restart exists at all and an extension disable/enable cycle was
used as the closest real equivalent).

**Baseline confirmed before disruption:** exactly one registered item
(`org.kde.StatusNotifierItem-26447-1`), candidate pid 26447 untouched.

**Panel restarted:** `xfce4-panel -r`, confirmed via a new `xfce4-panel`
process pid (26893) replacing the old one.

**Result: PASS.**
`gnome50-xfce420-closure/candidate-ksni_2026-09-01T1054Z_xfce420-panel-watcher-restart-reconnect-pass.png`
shows the icon present again after the panel widget was destroyed and
rebuilt. A follow-up click
(`..._xfce420-panel-restart-menu-functional.png`) confirms the menu
still opens and shows the candidate's persisted state ("clicks so far:
1"), proving the same running process is still being served, not a
different one.

**Mechanism, verified directly (not assumed):** the candidate's own log
shows no new `tray.spawn()` event and no re-registration message across
the panel restart -- `ksni` did nothing. `ps aux` confirms
`ayatana-indicator-application-service` (pid 25988, started well before
the panel restart) was **not** restarted by `xfce4-panel -r` -- only the
panel's own plugin widget was. Recovery therefore comes from **watcher-
side persistence, not candidate-side re-registration**: the long-lived
`ayatana-indicator-application-service` retained the registration across
the panel widget's destroy/recreate cycle, and the freshly-built plugin
widget simply re-queried it for current apps. This is the direct Xfce
analog of the GNOME finding (recovery via the extension's own persistent
state, not `ksni` proactively announcing itself), independently
confirmed here via process inspection rather than assumed from
similarity to the GNOME case.

## Scenario B -- indicator-process restart (NOT Guardian-daemon restart -- see correction notice at top of this document)

**Baseline confirmed:** exactly one registered item, candidate pid 26447.

**Candidate killed:** `kill -TERM 26447`. Immediately after,
`RegisteredStatusNotifierItems` returned `(<@as []>,)` -- empty, real
deregistration, not merely a stale record. Screenshot
(`candidate-none_2026-09-01T1055Z_xfce420-daemon-killed-icon-removed-clean.png`)
confirms the icon is visually gone, not just absent from the D-Bus
property.

**Candidate relaunched:** fresh process, new pid (27255).
`RegisteredStatusNotifierItems` immediately showed exactly one item under
the new pid -- no duplicate, no stale entry alongside it.

**Result: PASS.**
`candidate-ksni_2026-09-01T1055Z_xfce420-daemon-restart-reconnect-menu-functional.png`
shows the icon back and the menu open with reset state ("clicks so far:
0"), confirming this is genuinely the new process instance being served,
not a cached panel entry -- recovery, not mere survival, exactly as the
closure brief required.

## §30 required tests now closed for ksni-on-Xfce

```text
reconnect after panel/Shell restart   PASS (this closure)
indicator-process restart             PASS (this closure -- real,
                                       useful evidence, but NOT credited
                                       toward "reconnect after daemon
                                       restart"; see correction notice
                                       at top of this document)
reconnect after daemon restart        PASS -- see
                                       G6_KSNI_XFCE_DAEMON_RESTART_REPAIR.md
                                       (added during G6 repair)
no duplicate icon                     PASS (confirmed across both scenarios)
```
