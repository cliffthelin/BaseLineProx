# Guardian Phase 0 — G5 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Accepted commit and tag

```text
Gate:             G5 — Diagnostic Safety
Accepted commit:  5bcf21bdb2fc07f0ccbef6051b9162e92c96f890
G5 tag:           phase0-g5-diagnostic-safety (annotated, points to 5bcf21b)
```

Implementation landed as a single commit (`5bcf21b`) adding three new
`guardian-core` modules -- `budget`, `psi`, `recorder` -- plus their
external contract test files, on top of the accepted G4 baseline
(`38245b1`, itself descending from `phase0-g4-transaction-engine`).

## Independent review

**Verdict: `PASS — G5 IMPLEMENTATION ACCEPTED`.**

Unlike G4, this gate passed on its first independent audit -- no repair
round was required. The auditor independently re-derived all nine
normative IDs from the contract text, independently ran twelve adversarial
mutations against a disposable scratch copy of the repository (never the
tracked tree), and confirmed nine were genuinely load-bearing (caught by
the test suite) while three were correctly judged not-applicable with
honest reasoning rather than forced: cost-ranking arithmetic has no
reachable overflow surface given the closed `CostLevel` enum; the
recorder's `spill()` has no accumulation mechanism to remove a bound
from; and the recorder has no round-trip load path for a "corrupt
evidence" mutation to target in the first place. No blocking findings.
Two non-blocking findings were recorded and are carried forward below as
explicit constraints for G6+, in the same spirit as G3's/G4's own forward
constraints.

## Normative test status

```text
P0-DIAG-001 — I/O budget veto              PASS
P0-DIAG-002 — memory budget veto           PASS
P0-DIAG-003 — disk-full degradation        PASS
P0-DIAG-004 — explain denial               PASS
P0-DIAG-005 — lower-cost alternative       PASS

P0-REC-001 — bounded memory                PASS
P0-REC-002 — dropped counter               PASS
P0-REC-003 — storage failure               PASS
P0-REC-004 — removable target rejected     PASS
```

`cargo test --workspace`: **189 passed, 0 failed** (157 pre-existing
G0-G4 tests unmodified + 32 new G5 tests: 10 budget + 14 psi + 8
recorder). `cargo fmt --check` and `cargo clippy --workspace
--all-targets --all-features -- -D warnings` both clean at the accepted
commit.

## Accepted invariants

These are the accepted, load-bearing decisions this milestone freezes.
Later gates build on top of them; they are not to be silently reopened.

### Diagnostic Budget Manager

- **Diagnostic safety only.** `budget.rs` decides whether a
  diagnostic/observational action may proceed given the host's current
  pressure state and the action's own declared `DiagnosticCost` -- nothing
  more.
- **Not authorization.** Never consults caller identity or any
  `guardian_core::authorization` type.
- **Not provider arbitration.** Never touches
  `guardian_core::arbitration`, ownership, or candidate selection --
  confirmed by grep: zero references anywhere in the module.
- **Not transaction control.** `guardian_core::transaction` is completely
  untouched by this gate (confirmed by empty diff against G4's accepted
  state) -- no `BudgetDecision` is constructed or consumed anywhere
  outside `budget.rs`/its own tests.
- **Not privileged execution.** No privileged calls, no I/O, no real host
  reads anywhere in the module.
- **Deterministic, fail-closed decisions.** `evaluate`/
  `evaluate_with_alternatives`/`recorder_policy_for` are pure functions of
  their inputs; every decision-relevant enum (`BudgetDecision`,
  `DenialReason`, `FreeSpaceState`, `SystemPressureState`) is closed with
  no silent-permit catch-all -- a future variant must be handled
  deliberately or the code fails to compile.
- **Expensive diagnostics cannot bypass governed budget policy.**
  Critical I/O pressure vetoes a `High` io-write-cost diagnostic
  (P0-DIAG-001); critical memory pressure vetoes a `High` memory-cost
  diagnostic (P0-DIAG-002); both proven load-bearing by real, executed
  mutation testing (disabling either veto condition broke the
  corresponding tests immediately).
- **Deliberately stateless.** There is no depletable "budget pool" to
  exhaust and reset -- every decision is evaluated fresh against current
  pressure. This is the accepted, deliberate reading of contract §19's
  actual text (per-action veto/explain behavior, not a cumulative
  currency system), confirmed correct by the independent audit rather
  than assumed.

### PSI

- **Deterministic parsing and thresholding**, exercised entirely against
  in-memory fixture text -- confirmed by grep that no real
  `/proc/pressure/*` read exists anywhere in `psi.rs` or its tests.
- **Malformed input handled safely.** Every failure path returns a real
  typed `PsiParseError`, never panics, never silently resolves to "zero
  pressure" -- proven load-bearing by mutation (a fail-open mutation that
  silently skipped an unrecognized line was caught, including the
  specific case of a malformed line appearing *alongside* an
  otherwise-valid line).
- **CPU's missing `full` line is a legitimate, distinct, explicitly
  tested state** -- never an error for any resource kind in this gate's
  model.
- **Monotonic PSI counter semantics preserved.** `MonotonicTotalCheck`
  correctly accepts a repeated/equal `total=` value and correctly rejects
  a strict decrease -- both directions independently tested and confirmed
  load-bearing by mutation.
