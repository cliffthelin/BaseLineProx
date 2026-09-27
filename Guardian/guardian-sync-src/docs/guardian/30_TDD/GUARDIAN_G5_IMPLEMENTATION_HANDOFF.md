# Guardian Phase 0 Implementation Handoff
## G5 — Diagnostic Safety Only

**Status:** authoritative for this gate. Prompts for this gate should
describe only the task and the delta against this document — this
document, not the prompt, carries the architecture, the contract
references, and the acceptance criteria. Do not silently reinterpret
anything below; if something here conflicts with the governing contract,
the contract wins and the conflict must be raised explicitly, not
resolved by guessing.

---

# 1. Mission

Implement exactly what TDD contract §"G5 — Diagnostic safety" requires:

```text
Required:
- Diagnostic Budget Manager;
- bounded recorder;
- PSI test fixtures.

Tests:
P0-DIAG-001..005
P0-REC-001..004
```

Do **not** begin G6, real providers, the privileged helper, GUI/TUI/CLI,
or packaging. Do **not** implement a real `/proc/pressure` reader wired to
the live host, a real systemd/UDisks/UPower provider, or any client
surface — those are G7/G8/G9 scope. "PSI test fixtures" means a typed,
testable PSI *parsing and event model* exercised entirely through
fixture/mock input in this gate; the real kernel-backed provider that
feeds it live data is G8's `P1-PSI-*` job (contract §38, gate G8).

# 2. Read before changing code

- `AGENTS.md` — repository-wide conventions (external test files only,
  workspace lint policy, no `serde`, manual `Display`/`FromStr` for any
  type crossing a real boundary).
- `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §19
  (Diagnostic Budget Manager), §20 (PSI event contract), §21 (boot
  availability — already implemented, reuse unchanged), §36 (P0-DIAG/
  P0-REC normative test list), §39 (implementation order — Diagnostic
  Budget is item 9, Recorder is item 10, both strictly after the
  transaction engine), §45 (Phase 0 exit criteria: "Diagnostic Budget can
  veto dangerous escalation," "recorder is bounded").
- `docs/evidence/g4/G4_MILESTONE.md` — the accepted G4 state and its
  forward constraints FC-1..FC-4, all of which this gate must resolve
  deliberately (not by silent omission).
- `docs/guardian/20_Control_Plane/Diagnostic_Budget.md`,
  `docs/guardian/20_Control_Plane/Flight_Recorder.md`,
  `docs/guardian/10_Platform/PSI.md`,
  `docs/guardian/90_Sources/wiki/linux-psi.md` — existing pointer pages
  and the external source snapshot; recheck the canonical kernel doc URL
  in the source snapshot before relying on any PSI format detail this
  handoff states, per that page's own "Refresh metadata" instruction.
- `crates/guardian-provider-api/src/capability.rs` — `DiagnosticCost`/
  `CostLevel` already exist (G3); this gate consumes them, does not
  redefine them.
- `crates/guardian-core/src/risk.rs` — `Risk` (G3); reused unchanged if a
  correlation with diagnostic cost is needed (see §5).

# 3. Normative G5 contract IDs

```text
P0-DIAG-001 — I/O budget veto
P0-DIAG-002 — memory budget veto
P0-DIAG-003 — disk-full degradation
P0-DIAG-004 — explain denial
P0-DIAG-005 — lower-cost alternative

