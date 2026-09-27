---
title: "Gate 2a Health-Lifecycle Repair TDD — reopened P2-COR-003/P2-COR-004"
kind: "reopened-gate-repair-tdd"
status: "active"
last_reviewed: "2026-09-07"
---
# Gate 2a Health-Lifecycle Repair TDD

Governing manifest:
`docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-manifest.toml`.

Full context (not to be re-derived here): `GUARDIAN_PHASE2_IMPLEMENTATION_HANDOFF.md`
§4.2 (provider health/availability transition → incident), §6 (ingress
order), §7 (bounded structures); `AGENTS.md` "Safety rules"; TDD contract
§51. This file states required behavior and acceptance evidence only —
not an implementation tutorial, not repeated safety doctrine.

**This is a repair of two already-closed, already-normative IDs, not a
new gate.** `P2-COR-003` and `P2-COR-004` remain exactly what they were
(debounced Available→Unavailable opens exactly one incident; flapping
faster than dwell produces no thrashing) — what changes is *how* their
own passing tests are allowed to prove that, and a correction to
`health_direction()`'s classification that both IDs' tests exercise
without currently noticing is wrong. All other 17 Gate 2a IDs are
unaffected and must keep passing unmodified.

## The defect (why this gate is reopened)

Gate 2a's own committed tests for `P2-COR-003`/`P2-COR-004`
(`crates/guardian-core/tests/correlation_contract.rs`) construct two
separate synthetic `Event`s by hand to drive a pending debounce candidate
past `health_min_dwell` — see `p2_cor_003_debounced_available_to_unavailable_opens_exactly_one_incident`,
which admits `evt-h1` then a second, independently-constructed `evt-h2`.
This passes today, but it does not prove the real pipeline can do the
same thing, and it cannot: the real production event source
(`crates/guardian-core/src/providers/health.rs`'s
`HealthTransitionProducer::observe`) is edge-triggered — "emits one
`Event` per `capability_id` whose `Health` or `Availability` changed"
(its own module doc), and "an unchanged pair emits nothing." A capability
that goes bad once and then *stays* bad produces exactly one `Event`,
never a second. Gate 2b's own Layer-2 test
(`crates/guardian-daemon/tests/phase2_2b_contract.rs`,
`build_engine_with_one_real_open_incident`) proves this concretely: after
admitting the one real `Event` the producer emits, it clones that event
and mutates `second_event.event_id` to fabricate a fake "second" `Event`
so the engine's admit-twice requirement is satisfied. No real
`capability_registry_tick` sequence ever produces that second `Event`.
The real pipeline therefore cannot open (or, symmetrically, close) a
provider-health incident at all today — `CorrelationEngine::
admit_health_candidate`/`admit_health_with_open_incident`
(`crates/guardian-core/src/correlation.rs`) require re-admitting the
*key* past `health_min_dwell`, and today the only way to do that is a
second `Event`, which production never generates.

A second, independent defect in the same area:
`crates/guardian-core/src/correlation.rs`'s `health_direction()` maps
`Availability::Available` unconditionally to `HealthDirection::Good`,
regardless of `Health`, and does not consult `Health` at all (`classify()`
never reads a `Health` attribute off the `Event`). `Available + Error` is
today actively misclassified as `Good` — not merely uninterpretable, but
wrong in the recovery-favorable direction.

## Requirements

**R1 — Fresh observation, not a second Event, advances dwell.**
Requirement: a pending debounce candidate (`DebounceCandidate`) may
advance past `health_min_dwell` and promote (open or close an incident)
on a fresh, successful re-observation of the specific capability's
current state — not merely because a second `Event` happened to arrive,
and not merely because wall-clock time elapsed with no fresh observation
of that capability at all. The producer's existing edge-triggered
behavior (one `Event` per real state change, nothing on an unchanged
pair) does not change; this repair adds a path for the *engine* to
consult a fresh snapshot/observation directly, independent of whether a
new `Event` was produced for it.
Evidence (`P2-COR-003`, repaired): a test drives the real production
shape — one real transition `Event` (as `HealthTransitionProducer`
actually emits it) opens no incident yet (`DebouncePending`), then a
later fresh re-observation showing the same capability still in the bad
state (with no second `Event` manufactured or cloned) advances the
candidate past dwell and opens exactly one `Incident`. A further
`Bad` `Event` or fresh bad re-observation links to the same incident,
never a second one.

