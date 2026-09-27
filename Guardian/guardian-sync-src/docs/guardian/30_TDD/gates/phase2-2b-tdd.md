---
title: "Gate 2b TDD — provider-health producer, daemon wiring, D-Bus population"
kind: "gate-tdd"
status: "active"
last_reviewed: "2026-09-07"
---
# Gate 2b TDD

Governing manifest: `docs/guardian/30_TDD/gates/phase2-2b-manifest.toml`.
Full context (not to be re-derived here): `GUARDIAN_PHASE2_IMPLEMENTATION_HANDOFF.md`
§4.2, §6, §7, §13, §20; TDD contract §51.

This file states required behavior and acceptance evidence only — not an
implementation tutorial, not repeated safety doctrine (see
`GUARDIAN_EXECUTION_PROTOCOL.md` and `AGENTS.md` for that).

## Requirements

**R1 — Provider-health transition Event producer.**
Requirement: diffing two successive `capability_registry_tick` snapshots
for the same `capability_id` where `Health` or `Availability` differs
produces exactly one new `Event`, admitted through the same
`CorrelationIngress` mechanism as every other event source.
Evidence: an unchanged snapshot pair emits no `Event`; a snapshot pair
whose `Health`/`Availability` differs for one `capability_id` emits
exactly one expected `Event` correlatable by that `capability_id`.
Scope note: REQUIRED FOUNDATION only (generic Availability/Health
signal, identical across all six G8 providers) — per-source enrichment
(UDisks2 device identity, logind inhibitor detail, UPower battery/AC
detail, AccountsService session specifics) is OPTIONAL FUTURE
ENRICHMENT, out of this gate.

**R2 — Single daemon-owned `CorrelationIngress` admission point.**
Requirement: `guardian-daemon`'s monitoring tick constructs one
`IngressClock`/`CorrelationIngress` admission point that every event
source actually producing events in `guardian-daemon` today — the
existing daemon-tick producer and this gate's new provider-health
producer — feeds through; no producer constructs its own ingress clock
or sequence. PSI is not a live event producer in `guardian-daemon` as of
this gate (confirmed: no production PSI event-generation loop exists
outside a standalone example) — this gate does not add one, since no
owned `P2-API-*` ID requires it and doing so would be scope creep beyond
R1's "required foundation only" framing. The single-admission-point
design is PSI-compatible: a future gate that wires a live PSI producer
must feed it through this same `IngressClock`/`CorrelationIngress`
point, not a separate one, but standing that producer up is not this
gate's work.
Evidence: a test/observation showing both currently-live sources'
events pass through the one admission point and receive monotonically
increasing `ingress_sequence` values regardless of source.

*Process note, recorded per this gate's own review:* when a Contract
Collision Table (per `GUARDIAN_EXECUTION_PROTOCOL.md`) surfaces a real
conflict like this one (TDD text presupposing a producer that doesn't
exist in production), the protocol's existing stop-and-report rule
governs — resolve it by stopping and reporting, not by adjudicating it
unilaterally inside the implementation. This TDD correction is the
result of that conflict being raised after the fact; future gates
should raise it before editing.

**R3 — `Incidents1.ListIncidents()` returns live data.**
Requirement: `dbus_surface.rs`'s `Incidents1::list_incidents` reads the
wired correlation engine's live incident store instead of returning
`Vec::new()`; its stale doc comment ("no incident producer exists") is
corrected to match reality.
Evidence (`P2-API-001`): a Layer-2 (mocked D-Bus) test drives a real
health transition end-to-end and observes `ListIncidents()` return a
non-empty, correctly round-tripped `IncidentWire` result.

**R4 — No new public surface.**
Requirement (`P2-API-002`): no new `Guardian1`, `Capabilities1`,
`Incidents1`, or `Transactions1` method/interface/object path is added
beyond what G9 already shipped.
Evidence: an introspection diff (or equivalent test) against the G9
baseline showing the public D-Bus surface is unchanged.

**R5 — `IncidentWire` shape-lock regression test.**
Requirement (`P2-API-003`): a regression test locks `IncidentWire`'s
exact current shape — a 7-field positional tuple of `String`s — so any
future accidental arity/order/type change fails immediately.
Evidence: the test exists, passes at this gate's baseline, and is shown
to fail if the tuple shape is deliberately perturbed (a throwaway local
check during development, not a committed test).

**R6 — `P2-REC-003`'s corrected ownership split is implemented as the
daemon-side half.**
Requirement: Gate 2a's `CorrelationEngine::reject_capacity()` already
performs the library-side half (reject, preserve, `saturating_add`
counter, typed `CapacityRejected` return, zero I/O — see
`crates/guardian-core/src/correlation.rs`). This gate implements the
other half only: when `guardian-daemon` consumes a `CapacityRejected`
outcome, it writes exactly one `eprintln!("[guardian-daemon] ...")` log
line using this file's existing logging convention (no new logging
facility). `guardian-core` is not modified to add I/O of any kind for
this.
Evidence: a test or direct observation that a `CapacityRejected` outcome
consumed by the daemon tick produces exactly one operational log line,
and that `guardian-core`'s correlation module contains no daemon-shaped
I/O.

**R7 — PSI correlation uses stable resource identity, not
transition-text `normalized_key`.**
Requirement: this gate's daemon wiring must feed PSI events into
correlation the same way Gate 2a's engine already correlates them —
grouped by `resource_refs.first()` (the stable `/proc/pressure/{resource}`
identity), never by `normalized_key` (which embeds transition text via
`providers/psi.rs`'s `event_from_crossing` and therefore differs between
two Critical-crossing events for the same resource with different
`{from}->{to}` transitions). Do not introduce daemon-side logic that
re-keys PSI correlation by `normalized_key`.
Evidence: no new test required beyond Gate 2a's own PSI correlation
tests continuing to pass unmodified through the real daemon wiring path
(Layer 2); if daemon wiring adds any PSI-specific glue code, it must not
construct or use a `normalized_key`-based correlation key.

## Out of scope for this gate

Incident severity (deferred in full, §15); `Transactions1` population
(§12); per-source health enrichment beyond the generic signal (§13);
VM evidence (Gate 2c); anything touching Wave 1's
`restart_capability.rs`/authorization files; any change to
`IncidentWire`'s shape or `Incident::link_event`'s signature.
