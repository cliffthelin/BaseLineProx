# G6 Evidence Closure — "daemon unavailable shows degraded state" (§30)

**Status: CLOSURE.** Closes §30's "daemon unavailable shows degraded
state" required test for `ksni`, with real, non-simulated detection of a
real absent/present D-Bus name -- not inferred from the pre-existing
"Simulate degraded status" menu item, which is a manual toggle and does
not by itself satisfy this specific required test (per the independent
audit's finding that the manual toggle alone was insufficient evidence
for this item).

## Why a minimal stub, and why this is not G7 work

Per `docs/guardian/30_TDD/GUARDIAN_G6_IMPLEMENTATION_HANDOFF.md` §8: "No
real production daemon ... unless needed as minimal evidence
infrastructure ... keep it to the minimal skeleton needed to prove that
one claim ... must be explicitly marked non-production." No real
Guardian daemon exists yet (that is G7+ work), so this required test
cannot be evidenced against the real thing. What *can* be evidenced at
G6 -- and what this closure does -- is whether the candidate's own
indicator mechanism can detect a real, external D-Bus name's
presence/absence and represent that as a real, distinct, observable
state, which is the mechanism-level property §30 is actually asking G6
to establish for the *chosen candidate*. The real Guardian daemon's own
health-reporting protocol remains G7+ design work, out of scope here.

`tests/vm/g6-daemon-evidence-stub/` is the minimal stub this required.
Its own module doc comment states, verbatim:

> G6 EVIDENCE-ONLY STUB — NON-PRODUCTION. DISPOSABLE. NOT A G7 DAEMON
> SKELETON.

It does exactly one thing: claim the well-known D-Bus name
`io.github.cliffthelin.GuardianG6EvidenceStub1` on the session bus and
hold it until terminated. It exposes no interfaces, no methods, no
properties, no persistent state, no authorization model, and has no
connection to `guardian-core`, `guardian-daemon`, or the real
`io.github.cliffthelin.Guardian1` namespace reserved by ADR-001. It is
not part of the Cargo workspace (own `[workspace]` table). "Daemon
unavailable" is evidenced simply by killing the process (the D-Bus name
is released automatically when its connection closes); "daemon
available" is evidenced by it running.

`tests/vm/g6-candidate-ksni/` was extended (not replaced -- the existing
menu/click-handler behavior from every prior spike is unchanged) with a
background task that polls `org.freedesktop.DBus.NameHasOwner` for that
same well-known name every 500ms via a real `zbus::fdo::DBusProxy` call,
and pushes the result into the running tray via `ksni::Handle::update`.
This is real detection of a real D-Bus signal, not a timer-driven
simulation -- only killing/starting the separate stub process changes
what this task observes. Detected daemon-unavailability takes visual
precedence over the pre-existing manually-simulated "Simulate degraded
status" toggle, per the G6 handoff's fail-closed/degraded-state
checklist requirement that this be "a real, distinct, observable state
-- never silently rendered as icon just doesn't appear."

## Environment

```text
VM:              disposable qemu overlay (/tmp/g6-evidence-vm-closure)
OS:              Ubuntu 26.04 LTS (Resolute Raccoon)
Desktop:         GNOME Shell 50.1, ubuntu-appindicators@ubuntu.com enabled
Candidates:      tests/vm/g6-candidate-ksni/, tests/vm/g6-daemon-evidence-stub/
Capture method:  QEMU QMP screendump; candidate's own log (real-time
                  daemon-watch presence-change messages)
Run window:      2026-09-01T10:46Z
```

## Procedure and result

1. **Both processes launched:** daemon stub first (claims the name),
   then `ksni` (begins polling for it). Candidate log confirms detection
   within one poll cycle:
   ```text
   [g6-evidence] daemon-watch: io.github.cliffthelin.GuardianG6EvidenceStub1 presence changed -> true
   ```
2. **Baseline, healthy:**
   `gnome50-xfce420-closure/candidate-ksni_2026-09-01T1046Z_gnome50-baseline-computer-icon.png`
   -- icon shown as `"computer"` (the corrected healthy icon).
3. **Daemon stub killed:** `kill -TERM`. Its own log confirms clean exit
   (`SIGTERM received, releasing name and exiting`). The candidate's log
   confirms real, immediate detection:
   ```text
   [g6-evidence] daemon-watch: io.github.cliffthelin.GuardianG6EvidenceStub1 presence changed -> false
   ```
4. **Real, distinct, observable degraded state:**
   `candidate-ksni_2026-09-01T1046Z_gnome50-daemon-unavailable-dialog-error-icon.png`
   shows the icon changed to `"dialog-error"` (a red circle-with-dash
   glyph) -- visually distinct from both the healthy `"computer"` icon
   and the separate manually-simulated `"dialog-warning"` (warning
   triangle) state used elsewhere in this gate's evidence, so a viewer
   cannot confuse "daemon unavailable" with "manually toggled degraded."
5. **Daemon stub relaunched:** candidate log confirms detection of
   recovery:
   ```text
   [g6-evidence] daemon-watch: io.github.cliffthelin.GuardianG6EvidenceStub1 presence changed -> true
   ```
   Screenshot
   (`candidate-ksni_2026-09-01T1046Z_gnome50-daemon-recovered-healthy-icon.png`)
   confirms the icon returned to `"computer"`.

## Result: PASS, tested and closed (not contractually deferred)

This required test is evidenced now, at G6, using the handoff's own
explicitly-permitted minimal evidence-only stub mechanism -- it is not
waived, and it is not deferred to G7 as "requires a real daemon,"
because the mechanism-level capability (detect a real D-Bus name's
presence/absence; represent it as a real, distinct, observable icon
state) is exactly what a candidate-evaluation gate can and should
establish. What *is* correctly left to G7+ is wiring this same mechanism
against the real Guardian daemon's own eventual health/liveness
signal -- a protocol-design question for G7, not a reason to leave this
§30 item untested here.

## §30 required test now closed

```text
daemon unavailable shows degraded state    PASS (real detection,
                                            evidence-only stub,
                                            explicitly non-production)
```