**R2 — No fresh observation means no promotion from wall time alone.**
Requirement: promotion is tied to an actual fresh re-observation of the
specific capability, never to a background clock advancing on its own.
A pending candidate with no fresh re-observation supplied must not
promote merely because `health_min_dwell` has elapsed in wall/ingress
time.
Evidence: a test constructs a pending candidate, advances `Instant` time
well past `health_min_dwell` with no fresh observation call for that
capability, and asserts the candidate has not promoted (still
`DebouncePending`/no incident opened or closed).

**R3 — Unknown/absent/unclassifiable never falsely advances Good or
Bad.**
Requirement: on a given fresh snapshot, a pending candidate whose
capability is not cleanly reobserved as either fully `Good`
(`Available`+`Healthy`) or fully `Bad` (see the state table below) must
not be silently pushed toward either outcome. This covers: the
capability being absent from the snapshot entirely; an `Unknown`
`Availability` or `Unknown` `Health`; and any other state this repair's
state table does not resolve (see `Health::Stale`, below).
Evidence: a test presents a fresh snapshot where the pending capability
is (a) absent, (b) `Availability::Unknown`, and (c) `Health::Unknown`,
in each case asserting the candidate neither promotes nor is silently
discarded/corrupted — it remains pending, unresolved, exactly as before
the fresh observation.

