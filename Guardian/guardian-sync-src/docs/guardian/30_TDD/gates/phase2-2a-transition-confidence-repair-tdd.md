---
title: "Gate 2a Transition-Confidence Repair TDD — reopened P2-COR-003 (confidence only)"
kind: "reopened-gate-repair-tdd"
status: "active"
last_reviewed: "2026-09-07"
---
# Gate 2a Transition-Confidence Repair TDD

Governing manifest:
`docs/guardian/30_TDD/gates/phase2-2a-transition-confidence-repair-manifest.toml`.

Full context (not to be re-derived here):
`GUARDIAN_PHASE2_IMPLEMENTATION_HANDOFF.md` §4.2 (provider health/
availability transition → incident — the normative source of the
confidence rule this repair corrects); `AGENTS.md` "Safety rules" ("Do
not convert UNKNOWN into HEALTHY"); the already-accepted first Gate 2a
repair's TDD (`docs/guardian/30_TDD/gates/
phase2-2a-health-lifecycle-repair-tdd.md`) for the fresh-observation
promotion mechanics and target-state classification table this repair
does not reopen. This file states required behavior and acceptance
evidence only — not an implementation tutorial.

**This is a second, separate reopening of Gate 2a, narrower than the
first.** `P2-COR-003` (debounced `Available→Unavailable` provider-health
incident behavior) is reopened again, specifically for *how its opened
incident's `Confidence` is computed* — `P2-COR-003`'s own behavior
(debounced transition into `Unavailable` opens exactly one incident) is
otherwise unchanged. `P2-COR-004` (flapping faster than dwell produces no
thrashing) is **not** reopened; it remains closed, and this repair's
diff must not change its observable behavior — its existing tests are
regression-only evidence in this repair, not requirements being
rewritten. **Confidence itself owns no dedicated `P2-*` ID.** It is
governed directly by binding §4.2's text, quoted exactly below; this
repair corrects Gate 2a's implementation against that binding text, it
does not invent a new normative ID or a new gate to hold it.

## The defect (why this gate is reopened a second time)

`crates/guardian-core/src/correlation.rs`'s `health_direction(availability:
Availability, health: Health) -> Option<HealthDirection>` derives
`Confidence` from the **destination** `(Availability, Health)` pair
alone — its signature carries no "from" state at all:

```
Availability::Unavailable => Some(HealthDirection::Bad(Confidence::Confirmed))
Availability::Degraded    => Some(HealthDirection::Bad(Confidence::Unknown))
Availability::Available, Health::Warning => Some(HealthDirection::Bad(Confidence::Probable))
```

Binding §4.2, quoted exactly:

> **Confidence**: `Confirmed` for `Available→Unavailable` (a direct
> provider-reported state); `Probable` for `Healthy→Warning` (providers
> may report `Warning` heuristically themselves); `Unknown` health never
> promotes to a confident incident by itself.

§4.2 names **transitions** (`Available→Unavailable`, `Healthy→Warning`),
not destination values. Confirmed independently by reading the current
code and the existing test suite (`crates/guardian-core/tests/
correlation_contract.rs` lines ~886-982): a fresh debounce candidate that
resolves to `Availability::Degraded` (regardless of what it was before)
opens at `Confidence::Unknown`; one that resolves to `Available +
Warning` opens at `Confidence::Probable`; one that resolves to
`Unavailable` opens at `Confidence::Confirmed` — every case keyed
entirely off the destination classification, never off any prior state.

Because destination alone decides confidence today, these concrete
transitions incorrectly inherit a tier §4.2 never authorized for them:

| Transition | Today's (wrong) confidence | Why it is wrong |
|---|---|---|
| `Degraded → Unavailable` | `Confirmed` | §4.2 names `Available→Unavailable` specifically as `Confirmed` (a direct provider-reported state change from a known-good baseline); a capability that was already `Degraded` and becomes `Unavailable` is not the transition §4.2 describes. Confirmed by reading `HealthTransitionProducer::observe` (`crates/guardian-core/src/providers/health.rs`): it skips emitting any `Event` on its very first baseline snapshot ("the very first snapshot ever observed establishes the baseline only... no event is produced"), so a non-`Available` baseline is structurally invisible to the correlation engine — nothing in the real pipeline today records that the capability was ever `Degraded` before it went `Unavailable`. |
| `Unknown → Unavailable` | `Confirmed` | Same mechanism: the producer's baseline-seeding skip means an `Unknown`-availability baseline is invisible; the engine cannot distinguish this from a genuine `Available→Unavailable` transition today, and wrongly assigns the same `Confirmed` tier §4.2 reserves for the latter. |
| `Error → Warning` | `Probable` | §4.2 names `Healthy→Warning` specifically as `Probable`. Confirmed by reading `classify()`: the current producer never emits a `health_to` attribute at all (`crates/guardian-core/src/providers/health.rs`'s `transition_event` sets only `HEALTH_AVAILABILITY_TO_ATTR`), and `Available + Error` classifies to `None`/unresolved under `health_direction()` — so there is no debounce candidate carrying any trace of the true `Error` prior state. The next real `Available + Warning` observation therefore opens a **fresh** candidate exactly as if the capability had been `Healthy` immediately before, inheriting `Probable` it was never earned. |
| `Degraded → Warning` | `Probable` | Same mechanism as `Error → Warning`: `Degraded` availability with any `Health` classifies `Bad(Confidence::Unknown)` under the state table, so a `Degraded`-then-`Available+Warning` sequence loses the `Degraded` prior state the same way, and the resulting `Available + Warning` candidate opens at `Probable` with no transition-level justification. |

## Requirements

**R1 — Transition confidence is derived from complete four-field
provenance, not destination alone.**
Requirement: a real health-transition event's confidence is computed
from `availability_from`, `availability_to`, `health_from`, `health_to`
together, with exactly this assignment:

```
availability_from == Available && availability_to == Unavailable  => Confidence::Confirmed
health_from == Healthy && health_to == Warning                    => Confidence::Probable
any other actionable transition                                   => Confidence::Unknown
```

No confidence tier is inferred from `availability_to`/`health_to` alone.
This is the exact §4.2 rule, applied at the transition level instead of
the destination level. The exact Rust helper/API shape (a new function
signature, a struct carrying all four fields, or an extension of
`health_direction`'s own signature) is an implementation-time decision,
not fixed by this contract — only the assignment rule and the structural
separation (R2) are normative.
Evidence: focused Layer-1 tests (see "Required acceptance evidence"
below) proving the assignment table, including the four counterexample
transitions in the defect table above resolving to `Confidence::Unknown`
under the corrected rule.

**R2 — State-vs-confidence separation remains structural, not
re-merged.**
Requirement: current-state classification (is this destination `Good`,
`Bad`, or unresolved?) stays completely unchanged from the already-
accepted first Gate 2a repair and structurally separate from confidence
derivation — two different functions of two different inputs (a
destination pair for state; a from/to quadruple for confidence), not one
function doing both. This repair must not alter the state table below in
any way; restated here only for reference, not as new work:

```
Unavailable                  -> Bad
Degraded                     -> Bad
Available + Warning          -> Bad
Available + Healthy          -> Good
Available + Error/Stale/etc. -> unresolved (already governed, unchanged)
Unknown/Unsupported          -> non-promoting (unchanged)
```

Evidence: a regression test (or explicit code-reading citation in the
completion report) confirming `health_direction`'s destination-only
classification table is byte-for-byte the same as the first repair left
it — only the `Confidence` value threaded through `HealthDirection::
Bad(Confidence)` changes source, not the `Good`/`Bad`/`None` decision
itself.

**R3 — Missing or incomplete "from" provenance never defaults to
`Available`/`Healthy`.**
Requirement: when `availability_from` and/or `health_from` are absent,
malformed, or otherwise unavailable for a given transition, the
resulting confidence must be `Confidence::Unknown` — never silently
assumed to be `Available`/`Healthy` (which would manufacture a
`Confirmed`/`Probable` tier for provenance that was never actually
observed). This mirrors `AGENTS.md`'s "Do not convert UNKNOWN into
HEALTHY" discipline, applied to provenance completeness rather than to
`Health`/`Availability` values directly.
Evidence: a test presenting incomplete/missing "from" provenance for
both an `Unavailable`-destination and a `Warning`-destination transition,
in each case asserting `Confidence::Unknown` rather than `Confirmed`/
`Probable`.

**R4 — Confidence policy stays owned entirely by Gate 2a's correlation
module.**
Requirement: no wording in this repair licenses `HealthTransitionProducer`
(`crates/guardian-core/src/providers/health.rs`, a Gate 2b file,
forbidden scope here) to make confidence *decisions*. The producer's
future job (Gate 2b's forward requirement, below) is only to **carry**
the four provenance fields on the `Event`, from data it already tracks
internally (`self.previous`) — never to interpret them into a
`Confidence` value itself. Interpretation happens exactly once, inside
`guardian-core`'s correlation module, at the same classification
boundary `health_direction`/`classify` already own.
Evidence: the Contract Collision Table below records this explicitly;
the implementation must not add any `Confidence`-typed return value or
decision branch to `crates/guardian-core/src/providers/health.rs` (out
of `allowed_scope` regardless).

## Fresh-observation path — explicitly NOT reopened

A prior review suggested that Gate 2b's forward wiring might need to
thread a "from" state into `advance_health_dwell()` so that a
fresh-observation-driven promotion could compute transition confidence
the same way an `Event`-driven one does. **That suggestion is incorrect
and must not be carried into this contract.** `FreshHealthObservation`
and `advance_health_dwell()` (both already accepted and committed by the
first Gate 2a repair) are explicitly **out of scope** for this repair —
not merely unmentioned, but a forbidden redesign target:

- Fresh re-observation answers exactly one question: "is this
  capability still (or again) cleanly `Good`/`Bad`/unresolved *right
  now*?" (`FreshHealthObservation::classify`, itself just
  `health_direction` applied to a fresh snapshot pair). It does not, and
  must not be made to, derive transition confidence.
- A pending debounce candidate's confidence is established **once** — at
  the moment the transition `Event` created or most recently reset that
  candidate (inside `admit_health_candidate`, via `HealthDirection::
  Bad(Confidence)`'s payload) — and is preserved unchanged from then on.
  A later fresh observation that matches the candidate's pending
  direction (`advance_health_dwell`) merely proves the resulting state
  persisted long enough to satisfy dwell; it neither reads nor needs to
  reconstruct any "from" state of its own, because the confidence
  decision was already made and stored on the candidate at creation
  time.
- No "from" state needs to be reconstructed or supplied by the
  dwell-advance call itself, now or after Gate 2b's forward repair lands.
  `advance_health_dwell`'s existing signature (`capability_id`,
  `observation: FreshHealthObservation`, `ingress_clock`,
  `ingress_sequence`) is sufficient and is not touched by this repair.

Evidence: `advance_health_dwell` and `FreshHealthObservation` are
byte-for-byte unmodified in this repair's diff (verifiable directly from
`git diff -- crates/guardian-core/src/correlation.rs` at review time);
no new parameter, field, or `Confidence`-carrying variant is added to
either.

## Contract Collision Table (mandatory preflight, built before scope is finalized)

| Requirement | Owner | Module/path | Potential conflict | Contract resolution |
|---|---|---|---|---|
| Transition-specific `Confidence` derivation (R1) | This repair (`P2-COR-003` reopened) | `crates/guardian-core/src/correlation.rs`, at the `health_direction`/`classify` boundary | Could be misread as redesigning `HealthDirection::Bad(Confidence)`, the already-accepted first Gate 2a repair's typed shape | No collision. The enum shape (`Bad(Confidence)`) is unchanged and not reopened; this repair is additive/corrective only to *how the `Confidence` value carried inside it is computed* — from a four-field transition instead of a destination pair. The first repair's own doc comment already anticipates this: "confidence is still decided *here*, at classification time" — this repair keeps that same call site, changes only its inputs. |
| Destination-state classification (`Good`/`Bad`/unresolved` table, R2) | Already-accepted first Gate 2a repair (committed in `0d071e1`) | `crates/guardian-core/src/correlation.rs`, `health_direction` | This repair's four-field confidence rule could be misread as replacing or merging into the state-classification table | No collision. Resolved by keeping the two derivations structurally separate (R2): state classification remains a function of the destination `(Availability, Health)` pair only, confidence becomes a function of the `(from, to)` quadruple — two outputs computed from overlapping but distinct inputs at the same call site, not one merged decision. |
| Fresh-observation dwell advancement (`advance_health_dwell`/`FreshHealthObservation`) | Already-accepted first Gate 2a repair (committed) | `crates/guardian-core/src/correlation.rs` | A prior review's suggestion to thread "from" state into `advance_health_dwell()` for confidence purposes | No collision — that suggestion is rejected outright (see "Fresh-observation path" above) rather than reconciled; confidence is fixed once at candidate-creation time and fresh observation never needs to touch it. This is a scope boundary, not two authoritative requirements actually disagreeing. |
| `P2-COR-004` flapping/no-thrashing behavior | Already-closed, not reopened by this repair | `crates/guardian-core/src/correlation.rs`, `admit_health_candidate`/debounce state machine | This repair's confidence-derivation change touches the same file/functions `P2-COR-004`'s tests exercise | No collision. The confidence-derivation change is confined to computing the `Confidence` payload passed into an already-existing `HealthDirection::Bad(_)` value; it does not alter dwell timing, promotion/rejection/flap-reset logic, or any capacity behavior `P2-COR-004` depends on. Required evidence explicitly reruns `P2-COR-004`'s existing tests unmodified as regression proof. |
| Real `Event` four-field provenance (`availability_from`/`availability_to`/`health_from`/`health_to`) | Gate 2b's forward repair (not this task) | `crates/guardian-core/src/providers/health.rs` (`HealthTransitionProducer`) | This repair's R1 requires "from" provenance to exist somewhere for real production transitions to be classified correctly, which could be misread as requiring producer changes now | No collision. This repair's own Layer-1 tests supply four-field provenance directly (test-constructed `Event`s or a test-facing API), exactly as Gate 2a's existing tests already synthesize `Health` attributes ahead of the real producer emitting them (see the first repair's TDD: "Gate 2a proves the correlation *rule*, not either real producer"). Actually wiring the real producer to emit `availability_from`/`health_from` is explicitly Gate 2b's forward work, recorded below and left in `forbidden_scope` here. |
| Confidence-decision ownership | This repair (`guardian-core`'s correlation module only) | `crates/guardian-core/src/providers/health.rs` vs. `crates/guardian-core/src/correlation.rs` | Gate 2b's forward work (carrying provenance) could be conflated with deciding confidence, duplicating or fragmenting the rule across two crates | No collision, resolved explicitly by R4: the producer only ever carries typed provenance fields on the `Event`; it never returns or decides a `Confidence` value. All interpretation stays in `guardian-core`'s correlation module, at one call site. |

**Binding rule check:** no row above surfaces two authoritative
requirements assigning genuinely incompatible ownership, privilege,
lifecycle, module, or gate responsibility. Each apparent tension resolves
to either "additive, not a redesign" or "explicitly out of this repair's
scope, recorded as a forward pointer." No STOP is triggered.

## Downstream / not implemented here: Gate 2b forward requirement

After this Gate 2a repair is accepted and committed, Gate 2b's separate,
already-parked envelope (`docs/guardian/30_TDD/gates/
phase2-2b-health-lifecycle-integration-repair-manifest.toml`/`-tdd.md`,
currently blocked, untouched by this task) must be updated so that
`HealthTransitionProducer` (`crates/guardian-core/src/providers/
health.rs`) emits all four real transition-provenance attributes —
`availability_from`, `availability_to`, `health_from`, `health_to` — on
its transition `Event`, sourced entirely from data it already holds
internally (`self.previous`/the current snapshot being diffed against
it). This requires **no new provider I/O**: the producer already tracks
the prior snapshot per `capability_id` (confirmed by reading
`HealthTransitionProducer::observe` — `self.previous` is compared
directly against `current_state` on every call), it simply does not yet
place the "from" half of that comparison onto the emitted `Event`.

Gate 2b's forward repair remains responsible for: producer provenance
(this item); the daemon's fresh-snapshot-driven dwell-advancement wiring
into `capability_registry_tick`; replacing `P2-API-001`'s synthetic
cloned-second-event test fixture with one driving the real production
sequence; and symmetric recovery integration. Gate 2b's forward repair is
explicitly **not** responsible for confidence policy — the assignment
rule in R1 above stays owned entirely by this Gate 2a repair and is not
re-derived, re-decided, or duplicated in Gate 2b's own envelope.

This Gate 2b repair's own manifest/TDD updates are not written in this
task — this section exists only so the requirement is not lost.

## Required acceptance evidence

Focused Layer-1 tests (to be written at implementation time, not fixed
here) proving at minimum:

```
Available -> Unavailable -> Confirmed
Degraded  -> Unavailable -> Unknown
Unknown   -> Unavailable -> Unknown

Healthy -> Warning       -> Probable
Error   -> Warning       -> Unknown

missing/incomplete from-provenance -> Unknown confidence (never defaulted to Available/Healthy)
```

Also required:

- Evidence that destination-state classification behavior itself
  (`Good`/`Bad`/unresolved) is unchanged by this repair — a regression
  concern, not new work (R2).
- Evidence that the already-accepted fresh-observation/dwell mechanics
  (`advance_health_dwell`, `FreshHealthObservation`) remain completely
  untouched/unmodified by this repair's diff.
- Evidence that `P2-COR-004`'s existing tests remain green, unmodified
  (regression-only, per the reopened-ownership section above).
- Evidence that the full set of Gate 2a normative IDs — the original 19
  plus the tests added by the already-accepted first Gate 2a repair —
  remain green.

## Not bound by this TDD: the exact typed API

This TDD does not fix the exact Rust shape that carries four-field
transition provenance into the confidence decision (a new function
parameter list, a small provenance struct, an extension of
`Classification::Health`, or something else). The requirements above are
semantic (the assignment rule, the structural separation, the
missing-provenance default) — the exact typed shape is an
implementation-time decision, to be made when this repair is actually
coded, consistent with how the first Gate 2a repair's TDD left its own
typed API open.
