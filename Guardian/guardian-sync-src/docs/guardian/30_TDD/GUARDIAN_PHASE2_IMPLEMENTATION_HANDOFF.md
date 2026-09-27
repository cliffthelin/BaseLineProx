# Guardian TDD-contract Phase 2 Implementation Handoff
## Read-Only Observability & Correlation — Planning Pass

Status: **Planning only.** No production Rust in this pass. Governed by
`GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §47 (original authorization) and
§51 (this pass's scope amendment, added alongside §47/§50, neither of
which it alters). Published baseline for this planning pass:
`HEAD`/`origin/main` = `1423d9c3053394e19e461ee6adea31bea9231fa7`, tag
`wave1-first-production-mutation`. G0–G9 and Wave 1 remain closed,
unmodified, and are not re-derived here.

**Repair pass, 2026-09-05.** An independent review of the original
version of this document, verified against real production source
(`crates/guardian-daemon/src/bin/guardian-daemon.rs`,
`crates/guardian-core/src/{providers/psi,incident}.rs`,
`crates/guardian-daemon/src/dbus_surface.rs`,
`crates/guardian-client/src/lib.rs`, `docs/evidence/g3/G3_MILESTONE.md`,
`docs/evidence/g4/G4_MILESTONE.md`, `docs/evidence/g5/G5_MILESTONE.md`),
found two blocking defects (an unsound `timestamp_monotonic`-based
correlation-ordering model; a self-contradictory, NB-3-reopening
incident-severity/wire proposal) and three non-blocking gaps (an
unspecified debounce-ring eviction policy; ungate-qualified FC-N
citations; an understated provider-health scope-honesty claim). All five
are corrected throughout this document; §51 of the TDD contract records
the same corrections as binding architectural decisions.

**Second repair pass, 2026-09-05.** A second, comprehensive combined
architecture-and-scope review found the planning almost entirely sound
but returned one blocking verdict — `FAIL — DEBOUNCE CAPACITY SEMANTICS
UNSAFE` — because the first repair pass's `CapacityRejected`
observability text was an unresolved disjunction whose "emit it as a
Guardian event" branch was never checked for recursive overflow back
into `CorrelationIngress`. That defect is now closed with a single,
non-disjunctive mechanism (§7, §18, `P2-REC-003`/`P2-REC-005`, §19). The
same review also found five cheap, non-blocking items, all fixed in this
pass: the §4.1/§18 window-duration-vs-`ingress_sequence` wording
inconsistency; the unstated `Instant`-construction test technique (now
§6a); a flat §20 file list restructured into an internal Gate 2a/2b/2c
decomposition; an implicit generic-vs-per-source enrichment boundary
(now explicit, §13); and a missing `IncidentWire` wire-shape regression
test requirement (`P2-API-003`). Nothing already cleared by either prior
review is re-litigated. Every section below reflects the corrected
model — sections are marked "corrected, repair pass," "corrected, second
repair pass," or "revised" inline where the text is materially different
from before.

---

# 1. Mechanically derived scope

§47's own text: "Phase 2 then expands **read-only observability and
correlation** without needing to redesign the privilege/control plane,"
predicated on a stable daemon/API, Capability Registry, Provider
Arbitrator, transaction framework, event/incident model, Diagnostic
Budget, initial providers, client shells, and package/install
foundation. All nine of those §47 planning inputs are independently
verified present and accepted (grep/read evidence below) — no governance
conflict exists between §47 and any other governing document.

| Capability/family | Source | In scope? | Read-only? | Existing foundation | Missing work |
|---|---|---|---|---|---|
| Event normalization/ordering | G3 (`crates/guardian-core/src/event.rs`); TDD §17 | Reused, not re-derived | Yes | `Event`, `normalize_key`, `sort_by_monotonic_order` — production types, no producer gap | None; Phase 2 only consumes these |
| Incident envelope | G3 (`crates/guardian-core/src/incident.rs`); TDD §18 | In scope (correlation *produces* these) | Yes | `Incident`, `IncidentStatus`, `Confidence`, `link_event`, `set_confidence` — types exist, fully tested, **never constructed by production code** (confirmed: only test/fixture call sites exist workspace-wide) | A correlation engine that constructs/updates real `Incident`s. **Corrected (repair pass):** no `severity` field is added to `Incident` in this phase (severity deferred in full — see §15) and `link_event`'s `(&mut self, event_id: EventId)` signature is genuinely unchanged, not merely claimed unchanged |
| Correlation engine (event→incident grouping) | §47; this planning pass | In scope | Yes | None — no correlation logic exists anywhere in the workspace | New Layer-1 module, `guardian-core::correlation` (name TBD at implementation) |
| PSI events | G5/G8 (`crates/guardian-core/src/psi.rs`, `providers/psi.rs`) | Correlation input, in scope | Yes | Real `/proc/pressure` reads, `ThresholdMonitor`, produces real `Event`s via `poll()` — production-wired since G8 | Correlating these events into incidents (net-new) |
| Provider health/availability transitions | G3 `Availability`/`Health` (`guardian-provider-api/src/capability.rs`); G8 six providers | Correlation input, in scope | Yes | `CapabilityRecord` populated by real G8 provider ticks in `guardian-daemon`'s `capability_registry_tick` | **Corrected (repair pass):** `capability_registry_tick` returns `CapabilityRecord` snapshots only — verified by reading `crates/guardian-daemon/src/bin/guardian-daemon.rs` directly, no `Event` of any kind is produced for provider-health today. This is not "needs detection logic atop an existing event" — it needs a new provider-health transition *`Event` producer* (diffing successive snapshots) in addition to the detection/debounce logic that consumes it |
| `Incidents1` D-Bus surface | G9 (`crates/guardian-daemon/src/dbus_surface.rs`) | In scope — Phase 2 populates it | Yes | Interface, object path, `IncidentWire`, `guardian_client::Incident` all shipped; `list_incidents()` hard-coded to `Vec::new()` | Wire it to the correlation engine's live incident store |
| `Transactions1` D-Bus surface | G9 dbus_surface.rs; Wave 1 helper-private persistence | **Deferred** (§12) | Yes (if pursued) | Interface/wire shape shipped, `TransactionWire` exists; helper-private state under `root:root` is the only real transaction persistence | A typed read bridge is an explicit future architectural decision, not implied by this planning pass |
| Diagnostic Budget Manager | G5 (`crates/guardian-core/src/budget.rs`) | Reused unmodified | Yes | `evaluate`, `evaluate_with_alternatives`, `RecorderPolicy` — pure functions, no correlation concept | Correlation must call `evaluate` before requesting any diagnostic (§16); no budget change needed |
| Flight Recorder | G5 (`crates/guardian-core/src/recorder.rs`) | Reused, bounds respected | Yes | `BoundedRecorder`, count-bounded (G5's FC-1 open), dropped-counter | Phase 2 does not close G5's FC-1; correlation gets its own, separately-bounded working set (§7) |
| journald | G2 privilege inventory | Optional, deferred unless mechanically required | Yes | Classified `no privilege` for reads | Not pulled in unless a concrete correlation rule needs it (none currently does) |
| Capability Registry / Provider Arbitrator | G3 (`crates/guardian-core/src/arbitration.rs`, `registry.rs`) | Reused unmodified | Yes | Stable since G3, exercised in production since G7/G8 | None |
| I/O Guardian, PPD/NM/AccountsService writes, storage power-off, arbitrary provider execution | Master-spec Phase 2; AGENTS.md privilege rules | Out of scope | N/A | N/A | Explicitly excluded per task framing and §51 |

**Correction (repair pass, 2026-09-05).** An independent review found this
pass's original correlation model unsound: it proposed sorting/windowing
events by `timestamp_monotonic`, but `guardian-daemon.rs`'s
`monitoring_tick` sets that field from `now_secs()` (literal wall-clock
seconds-since-epoch) while `providers/psi.rs`'s `event_from_crossing`
sets it from `ThresholdMonitor`'s own per-instance `sequence` counter —
two mutually incomparable domains. See §6 for the corrected
correlation-ingress ordering model, which is now normative for every
section below that references ordering, windowing, or determinism.

No governance conflict was found between §47 and any other document (the
master spec's own "Phase 2 — I/O Guardian" is a different, already-
disambiguated numbering per §50; it does not contradict §47).
**Completion status is therefore not the governance-conflict or
privilege-boundary blocked states** (see §11 below for the one privilege
question this pass could and did resolve, and the one it could not).

---

# 2. Preserving the read-only boundary

This pass introduces, and will introduce at implementation time, no:
new helper write method; new privileged mutation; new systemd mutation
capability; PPD/NetworkManager/AccountsService writes; storage power-off;
I/O Guardian; arbitrary provider execution; new `Guardian1` method. Wave
1's `cups-restart → cups.service → Restart` remains the sole governed
production mutation. Correlation may *observe* Wave 1 transaction
existence only if §12's typed read bridge is separately approved later
— this pass does not approve it, and defers it (see §12).

---

# 3. Existing observability primitive inventory

| Primitive | Exists? | Production caller? | Persisted? | Publicly exposed? | Correlatable? | Phase 2 gap |
|---|---|---|---|---|---|---|
| `Event` | Yes (G3) | Yes — PSI (`providers/psi.rs`), daemon monitoring tick (`guardian-daemon.rs:132`) | No (memory only, via recorder) | No (no `Events1` interface exists or is proposed) | Yes — `normalized_key`, `source_provider` already present. **Corrected (repair pass):** `timestamp_monotonic` is *not* cross-producer comparable (PSI's is a sequence counter, the daemon tick's is wall-clock seconds) — correlation uses the new ingress order (§6), and `timestamp_monotonic` is provenance-only | Needs a consumer that groups them, ordered by ingress, not by `timestamp_monotonic` |
| `Incident` | Yes (G3, type only) | **No** — grep of every non-test/non-fixture call site in the workspace found zero production construction | No | Yes, wire shape only (`Incidents1.ListIncidents()` always empty) | N/A until produced | The producer itself — this phase's core deliverable |
| Correlation chain | No | No | No | No | N/A | Net-new; no prior gate attempted this |
| PSI telemetry/events | Yes (G5 model, G8 wiring) | Yes — real `/proc/pressure` via `poll()` | No | Via `Capabilities1.PsiSummary()` (snapshot only, not event history) | Yes | Needs correlation, not re-implementation |
| Provider health/state (`CapabilityRecord`) | Yes (G3/G8) | Yes — `capability_registry_tick` for six providers | No (recomputed each tick) | Yes — `Capabilities1.ListCapabilities()` | Yes, but only as a snapshot; transitions must be derived by diffing successive ticks | **Corrected (repair pass):** no `Event` of any kind is produced for provider-health today (verified: `capability_registry_tick` returns `Vec<CapabilityRecord>` snapshots only, nothing else) — the gap is producing a transition `Event` from a snapshot diff, not merely "transition-detection logic" atop an event stream that does not exist |
| systemd read provider | Yes (G8, `providers/systemd.rs`) | Yes | No | Via `Capabilities1` | Yes | **REQUIRED FOUNDATION** (generic Availability/Health-transition correlation via the Capability Registry, §4.2/Gate 2b) — no systemd-specific event semantics beyond that are in scope this phase |
| logind | Yes (G8, `providers/logind.rs`) | Yes — `list_blockers()` on `Capabilities1` | No | Yes | Yes (inhibitor changes) | **REQUIRED FOUNDATION**: generic Availability/Health-transition correlation (same as systemd, above). **OPTIONAL FUTURE ENRICHMENT, not part of this Phase 2 gate sequence**: session/inhibitor-lifecycle-specific event semantics (e.g. a distinct incident shape for "inhibitor added" vs. "inhibitor removed" rather than a generic health transition) |
| UDisks2 | Yes (G8, `providers/udisks.rs`) | Yes — `TopologyTracker` | No | Via `Capabilities1` | Yes | **REQUIRED FOUNDATION**: generic Availability/Health-transition correlation (same as systemd, above). **OPTIONAL FUTURE ENRICHMENT, not part of this Phase 2 gate sequence**: device-identity/appearance-disappearance-specific event semantics beyond the existing generic topology-event log line (§ `guardian-daemon.rs`'s `[guardian-daemon] UDisks topology event` line, unchanged by this phase) |
| UPower | Yes (G8, `providers/upower.rs`) | Yes | No | Via `Capabilities1` | Yes | **REQUIRED FOUNDATION**: generic Availability/Health-transition correlation (same as systemd, above). **OPTIONAL FUTURE ENRICHMENT, not part of this Phase 2 gate sequence**: battery/AC-transition-specific event semantics (e.g. distinguishing "on battery" from "AC restored" as named incident kinds rather than a generic health transition) |
| AccountsService | Yes (G8, `providers/accounts.rs`) | Yes | No | Via `Capabilities1` | Yes | **REQUIRED FOUNDATION**: generic Availability/Health-transition correlation (same as systemd, above). **OPTIONAL FUTURE ENRICHMENT, not part of this Phase 2 gate sequence**: session-specific event semantics (e.g. per-account session-list changes as their own correlation input) |
| Transaction/recovery state | Yes (G4), but helper-private | Yes (Wave 1) | Yes — `guardian-helper`'s own schema-versioned store, `root:root`, under `/var/lib/guardian/helper/` | No (no daemon-side read path; forbidden by G9 handoff §6.1) | Not yet — crosses a trust boundary | §12: explicit architectural decision, deferred |
| Diagnostic Budget Manager | Yes (G5) | Not yet wired to any real caller that requests diagnostics | No (pure function) | No | N/A (a gate, not a data source) | Correlation must call it before any diagnostic escalation (§16) |
| Flight Recorder | Yes (G5), and genuinely wired since G7 (`monitoring_tick`) | Yes | No (G5's FC-1/FC-2 open) | No | Partially — it holds `Event`s, but has no query API | Not a correlation *input* directly; correlation should tap the same event stream the recorder taps, not read the recorder itself |
| `RecorderPolicy` | Yes (type), evaluated on a real tick since G7 | Yes (evaluated), but its output (`Normal`/`MemoryFirst`) still drives no real spill/retention sink | No | No | N/A | G5's FC-2 remains open; Phase 2 does not close it |
| Journald operational info | Not read by any Guardian code | No | N/A | No | Classified `no privilege` (G2) but unused | Only pulled in if a concrete rule needs it (none does in this scope) |
| Capability registry state | Yes (G3/G8) | Yes | No (in-memory, `Arc<Mutex<Vec<CapabilityRecord>>>`) | Yes | Yes | None beyond diffing successive snapshots |

**G4-lesson check (module presence ≠ executed contract), applied here**:
`Incident`/`link_event`/`set_confidence` are real, tested types with zero
production call sites — this is the same class of gap G4's audit found
and G5's FC-2 restated ("module presence is not proof the... contract is
executed"). This planning pass names that gap explicitly rather than
treating the type's existence as if it were already a working
correlation system.

---

# 4. Correlation, defined concretely

Derived from repository scope (G8's six providers + G5 PSI + G3
Event/Incident), not adopted uncritically from the task's candidate
list. Three correlation relationships are in scope; a fourth
(transaction→incident) is explicitly deferred per §12.

## 4.1 PSI pressure event → incident

- **Source event(s)**: `Event`s produced by `providers::psi`'s
  `ThresholdMonitor::observe` crossing into `PressureSeverity::Critical`
  for a resource kind (cpu/memory/io).
- **Correlation key**: **Corrected (Gate 2a implementation-repair pass,
  2026-09-06) — original text below was wrong, verified against real
  production source.** This row originally specified `(source_provider =
  ProviderId("psi"), normalized_key)`, reasoning that `normalized_key`
  "already encodes the resource kind per `event::normalize_key`." Reading
  `crates/guardian-core/src/providers/psi.rs`'s actual `event_from_crossing`
  directly shows this is false: `normalized_key` is derived from
  `format!("PSI {resource} threshold crossing {:?}->{:?}", crossing.from,
  crossing.to)`, passed through `normalize_key` (a pure lowercase/
  whitespace-collapse transform that does **not** strip the `{from}->{to}`
  transition text). Two legitimate Critical-crossing events for the
  *same* resource but *different* transitions therefore get *different*
  `normalized_key` values and would not correlate under the original
  wording — a real defect, not a paraphrase issue. `resource_refs[0]`
  (`format!("/proc/pressure/{resource}")`) is the actual stable resource
  identity, unaffected by transition text. **Corrected rule, binding:**
  PSI events for the same source/resource correlate by `(source_provider
  = ProviderId("psi"), resource_refs.first())` — the stable PSI resource
  identity — even when their transition-description text differs.
  `normalized_key` remains G3 `Event`/`normalize_key` provenance exactly
  as originally defined for other purposes (e.g. display, dedup-by-text
  where that is what is wanted elsewhere); this correction only replaces
  the *Phase 2 correlation-rule* text that incorrectly cited it, and does
  not touch G3's `Event`/`normalize_key` semantics themselves. Gate 2a's
  committed, tested implementation (`crates/guardian-core/src/
  correlation.rs`) already correlates by `resource_refs.first()`, not
  `normalized_key` — this correction brings the contract text into
  agreement with the accepted implementation, not the other way around.
- **Temporal window**: a fixed, configurable debounce window (default
  proposed: 30s, matching the daemon's existing monitoring-tick cadence
  order of magnitude — exact value is an implementation-time decision,
  not fixed here). **Corrected (second repair pass)**: the window is a
  **duration**, measured against `CorrelationIngress`'s `ingress_clock`
  (an `Instant`-based reading, §6) — never the event's own
  `timestamp_monotonic` (PSI's `timestamp_monotonic` is a per-instance
  sequence counter unrelated to wall time and is not usable as a window
  boundary). `ingress_sequence` plays no role in the window measurement
  itself; it exists solely as a tie-breaker for two events that share an
  identical `ingress_clock` `Instant` reading. During this
  `ingress_clock`-duration window, repeated critical readings for the
  same key attach to one open incident rather than opening a new one.
  Tests construct window-boundary placements using the `Instant`-
  construction technique in §6a.
- **Deterministic vs. heuristic**: deterministic — same ordered input
  (severity transitions admitted in the same ingress order) always
  produces the same grouping. PSI's own `timestamp_monotonic` is recorded
  on the resulting incident's evidence as provenance only, never
  consulted for the grouping decision itself.
- **Confidence**: `Confirmed` — PSI crossing a kernel-reported threshold
  is a direct observation, not an inference.
- **Incident creation/update rule**: first `Critical` event for a key
  with no open incident creates one; subsequent `Critical` events for
  the same key within the window call `link_event`.
- **Terminal/closure rule**: incident closes (status → `Closed`) after
  one full window elapses with no further `Critical` event for that key,
  or immediately on the first `Nominal`/`Low` reading for that key
  (recovery), whichever the implementation chooses — this pass requires
  the rule be one of these two, explicitly documented, not both silently
  active.
- **Provenance**: `evidence` field carries the raw PSI line's
  `raw_reference`; `candidate_causes` stays empty (no causal claim).

## 4.2 Provider health/availability transition → incident

- **Source event(s)**: **Corrected (repair pass):** no `Event` exists
  for this today — `capability_registry_tick` (`guardian-daemon.rs`)
  returns `CapabilityRecord` snapshots only. This rule's real source
  event is a *new* provider-health transition `Event`, synthesized by
  diffing two successive `capability_registry_tick` snapshots for the
  same `capability_id` where `Health` or `Availability` differs (e.g.
  `Healthy→Warning`, `Available→Unavailable`, `Unavailable→Available`,
  `Stale→refreshed`/non-`Stale`), and admitted through the same
  correlation-ingress mechanism (§6) as every other event source. This
  is net-new production work, not "detection logic" layered on an
  existing event stream.
- **Correlation key**: `capability_id` (stable per G3 — never
  `provider_id`, which can change independently per
  `CapabilityRecord::with_provider`).
- **Temporal window**: debounce against flapping, measured in **ingress
  order** (§6) — an implementation must not open a new incident on every
  tick if a capability oscillates; a minimum-dwell requirement (N
  consecutive ticks in the new state, or a minimum ingress-clock
  duration) is required before treating a transition as incident-worthy.
  Exact N/duration is an implementation decision; this pass requires the
  debounce exist and be tested (§18), and requires the debounce
  bookkeeping ring follow the reject-not-evict `CapacityRejected` policy
  specified in §7.
- **Deterministic vs. heuristic**: deterministic given a fixed debounce
  policy and ordered (ingress-order) tick history.
- **Confidence**: `Confirmed` for `Available→Unavailable` (a direct
  provider-reported state); `Probable` for `Healthy→Warning` (providers
  may report `Warning` heuristically themselves); `Unknown` health never
  promotes to a confident incident by itself (AGENTS.md: "Do not convert
  UNKNOWN into HEALTHY" — the same discipline applies to not converting
  `Unknown` into a confident incident).
- **Incident creation/update rule**: a debounced transition into
  `Unavailable`, `Error`, or sustained `Degraded` opens or updates one
  incident per `capability_id`; a debounced transition back to
  `Available`/`Healthy` updates it toward closure.
- **Terminal/closure rule**: closes on a debounced recovery transition
  for the same `capability_id`.
- **Provenance**: `primary_resource` = the capability's `provider_id`;
  `evidence` records both `CapabilityRecord` snapshots (before/after)
  by value, not by reference (they are not `Event`s).

## 4.3 PSI pressure ↔ provider degradation (cross-source correlation)

- **Source event(s)**: an open PSI incident (§4.1) and an open
  provider-health incident (§4.2) whose windows overlap.
- **Correlation key**: temporal overlap only — there is no shared
  identity key between a PSI resource kind and a `capability_id`, so
  this rule is explicitly weaker than §4.1/§4.2.
- **Temporal window**: overlap of the two incidents' `[opened_at,
  closed_at)` (or `[opened_at, now)` if still open) intervals, using
  **ingress order** (§6) — never either source producer's own
  `timestamp_monotonic`, which is not comparable across PSI and
  provider-health events.
- **Deterministic vs. heuristic**: heuristic — this pass requires the
  incident's `confidence` be no higher than `Hypothesis` for this
  relationship, and requires the language "correlated with" to be used
  in `summary`/`candidate_causes`, never "caused by" (§14 below).
- **Incident creation/update rule**: does not create a third incident;
  it links the two incidents' IDs into each other's
  `candidate_causes`/`evidence` as text references (both `Incident`
  structs use `Vec<String>` for these fields already — no schema change
  needed) rather than inventing an incident-of-incidents type.
- **Terminal/closure rule**: the cross-reference itself has no separate
  lifecycle; it exists only while both referenced incidents are
  findable, and is not re-verified once either closes.
- **Provenance**: both referenced incident IDs, explicitly labeled as
  temporal association, not causation.

No opaque AI/LLM correlation is introduced; nothing in §47, §50, or §51
requires it, and AGENTS.md's "no placeholders" and "no fake
implementation" rules would otherwise be violated by an unexplainable
scoring model.

---

# 5. Events versus incidents

Using G3's existing models exactly as written (no `EventId`/`IncidentId`
validation change — no real boundary requiring one was found):

- An event remains just an event when no correlation rule (§4.1–§4.3)
  matches it — e.g. a `Nominal` PSI reading, or a capability tick with
  no `Health`/`Availability` change.
- Multiple events become one incident exactly per §4.1/§4.2's creation/
  update rules — never a fixed count; the debounce/window governs it.
- A single sufficiently significant event **can** create an incident:
  the first debounced `Available→Unavailable` transition, or the first
  `Critical` PSI reading for a previously-nominal key, opens an incident
  immediately — G3's `Incident` was never designed to require a
  minimum-N before creation, and this pass finds no reason to add one.
- **Incident identity**: generated by `guardian-core::identifiers`'s
  existing `IncidentId` constructor (unchanged) at creation time; stable
  for the incident's lifetime.
- **New related events attach** via the existing `link_event` method —
  idempotent, already tested, reused unmodified.
- **Incidents close** per each rule's terminal condition (§4.1/§4.2);
  §4.3 cross-references do not have their own closure.
- **Reopening**: `IncidentStatus` has no `Reopened` variant and this pass
  does not add one — a closed incident that sees a new matching event
  after closure is treated as a **new** incident with a fresh
  `IncidentId` that references the prior one's ID in `evidence` (a
  plain-text back-reference, not a new field). This is an explicit
  design decision this pass makes, flagged here rather than left
  implicit, precisely because the task calls out "whether reopening
  exists" as something to resolve rather than assume.
- **Ordering guarantees**: `event_ids` accumulate in the order
  `link_event` is called, which the correlation engine must call in
  **ingress order** (§6's `CorrelationIngress` clock/sequence total
  order) — never wall-clock order, and never each producer's own,
  mutually incomparable `timestamp_monotonic` value.
- **Provenance**: `evidence`/`candidate_causes`/`recommended_actions`
  remain free-text `Vec<String>` exactly as G3 shipped them; this pass
  does not introduce a structured evidence type.

---

# 6. Correlation determinism (corrected, repair pass)

**Original defect, and why it was wrong.** This section originally
specified sorting/windowing by each event's own `timestamp_monotonic`,
citing `event::sort_by_monotonic_order`/`P0-EVT-001`. An independent
review, verified against real production source, found this unsound:
`guardian-daemon.rs`'s `monitoring_tick` sets `timestamp_monotonic` from
`now_secs()` — literal `SystemTime::now()` wall-clock seconds-since-epoch
(can jump backward on NTP correction, which the field's own doc comment
forbids relying on) — while `providers/psi.rs`'s `event_from_crossing`
sets it from `ThresholdMonitor`'s own per-instance `sequence` counter
(starting near 0, unrelated to any clock). These two domains are not
comparable; a merged-stream sort by `timestamp_monotonic` does not
reflect real temporal order across producers. Neither producer is
modified to fix this — both are existing, accepted, unmodified
production code, out of scope for a docs-only repair regardless.

**Corrected model: the `CorrelationIngress` envelope.** The correlation
engine owns a new, single, daemon-owned ingress mechanism, constructed by
`guardian-daemon` at the one point every event source (PSI, the
daemon-tick producer, and the new provider-health producer, §4.2) feeds
into the correlation engine:

```text
CorrelationIngress {
    event: Event,
    ingress_clock: Instant,   // one process-local Instant-based clock
    ingress_sequence: u64,    // strictly increasing, one daemon-owned counter
}
```

(Exact naming is not binding; the semantics are.) `ingress_clock` is
read from a single daemon-owned clock; `ingress_sequence` increments by
exactly one per admitted event, breaking ties when two `Instant` readings
are equal. **All correlation grouping, windowing, and ordering is defined
over `(ingress_clock, ingress_sequence)` — never over any producer's own
`timestamp_monotonic`,** which is retained on the resulting event/
incident evidence as **provenance only** ("what the source claimed") and
is never consulted for a correlation decision. `timestamp_wall` continues
to serve only human-readable `opened_at`/`closed_at` display, exactly as
originally specified.

Same inputs (an ordered sequence of events admitted through
`CorrelationIngress` in a given order) + same policy (fixed debounce
windows, fixed correlation keys) → same incident grouping, every run —
tests control ordering by constructing `CorrelationIngress` values with
explicit `ingress_sequence` values directly (no new time-mocking crate
needed; the real wall-clock `Instant` reading is irrelevant to
determinism because `ingress_sequence` alone total-orders a fixed test
input deterministically).

**§6a. `Instant`-construction test technique (added, second repair
pass).** A second, comprehensive combined review found this document
implied tests can "inject arbitrary `Instant` values" without stating
how, given that `std::time::Instant` has no public "construct from an
arbitrary timestamp" constructor — only `Instant::now()` plus `Duration`
arithmetic. The actual, working technique, binding for every Layer-1
test in this phase that needs deterministic relative event placement
(window-boundary tests, §4.1/§18's "correlation-window boundary" row,
out-of-order/backwards-timestamp tests, and any other test needing
precise relative `Instant` placement): establish one real `base =
Instant::now()` once at test setup, then construct every synthetic
`CorrelationIngress` record's `ingress_clock` as `base +
Duration::from_millis(N)` for forward placement, or
`base.checked_sub(Duration::from_millis(N))` for backwards/reordering
cases, choosing `N` per test to place each record precisely at, just
inside, or just outside a window boundary relative to `base`. This is a
real, working technique in Rust and is named here explicitly so a future
implementer does not have to rediscover it. `ingress_sequence` is
assigned independently by the test to break ties when two constructed
records intentionally share the identical `Instant`; it never encodes
the window measurement itself (see §4.1's window-definition correction,
also second repair pass).

- **Restart-epoch semantics**: `ingress_clock`/`ingress_sequence` are
  process-local and reset on every `guardian-daemon` restart — no
  persistence, consistent with §8/§9's memory-only decision. A restart
  begins a new ingress epoch at sequence 0; ordering guarantees hold only
  within one daemon process lifetime, exactly as incidents themselves do
  not survive a restart (§9).
- **Out-of-order arrival**: the correlation engine applies rules strictly
  in ingress order (assignment order at the single ingestion point) — a
  rule must never see events out of that order, since ingress order is
  assigned at admission, not re-derived afterward. A single delayed event
  admitted after its window has already closed must not reopen a closed
  incident (see §5's reopening rule) — it starts a new one, with
  backreference.
- **Duplicates**: an event with an `EventId` already present in an open
  incident's `event_ids` is a no-op via `link_event`'s existing
  idempotency — no double-counting, no duplicate-detection logic needed
  beyond what G3 already guarantees.
- **Replay**: replaying an identical event log, admitted in the same
  order, against a fresh correlation engine instance must produce
  byte-identical (mod `IncidentId` generation, wall-clock stamps, and the
  real `Instant` value itself — only relative/sequence order is
  normative) incident structure — this is the concrete Layer-1
  acceptance test for determinism (§17), and it is also the test that
  proves ingress order, not raw `timestamp_monotonic`, drives grouping:
  two synthetic events from different fake producers with wildly
  different or backwards raw `timestamp_monotonic` values must still
  group according to their ingress order, not their raw timestamps
  (`P2-EVT-003`, §19).

---

# 7. Bounded memory and diagnostic safety

Phase 2 remains subordinate to G5. **This pass defines three bounded
state classes, not two** — an independent review found the original
draft of this section described a third, unheadlined bounded structure
(debounce bookkeeping) without ever specifying its eviction behavior,
which is corrected below. Concrete numbers remain implementation-time
tuning, not fixed here; the *existence* and *exact policy* of each bound
is required, not optional:

1. **Open-incident cap (bounded map, keyed by correlation key)**: a hard
   cap on open-incident count; when the cap is reached, the
   oldest-by-`opened_at` (ingress order, §6) open incident is
   force-closed (status → `Closed`, with an `outcome`/`evidence` note
   recording forced closure) rather than silently dropping a new one or
   growing unbounded. **Eviction policy: force-close-oldest.**
2. **Closed-incident ring**: closed incidents are not retained in the
   live correlation engine's memory beyond what `Incidents1.
   ListIncidents()` needs to serve — a second, separately bounded
   closed-incident ring with its own cap, distinct from the
   open-incident cap above. **Eviction policy: FIFO-drop-oldest**,
   mirroring `BoundedRecorder`'s own FIFO-eviction pattern (P0-REC-002).
3. **Debounce/dwell bookkeeping ring** (provider-health flapping
   detection, §4.2): a small bounded set of "recent but not yet
   incident-worthy" candidate keys. **Corrected (repair pass) — eviction
   policy: reject-not-evict, never force-close-oldest or FIFO-drop.** An
   independent review found the original text left this ring's
   overflow behavior unspecified — worse than the other two, because
   silently evicting an in-progress, not-yet-incident-worthy candidate
   under a many-distinct-key event storm means a real sustained
   transition could be silently forgotten with no forced closure and no
   evidence note. **Binding policy:** at capacity, this ring never
   evicts an existing tracked candidate to admit a new one. A brand-new
   candidate key presented at capacity is rejected outright, returning a
   typed, bounded `CapacityRejected`-style outcome (a typed result/error
   variant, not a silently-dropped return value). Existing tracked
   candidates are never disturbed by a storm of new distinct keys; only
   entirely-new candidates can be rejected.

   **Corrected (second repair pass) — the `CapacityRejected`
   observability mechanism is a single, non-disjunctive rule, not a
   menu.** A second, comprehensive combined review found the first
   repair pass's "as a normal Guardian event of its own, or at minimum a
   documented internal counter/log line (an implementation pass must
   pick one and state which)" text an unresolved disjunction — a future
   implementer could pick either branch and both would technically
   satisfy the wording, and the "emit it as a Guardian event" branch was
   never checked for recursive overflow: a `CapacityRejected` outcome
   emitted as an ordinary `Event` fed back into the very
   `CorrelationIngress`/open-incident-cap machinery the debounce ring
   exists to protect would let a genuine many-distinct-key storm (exactly
   the scenario this ring exists to survive) generate a rejection-event
   per rejected key, which itself becomes correlation-ingress pressure,
   which itself can pressure the open-incident cap — an unanalyzed
   cascade. **The sole binding mechanism, effective immediately, is:**

   - `CapacityRejected` increments a daemon-owned, bounded/saturating
     rejection counter — a plain `u64` (or similar), incremented with
     `saturating_add`, never itself unbounded.
   - `CapacityRejected` also writes one plain operational log line via
     the existing `eprintln!("[guardian-daemon] ...")` convention this
     project already uses everywhere else in
     `crates/guardian-daemon/src/bin/guardian-daemon.rs` (e.g. the
     monitoring-tick and capability-registry-tick log lines) — confirmed
     by reading that file directly; no `tracing`/`log` crate or any other
     logging facility exists anywhere in this workspace's `Cargo.toml`
     files today, so none is introduced for this.
   - `CapacityRejected` **by rule DOES NOT construct or feed another
     `Event` into `CorrelationIngress` or any other correlation input
     path.** This is the specific provision that forecloses the
     recursive-overflow risk above, and it is independently testable —
     see `P2-REC-005` (§19): under a sustained storm of many distinct new
     debounce-candidate keys past capacity, the number of
     `CorrelationIngress`-admitted events must be provably bounded by the
     real event producers alone, never inflated by the count of
     `CapacityRejected` outcomes themselves.

   See `P2-REC-001`/`P2-REC-003`/`P2-REC-004`/`P2-REC-005` (§19).

   **Corrected (Gate 2a implementation-repair pass, 2026-09-06) —
   ownership of the two `CapacityRejected` observability actions is a
   gate split, not a single undivided requirement.** The second repair
   pass's wording above states *what* must happen (counter + log line)
   but does not state *which crate performs the log write*, and citing
   `crates/guardian-daemon/src/bin/guardian-daemon.rs`'s existing
   convention while describing `CapacityRejected` as something "the
   correlation engine" (a `guardian-core` library type) itself "writes"
   left the boundary ambiguous. During Gate 2a implementation this
   ambiguity led an implementer to place the `eprintln!` call inside
   `guardian-core` — a real layering/gate-ownership violation
   (`guardian-core` is a library crate; it must not perform daemon-shaped
   I/O), caught and repaired before Gate 2a's independent review accepted
   it. The now-accepted, tested, binding split, verified against the
   committed `crates/guardian-core/src/correlation.rs`:

   - **Gate 2a / `guardian-core`'s correlation engine** (already
     implemented, tested, and closed at this handoff's Gate 2a baseline):
     `reject_capacity()` rejects the new candidate, preserves existing
     tracked candidates, increments the `saturating_add`-based rejection
     counter, and returns a typed `AdmitOutcome::CapacityRejected`
     value carrying `{capability_id, rejection_count}` — **zero I/O of
     any kind.**
   - **Gate 2b / `crates/guardian-daemon/src/bin/guardian-daemon.rs`**:
     when the daemon tick consumes that typed `CapacityRejected` outcome,
     it writes the one `eprintln!("[guardian-daemon] ...")` operational
     log line, using the file's existing convention.

   `guardian-core` must never be required to perform daemon I/O to
   satisfy `P2-REC-003`. This does not change `P2-REC-003`'s substance
   (both actions — counter and log line — are still required, always,
   never a choice between them) — it corrects only the ownership
   boundary the original wording left implicit. See §19's revised
   `P2-REC-003` row and Gate 2b's manifest/TDD
   (`docs/guardian/30_TDD/gates/phase2-2b-*`) for the binding split as
   implemented.
- **Event retention needed for correlation**: the correlation engine
  does not need its own separate unbounded event store — it consumes
  the same event stream `guardian-daemon`'s existing `BoundedRecorder`
  already taps (§3), and only needs to retain, per open incident, the
  `EventId`s already linked (bounded by cap 1 above) plus the bounded
  debounce ring (cap 3 above, reject-not-evict).
- **Event storms**: the debounce windows in §4.1/§4.2 are exactly the
  storm mitigation for a *single* key — a storm of PSI or
  health-transition events for the same key collapses into one
  incident's `link_event` calls, not N incidents. A storm across *many
  distinct existing* keys is bounded by the open-incident cap (1) above,
  which forces closure. A storm across *many distinct new* debounce
  candidate keys (none yet incident-worthy) is bounded by the debounce
  ring's reject-not-evict policy (3) above, which rejects new candidates
  rather than evicting tracked ones — the two storm shapes have
  deliberately different, non-interchangeable mitigations.
- **Diagnostic Budget Manager interaction**: correlation itself performs
  no diagnostics (it only groups already-produced events) and therefore
  never calls `budget::evaluate` on the *grouping* path. Only a future,
  explicitly deferred diagnostic-escalation feature (§16) would call it,
  and only that feature's request — never the correlation engine's own
  bookkeeping — can be vetoed.
- **Can correlation itself become a pressure source?** Yes, in
  principle (unbounded incidents would consume memory) — mitigated
  entirely by the three bounded classes above; this pass requires all
  three exist as a Layer-1-tested invariant (§17/§18), not as an
  assumption.

---

# 8. Flight Recorder / persistence boundary

| Persistence boundary | Needed now? | Why | Storage location | Format | Bound | Recovery behavior | Migration/backward compat |
|---|---|---|---|---|---|---|---|
| Byte-based recorder limits (G5's FC-1) | No | G5's FC-1 was explicitly deferred by G5's own milestone record (`docs/evidence/g5/G5_MILESTONE.md`: "later gate... must determine whether byte-level bounds are required") and this phase does not add long-running/large-payload capture beyond what G7 already runs | N/A | N/A | N/A | N/A | N/A |
| Persistent recorder spill (G5's FC-2) | No | `RecorderPolicy` is evaluated on a real tick since G7 but drives no sink (G5's own milestone FC-2, confirmed still true by source inspection: no code outside `budget.rs`/its tests constructs a `RecorderPolicy` consumer with a real sink); this phase's correlation engine reads the same in-memory event stream, not the recorder's spill (there is none) | N/A | N/A | N/A | N/A | N/A |
| Incident persistence | No | Incidents are net-new in this phase; nothing in §46/§47 requires them to survive daemon restart — see §9 | N/A | N/A | N/A | N/A | N/A |
| Event persistence (beyond `BoundedRecorder`) | No | Same reasoning; correlation consumes the live stream, not a durable log | N/A | N/A | N/A | N/A | N/A |
| Correlation state persistence | No | Same reasoning | N/A | N/A | N/A | N/A | N/A |

**This planning pass finds TDD-contract Phase 2 is *not* the first gate
that requires any of the five persistence boundaries above.** All five
remain deferred, each for a stated reason, not by omission. If a future
implementation pass finds a concrete requirement (e.g. an operator
wanting incident history across reboot), that is a scope change to be
recorded as a §51 revision, per §51's own rollback/migration clause — not
something to add silently during implementation.

The `/var/lib/guardian/` convention (confirmed by reading ADR-008 and
`guardian-daemon`/`guardian-helper`'s own path defaults) is two disjoint,
separately-owned directories: `/var/lib/guardian/daemon/`
(`guardiand:guardiand`, `0750`-class) and `/var/lib/guardian/helper/`
(`root:root`) — this phase's decision not to persist anything means
neither directory gains a new write path in this phase. AGENTS.md's
removable-media exclusion ("Never make monitored removable storage the
required live destination for Guardian's own critical incident
recorder," P0-REC-004) remains satisfied trivially — there is nothing to
place there, since nothing new is persisted.

---

# 9. Reboot/restart semantics

Because §8 finds no persistence is needed now:

- **guardian-daemon restart**: open incidents, correlation windows, and
  historical events do **not** survive — the correlation engine's state
  is process-memory-only, exactly like the existing `BoundedRecorder`
  and `Arc<Mutex<Vec<CapabilityRecord>>>` registry snapshot it sits
  alongside. This is an explicit, accepted loss: a daemon restart clears
  in-flight incident correlation, and the next tick starts fresh
  detection from the current provider state.
- **Machine reboot**: same as daemon restart — no additional loss beyond
  what a daemon restart already causes, since nothing was persisted to
  lose differently.
- **Provider disappearance/reappearance**: this *is* a first-class
  correlation input (§4.2), not a restart-recovery concern — a provider
  going `Unavailable` then `Available` again produces two debounced
  transitions, correlated per §4.2's own rule, independent of whether
  the daemon itself restarted.
- **Incident IDs**: not stable across a daemon restart, since incidents
  themselves do not survive one. This is the accepted loss-semantics
  statement the task requires when persistence is not required.
- **Ingress clock/sequence (added, repair pass, §6)**: `CorrelationIngress`'s
  `ingress_clock`/`ingress_sequence` are process-local and reset on every
  `guardian-daemon` restart — no persistence, exactly the same
  memory-only decision as the rest of this section. A restart begins a
  new ingress epoch at sequence 0; total-order guarantees hold only
  within one daemon process lifetime and never span a restart boundary,
  consistent with (and not an exception to) incidents themselves not
  surviving restart.

---

# 10. Public API analysis

G9 already shipped the exact typed read surface this phase needs:
`Incidents1.ListIncidents()` → `Vec<IncidentWire>` →
`guardian_client::Incident` (with a lossless `From<IncidentWire>`
conversion already implemented and tested). **This phase's public-API
decision is to populate that existing surface, adding no new interface,
no new object path, and no new method**, unless implementation
discovers a genuine boundary (e.g. a client needing to filter by
severity server-side rather than client-side — deferred, not assumed
needed). No generic `Query(JSON)`, no `SearchEvents(...)`, no raw SQL, no
arbitrary provider reads, and no opaque JSON blob is introduced —
`IncidentWire`'s fields remain the frozen G9 shape. CLI/TUI/GUI already
render `Incident` values today (`guardian-tui`'s
`empty_incident_list_renders_as_a_healthy_state_not_an_error` and
`real_incident_renders_its_status_and_summary` tests, both passing in
this pass's baseline run) against a permanently-empty list; this phase
changes only what `ListIncidents()` returns, not any client code path
(client UX is explicitly out of scope for this planning task).

---

# 11. Incident/correlation privacy and privilege

Reusing G2's classifications exactly (`docs/evidence/g2/
PRIVILEGE_REQUIREMENT_INVENTORY.md`), none promoted or demoted:

- Every data source this phase's in-scope correlation rules use (PSI
  reads, systemd/logind/UDisks2/UPower/AccountsService reads via the
  existing six G8 providers) is already classified `no privilege` by
  G2. Correlating them does not, by itself, require new privilege —
  Guardian's existing unprivileged daemon access is sufficient for
  everything in §4.1–§4.3.
- **journald** is classified `no privilege` for reads by G2 — if a
  future implementation pass adds a journald-based correlation rule, no
  new privilege boundary is crossed for the *read* itself (rotation/
  capacity policy remains `unknown`, untouched, and irrelevant to a
  read-only consumer). This phase does not add a journald rule, so this
  is recorded as available headroom, not a decision made.
- **Can correlation accidentally expose data an individual source API
  would not?** This is the one real, evidenced privacy risk this
  planning pass identifies: §4.3's cross-source correlation links a PSI
  incident to a provider-health incident by temporal overlap, and in
  doing so associates two facts (e.g. "memory pressure was critical" and
  "AccountsService session list changed") that neither source API states
  are related. Both individual facts are already unprivileged and
  already exposed via `Capabilities1`, so no *new* privilege boundary is
  crossed, but this pass requires the resulting incident's `confidence`
  be capped at `Hypothesis` (§4.3, §14) specifically so the correlation
  layer never overstates a relationship the underlying no-privilege data
  cannot itself support.
- No previously `Unknown` G2 privilege requirement (BPF/eBPF,
  thermald-write, NVML, fwupd, journald-rotation, apt/package state,
  generic hardware control, usbguard) is used by any in-scope correlation
  rule in this phase, and none is silently promoted to no-privilege
  here — they remain `unknown` exactly as G2 left them.

**This resolves the privilege question in full for the scope this pass
actually defines.** No `PRIVILEGE BOUNDARY UNRESOLVED` block condition
applies.

---

# 12. Transaction observability — deferred

Wave 1 provides real mutation/recovery history, but it lives entirely in
`guardian-helper`'s private, schema-versioned store under
`/var/lib/guardian/helper/` (`root:root`), by deliberate G4/G7 design
(G4's FC-3: the Flight Recorder has no relationship to G4's persistence
module — `docs/evidence/g4/G4_MILESTONE.md` — Flight Recorder and
transaction persistence are independent mechanisms; G9 handoff §6.1
explicitly forbids `guardian-daemon` reading
`guardian-helper`'s state directory or adding a new
`guardian-daemon`→`GuardianHelper1` call). Populating `Transactions1`
would require exactly one of: (a) `guardian-helper` itself exposing a
new, typed, read-only D-Bus method Guardian's daemon calls (a new
cross-process contract, requiring its own ADR and G1/G7-style review),
or (b) `guardian-daemon` independently re-deriving transaction state from
systemd job history it already observes (lossy — it would not see
Wave 1's own recovery-classification detail). **This planning pass
declines to make that architectural call unilaterally** and defers it —
Phase 2 succeeds without transaction visibility: `Incidents1` can be
fully and honestly populated by PSI/provider-health correlation alone,
and `Transactions1` remains honestly empty exactly as G9 shipped it,
with the same "genuinely, honestly empty" doc-comment discipline
`dbus_surface.rs` already uses for `Incidents1` before this phase.

---

# 13. Provider-health correlation

Covered concretely in §4.2. **Corrected (repair pass):** this phase's
provider-health scope is not merely "detection logic" atop an existing
event stream — verified by reading `guardian-daemon.rs` directly,
`capability_registry_tick` returns `CapabilityRecord` snapshots only, and
no `Event` of any kind is produced for a Health/Availability change
today. This phase's real scope is therefore two things, not one: (a) a
new provider-health transition `Event` producer that diffs successive
snapshots and emits an `Event` when `Health`/`Availability` changes for
a `capability_id`, admitted through the correlation-ingress mechanism
(§6) like every other event source; and (b) the debounce/dwell detection
logic (§4.2) that consumes those events to decide incident-worthiness.
Debounce is required (not optional) to avoid opening/closing an incident
on every flapping tick, and its bookkeeping ring follows the
reject-not-evict `CapacityRejected` policy (§7). Duplicate suppression
is inherited free from `link_event`'s existing idempotency.
Recovery/closure is the debounced reverse transition. This reuses G8's
real typed health probes (`Availability`/`Health` enums,
`CapabilityRecord`) exactly as shipped — no new health vocabulary is
introduced, correcting a possible misreading of the task's example
transition list (`Healthy→Degraded` is not a real `Health` variant pair
in this codebase; the real pairs are `Availability`'s
`Available/Degraded/Unavailable/Unsupported/Unknown` and `Health`'s
`Healthy/Warning/Error/Stale/Unknown`, and §4.2 is written against the
real enums, not the task's illustrative ones).

**Generic vs. per-source scope, made explicit (added, second repair
pass).** §3's primitive-inventory table previously left the systemd/
logind/UDisks2/UPower/AccountsService rows' scope implicit behind a
blanket "no gap beyond general correlation wiring" cell. That is now
corrected: the generic, uniform Availability/Health-based transition
signal §4.2 describes — produced identically for all six G8 providers
via the Capability Registry, and delivered by Gate 2b (§20) — is
**REQUIRED FOUNDATION** for this phase. Each source's richer,
source-specific event semantics — UDisks2 device identity/appearance-
disappearance detail, logind session/inhibitor lifecycle detail, UPower
battery/AC transition detail, AccountsService session specifics — is
**OPTIONAL FUTURE ENRICHMENT, explicitly not part of this Phase 2 gate
sequence.** A future gate that wants richer per-source semantics makes
that decision deliberately, the same way severity (§15) and transaction
observability (§12) are deferred deliberately rather than assumed.

---

# 14. PSI correlation

Covered concretely in §4.1 (direct) and §4.3 (cross-source). Terminology
is explicit and binding for implementation: **"correlated with"** is
used for every relationship in §4.3 (temporal overlap only, no shared
identity key, `confidence` capped at `Hypothesis`); **"caused by"** is
never used anywhere in a produced `Incident`'s `summary`,
`candidate_causes`, or `evidence` text for a §4.3-derived relationship.
§4.1's direct PSI→incident relationship is a *direct observation* (the
kernel itself reports the threshold crossing), not a correlation claim,
and is worded accordingly.

**Correction pointer (Gate 2a implementation-repair pass, 2026-09-06):**
§4.1's correlation-key row is corrected in place — PSI events correlate
by the stable `resource_refs.first()` identity, never by
transition-text-bearing `normalized_key`. See §4.1 for the full
corrected text and rationale; this section's own terminology rules
("correlated with"/"caused by") are unaffected by that correction.

---

# 15. Incident severity/risk — deferred (corrected, repair pass)

**Original defect.** This section originally proposed adding a
`severity: Risk` field to `Incident`, recomputed on every `link_event`
call, while §1's row for `IncidentWire` elsewhere claimed the wire shape
"stays frozen" — directly contradictory, since the file-impact list
(§20, pre-repair) required updating `IncidentWire`'s conversion code to
carry the new field. It also silently reopened G3's own deliberately
deferred NB-3 note (`docs/evidence/g3/G3_MILESTONE.md`: `Risk` has
`Display`/`wire_token()` but no `FromStr`, so it cannot round-trip
through a wire string; NB-3's disposition assigns closure to "whichever
gate first needs to reconstruct a `Risk` value from a serialized
representation," which wire-visible severity would be) without ever
citing or closing it. Separately, `Incident::link_event(&mut self,
event_id: EventId)` (`crates/guardian-core/src/incident.rs`) only ever
receives an `EventId`, never an `Event` or its `Risk` — so "severity =
max linked-event `Risk`, recomputed on `link_event`" was not actually
implementable under the signature this same section described as
"reused unmodified."

**Binding resolution: severity is deferred in full for TDD-contract
Phase 2.**

- No `severity` field is added to `Incident` in this phase. `Incident`
  gains no new field of any kind for severity/risk.
- `IncidentWire`'s positional 7-tuple
  (`crates/guardian-daemon/src/dbus_surface.rs`,
  `crates/guardian-client/src/lib.rs`) stays **completely unchanged** —
  no new field, no shape change, no version negotiation, because nothing
  about the wire shape changes in this phase. §1's "stays frozen" claim
  and §20's file-impact list no longer contradict each other because
  there is no severity work to list.
- `Incident::link_event(&mut self, event_id: EventId)`'s signature stays
  **completely unchanged** — since severity is deferred, there is no
  need to give it access to event severity data.
- **G3's NB-3 note remains explicitly open.** This phase does not
  trigger it and does not close it — `Risk`'s `FromStr`/round-trip gap
  remains exactly as G3 left it deferred, owned by "whichever gate first
  needs to reconstruct a `Risk` value from a serialized representation."
  This phase is not that gate, because it adds no wire-visible severity.
- **Does the confidence-cap/`Hypothesis` mechanism (§4.3) still need
  something severity-like?** No. §4.3's cross-source correlation rule
  caps the derived incident's *existing* `confidence: Confidence` field
  (a G3 field, independent of `Risk`) at `Hypothesis` — this already
  fully expresses "this is a heuristic association, not a confirmed
  fact" without any severity concept. No lighter-weight severity
  substitute (a bare `Confidence`-only signal, a linked-event count, or
  anything else) is introduced either, because nothing in §4's rules
  actually needs one once severity itself is deferred — inventing a
  substitute here would reintroduce the same problem under a different
  name. A future gate that does need incident severity must decide it
  deliberately, including its NB-3 consequence, not inherit an
  ad hoc substitute from this phase.

---

# 16. Diagnostic escalation — deferred

Not required for this phase's exit criteria. §7 already establishes
correlation performs no diagnostics of its own. A future phase's
"incident condition → requested diagnostic → budget decision → evidence"
pipeline would compose `budget::evaluate`/`evaluate_with_alternatives`
(unmodified) with a new incident-triggered request type — cleanly
addable later without any change this pass makes, which is exactly why
it is deferred rather than spec'd prematurely.

---

# 17. Testing ladder

- **Layer 1 (pure Rust, `guardian-core`)**: correlation grouping
  (§4.1–§4.3), dedupe (`link_event` idempotency reused), ordering via
  `CorrelationIngress`'s ingress clock/sequence (§6, corrected — never
  `sort_by_monotonic_order`/raw `timestamp_monotonic`), incident
  lifecycle (create/update/close/reopen-as-new per §5), bounds
  (open-incident cap, closed-incident ring, debounce
  reject-not-evict ring, §7), replay determinism (§6), debounce
  `CapacityRejected` behavior and its observable recording (§7). This is
  the majority of Phase 2's normative-ID surface (`P2-COR-*`,
  `P2-INC-*`, `P2-EVT-*`, `P2-REC-*`).
- **Layer 2 (private D-Bus/dbusmock)**: provider health transitions
  driven through a mocked `org.freedesktop.systemd1`/UDisks2/etc. bus
  (reusing G8's existing dbusmock fixtures where present), the new
  provider-health transition `Event` producer (§4.2, §13) actually
  emitting on a snapshot diff, event ingestion into the correlation
  engine via the daemon's real tick loop and the single
  `CorrelationIngress` admission point, `Incidents1.ListIncidents()`
  returning real, non-empty data over a private bus (`P2-API-*`).
- **Layer 3 (umockdev)**: only if a genuinely hardware-backed read
  behavior is needed for a correlation input this phase actually uses
  (PSI is `/proc`-backed, not umockdev-shaped; UDisks2/UPower already
  have G8-era umockdev fixtures this phase can extend if a topology-
  change correlation test needs one — not required by §4.1/§4.2 as
  currently scoped).
- **Layer 4 (disposable Ubuntu 26.04.1 VM, `guardian-g9` or equivalent)**:
  real systemd/PSI, real provider disappearance/recovery (stop/start
  `cups.service` or another already-evidenced unit and observe a real
  `Incidents1` transition), real daemon restart/recovery (confirm §9's
  loss semantics empirically — incidents genuinely vanish on restart,
  not just in theory), journald only if a future rule adds it (`P2-VM-*`).
- **Layer 5**: not mechanically required — no in-scope correlation rule
  depends on physical hardware absent from the VM fleet.

---

# 18. Failure/adversarial matrix

| Scenario | Required behavior |
|---|---|
| Duplicate events | `link_event` idempotency — no duplicate `EventId` in `event_ids` |
| Out-of-order arrival | Rules apply strictly in ingress order (§6, corrected — never raw `timestamp_monotonic`); a late event admitted after its window closed starts a new incident with backreference, never reopens a closed one |
| Two producers with incompatible/backwards raw timestamps (added, repair pass) | A synthetic event from a fake "wall-clock" producer and one from a fake "sequence-counter" producer, with wildly different or backwards raw `timestamp_monotonic` values, must still group according to ingress admission order, not raw timestamps (`P2-EVT-003`) |
| Event storms (single key) | Debounce window (ingress-order-measured) collapses into one incident, no unbounded `link_event` growth beyond the linked-event set's own implicit bound |
| Event storms (many existing keys) | Open-incident cap (§7, class 1) forces oldest-incident closure rather than unbounded growth |
| Event storms (many new, not-yet-incident-worthy debounce keys) (corrected, second repair pass) | Debounce ring (§7, class 3) rejects new candidates once at capacity (`CapacityRejected`), recorded via a saturating counter increment plus one `eprintln!("[guardian-daemon] ...")` log line — never as a fed-back `Event`; existing tracked candidates are never evicted or disturbed; `CorrelationIngress`'s admitted-event count is provably unaffected by the rejection count (`P2-REC-001`/`P2-REC-003`/`P2-REC-004`/`P2-REC-005`) |
| Provider flapping | Debounce/minimum-dwell (§4.2) prevents open/close thrashing |
| Daemon restart during active incident | Incident is lost per §9's accepted loss semantics; ingress clock/sequence also reset to a fresh epoch; next tick starts fresh — tested at Layer 4 |
| Malformed provider data | Existing G8 provider adapters already fail closed to `Unknown`/`Unavailable` (AGENTS.md); correlation must treat `Unknown` as never incident-worthy on its own (§4.2), consistent with "do not convert UNKNOWN into HEALTHY" |
| Stale snapshots | A `Stale→`non-`Stale` transition is itself a correlatable event per §4.2's candidate list; a snapshot that stays `Stale` produces no repeated incident (debounced) |
| Correlation-window boundary (corrected, second repair pass) | An event exactly at the window edge is tested both just-inside and just-outside at Layer 1, deterministically, by constructing `Instant` values via `Instant`+`Duration` arithmetic (§6a) and injecting them directly into test-constructed `CorrelationIngress` records to place events precisely at/inside/outside the window **duration** boundary; `ingress_sequence` is used only to break ties when two constructed events share the identical `Instant`, never as the window measurement itself |
| Clock jumps | Irrelevant to grouping decisions (ingress-order-only, §6 — never wall-clock, never raw `timestamp_monotonic`); `timestamp_wall`/raw `timestamp_monotonic` display fields may show a jump but never affect grouping — tested by constructing events with a backward raw `timestamp_monotonic`/`timestamp_wall` but forward ingress order and asserting grouping follows ingress order only |
| Persistence corruption | N/A — no persistence in scope (§8) |
| Budget exhaustion | N/A to correlation's own path (§7); relevant only to the deferred §16 feature |
| Provider disappearance during correlation | Exactly §4.2's `Available→Unavailable` input — not a special case |
| Read API unavailable | `Incidents1` itself is part of the already-hardened G9 daemon surface; a client-side `ClientError` path already exists (`guardian_client::classify_call_error`) and needs no Phase 2 change |
| Replay after restart | Per §9, incidents and the ingress epoch do not survive; replay of the *same event log admitted in the same order* into a fresh engine instance must reproduce the same grouping (§6) — this is the meaningful replay guarantee, not restart-survival |
| Wire-visible severity assumed reachable (removed, repair pass) | N/A — severity is deferred in full (§15); no test asserts severity reaches `IncidentWire`, and any such test from a prior draft is removed, not merely left unasserted |

---

# 19. Phase 2 normative IDs (revised, second repair pass)

Stable `P2-*` prefix, per §50's original reservation and §51's decision
to actually spend it now. No suffix letters (avoiding the `002b` defect
§50's revision history records and fixed for Wave 1) — every ID here is
a plain, sequential, zero-padded number within its family, and any
future addition gets the next unused number in its family, never an
inserted letter.

**Revision note.** This ID inventory is revised, not merely re-typeset:
`P2-EVT-001` is reworded (ingress order, not raw `timestamp_monotonic`);
`P2-EVT-003`/`P2-EVT-004` are new (ingress total-order guarantee under
`Instant` ties; restart-epoch reset); `P2-INC-001` is **retired**
(severity deferred in full, §15 — no replacement ID is minted, because
no replacement mechanism is needed); `P2-REC-001` is reworded
(reject-not-evict, not FIFO eviction); `P2-REC-003`/`P2-REC-004` are new
(`CapacityRejected` observability; existing-candidate survival under a
new-key storm). `P2-COR-*`/`P2-INC-002..004`/`P2-API-002`/`P2-VM-*` are
unaffected by the three architectural decisions and are carried forward
unchanged. Per the task's own instruction, "19 IDs" is not preserved as
a cosmetic target — the count changes because the underlying scope
changed.

**Second revision note (second repair pass).** `P2-REC-003` is
**reworded** to state the single, non-disjunctive `CapacityRejected`
observability mechanism (bounded/saturating counter + `eprintln!` log
line) rather than the retired disjunction ("a Guardian event, or at
minimum... implementation states which"). `P2-REC-005` is **new** —
the independently-testable rule that a `CapacityRejected` outcome never
constructs or feeds an `Event` into `CorrelationIngress` or any other
correlation input path, closing the recursive-overflow risk the second
review identified. `P2-API-003` is **new** — the `IncidentWire`
wire-shape regression test requirement. No existing ID's number is
reused for a different requirement; `P2-EVT-*`/`P2-COR-*`/
`P2-INC-002..004`/`P2-REC-001`/`P2-REC-002`/`P2-REC-004`/`P2-API-001`/
`P2-API-002`/`P2-VM-*` are unaffected by this second repair pass and are
carried forward unchanged.

**Third revision note (Gate 2a implementation-repair pass, 2026-09-06).**
Two contract defects discovered during Gate 2a implementation and
independently confirmed by review are corrected here, matching the
committed, tested Gate 2a code — no ID's number or normative substance
changes, only ownership/identity text that was previously ambiguous or
wrong: (1) `P2-REC-003`'s row is corrected to state the counter/log-line
split explicitly by gate (`guardian-core`/Gate 2a: counter + typed
return, zero I/O; `guardian-daemon`/Gate 2b: the actual `eprintln!`
write) — see §7's corrected text; (2) §4.1's PSI correlation-key row is
corrected from `normalized_key` (which embeds transition text and would
wrongly split same-resource, different-transition events into separate
groups) to `resource_refs.first()` (the actual stable PSI resource
identity) — see §4.1's corrected text. `P2-COR-001`/`P2-COR-002` below
are reworded to name the corrected key explicitly; no other row changes.

| ID | Requirement |
|---|---|
| P2-EVT-001 | Correlation engine consumes events in **ingress order** (`CorrelationIngress`'s `ingress_clock`/`ingress_sequence`, §6), never insertion order and never a producer's own `timestamp_monotonic`, regardless of arrival order |
| P2-EVT-002 | A duplicate `EventId` presented to the same open incident never appears twice in `event_ids` |
| P2-EVT-003 *(new)* | Two events admitted from different fake producers with wildly different or backwards raw `timestamp_monotonic` values group according to ingress admission order, not raw timestamps |
| P2-EVT-004 *(new)* | `CorrelationIngress`'s `ingress_clock`/`ingress_sequence` reset to a fresh epoch (sequence 0) on every `guardian-daemon` restart; no ordering guarantee is claimed or tested across a restart boundary |
| P2-COR-001 *(key reworded, Gate 2a implementation-repair pass)* | A PSI `Critical` event for a previously-nominal `(provider, resource_refs.first())` key opens a new incident when none is open for that key — keyed by stable resource identity, never transition-text-bearing `normalized_key` (§4.1) |
| P2-COR-002 *(key reworded, Gate 2a implementation-repair pass)* | A second PSI `Critical` event for the same `(provider, resource_refs.first())` key within the debounce window (measured in ingress order) links to the existing open incident, not a new one, even when its transition-description text differs from the first event's |
| P2-COR-003 | A debounced `Available→Unavailable` transition for a `capability_id` opens or updates exactly one incident for that `capability_id` |
| P2-COR-004 | A capability that flaps faster than the minimum dwell produces no incident open/close thrashing |
| P2-COR-005 | Two temporally-overlapping incidents (one PSI, one provider-health) are cross-referenced with `confidence <= Hypothesis` and text using "correlated with," never "caused by" |
| P2-COR-006 | Identical event log, admitted in the same order, run twice through fresh engine instances, produces identical incident grouping (mod `IncidentId` values, wall-clock text, and the real `Instant` reading — only relative ingress order is normative) |
| P2-COR-007 | An event admitted after its window closed starts a new incident referencing the prior one, never reopens the closed one |
| ~~P2-INC-001~~ *(retired, repair pass)* | ~~`Incident` gains a `severity: Risk` field...~~ — **retired**: severity is deferred in full for this phase (§15); no field is added to `Incident`, and no replacement ID is minted because no replacement severity-like mechanism is needed |
| P2-INC-002 | Open-incident count never exceeds the configured cap; exceeding it force-closes the oldest open incident by ingress-order `opened_at` |
| P2-INC-003 | Closed-incident retention never exceeds its configured cap; exceeding it evicts the oldest closed incident FIFO |
| P2-INC-004 | A closed incident that later matches a new event produces a new `IncidentId` with a text backreference to the prior one, never a `Reopened` status (no such status is added) |
| P2-REC-001 *(revised)* | The debounce/dwell bookkeeping ring never evicts an existing tracked candidate to admit a new one; capacity exhaustion produces a typed `CapacityRejected` outcome for the new candidate only |
| P2-REC-002 | Correlation never calls `budget::evaluate`/`evaluate_with_alternatives` on its own grouping path (that call is reserved for the deferred diagnostic-escalation feature, §16) |
| P2-REC-003 *(reworded, second repair pass; ownership split corrected, Gate 2a implementation-repair pass, 2026-09-06)* | A `CapacityRejected` debounce-ring outcome increments a bounded/saturating rejection counter (`saturating_add`, never itself unbounded) **and** results in one plain operational log line via the existing `eprintln!("[guardian-daemon] ...")` convention — both, always, never a choice between them, and never silently dropped. **Ownership is split by gate, not undivided:** `guardian-core`'s `CorrelationEngine::reject_capacity()` (Gate 2a, closed) performs the counter increment and returns the typed `CapacityRejected{capability_id, rejection_count}` value with zero I/O; `crates/guardian-daemon/src/bin/guardian-daemon.rs` (Gate 2b) performs the actual `eprintln!` log write when it consumes that value. `guardian-core` must never perform the daemon-shaped I/O itself — see §7's corrected text above |
| P2-REC-004 *(new)* | Under a storm of many distinct new debounce candidate keys at capacity, only new candidates are rejected; existing tracked candidates' state and progress are provably unaffected |
| P2-REC-005 *(new, second repair pass)* | A `CapacityRejected` outcome never constructs or feeds an `Event` into `CorrelationIngress` or any other correlation input path — under a sustained storm of many distinct new debounce-candidate keys past capacity, the number of `CorrelationIngress`-admitted events is provably bounded by the real event producers alone, never inflated by the count of `CapacityRejected` outcomes themselves |
| P2-API-001 | `Incidents1.ListIncidents()` returns real, live incidents once the correlation engine is wired in, with lossless `IncidentWire`/`guardian_client::Incident` round-tripping (already proven by existing G9 tests; this ID requires it hold with non-empty data) |
| P2-API-002 | No new `Guardian1`, `Capabilities1`, `Incidents1`, or `Transactions1` method/interface/object path is added beyond what G9 already shipped, unless a future §51 revision explicitly approves one |
| P2-API-003 *(new, second repair pass)* | A regression test locks `IncidentWire`'s exact current shape — a 7-field positional tuple of `String`s — so that any future accidental change to its arity, field order, or field type fails a test immediately rather than silently drifting; this is a regression guard for Phase 2, not a new capability |
| P2-VM-001 | Real disposable-VM stop/start of an already-evidenced unit (e.g. `cups.service`) produces a real, observable `Incidents1` transition over the real system bus |
| P2-VM-002 | A real `guardian-daemon` restart during an open incident loses that incident, per §9's accepted semantics (including a fresh ingress epoch), confirmed by fresh VM evidence, not asserted from source reading alone |

---

# 20. Implementation file expectations (for a future, separately-gated implementation pass) — revised, repair pass

**Internal gate decomposition (added, second repair pass).** A second,
comprehensive combined review found this section a flat file list, not a
gated sequence, despite the real scope (a new pure-Rust correlation
engine + a new provider-health event producer + daemon wiring + D-Bus
population + four test layers) being large enough to warrant
decomposition. This adds a sequencing/structuring breakdown on top of
already-approved scope — it changes neither the scope nor the `P2-*` ID
list. A future, separately-gated implementation pass should execute
these as three internal gates in order:

- **Gate 2a — Layer-1 correlation engine (pure Rust, no daemon wiring).**
  - *Purpose*: build and prove the deterministic correlation engine in
    isolation, with no dependency on a running daemon or real D-Bus
    connections.
  - *Depends on*: nothing beyond the published baseline
    (`1423d9c3053394e19e461ee6adea31bea9231fa7`) — no prior Phase 2 gate.
  - *Responsible for*: `P2-EVT-001..004`, `P2-COR-001..007`,
    `P2-INC-002..004`, `P2-REC-001..005`.
  - *Implementation scope*: `CorrelationIngress` (§6) and its ingress
    clock/sequence; the three bounded structures (§7) — open-incident
    cap, closed-incident ring, debounce/dwell ring with its
    `CapacityRejected` outcome, saturating counter, and log line; the
    PSI correlation rule (§4.1); the provider-health-transition
    correlation rule's debounce/lifecycle logic (§4.2, consuming
    whatever event shape Gate 2b will later produce — this gate may use
    a test-local synthetic producer, not the real one); the cross-source
    rule (§4.3); incident lifecycle (create/update/close/reopen-as-new,
    §5).
  - *Test layers*: Layer 1 only (`crates/guardian-core/tests/
    correlation_contract.rs`).
  - *VM evidence*: none required.
  - *Exit criteria*: every `P2-EVT-*`/`P2-COR-*`/`P2-INC-002..004`/
    `P2-REC-*` normative ID has a passing Layer-1 test; the engine
    compiles and is tested with zero dependency on `guardian-daemon` or
    a live bus.
- **Gate 2b — provider-health event producer, daemon wiring, D-Bus
  population.**
  - *Purpose*: make the engine built in Gate 2a real inside
    `guardian-daemon`, and make `Incidents1.ListIncidents()` return live
    data.
  - *Depends on*: Gate 2a complete and merged (the engine this gate wires
    in must already be fully tested in isolation).
  - *Responsible for*: `P2-API-001..003`; exercises `P2-COR-003/004`
    against the real provider-health producer built here (not the
    Gate 2a synthetic one).
  - *Implementation scope*: the new provider-health transition `Event`
    producer that diffs successive `capability_registry_tick` snapshots
    (§4.2, §13 — REQUIRED FOUNDATION only, per the generic-vs-enrichment
    categorization above; no per-source enrichment); wiring the Gate 2a
    engine into `guardian-daemon`'s monitoring tick, constructing the
    single daemon-owned `CorrelationIngress` admission point for PSI, the
    daemon-tick producer, and the new provider-health producer;
    `Incidents1::list_incidents` reading the engine's live incident store
    instead of `Vec::new()`, including the doc-comment correction §20
    (below) already specifies; the `IncidentWire` regression test
    (`P2-API-003`, §19) locking the existing 7-tuple shape.
  - *Test layers*: Layer 2 (mocked D-Bus/dbusmock) primarily; Layer 3
    only if a topology-change correlation test needs a UDisks2/UPower
    umockdev fixture extension (not required by §4.1/§4.2 as scoped).
  - *VM evidence*: none required for this gate itself (deferred to
    Gate 2c).
  - *Exit criteria*: `Incidents1.ListIncidents()` returns real, non-empty
    incidents over a private/mocked bus in a Layer-2 test; the
    provider-health producer is proven to emit on a real snapshot diff;
    no file in §20's "Unmodified, explicitly" list is touched.
- **Gate 2c — VM evidence and restart/epoch proof.**
  - *Purpose*: prove, on real hardware/systemd (not source-reading or
    mocks), the behaviors Gate 2a/2b only proved in isolation or against
    a mock bus.
  - *Depends on*: Gate 2b complete and merged (there must be a real,
    wired `Incidents1` to observe).
  - *Responsible for*: `P2-VM-001`, `P2-VM-002`.
  - *Implementation scope*: none — this gate produces evidence, not new
    code, beyond whatever minimal test harness the VM run itself needs.
  - *Test layers*: Layer 4 (disposable Ubuntu 26.04.1 VM, `guardian-g9`
    or equivalent) exclusively.
  - *VM evidence*: real stop/start of an already-evidenced unit (e.g.
    `cups.service`) producing a real, observable `Incidents1` transition
    (`P2-VM-001`); a real `guardian-daemon` restart during an open
    incident, confirmed to lose that incident and reset the ingress
    epoch (`P2-VM-002`) — evidence written to `docs/evidence/p2/`
    per §21, not asserted from source reading alone.
  - *Exit criteria*: both VM evidence artifacts exist under
    `docs/evidence/p2/` and are reproducible from a fresh VM clone at the
    implementation pass's own baseline commit.

---

- New: `crates/guardian-core/src/correlation.rs` (or `correlation/`
  module) — the Layer-1 engine, pure Rust, no I/O (Gate 2a). Includes the
  `CorrelationIngress` envelope type (§6) and the debounce/dwell
  bookkeeping ring with its `CapacityRejected` outcome type (§7),
  including the outcome's bounded/saturating rejection counter and the
  by-rule prohibition on constructing or feeding another `Event` back
  into `CorrelationIngress` from a rejection (§7, `P2-REC-005`).
- New: `crates/guardian-core/tests/correlation_contract.rs` — Layer-1
  normative tests for `P2-COR-*`/`P2-EVT-*`/`P2-INC-002..004`/`P2-REC-*`
  (Gate 2a), including the ingress-order-vs-raw-timestamp test
  (`P2-EVT-003`), the window-boundary tests using the §6a
  `Instant`-construction technique, and the debounce
  `CapacityRejected`/existing-candidate-survival/no-re-entry tests
  (`P2-REC-003`/`P2-REC-004`/`P2-REC-005`).
- Modified: `crates/guardian-daemon/src/bin/guardian-daemon.rs` (Gate
  2b) — wire the correlation engine into the existing monitoring tick,
  feeding it the same `Event`s already produced for the recorder (no new
  provider read for PSI/daemon-tick events); construct the single,
  daemon-owned `CorrelationIngress` clock/sequence at the one point every
  event source (PSI, daemon-tick, and the new provider-health producer)
  feeds into the correlation engine; add the new provider-health
  transition `Event` producer that diffs successive
  `capability_registry_tick` snapshots (§4.2, §13, REQUIRED FOUNDATION
  only — no per-source enrichment) — this is new production logic, not a
  modification of `capability_registry_tick`'s existing snapshot behavior
  itself; the debounce ring's `CapacityRejected` log line uses this
  file's existing `eprintln!("[guardian-daemon] ...")` convention, not a
  new logging facility.
- Modified: `crates/guardian-daemon/src/dbus_surface.rs` (Gate 2b) —
  `Incidents1::list_incidents` reads the correlation engine's live
  incident store instead of returning `Vec::new()`; update its doc
  comment (currently states "no incident producer exists" — this
  becomes false and must be corrected, not left stale, per this
  project's own G8/G9 precedent of correcting doc comments that drift
  from reality). `IncidentWire`'s tuple definition itself is
  **not modified** (severity deferred, §15) — locked by the new
  regression test required by `P2-API-003` (§19, new).
- **Corrected (repair pass) — `crates/guardian-core/src/incident.rs` is
  NOT modified in this phase.** The original draft required adding a
  `severity: Risk` field and updating `link_event` to recompute it;
  severity is now deferred in full (§15), so `Incident` and
  `Incident::link_event(&mut self, event_id: EventId)` both remain
  byte-for-byte as G3 shipped them. No construction site (tests,
  `dbus_surface.rs`, `guardian-client`'s `From<IncidentWire>`) needs
  updating for a field that is not added.
- New (added, second repair pass) — a regression test in
  `crates/guardian-client/src/lib.rs`'s existing `#[cfg(test)] mod
  tests` (or an added `crates/guardian-daemon/tests/incident_wire_shape.rs`,
  implementer's choice — the requirement is the assertion, not the file)
  locking `IncidentWire`'s exact current shape: a 7-field positional
  tuple of `String`s (confirmed unchanged by both prior reviews;
  `crates/guardian-daemon/src/dbus_surface.rs:233` and
  `crates/guardian-client/src/lib.rs:195` both currently read `pub type
  IncidentWire = (String, String, String, String, String, String,
  String);`). This is a regression guard for Phase 2 (`P2-API-003`,
  §19) — it locks the wire shape this phase relies on staying frozen so
  any future accidental change fails a test immediately instead of
  silently drifting; it is not a new capability.
- Unmodified (explicitly, and must remain so): `Guardian1` contract,
  `Transactions1` (still honestly empty, §12), `guardian-helper`'s
  entire crate, all Wave 1 authorization/transaction code,
  `budget.rs`/`recorder.rs` (consumed, not changed),
  `crates/guardian-core/src/incident.rs` (consumed, not changed — see
  above, corrected from the original draft which required a change
  here), `crates/guardian-daemon/src/dbus_surface.rs`'s `IncidentWire`
  tuple shape and `crates/guardian-client/src/lib.rs`'s matching
  `IncidentWire`/`From<IncidentWire>` (both frozen, §15), `now_secs()`
  and `providers/psi.rs`'s `ThresholdMonitor::sequence` (existing,
  accepted, unmodified — the new `CorrelationIngress` mechanism wraps
  their output, it does not alter either producer, §6).

---

# 21. Audit requirements

A future implementation pass must, at completion, produce:
`docs/evidence/p2/` (mirroring `docs/evidence/g8/`, `docs/evidence/g9/`
naming) containing: correlation determinism replay evidence (including
the ingress-order-vs-raw-timestamp proof, `P2-EVT-003`); debounce
`CapacityRejected` observability evidence (`P2-REC-003`/`P2-REC-004`),
including the non-re-entry proof required by `P2-REC-005` (evidence that
`CorrelationIngress`'s admitted-event count under a many-new-key storm
is bounded by the real producers alone, not inflated by rejection
outcomes); the `IncidentWire` shape-lock regression test result
(`P2-API-003`); VM evidence for P2-VM-001/002; a milestone record
following the `G*_MILESTONE.md` format documenting any forward
constraints this phase leaves open for whatever comes after it (at
minimum: `Transactions1` population remains open per §12; G5's FC-1/FC-2
remain open per §8; **G3's NB-3 remains explicitly open, not closed by
this phase**, per §15; the OPTIONAL FUTURE ENRICHMENT per-source
semantics named in §13 remain undecided, not silently ruled out).
