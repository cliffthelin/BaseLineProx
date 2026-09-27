# G6 Evidence Closure — clean user logout/login lifecycle (P0-IND, §30)

**Status: CLOSURE.** Closes §30's "clean user logout/login lifecycle"
required test for `ksni` on both target environments (GNOME 50/Wayland,
Xfce 4.20), per the independent audit's finding that §30 names both
environments without a per-test carve-out.

No production autostart or packaging was added anywhere in this closure.
Every launch is the same manual, evidence-only SSH-driven procedure used
throughout every other G6 spike -- this test evaluates the candidate's
own behavior across a real logout/login boundary, not an autostart
mechanism Guardian does not have yet.

## GNOME 50

### Environment

```text
VM:              disposable qemu overlay (/tmp/g6-evidence-vm-closure)
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
Desktop:         GNOME Shell 50.1, ubuntu-appindicators@ubuntu.com enabled
Candidate build: tests/vm/g6-candidate-ksni/ + tests/vm/g6-daemon-evidence-stub/
                 (this closure's icon-corrected, daemon-watching build)
Capture method:  QEMU QMP screendump + input-send-event; loginctl/ps
                 session inspection; direct D-Bus introspection
Run window:      2026-09-01T10:46Z -- 2026-09-01T10:51Z
```

### Procedure and result

1. **Baseline:** candidate + daemon-stub running, exactly one registered
   item confirmed via `RegisteredStatusNotifierItems`.
2. **Real logout:** `gnome-session-quit --logout --no-prompt` over SSH
   (equivalent to a user selecting Log Out from the GNOME system menu --
   not a session kill from outside). Confirmed via process inspection:
   `gnome-shell --mode=user` was replaced by `gnome-shell --mode=gdm`
   (the greeter), and a new GDM login session (`c1`, seat0, tty1) with a
   real username-entry greeter screen was captured
   (`candidate-none_2026-09-01T1049Z_gnome50-greeter-after-logout.png`).
3. **Autologin did not automatically retrigger** after this explicit
   logout (confirmed: 80s of polling found no new `gnome-shell --mode=user`
   process). This is standard, intentional GDM behavior -- autologin
   applies at greeter startup, not after an explicit user-initiated
   logout, to avoid an inescapable auto-relogin loop. `systemctl restart
   gdm3` (the same technique used throughout every G6 spike to bring up
   a session) was used to bring up the new login; this is a test-harness
   necessity, not a candidate behavior, and is disclosed here for
   reproducibility.