**R4 — `health_direction()` uses both `Availability` and `Health`.**
Requirement: classification of a fresh observation (or a transition
`Event` that carries both dimensions once Gate 2b's own downstream
repair adds them — see "Downstream Gate 2b repair" below) never treats
`Availability::Available` alone as `Good` regardless of `Health`. Per
the "Target-state classification vs. incident confidence" section below:
`Available + Warning` classifies `Bad`/actionable (a governed transition);
`Available + Error` classifies as **unresolved/non-promoting — explicitly
not `Good`, and not assumed `Bad` either**, since no existing §4.2 rule
authorizes treating it as incident-worthy. This repair changes
`health_direction()`'s signature/logic to accept both dimensions; Gate
2a's *own* tests (which today construct `Event`s carrying only an
`Availability` wire token) are updated to exercise both dimensions where
the corrected behavior requires it, but this does not require or depend
on Gate 2b's separate Event-shape repair (recorded below) to land first —
Gate 2a's own test fixtures can carry a `Health` attribute even before
the real production producer does, exactly as
`crates/guardian-core/tests/correlation_contract.rs` already synthesizes
`Event`s shaped like, but not identical to, whatever producer eventually
exists (module doc: "Gate 2a proves the correlation *rule*, not either
real producer").
Evidence: a test exercises `Available + Healthy` → `Good`,
`Available + Warning` → `Bad`, and `Available + Error` → neither `Good`
nor a false `Bad`/incident-open (i.e. it must not silently classify as
`Good`, which is the regression this repair closes, and must not be
asserted `Bad` either, since that would itself be an invented
classification this repair explicitly declines to make).

**R5 — Symmetric recovery/closure.**
Requirement: the recovery/closure side is handled symmetrically to the
opening side. A capability that flips bad→good once and then stays good
must be able to close its pending incident on a later fresh
re-observation — exactly mirroring R1's opening case, not a
separately-discovered second gap. `admit_health_with_open_incident`'s
existing `Good`-direction debounce-and-close path is the closure
counterpart to `admit_health_candidate`'s `Bad`-direction open path;
both must support fresh-observation-driven advancement, not just
Event-driven advancement.
Evidence (`P2-COR-003`'s closure counterpart): after an incident is
open (via R1's repaired opening path), a fresh re-observation showing
the capability has returned to `Good` and stayed there advances the
pending recovery candidate past `health_min_dwell` and closes exactly
one `Incident` — again with no second `Event` manufactured.

**R6 — Flapping regression, repaired semantics.**
Requirement (`P2-COR-004`, repaired): flapping faster than dwell must
still never open or close an incident, under the corrected
fresh-observation-driven promotion path — not only under the old
two-synthetic-Event path.
Evidence: the existing flap test's scenario (alternating states every
100ms against a 500ms dwell) is re-expressed (or extended) to drive
promotion via fresh re-observations rather than solely via distinct
`Event`s, and still asserts zero incidents opened.

**R7 — Regression: all 19 Gate 2a IDs still pass, and the existing
Event-driven dwell path remains valid alongside the new
fresh-observation path.**
Requirement: this repair does not change the observable behavior of the
other 17 Gate 2a normative IDs (`P2-EVT-001..004`, `P2-COR-001/002/005/
006/007`, `P2-INC-002..004`, `P2-REC-001..005`). Their existing tests in
`crates/guardian-core/tests/correlation_contract.rs` continue to pass
unmodified in their own right. Explicitly: R1/R5's new fresh-observation
advancement path is *additive* — a second, genuinely distinct `Bad`/`Good`
`Event` arriving for the same candidate (real flapping, or any test that
constructs one) must still promote/close exactly as it does today. The
implementer must not remove or weaken Event-driven promotion when adding
the fresh-observation path; the two paths coexist, and other IDs' tests
(and any future real flapping scenario) continue to rely on the
Event-driven one.
Evidence: full `correlation_contract.rs` suite run, all pre-existing
tests for the 17 non-reopened IDs green, with no test for those IDs
edited as part of this repair; plus one explicit regression test
confirming a second real `Bad` `Event` (not a fresh-observation call)
still promotes a pending candidate exactly as before this repair.

## Not bound by this TDD: the exact typed API

This TDD deliberately does **not** bind the repair to
`advance_health_dwell(still_bad: HashSet<CapabilityId>, observed_at:
Instant)`, a shape a prior adjudication pass proposed and which this
repair's own discovery of the symmetric recovery requirement (R5) found
insufficient: that signature can prove "still `Bad`" but cannot
distinguish "still `Good`" from "`Degraded`" from "`Unknown`" from
"absent from this snapshot" for a *pending recovery* candidate — exactly
the ambiguity R3 requires be preserved as non-promoting rather than
resolved by assumption. The requirements above are semantic
(observable engine behavior); the exact typed shape of whatever method(s)
`CorrelationEngine` exposes to accept a fresh observation is an
implementation-time decision, to be made when this repair is actually
coded, not fixed here.

## Target-state classification vs. incident confidence — kept as two separate concepts

An earlier version of this repair TDD's classification table conflated
*current-state classification* (is this state Good, Bad, or unresolved?)
with *incident confidence* (how certain is Guardian about the incident it
opens?), and in doing so assigned `Probable`/`Confirmed` confidence tiers
to two states (`Available`+`Error`, `Degraded`+`Error`) that §4.2 does
not actually specify a tier for. Independent review correctly rejected
this as invented policy dressed as citation — §4.2 names specific
**transitions** (`Available→Unavailable`, `Healthy→Warning`), not a
universal mapping from target `Availability`/`Health` values to a
confidence tier, and confidence is a property of the evidence path that
produced an incident, not merely of the destination state it landed on.

This repair therefore keeps the two concepts separate, exactly as
Guardian's own model already permits: `Confidence` has an explicit
`Unknown` variant precisely so a legitimately-opened incident can honestly
represent "we do not have a governed confidence tier for this," rather
than the alternative — silently promoting the *state's* classification into
a *confidence* claim §4.2 never made.

### Current-state classification (grounded only in §4.2's incident
creation/update rule, quoted exactly)

> a debounced transition into `Unavailable`, `Error`, or sustained
> `Degraded` opens or updates one incident per `capability_id`; a
> debounced transition back to `Available`/`Healthy` updates it toward
> closure.

| `Availability` | `Health` | Classification |
|---|---|---|
| `Available` | `Healthy` | Good |
| `Available` | `Warning` | Bad / actionable — `Healthy→Warning` is a named, governed transition |
| `Available` | `Error` | **Unresolved / non-promoting.** Not `Good` — this is the exact regression this repair closes (today `health_direction()` returns `Good` here, which is actively wrong). But no existing §4.2 text authorizes classifying this as `Bad`/incident-worthy either; §4.2 only ever discusses `Error`/`Warning` in combination with a change in `Availability` itself (`Available→Unavailable`) or as the governed `Healthy→Warning` case, never as an `Error` `Health` value coexisting with an unchanged `Available` `Availability`. This repair fixes the bug (never `Good`) without inventing a further classification decision; whether this state should later become incident-worthy is an explicit future policy decision, not decided here. |
| `Degraded` | any | Bad / actionable, after governed dwell — §4.2's creation rule names "sustained `Degraded`" directly, alongside `Unavailable`/`Error`, as incident-worthy |
| `Unavailable` | any | Bad / actionable — §4.2: "a debounced transition into `Unavailable`..."; confirmed already-true today in `health_direction()`'s current code |
| `Unknown` (either dimension) | — | Non-promoting. Per `AGENTS.md` "Safety rules," line 120: "Do not convert UNKNOWN into HEALTHY." §4.2 restates this explicitly for confidence too (see below), and the same discipline governs state classification: `Unknown` is never treated as `Good` or `Bad`. |
| `Unsupported` | — | Non-promoting — not addressed by §4.2's table; treated the same as `Unknown`/`Stale`: unresolved, not assigned a classification by assumption. |
| any | `Stale` (where no stronger governed `Availability` state already decides it) | Non-promoting. `Health::Stale` is a real governed enum variant (`crates/guardian-provider-api/src/capability.rs`) with no existing governed disposition in the accepted Phase 2 contract for *this* purpose. (§4.2 separately discusses `Stale→refreshed` as itself a correlatable *source event* for a different concern — snapshot-staleness detection, not target-state classification — and does not contradict or resolve this row; checked, not missed.) Falls under R3's "not cleanly reobserved as either fully Good or fully Bad" rule. |

### Incident confidence (grounded only in §4.2's confidence rule, quoted
exactly — a property of the transition/evidence path, not the destination
state alone)

