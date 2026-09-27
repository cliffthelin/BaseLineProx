---
title: "Gate 2b Health-Lifecycle Integration Repair TDD — reopened P2-API-001"
kind: "reopened-gate-repair-tdd"
status: "active"
last_reviewed: "2026-09-07"
---
# Gate 2b Health-Lifecycle Integration Repair TDD

Governing manifest:
`docs/guardian/30_TDD/gates/phase2-2b-health-lifecycle-integration-repair-manifest.toml`.

Full context (not to be re-derived here): `GUARDIAN_PHASE2_IMPLEMENTATION_HANDOFF.md`
§4.2 (provider health/availability transition → incident, confidence-by-
transition rules), §6 (ingress order), §13 (Gate 2b scope); `AGENTS.md`
"Safety rules"; TDD contract §51; the Gate 2a health-lifecycle repair TDD
(`docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-tdd.md`),
whose own "Downstream Gate 2b repair" section is the direct forward
pointer this file closes. This file states required behavior and
acceptance evidence only — not an implementation tutorial.

**This is a repair of one already-closed, already-normative ID, not a new
gate.** `P2-API-001` ("`Incidents1.ListIncidents()` returns real,
non-empty incidents") remains exactly what it was — what changes is *how*
its evidence is allowed to prove that: the real production sequence, not
a synthetic cloned-second-event admission. `P2-API-002` (no new public
D-Bus surface) and `P2-API-003` (`IncidentWire` shape-lock) are
unaffected and must keep passing unmodified — this repair adds no D-Bus
member and does not touch `IncidentWire`'s shape.

## The defect (why this gate is reopened)

`crates/guardian-daemon/tests/phase2_2b_contract.rs`'s
`build_engine_with_one_real_open_incident` — the fixture `P2-API-001`'s
acceptance evidence is built on — drives one real
`HealthTransitionProducer`-emitted `Event` through the shared ingress
point, then **clones that event and mutates the clone's `event_id`** to
fabricate a fake second admission, because `CorrelationEngine`'s
pre-repair dwell-promotion path required two `Event` admissions and the
real producer is edge-triggered (one `Event` per real state change,
never a second for an unchanged pair). The just-committed Gate 2a
health-lifecycle repair added exactly the capability that makes this
fabrication unnecessary — `CorrelationEngine::advance_health_dwell`, fed
a `FreshHealthObservation` derived from a real re-observed snapshot, with
no second `Event` required. But nothing in `guardian-daemon` calls it:
`capability_registry_tick` (`crates/guardian-daemon/src/bin/
guardian-daemon.rs`) feeds `HealthTransitionProducer::observe`'s output
`Event`s through `admit_event` and stops there. The real pipeline
therefore still cannot open (or close) a provider-health incident
end-to-end without Gate 2a's fresh-observation entry point being wired
in, and `P2-API-001`'s own acceptance test papers over exactly that gap.

A second, narrower defect in the same area: `HealthTransitionProducer::
transition_event` (`crates/guardian-core/src/providers/health.rs`) only
ever sets `HEALTH_AVAILABILITY_TO_ATTR` on the `Event` it emits — never
`HEALTH_HEALTH_TO_ATTR`. `CorrelationEngine::classify()` (Gate 2a,
`crates/guardian-core/src/correlation.rs`) treats a missing
`HEALTH_HEALTH_TO_ATTR` as `Health::Healthy` (a deliberate
backward-compatibility default documented on the constant itself). Every
real production `Event` today is therefore classified as though its
`Health` were always `Healthy`, regardless of the real observed value —
harmless for the `Available`/`Unavailable` rows of `health_direction()`'s
table (which do not depend on `Health`), but silently wrong for the one
row that does: a real `Available` + `Warning` transition is misclassified
as `Available` + defaulted-`Healthy` = `Good`, never reaching `Bad`/
`Probable` at all.

## Contract Collision Table (mandatory preflight — completed before any
requirement below is written)