- **Threshold severity direction is correct** (`Critical > Elevated >
  Nominal`) and threshold events fire only on genuine crossings, never on
  every observation -- confirmed by mutation (a reversed comparison was
  caught immediately).
- **No real-host polling/daemon loop introduced in G5.**
  `ThresholdMonitor`'s only public surface is push-based `observe()`/
  `teardown()`/`is_torn_down()` -- there is no method that could spin or
  poll, structurally, not merely by convention.

### Recorder

- **Bounded by governed record-count policy.** `BoundedRecorder` never
  exceeds its configured capacity at any point during a push sequence --
  proven with a real 500-push stress test asserting the bound at every
  single step, not only at the end. Explicitly bounded by record count
  only in this gate, not by serialized byte size -- see FC-1 below.
- **Deterministic eviction/drop behavior.** Overflow always evicts the
  oldest retained event (FIFO); confirmed both by a dedicated determinism
  test and by mutation (disabling eviction broke 5 of 8 recorder tests
  immediately).
- **Dropped evidence is accounted for.** A real, public `dropped_count()`
  counter increments exactly once per eviction -- exact arithmetic
  checked (not merely `> 0`), and independently confirmed load-bearing:
  a mutation that disabled only the counter increment (leaving eviction
  itself intact) broke exactly the counter-checking tests and no others,
  proving the two properties are independently, not incidentally, tested.
- **Insertion ordering is monotonic**, proven with a real multi-element
  ascending-with-repeat sequence (not a two-element toy case), confirmed
  load-bearing by a reversed-insertion mutation.
- **Removable-media exclusion is enforced.** `validate_critical_target`
  is a real, bidirectional gate -- both a removable-marked target
  (rejected) and a fixed-marked target (accepted) are exercised in the
  same test, so it cannot pass via a fixture that trivially always-accepts
  or always-rejects; confirmed load-bearing by mutation.
- **Memory-first/local safety model.** No real disk I/O anywhere in this
  gate's tests (a test-controlled temporary-directory convention matching
  G4's persistence tests is available but the recorder itself performs no
  real filesystem writes in G5); spill is modeled as a one-shot,
  non-accumulating, fallible operation that can never block or fail
  `record()` itself (P0-REC-003).
- **No production recorder daemon wiring yet.** No systemd unit, no
  D-Bus registration, no real recorder instance running anywhere --
  correctly deferred, per scope.

## Disclosed limitation (carried forward from G4, still true here)

As with G4's fsync durability barrier, in-process `cargo test` runs
cannot experimentally distinguish "the recorder's memory bound holds
under real, sustained production load" from "it holds under this gate's
stress tests" -- the 500-push and 2000-push stress tests prove the bound
holds deterministically for the *code as written*, which is the
strongest claim a fixture-only gate can make. Real production-scale
validation is a later-gate concern once a real recorder instance exists
in a running daemon.

## Forward Constraints for G6+

Neither of the following is a G5 defect -- both were explicitly recorded
as non-blocking findings by the independent audit and are preserved here,
neutrally, as constraints later gates must resolve deliberately, not by
silent omission. This mirrors the G3→G4 and G4→G5 forward-constraint
discipline already established in this project.

### FC-1 — Recorder byte boundedness

G5 proves bounded recorder growth by record count, as allowed by the
governing G5 contract's actual text (§22 specifies a bounded *queue*, not
a byte-size bound). It does not yet establish a byte-size memory/disk
bound. `Event` (the recorder's element type) carries variable-length
`String`/`BTreeMap`/`Vec` fields, so a capacity-bounded buffer of
arbitrarily large `Event`s is not itself byte-bounded.

When a later gate introduces real payloads, longer-running production
capture, or persistent recorder storage, that gate must determine whether
byte-level bounds are required and make them explicit. **Do not
retroactively treat G5 as proving a byte bound it did not implement.**

### FC-2 — `RecorderPolicy` runtime wiring

G5 implements and independently tests `RecorderPolicy` and
`recorder_policy_for()` (the P0-DIAG-003 disk-full-degradation decision)
as a distinct diagnostic-safety decision type, per the G5 handoff's
explicit requirement that this outcome be separately tested and *not*
folded into `BudgetDecision`. It is confirmed, by grep, that nothing
outside `budget.rs`/its own tests ever constructs or consumes a
`RecorderPolicy` value -- it is not yet wired into a real
production recorder+budget runtime path. This is correctly deferred per
the G5 handoff's own scope (no requirement to wire it in this gate).

The first later gate that instantiates such a runtime path (a real
recorder instance actually driven by real budget decisions) must ensure
the policy decision is actually *consumed* by that runtime path, not
merely present as an isolated, tested model. **Preserve the G4 lesson:
module presence != executed safety contract.** G4's own independent
audit found and repaired exactly this class of gap (a precondition gate
that existed in isolation but wasn't wired into `apply()`'s real call
path) -- G6+ must not repeat it here.

## Evidence index (referenced, not duplicated here)

```text
docs/guardian/30_TDD/GUARDIAN_G5_IMPLEMENTATION_HANDOFF.md
docs/guardian/30_TDD/GUARDIAN_G5_INDEPENDENT_REVIEW_HANDOFF.md
crates/guardian-core/src/{budget,psi,recorder}.rs
crates/guardian-core/tests/{budget,psi,recorder}_contract.rs
```