> **Confidence**: `Confirmed` for `Available→Unavailable` (a direct
> provider-reported state); `Probable` for `Healthy→Warning` (providers
> may report `Warning` heuristically themselves); `Unknown` health never
> promotes to a confident incident by itself (AGENTS.md: "Do not convert
> UNKNOWN into HEALTHY" — the same discipline applies to not converting
> `Unknown` into a confident incident).

| Transition / evidence path | Confidence |
|---|---|
| `Available` → `Unavailable` | `Confirmed` — the exact transition §4.2 names |
| `Healthy` → `Warning` | `Probable` — the exact transition §4.2 names |
| Sustained `Degraded` (opens/updates per the state table above) | `Confidence::Unknown` — §4.2's creation rule says `Degraded` is incident-worthy, but its own confidence rule assigns no tier to it. Rather than inventing one by analogy to `Confirmed`, this repair uses the model's existing `Confidence::Unknown` variant to represent "a real incident, honestly uncertain confidence" — not "no incident" and not a fabricated certainty. |
| Any other transition/state without an explicit §4.2 rule | `Confidence::Unknown` — no invented tier. If a future gate wants a governed tier for a currently-`Unknown` case, that is an explicit policy decision for that gate, not an inference this repair makes. |

This resolves cleanly against the Gate 2c VM evidence already found: a
real UPower `mask` transition (`Available/Healthy → Degraded/Error`) is
incident-worthy per the state table (sustained `Degraded`), opens after
dwell, and is honestly recorded at `Confidence::Unknown` — not silently
promoted to `Confirmed`, which §4.2 never authorized for this case.

## Downstream Gate 2b repair (forward pointer only — NOT implemented here)

After this Gate 2a repair is accepted and committed, Gate 2b requires
its own separate, narrow repair. Recorded here so it is not lost, not
implemented in this pass:

1. **Complete target-state provenance on the `Event`.** The
   health-transition `Event` (`crates/guardian-core/src/providers/
   health.rs`'s `transition_event`) currently carries only
   `HEALTH_AVAILABILITY_TO_ATTR` (the target `Availability` wire token).
   It must carry both `Availability` and `Health` so a real production
   `Event` can be classified against the table above without relying
   solely on fresh-snapshot re-observation to supply the `Health`
   dimension.
2. **Wire the daemon's fresh-snapshot-driven dwell-advance call.**
   `crates/guardian-daemon/src/bin/guardian-daemon.rs`'s
   `capability_registry_tick` currently only feeds
   `HealthTransitionProducer::observe`'s output `Event`s through
   `admit_event`; it must also call whatever fresh-observation-advance
   entry point this Gate 2a repair adds to `CorrelationEngine`, once per
   tick, using the same snapshot already collected.
3. **Replace `P2-API-001`'s synthetic cloned-second-event test fixture.**
   `crates/guardian-daemon/tests/phase2_2b_contract.rs`'s
   `build_engine_with_one_real_open_incident` must be replaced with a
   fixture that drives the real production sequence: baseline snapshot →
   real bad transition (one real `Event`) → `DebouncePending` → a later
   unchanged-bad fresh snapshot with no second `Event` produced →
   advance from that real snapshot → real `Incident` opens →
   `ListIncidents` returns it — and symmetrically for recovery (a later
   unchanged-good fresh snapshot advances a pending recovery candidate
   and closes the incident, again with no second `Event` produced).

This Gate 2b repair's own manifest/TDD are not written in this task.