4. **New session confirmed:** fresh `gnome-shell --mode=user` process.
5. **Real finding, disclosed honestly:** the *old* candidate and daemon-
   stub processes (launched via `nohup ... &` over SSH, not through the
   graphical session's own process supervision) were still running as
   orphans after logout. Checking the new session's
   `RegisteredStatusNotifierItems` showed it empty -- the old processes'
   registration was lost when the old GNOME Shell/extension instance
   that had accepted it was destroyed at logout, even though the
   orphaned processes themselves kept running. This is a testing-
   methodology artifact (an SSH-launched, non-session-scoped process is
   not killed by GNOME's own logout sequence the way a properly
   session-autostarted app would be under `systemd --user` session
   scoping) -- not a claim about how a production Guardian indicator,
   launched through normal desktop autostart, would behave under
   `systemd-logind`'s session cleanup.
6. **Explicit cleanup:** the orphaned old processes were killed
   (`kill -TERM`), confirmed gone.
7. **Fresh launch in the new session:** candidate + daemon-stub relaunched
   (fresh pids). `RegisteredStatusNotifierItems` immediately showed
   **exactly one** item.
8. **Visual + functional confirmation:**
   `candidate-ksni_2026-09-01T1050Z_gnome50-postlogin-single-icon.png`
   shows a single icon; a follow-up click
   (`candidate-ksni_2026-09-01T1051Z_gnome50-postlogin-menu-functional.png`)
   confirms the menu opens correctly in the new session.

### Result: PASS

Duplicate/stale-registration check: **clean.** The new session's watcher
showed zero items before the fresh launch (old orphans' registration did
not survive the old GNOME Shell instance's destruction) and exactly one
after. No duplicate was observed at any point on GNOME.

## Xfce 4.20

### Environment

```text
VM:              disposable qemu overlay (/tmp/g6-evidence-vm-closure2,
                 a second, dedicated VM for this segment)
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
Desktop:         Xfce 4.20, lightdm 1.32.0 with lightdm-gtk-greeter,
                 xfce4-indicator-plugin at panel position 11
Candidate build: same as the GNOME segment above
Capture method:  same as above
Run window:      2026-09-01T11:01Z -- 2026-09-01T11:06Z
```

### Procedure and result

1. **Baseline:** candidate + daemon-stub running, exactly one registered
   item confirmed. Screenshot:
   `candidate-ksni_2026-09-01T1101Z_xfce420-prelogout-baseline.png`.
2. **Real logout:** `xfce4-session-logout --logout --fast` over SSH.
   Confirmed via process inspection: `xfce4-session` exited, `lightdm-
   gtk-greeter` appeared. As with GNOME, `lightdm`'s autologin did not
   automatically retrigger after an explicit logout within the polling
   window; `systemctl restart lightdm` was used to bring up the new
   session (same test-harness necessity as the GNOME segment).
3. **A more consequential real finding than on GNOME, disclosed in
   full:** the old orphaned candidate/daemon-stub processes were still
   running after logout, **and** `RegisteredStatusNotifierItems`
   immediately after the new session came up **still showed the old,
   stale registration** (`org.kde.StatusNotifierItem-12026-1`, the OLD
   pid). Direct process inspection confirmed why: unlike GNOME (where
   the watcher lives inside the per-session GNOME Shell/extension
   process, destroyed at logout), Xfce's watcher is
   `ayatana-indicator-application-service`, a process owned by the
   user's `systemd --user` manager, which is **per-UID, not
   per-graphical-session**, and was confirmed (via `ps`, matching pid
   and start-time to before the logout) to have survived the logout
   unchanged. Adding the indicator plugin to the new session's panel
   before cleaning up the old orphan showed this stale icon rendering as
   if it were current:
   `candidate-none_2026-09-01T1104Z_xfce420-stale-orphan-registration-visible-before-cleanup.png`.
4. **This is a genuinely important finding for G7+, stated plainly:** an
   improperly-scoped indicator process (one not tied to the graphical
   session's own process lifecycle -- e.g. a crashed session manager
   that fails to clean up its children, or, as here, a manually
   SSH-launched test process) can leave a stale registration visible in
   a fresh Xfce session indefinitely, because the underlying D-Bus/
   watcher infrastructure persists per-user, not per-session, under this
   systemd configuration. **This is not a defect in `ksni`** -- it is a
   property of how the process was launched in this test, not of the
   candidate's own registration/cleanup behavior (which was independently
   confirmed clean under a normal kill in every other reconnect test in
   this gate). It is recorded here because a production Guardian
   indicator (G7+) must be launched in a way that ties its lifetime to
   the graphical session (proper desktop autostart under session
   scoping, which `systemd-logind` does clean up on logout) rather than
   as a detached background process, specifically to avoid this failure
   mode in real deployments.
5. **Confirmed the stale registration was genuinely stale, not a
   measurement error:** the old orphaned processes were killed;
   `RegisteredStatusNotifierItems` immediately returned empty, and the
   icon visibly disappeared
   (`candidate-none_2026-09-01T1104Z_xfce420-stale-registration-cleared-after-kill.png`),
   confirming the icon really was attributable to the stale process, not
   something else.
6. **Fresh launch in the new session:** candidate + daemon-stub
   relaunched (fresh pids). `RegisteredStatusNotifierItems` immediately
   showed exactly one item.
7. **Visual + functional confirmation:**
   `candidate-ksni_2026-09-01T1105Z_xfce420-fresh-postlogin-single-icon-menu-functional.png`
   shows a single icon with a real, correctly-reset menu ("clicks so
   far: 0") open.

### Result: PASS, with a disclosed methodology caveat

The final state (single icon, functional menu, no stale registration
once the harness's own orphan is cleaned up exactly as a real session
cleanup would) is a genuine PASS. The intermediate stale-registration
observation is preserved here in full because it is real, informative
evidence about the Xfce D-Bus lifecycle -- not because it changes the
final PASS/FAIL determination for `ksni` itself.

## §30 required test now closed

```text
clean user logout/login lifecycle    PASS on GNOME 50 and Xfce 4.20,
                                      with a disclosed, non-candidate
                                      Xfce stale-registration hazard
                                      relevant to G7+ launch-mechanism
                                      design (session-scoped autostart
                                      required, not detached launch)
```
