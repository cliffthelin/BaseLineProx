# G6 Repair — `ksni` Xfce Guardian-daemon-analog restart (closes blocking finding 2's Xfce gap)

**Status: REPAIR, corrects the second half of blocking finding 2 of the
independent audit.** The audit found that `G6_P0_IND_003_RECONNECT_
EVIDENCE.md` and `G6_XFCE_RECONNECT_EVIDENCE.md` labeled candidate-
process kill/relaunch as "reconnect after daemon restart," conflating it
with the contractually distinct scenario of the Guardian-daemon analog
restarting while the indicator process itself stays alive. The audit
confirmed real evidence for the correct scenario already existed for
`ksni` on GNOME (`G6_DAEMON_UNAVAILABLE_EVIDENCE.md`) but had never been
run on Xfce at all. This document closes that specific gap.

## Environment

```text
VM:              disposable qemu overlay (/tmp/g6-repair-vm), shared
                 with the candidate 1 repair pass in the same session
                 (see G6_CANDIDATE1_REPAIR_EVIDENCE.md for the shared
                 environment block)
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
Desktop:         Xfce 4.20, xfce4-indicator-plugin at panel position 11
Candidate build: tests/vm/g6-candidate-ksni/ (unchanged from the earlier
                 G6 closure pass -- already had daemon-analog watching)
Stub build:      tests/vm/g6-daemon-evidence-stub/ (unchanged)
Capture method:  QEMU QMP screendump; direct D-Bus introspection; process
                 log inspection; `ps` for pid-continuity confirmation
Run window:      2026-09-01T16:29Z -- 16:30Z
Teardown:        covered under the shared VM teardown in
                 G6_CANDIDATE1_REPAIR_EVIDENCE.md (same VM session)
```

## Procedure and result

- Candidate 1 was stopped first (`kill -TERM`, confirmed exited) to free
  the panel slot for a clean single-candidate test; the daemon stub was
  left running from the prior test.
- `ksni` launched fresh (pid 27579). Log confirms immediate detection of
  the already-running stub:
  ```text
  [g6-evidence] tray.spawn() succeeded, StatusNotifierItem registered
  [g6-evidence] daemon-watch: io.github.cliffthelin.GuardianG6EvidenceStub1 presence changed -> true
  ```
- Baseline confirmed:
  `candidate1-repair/candidate3-ksni_2026-09-01T1629Z_xfce420-daemon-analog-baseline.png`
  -- `computer` icon visible.
- **Disruption: `kill -TERM` on the daemon stub only** (pid 27473).
  `ksni`'s process (pid 27579) was never touched -- confirmed via `ps`
  immediately after.
- **Observable degraded state:** `ksni`'s own log shows real detection:
  ```text
  [g6-evidence] daemon-watch: io.github.cliffthelin.GuardianG6EvidenceStub1 presence changed -> false
  ```
  Screenshot
  `candidate3-ksni_2026-09-01T1629Z_xfce420-daemon-analog-unavailable-visible.png`
  shows the icon changed to a real, distinct red `dialog-error` glyph
  (`ksni`'s implementation does visually distinguish this real-detected
  state from the manually-simulated warning-triangle, unlike candidate
  1's prototype -- see the candidate 1 repair document for that
  disclosed difference).
- **Recovery:** daemon stub relaunched (fresh pid). `ksni`'s log:
  ```text
  [g6-evidence] daemon-watch: io.github.cliffthelin.GuardianG6EvidenceStub1 presence changed -> true
  ```
  `RegisteredStatusNotifierItems` immediately after showed exactly one
  entry (`org.kde.StatusNotifierItem-27579-1` -- same pid as the original
  launch, confirming this is genuinely the same process, not a
  respawn). Screenshot
  `candidate3-ksni_2026-09-01T1629Z_xfce420-daemon-analog-recovered.png`
  confirms the icon returned to `computer`.
- **No duplicate registration/icon** at any point -- confirmed via the
  single-entry `RegisteredStatusNotifierItems` result above.
- **Menu remains usable** after the full cycle: a follow-up click
  (`candidate3-ksni_2026-09-01T1630Z_xfce420-menu-functional-after-daemon-analog-cycle.png`)
  shows the real 3-item menu still opens correctly.

## Required-proof checklist (from the repair brief), all satisfied

```text
indicator process remains alive throughout    YES -- pid 27579 unchanged
stub initially present                        YES
healthy indicator visible                     YES (computer icon)
stub terminated                               YES (kill -TERM)
indicator detects absence                     YES (real log line)
visible state changes away from healthy       YES (dialog-error icon)
stub relaunched                               YES
same indicator process detects return         YES (same pid, real log line)
healthy state returns                         YES (computer icon)
no duplicate registration/icon                YES (single D-Bus entry)
menu remains usable                           YES (real click confirmed)
```

## §30 required test now closed for `ksni` on Xfce

```text
reconnect after daemon restart (Guardian-daemon-analog, indicator alive)   PASS
```

This closes the specific gap the independent audit identified: `ksni`
now has real, correctly-scoped evidence for this exact required test on
**both** GNOME (`G6_DAEMON_UNAVAILABLE_EVIDENCE.md`) and Xfce (this
document), with the indicator process's own identity (pid) confirmed
unchanged throughout in both cases.
