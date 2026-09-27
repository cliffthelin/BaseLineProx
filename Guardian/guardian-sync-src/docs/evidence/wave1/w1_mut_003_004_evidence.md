# W1-MUT-003 / W1-MUT-004 — repair-pass evidence closure

**Status before this repair pass**: implemented (live `LoadState` /
`RefuseManualStart`/`Stop` checks in `restart_validate`), but "not
separately unit-tested against a real 'not-found' unit" (W1-MUT-003) /
"not separately VM-reproduced against a real such unit" (W1-MUT-004) — see
`WAVE1_MILESTONE.md`'s original ID table.

## What changed

The two live-precondition checks inline in
`crates/guardian-helper/src/main.rs::restart_validate` were extracted into
pure, independently unit-testable predicates on
`crates/guardian-helper/src/restart_capability.rs::LiveUnitState`:

- `LiveUnitState::is_load_state_blocked(&self) -> bool` (W1-MUT-003:
  `load_state == "not-found" || load_state == "masked"`)
- `LiveUnitState::refuses_manual_start_or_stop(&self) -> bool` (W1-MUT-004:
  `refuse_manual_start || refuse_manual_stop`)

`restart_validate` now calls these directly (identical behavior, just
factored so the branch condition itself is unit-testable in isolation from
any live D-Bus call). New deterministic unit tests in
`restart_capability.rs`'s test module cover both predicates for every
relevant `LiveUnitState` fixture (blocked/masked/loaded;
start-only/stop-only/both/neither).

This closes the "deterministically testable" half of the gap. The
remaining half — whether real Ubuntu 26.04.1 systemd genuinely reports the
values these predicates branch on — required real VM evidence, gathered
below, independent of (and without touching) the one governed
`cups-restart` → `cups.service` capability row.

## Real VM evidence (`guardian-g9`)

### W1-MUT-003: a genuinely nonexistent unit reports `LoadState == "not-found"`

```
$ busctl call --system org.freedesktop.systemd1 /org/freedesktop/systemd1 \
    org.freedesktop.systemd1.Manager LoadUnit s "definitely-nonexistent-w1mut003.service"
o "/org/freedesktop/systemd1/unit/definitely_2dnonexistent_2dw1mut003_2eservice"

$ busctl get-property --system org.freedesktop.systemd1 \
    /org/freedesktop/systemd1/unit/definitely_2dnonexistent_2dw1mut003_2eservice \
    org.freedesktop.systemd1.Unit LoadState
s "not-found"
```

Confirms the exact real value `is_load_state_blocked` checks for
(`LoadState == "not-found"`) is what real systemd actually reports for a
unit that does not exist — not a hypothetical string.

### W1-MUT-004: a real unit configured with `RefuseManualStart=yes` reports it truthfully

A disposable transient unit was written (never `cups.service`, never
touching the one governed capability row):

```
$ cat /etc/systemd/system/w1mut004-test.service
[Unit]
RefuseManualStart=yes

[Service]
ExecStart=/bin/sleep 3600

$ systemctl daemon-reload
$ busctl call --system org.freedesktop.systemd1 /org/freedesktop/systemd1 \
    org.freedesktop.systemd1.Manager LoadUnit s "w1mut004-test.service"
o "/org/freedesktop/systemd1/unit/w1mut004_2dtest_2eservice"

$ busctl get-property --system org.freedesktop.systemd1 \
    /org/freedesktop/systemd1/unit/w1mut004_2dtest_2eservice \
    org.freedesktop.systemd1.Unit RefuseManualStart
b true

$ busctl get-property --system org.freedesktop.systemd1 \
    /org/freedesktop/systemd1/unit/w1mut004_2dtest_2eservice \
    org.freedesktop.systemd1.Unit LoadState
s "loaded"
```

Confirms `RefuseManualStart` is real, live, correctly-typed (`b`, i.e. a
D-Bus boolean, matching `bool_field`'s `downcast_ref::<bool>()` parsing in
`SystemdRestartAdapter::read_live_state`) systemd wire data for a unit
genuinely configured this way, and that this is orthogonal to `LoadState`
(this unit is `loaded`, so W1-MUT-004's check is reached and evaluated
independently of W1-MUT-003's).

The transient test unit was removed after capture
(`rm /etc/systemd/system/w1mut004-test.service; systemctl daemon-reload`);
no `debian/`, packaging, or the governed `cups-restart` capability row was
touched.

## Disposition

Both IDs are now closed: deterministic unit tests prove Guardian's own
branch logic for every relevant input, and real, independent VM evidence
proves the real-world values that logic depends on genuinely occur exactly
as assumed.