| Requirement | Owner | Module/path | Potential conflict | Contract resolution |
|---|---|---|---|---|
| Confidence-by-transition (§4.2: `Available→Unavailable`=`Confirmed`, `Healthy→Warning`=`Probable`) must be preserved end-to-end from a real `Event`/fresh observation through to the opened `Incident`'s `Confidence`. | Gate 2a owns the classification/confidence *rule* (`health_direction`); Gate 2b owns the *inputs* fed to it (`Event` provenance, snapshot re-observation). | `crates/guardian-core/src/correlation.rs` (`health_direction`, `FreshHealthObservation::classify`, `HealthDirection::Bad(Confidence)`) vs. `crates/guardian-core/src/providers/health.rs` (`transition_event`) and `crates/guardian-daemon/src/bin/guardian-daemon.rs` (`capability_registry_tick`). | Does Gate 2a's already-closed API need a *from/to pair* to preserve §4.2's named-transition confidence tiers, or does it only need the current/target `(Availability, Health)`? If the former and Gate 2b's `Event`/snapshot shape cannot supply "from", Gate 2b would have to either infer confidence itself (broadening policy without authority) or leak correlation policy into the producer — both forbidden by this repair's own scope. | **No collision — resolved, not blocked.** Read directly: `health_direction(availability: Availability, health: Health) -> Option<HealthDirection>` (`correlation.rs` lines ~342–369) takes only the *current/target* pair — no "previous" parameter exists anywhere in its signature, `Classification::Health`, `classify(event: &Event)`, or `FreshHealthObservation::classify(availability, health)`. Gate 2a's own docs on `health_direction` state the table's ceiling explicitly: `Unavailable` → `Confirmed` "(already-true prior behavior)" and `Available`+`Warning` → `Probable`, each keyed purely off the target state, never off what the capability transitioned *from*. §4.2's "transitions" collapse, by Gate 2a's own accepted design, into pure destination-state classification, because the *fact* that a transition occurred at all is already established structurally (a new debounce candidate, or a fresh re-observation matching a pending candidate's `target`) before `health_direction`/`classify` is ever consulted for confidence. Therefore Gate 2a's API is **already sufficient as-is**: it needs the real, current `(Availability, Health)` pair on the `Event` (both dimensions, not just `Availability`) and the real, current `(Availability, Health)` pair on each fresh snapshot re-observation (already true — `HealthTransitionProducer`'s `previous`/`current` diff and `capability_registry_tick`'s live snapshot both carry both dimensions internally; the *only* gap is that `transition_event` drops `Health` before it ever reaches the `Event`'s wire attributes). This repair's Event-provenance requirement (R1 below) is written assuming this API is sufficient: populate `HEALTH_HEALTH_TO_ATTR` with the real destination `Health`, alongside the already-populated `HEALTH_AVAILABILITY_TO_ATTR`. No "previous" state needs to be added to the `Event` shape, and no confidence-classification logic is duplicated, broadened, or moved into `guardian-core::providers::health` or `guardian-daemon`. |
| Fresh-observation dwell-advancement must run once per tick per capability, without a second provider read and without fabricating an `Event`. | Gate 2a owns the promotion mechanism (`advance_health_dwell`); Gate 2b owns calling it from the daemon's real tick loop. | `crates/guardian-core/src/correlation.rs::advance_health_dwell` vs. `crates/guardian-daemon/src/bin/guardian-daemon.rs::capability_registry_tick`. | Does `advance_health_dwell`'s signature give the daemon everything it needs from data already in hand (the tick's own snapshot), or does it require something the daemon does not already have without a second registry read? | **No collision.** `advance_health_dwell(&mut self, capability_id: &CapabilityId, observation: FreshHealthObservation, ingress_clock: Instant, ingress_sequence: u64) -> AdmitResult` needs exactly: a `capability_id` (present on every `CapabilityRecord` in the snapshot `capability_registry_tick` already collected), a `FreshHealthObservation` (constructible via `FreshHealthObservation::classify(record.availability, record.health)` from that same record, no extra read), and an `(Instant, u64)` ingress-order pair (`Instant::now()` plus the daemon's already-shared `IngressClock::sequence()` — a non-mutating read of the same clock every other producer already feeds through, requiring no second admission). Confirmed as a no-op (`AdmitOutcome::Ignored`) for any `capability_id` with no pending debounce candidate (see `advance_health_dwell`'s own doc comment), so the daemon may call it unconditionally for every capability in the fresh snapshot each tick without first having to know which ones are pending. |
| `P2-API-002` (no new D-Bus surface) / `P2-API-003` (`IncidentWire` shape-lock) must remain closed and unmodified by this repair. | Gate 2b (already closed, not reopened here for these two IDs). | `crates/guardian-daemon/src/dbus_surface.rs`, `crates/guardian-client/src/lib.rs`. | Does replacing `P2-API-001`'s fixture or wiring fresh-observation advancement require touching either `IncidentWire`'s shape or adding a D-Bus member? | **No collision, and no reopening required.** Neither R1 (Event provenance) nor R2 (daemon wiring) below touches `Incidents1`, `dbus_surface.rs`, or `IncidentWire` in any way — both requirements are internal to the producer and the daemon's pre-D-Bus event pipeline. `P2-API-002`/`P2-API-003`'s existing evidence in `phase2_2b_contract.rs` is required to keep passing unmodified (regression only), not re-verified as new evidence. |

**Verdict: no STOP triggered.** Gate 2a's already-closed API
(`health_direction`, `FreshHealthObservation`, `advance_health_dwell`)
is sufficient as-is for every requirement this repair owns. All
requirements below are written as active, not blocked.

## Requirements

**R1 — Complete target-state `Event` provenance.**
Requirement: every real health-transition `Event`
(`HealthTransitionProducer::observe`'s output, via `transition_event`)
must carry both `HEALTH_AVAILABILITY_TO_ATTR` (already true) and
`HEALTH_HEALTH_TO_ATTR` (currently missing), set to the real,
current/target `Availability`/`Health` pair for that `capability_id` —
never the previous pair, never inferred or defaulted. The producer
remains edge-triggered (a real, valuable property, per its own
`unchanged_snapshot_pair_emits_no_event` test) and gains no new
provider I/O: both attributes are already present on the
`CapabilityRecord` the producer already diffs. This requirement does not
change `health_direction()`, `classify()`, or any other Gate 2a code
(forbidden scope) — it only ensures the `Event` the producer hands to
Gate 2a's existing, unmodified `classify()` carries the data that
function already knows how to consume.
Evidence: a test asserts a real transition `Event`'s
`HEALTH_HEALTH_TO_ATTR` attribute equals the target `Health`'s wire
token for at least the `Available`+`Warning` case (the row this repair's
Contract Collision Table identifies as silently misclassified today) and
the `Unavailable` case; a second test confirms
`unchanged_snapshot_pair_emits_no_event` (or equivalent) still holds —
the edge-triggered property is unaffected by adding the attribute.

**R2 — Daemon fresh-snapshot → Gate 2a dwell-advancement wiring.**
Requirement: after `capability_registry_tick` collects a fresh registry
snapshot and admits any real diff-driven `Event`s from
`HealthTransitionProducer::observe` (as today), it must additionally
call `CorrelationEngine::advance_health_dwell` once per `CapabilityRecord`
in that same fresh snapshot — no second provider/registry read, no
fabricated `Event`. Each call uses
`FreshHealthObservation::classify(record.availability, record.health)`
for `observation`, the `capability_id` from the same record, and a
single shared `(Instant::now(), IngressClock::sequence())` pair captured
once per tick (not once per capability) so every fresh-observation call
in the same tick shares one ingress-order point, consistent with the
"one tick, one fresh observation" framing R1/R2 of the Gate 2a repair TDD
establish. Must support both directions: sustained-`Bad` →
`advance_health_dwell` opens an incident once dwell has elapsed;
sustained-recovery-to-`Good` → it closes one. Must preserve Gate 2a's own
invariants unmodified: no fresh observation for a capability means no
promotion for it (a capability absent from a given tick's snapshot is
simply not called for that tick — never treated as an implicit `Good` or
`Bad`); an `Unresolved` `FreshHealthObservation` (absent, `Unknown`
`Availability`, or `Available`+`Error`/`Stale`/`Unknown` `Health`) must
never falsely advance a pending candidate in either direction.
Evidence: a test drives `capability_registry_tick`-shaped calls (or the
extracted wiring function, if the implementation factors one out)
through a sequence of snapshots and asserts: (a) a capability that goes
bad and stays bad across enough ticks to satisfy `health_min_dwell`
opens exactly one incident with no second `Event` ever constructed; (b)
a capability with no pending candidate is unaffected by being called
every tick (no spurious outcome); (c) a capability that disappears from
one tick's snapshot entirely does not promote a pending candidate on
that tick.

**R3 — Replace `P2-API-001`'s synthetic fixture with the real production
sequence.**
Requirement: `build_engine_with_one_real_open_incident`
(`crates/guardian-daemon/tests/phase2_2b_contract.rs`) must no longer
clone an `Event` and mutate its `event_id` to fabricate a second
admission. Its replacement (same name or a new one — implementation's
choice) must drive: baseline snapshot (seeds the producer, no `Event`)
→ bad-transition snapshot (`HealthTransitionProducer` emits exactly one
real `Event`, admitted through the shared ingress point;
`AdmitOutcome::DebouncePending`) → a later, unchanged-still-bad fresh
snapshot (`HealthTransitionProducer` emits **zero** new `Event`s,
confirmed by assertion — proving R1's edge-triggered property still
holds under repeated bad readings — and R2's daemon-side wiring calls
`advance_health_dwell` against that same fresh snapshot) →
fresh-observation advancement promotes the candidate → a real `Incident`
opens → `Incidents1::list_incidents` (over the private/mocked bus, as
today) returns it, correctly round-tripped through the unmodified
`IncidentWire` shape. No `event_id` mutation, no cloned `Event`, anywhere
in the fixture.
Evidence: the rewritten fixture/test itself, plus the existing
`assert_p2_api_001_list_incidents_returns_the_real_open_incident`
assertions (incident status `open`, confidence `confirmed` for the
`Unavailable` case per §4.2, `primary_resource` equal to the real
`capability_id`, non-empty `incident_id`) continuing to pass unchanged
against the real-sequence-built engine.

**R4 — Symmetric recovery evidence.**
Requirement: the same real-sequence integration layer must prove the
closure counterpart to R3, mirroring the Gate 2a repair's own R5:
sustained-bad snapshot sequence → incident opens (as R3) → a later
good-transition snapshot (`HealthTransitionProducer` emits one real
recovery `Event`, or the fresh-snapshot path alone is sufficient —
reason through the actual minimal snapshot sequence needed, since a
debounced-recovery candidate can be seeded either by a real `Good`
`Event` admission or by a fresh observation while the incident is open;
either is acceptable as long as no `Event` is fabricated/cloned) →
sustained-good-recovery persists across enough fresh snapshots to
satisfy `health_min_dwell`, with `HealthTransitionProducer` emitting
**zero** new `Event`s once the pair is unchanged from the last-observed
state → fresh-observation advancement closes the incident →
`Incidents1::list_incidents` reflects it as closed (present in the
closed-incident set the interface already serializes, per
`to_incident_wire`/`IncidentStatus::Closed` → `"closed"`).
Evidence: a new test (sibling to R3's, in the same integration layer)
proving this full sequence, with an explicit assertion that at least one
fresh snapshot in the sequence produces zero new `Event`s from the
producer while still driving the recovery candidate toward promotion via
`advance_health_dwell` alone.

**R5 — Regression: `P2-API-002`/`P2-API-003` unaffected.**
Requirement: `assert_p2_api_002_no_new_dbus_surface` and the
`IncidentWire` shape-lock test in `phase2_2b_contract.rs` continue to
pass unmodified — this repair adds no D-Bus member and does not touch
`IncidentWire`'s 7-field shape.
Evidence: the existing tests, unmodified, still green.

## Scope note

Per-source enrichment (`UDisks2` device identity, `logind` inhibitor
detail, `UPower` battery/AC detail, `AccountsService` session specifics)
remains explicitly out of scope, exactly as Gate 2b's own TDD already
states — this repair touches only the generic Availability/Health signal
shape every provider already shares.