P0-REC-001 — bounded memory
P0-REC-002 — dropped counter
P0-REC-003 — storage failure
P0-REC-004 — removable target rejected
```

Every one of these must have a real, focused test — not a shared fixture
that happens to also exercise it. Contract text for each (§36, verbatim):

- **P0-DIAG-001**: Critical I/O pressure prevents a high I/O-write-cost
  diagnostic.
- **P0-DIAG-002**: Critical memory pressure prevents large-memory
  diagnostic allocation.
- **P0-DIAG-003**: Critical free-space condition forces memory-first
  recorder policy.
- **P0-DIAG-004**: A denied escalation returns a reason code.
- **P0-DIAG-005**: Budget manager can select a cheaper available
  diagnostic path.
- **P0-REC-001**: Ring buffer never grows beyond configured limit.
- **P0-REC-002**: Overflow increments a dropped-event counter.
- **P0-REC-003**: Persistence failure does not block the monitoring loop.
- **P0-REC-004**: Critical recorder path cannot be configured to a
  monitored removable device.

# 4. Diagnostic Budget Manager (§19)

## 4.1 Inputs

The Budget Manager decides whether a *diagnostic* action (not a
mutating/write transaction — see §5 for the explicit scope boundary) may
proceed, given:

- the diagnostic's own declared `DiagnosticCost` (G3, already typed:
  `cpu_cost`/`memory_cost`/`io_read_cost`/`io_write_cost`/
  `kernel_trace_cost`/`expected_duration_ms`, each `CostLevel` ∈
  `{Negligible, Low, Moderate, High}`);
- the current system pressure state (from the PSI fixture model, §6) —
  at minimum per-resource-class current severity;
- a free-space signal for the root/recorder-target filesystem (for
  P0-DIAG-003/P0-REC-004 — this gate needs a typed, injectable
  free-space/removable-device fact, not a real `statvfs`/`udev` call; the
  real read comes from G8).

## 4.2 Required decision shape

Model the decision as a real typed function, not a boolean:

```rust
pub enum BudgetDecision {
    Permitted,
    Denied { reason: DenialReason },
    Downgraded { alternative: /* cheaper diagnostic identity */, reason: DenialReason },
}
```

`DenialReason` must be a real enum (P0-DIAG-004 requires the denial to be
*explainable* — a `String` alone is not enough; at minimum distinguish
which resource class triggered the denial: I/O, memory, disk-space,
other). Do not reuse `guardian_core::transaction::engine::EngineError` for
this — see forward constraint FC-2 in the G4 milestone record: diagnostic-
budget denial is a distinct concern from transaction-engine error, and
folding one into the other blurs a boundary G4 deliberately kept clean.

## 4.3 Cost-class veto logic (P0-DIAG-001/002/003)

At minimum, the manager must be able to look at one pressure signal and
one cost declaration and produce a real veto — the contract's own
examples are the floor, not the ceiling:

- `io_write_cost == High` (or `Moderate`, if you choose a stricter
  threshold — state and test the exact threshold chosen) while I/O
  pressure is at its most severe fixture-representable level → `Denied`.
- `memory_cost == High` while memory pressure is at its most severe
  fixture-representable level → `Denied`.
- root/recorder-target free space below a defined critical threshold →
  the *recorder* (not the diagnostic action generally) is forced into a
  memory-only policy (P0-DIAG-003) — this is a distinct outcome from a
  plain `Denied`, since it changes *how* the recorder behaves rather than
  refusing one action; make this an explicit, separately-tested behavior,
  not folded into `BudgetDecision`.

## 4.4 Lower-cost alternative (P0-DIAG-005)

The manager must be able to receive more than one candidate diagnostic
identity/cost pair for the same underlying question and pick a cheaper one
that the current pressure state permits. Model this as a real function
over a real `Vec`/slice of candidates, not a hard-coded two-diagnostic
example — the test must prove selection logic, not a single lucky branch.

## 4.5 Explicit non-goals (do not implement here)

- No real PSI reader, no real `/proc/pressure/*` I/O.
- No correlation with G4's `TransactionRecord`/`Risk` unless you
  explicitly decide this gate needs one (see FC-1 in the G4 milestone
  record) — if you decide it does not, say so explicitly in the
  completion report rather than silently leaving the two types
  unconnected without comment.
- No thermal/PSI *trigger* wiring to a real epoll/poll loop — that is
  G8's `P1-PSI-004` (event-driven threshold monitoring on real kernel
  data). This gate proves the *parsing and decision* model with fixtures.

# 5. Diagnostic vs. transaction scope boundary (read before writing code)

The G4 milestone's FC-1/FC-2 flag exactly this decision point: does a
*mutating* `Apply` in the transaction engine ever get vetoed by the
Diagnostic Budget Manager? The governing contract's §19 examples are all
diagnostic-only ("veto an I/O-write-heavy trace," "veto a large diagnostic
buffer," "prevent expensive diagnostic escalation") — nothing in the
contract text requires G5 to gate G4's `Apply` step. Resolve this
explicitly and record the decision in the completion report:

- **Option A (recommended default, smaller/cleaner scope):** the Budget
  Manager governs only diagnostic/observational actions in this gate.
  `TransactionRecord`/`engine::apply()` are untouched — G4's own module
  boundary stays exactly as accepted. A future gate may explicitly widen
  this if the contract requires it.
- **Option B:** if you find explicit contract language requiring
  transaction-mutation gating by diagnostic budget that this handoff
  missed, cite the exact section, and implement the narrowest change to
  `guardian-core` that satisfies it without altering any already-accepted
  G4 invariant (do not touch `apply()`'s entry gate/TOCTOU logic; a
  budget check, if required, is a precondition checked *before* the
  transaction engine is ever invoked, analogous to how `Validate`
  precedes `Authorize`).

Do not implement both halfway. Pick one, implement it completely, test it,
and say which one in the completion report.

# 6. PSI test fixtures (§20)

## 6.1 Required parsing model

`/proc/pressure/{cpu,memory,io}` format (per the kernel source snapshot):
each file has a `some` line and (for memory/io) a `full` line, each with
`avg10=`/`avg60=`/`avg300=`/`total=` fields. CPU has no `full` line on
some kernels — the contract explicitly requires a test for "CPU lacking a
`full` line" (§20), so the parser must treat a missing `full` line as a
legitimate, distinct state (not an error) for CPU specifically, while
still surfacing a real parse error for a genuinely malformed line.

Build a real parser (`&str -> Result<PsiSnapshot, PsiParseError>` or
equivalent) that operates on an in-memory string — do not require an
actual filesystem read for this gate's tests (that real read is a thin,
separately-testable G8 wrapper). Required test coverage, all listed
explicitly in §20:

- valid `some` and `full` parsing;
- CPU lacking a `full` line (explicit, not incidentally covered);
- counter monotonicity (`total=` must be non-decreasing across
  successive real/fixture samples — model this as a property the parser
  or a thin sequencing wrapper can prove, not an assumption);
- malformed/unavailable PSI source (a real typed error, never a panic,
  never silently treated as "zero pressure");
- threshold event triggering (given a sequence of snapshots and a
  threshold, produce a real typed event when pressure crosses it);
- threshold monitor teardown (whatever "monitor" abstraction you build
  must have an explicit stop/drop path that is actually tested, not
  assumed correct because `Drop` exists);
- no busy-loop when there is no event (this gate cannot test real
  `poll`/`epoll` timing without a real kernel — model this as: the
  monitor abstraction's public API has no method that spins without an
  explicit wait/wake input, and state that explicitly in the completion
  report; do not claim you tested real poll/epoll behavior when you
  tested a fixture-driven state machine instead).

## 6.2 Availability

A missing/unavailable PSI source (kernel doesn't export it, or the read
fails) must produce an explicit unsupported/unavailable state — reuse G3's
`Availability`/`Knowledge<T>` pattern if a natural fit, or a
locally-scoped equivalent; do not invent a third "maybe" representation
alongside G3's existing `Unknown`/`Unavailable` vocabulary without a
stated reason.

# 7. Bounded recorder / Flight Recorder (P0-REC-001..004)

## 7.1 Required shape

A bounded, memory-first ring buffer that:

- never exceeds a configured capacity (P0-REC-001) — prove this by
  pushing more events than the configured limit and asserting the buffer
  size never exceeds it, not merely that old entries are eventually
  evicted;
- increments a real, readable dropped-event counter on overflow
  (P0-REC-002) — the counter itself must be part of the public,
  observable state, not an internal detail a test infers indirectly;
- does not block or fail the caller when its own optional persistence
  step fails (P0-REC-003) — model persistence as a fallible operation the
  recorder calls, and prove that a forced failure of that call still
  lets the record/push operation itself succeed and the "monitoring loop"
  (whatever minimal loop-like abstraction this gate builds) keep running;
- rejects being configured to write its critical path to a location the
  system identifies as a monitored *removable* device (P0-REC-004) — this
  needs a typed "is this target removable" fact injectable by a test
  fixture (do not require real `udev`/`lsblk` in this gate; that's G8).
  "Critical path" means whatever this gate defines as the recorder's
  non-optional/primary target, as distinct from an optional spill target
  — define that distinction explicitly if the recorder has more than one
  configurable target.

## 7.2 Explicit non-goals

- No real disk I/O against `/var/lib/guardian` or any real path — a
  test-controlled temporary directory (matching G4's persistence-test
  convention) is sufficient, exactly like G4's persistence module.
- No wiring to G4's `TransactionRecord` events unless §21 (event/incident
  integration, reused unchanged from G3/G4) already gives you a natural,
  minimal touchpoint — if you add one, keep it to "the recorder can
  accept a `guardian_core::event::Event`," not a redesign of either
  module.

# 8. Fail-closed checklist

- An unrecognized/malformed PSI line is a typed parse error, never
  silently treated as "no pressure" (which would fail *open* — the
  opposite of what a safety-critical pressure signal requires).
- A `BudgetDecision` variant that can't be reasoned about (e.g. a future
  enum extension) must not silently resolve to `Permitted` — if you add
  an `Unknown pressure state` concept, it must veto/deny by default, not
  permit by default, matching G3's established `Knowledge::Unknown`
  fail-closed discipline.
- Recorder overflow must never panic, block, or silently drop without
  incrementing the counter.
- Persistence failure in the recorder must never propagate as a panic or
  as a failure of the thing being recorded (P0-REC-003's entire point).

# 9. TDD sequence

Failing test → minimal implementation → focused pass → full workspace
pass, exactly as G3/G4. Suggested order (not mandatory, but matches
contract §39's ordering: Diagnostic Budget before Recorder):

1. `DiagnosticCost`/`CostLevel` consumption + `BudgetDecision`/
   `DenialReason` types, P0-DIAG-001/002.
2. P0-DIAG-003 (disk-full degradation) — requires the recorder's
   memory-first-policy concept to exist at least as a typed target state,
   even before the recorder itself is fully built.
3. P0-DIAG-004/005.
4. PSI parsing model + its required test list (§6.1).
5. Recorder P0-REC-001/002.
6. Recorder P0-REC-003/004.

# 10. Adversarial self-check before reporting done

1. real host leakage — does any test read `/proc/pressure/*`,
   `/proc/meminfo`, `statvfs` on a real path, or any real `udev`/`lsblk`
   output?
2. fail-open pressure — does a malformed/missing PSI source ever get
   treated as "no pressure, proceed"?
3. silent permit — does an unrecognized/future `BudgetDecision`-adjacent
   state ever default to `Permitted`?
4. unbounded growth — does the recorder's buffer ever grow past its
   configured limit under a real stress test (push far more entries than
   the limit, assert size every iteration, not just at the end)?
5. dropped-counter drift — does the dropped counter ever fail to
   increment on an overflow that definitely happened?
6. persistence failure swallowed as recorder failure — does a forced
   persistence-layer failure ever prevent the in-memory push from
   succeeding, or crash the process?
7. removable-device bypass — can the critical recorder path be configured
   to a fixture-marked-removable target through any code path, including
   a default/fallback?
8. G4 boundary — did this gate touch `engine::apply()`'s entry gate,
   TOCTOU recheck, or persistence wiring in any way not explicitly
   justified per §5's Option A/B decision?
9. G6/G7/G8/G9 leakage — any GUI/TUI/CLI code, any real D-Bus provider
   adapter, any systemd unit, any packaging?
10. explainability — does every `Denied`/`Downgraded` decision actually
    carry a real, distinct `DenialReason`, or does everything collapse to
    one generic "denied" variant that technically satisfies the type
    signature but not the contract's "explainable reason" requirement?

# 11. Completion states

Report exactly one, honestly:

```text
G5 CANDIDATE — DIAGNOSTIC SAFETY READY FOR INDEPENDENT AUDIT
G5 PARTIAL — CONTRACT TESTS INCOMPLETE
G5 BLOCKED — GOVERNING CONTRACT INSUFFICIENT
G5 BLOCKED — DIAGNOSTIC/TRANSACTION SCOPE CONFLICT
```

Do not report `CANDIDATE` if any `P0-DIAG-*`/`P0-REC-*` test is red,
skipped, or asserts against a fixture that cannot fail.

# 12. Completion report

Include, at minimum: which normative tests are green with exact
names/IDs (all 5 `P0-DIAG-*`, all 4 `P0-REC-*`); the §5 scope-boundary
decision (Option A or B) and why; the exact `BudgetDecision`/
`DenialReason` shape built and how each P0-DIAG test maps to it; the PSI
parsing model's exact type shape and confirmation that the CPU-missing-
`full`-line case is explicitly tested (not incidental); the recorder's
exact bounded-buffer/dropped-counter/persistence-failure/removable-target
mechanism and its four tests' results; the §10 adversarial self-check
results item-by-item, stating which were executed as real scratch
mutations vs. reasoned by inspection; full `cargo fmt --check` / `cargo
clippy --workspace --all-targets --all-features -- -D warnings` / `cargo
test --workspace` output; and an explicit statement of what was deferred
to G6/G7/G8 and why (in particular: the real PSI provider, real
recorder-target device detection, and any GUI/TUI/CLI surface).

Then stop. Do not begin G6. Do not tag G5 — independent review happens
first, exactly as it did for G0 through G4.
