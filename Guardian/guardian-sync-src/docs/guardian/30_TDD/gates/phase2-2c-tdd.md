---
title: "Gate 2c TDD — VM evidence and restart/epoch proof"
kind: "gate-tdd"
status: "active"
last_reviewed: "2026-09-06"
---
# Gate 2c TDD

Governing manifest: `docs/guardian/30_TDD/gates/phase2-2c-manifest.toml`.
Full context: `GUARDIAN_PHASE2_IMPLEMENTATION_HANDOFF.md` §9, §20, §21.

This gate produces evidence, not new production code, beyond whatever
minimal VM-only test harness the run itself needs. It proves on real
hardware/systemd what Gates 2a/2b only proved in isolation or against a
mock bus.

## Requirements

**R1 — Real provider transition produces a real `Incidents1` transition
(`P2-VM-001`).**
Requirement: on the disposable Ubuntu 26.04.1 VM, a real, safe, reversible
VM action causes an actually registry-observed capability/provider (per
the Gate 2b health-diff producer, `guardian-core/src/providers/
health.rs`, which diffs successive `capability_registry_tick` snapshots)
to transition `Availability`/`Health`, producing a real, observable
`Incidents1` transition over the real system bus — not a mock, not
asserted from source reading alone.

This corrects two independent errors in the prior wording. First, an
arbitrary unit such as `cups.service` is never read by the registry at
all, so stopping/starting it cannot produce any transition. Second, the
originally-intended `systemd-logind.service` does not work either:
`systemd_capabilities()` (`guardian-core/src/providers/registry.rs`) only
asks whether `org.freedesktop.systemd1`'s `LoadUnit` + property read for
`systemd-logind.service` succeeds; `read_state()` maps any `Ok(_)` to
`Available`/`Healthy` regardless of that unit's own `ActiveState`, so an
ordinary stop/start of `systemd-logind.service` produces no observable
Availability/Health change through this code path (confirmed by reading
the accepted Gate 2b code directly, matching Gate 2b's own accepted test
`build_engine_with_one_real_open_incident` in
`crates/guardian-daemon/tests/phase2_2b_contract.rs`, which synthesizes —
never actually performs — "the shape `capability_registry_tick` would
observe if the real `systemd-logind.service` unit actually went
unavailable").

Confirmed candidate, validated live on `guardian-g9` during this preflight
correction: `sudo systemctl mask --now upower.service` causes
`guardian-core/src/providers/upower.rs`'s `display_device()` read to fail
with a real `org.freedesktop.systemd1.UnitMasked` D-Bus error (confirmed
via `busctl`/`dbus-send`), which `registry.rs`'s `read_state()` maps to a
real `Available`/`Healthy` -> `Degraded`/`Error` transition of the
`upower.display-device` capability; `sudo systemctl unmask upower.service
&& sudo systemctl start upower.service` reverses it back to
`Available`/`Healthy` (also confirmed live). The Gate 2c implementer may
use this candidate directly, or — per `AGENTS.md`'s required lookup
workflow — confirm an equivalent safe/reversible candidate against
another of the six registry providers (systemd, PSI, logind, UDisks2,
UPower, AccountsService).

Evidence: a captured transcript/log under `docs/evidence/p2/` showing the
real provider transition and the corresponding
`Incidents1.ListIncidents()` change, reproducible from a fresh VM clone
at this gate's `baseline_sha`.

**R2 — Daemon restart during an open incident loses it; fresh ingress
epoch is a process-level fact, not an externally re-derived value
(`P2-VM-002`).**
Requirement: a real `guardian-daemon` restart while an incident is open
loses that incident (per §9's accepted no-persistence semantics) —
confirmed on real hardware, not asserted from source reading alone.

This corrects the prior wording's additional claim that the VM run must
observe "a fresh `CorrelationIngress` epoch at sequence 0" as an external
fact. `IncidentWire` (`crates/guardian-daemon/src/dbus_surface.rs`,
`crates/guardian-client/src/lib.rs`) is confirmed to be exactly a 7-field
`String` tuple with no ingress-sequence field on any public surface, and
no production log line in `guardian-daemon` emits `ingress_sequence`
today — there is no channel through which a VM-level Layer 4 test could
externally observe the raw sequence value without changing production
code or the public D-Bus shape, both forbidden for this gate. Claiming
such an observation would not be a real VM proof.

The fresh-epoch *mechanism* itself does not need re-proving here: it is
already proven deterministically at Gate 2a
(`crates/guardian-core/tests/correlation_contract.rs`,
`p2_evt_004_fresh_ingress_clock_resets_epoch`), and `guardian-daemon`'s
`main()` is confirmed to construct a fresh `IngressClock::new()` /
`CorrelationEngine::new()` pair at process start
(`crates/guardian-daemon/src/bin/guardian-daemon.rs`), never reusing or
persisting a prior instance. Gate 2c's job is only to prove the
process-level fact that a genuinely fresh `guardian-daemon` process
starts with no cross-restart incident state — the epoch-reset
consequence follows from the already-accepted Gate 2a proof plus this
fresh-process fact, not from a new external observation channel.

Evidence: a captured transcript/log under `docs/evidence/p2/` showing an
open incident before restart, the real process restart itself, and the
incident's absence from `Incidents1.ListIncidents()` after restart.

## Out of scope for this gate

Any new correlation/daemon-wiring logic (Gates 2a/2b, both closed by the
time this gate runs); any change to `Incidents1`/`IncidentWire`; any
non-VM (Layer 1/2/3) test work.
