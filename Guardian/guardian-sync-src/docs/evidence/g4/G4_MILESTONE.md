# Guardian Phase 0 — G4 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Accepted commit and tag

```text
Accepted commit: 5b53d4a1c4e7dd467fe965bc0bc22484a6f26d72
G4 tag:          phase0-g4-transaction-engine (annotated, points to 5b53d4a)
```

Implementation landed across two commits: `991feb4` (transaction engine —
state machine, apply/observe/rollback/cancellation step functions, bounded
persistence — initial candidate) and `5b53d4a` (repair closing the three
blocking findings from the initial independent audit).

## Independent review — two rounds

G4 went through independent review twice, unlike G0–G3, because the first
round found real blocking defects rather than only non-blocking findings.
Both rounds are preserved here as part of the accepted history — the
initial `FAIL` is not erased or superseded silently.

### Round 1 — initial candidate (`991feb4`)

**Verdict: `FAIL — TRANSACTION ORDERING UNSAFE`.**

Three blocking findings:

1. **Mutation possible without authorization/state precondition.**
   `engine::apply()` had no precondition gate on the transaction's state —
   it invoked `provider.apply()` (the real mutation) even when called on a
   record that had never passed through `Validate`/`Authorize` (e.g. still
   `Created`). The illegal-transition error only fired *after* the
   mutation had already happened, via the subsequent attempted transition
   to `Observing`.
2. **Unsafe recovery/resume exposure from the same root issue.**
   `recovery::classify()` is a pure classifier with no execution
   authority, and nothing in the codebase called it and then resumed
   execution — but nothing in the API shape prevented a future caller
   from taking a `SafeToResume` classification straight into `apply()`
   without a fresh revision/ownership/TOCTOU recheck, because `apply()`
   itself performed no such recheck regardless of how a record arrived at
   an apparently-resumable state.
3. **Persistence/durability not wired into the real Apply path.**
   The G4 handoff's §19.1 durable ordering (persist intent → durability
   barrier → invoke provider → persist outcome) did not exist as executed
   code. `engine::apply()` never called `persistence::persist()` at all —
   only a doc comment described what a caller *could* do — and `persist()`
   itself had no `fsync`/`sync_all` durability barrier (atomic
   temp-file-then-rename only, which proves atomicity but not durability).

Two non-blocking findings were also recorded: no dedicated test for a
duplicate `apply()` call when the prior outcome was
`ConfirmedFailureNoMutation` specifically, and persistence/recovery were
never exercised together as an integrated flow (a real persisted record
was never loaded and fed into `classify()`).

### Repair (`5b53d4a`)

All three blocking findings were closed:

- `apply()` gained a typed, unconditional entry-precondition gate —
  `Authorized` (fresh attempt), `Applying` with a genuine prior
  `ApplyRecord` (in-flight retry), or `Observing` with a durably-known
  `ConfirmedSuccess` (idempotent no-op) — checked *before* anything else,
  including before the provider is ever reached.
- The immediate-pre-Apply revision/TOCTOU recheck
  (`revalidate_immediately_before_apply`) is now called unconditionally
  from inside `apply()`'s own entry path, not left as a separate function
  a caller could omit.
- `persist()` now performs a real durability barrier (temp-file `fsync`
  before rename, directory `fsync` after rename), and `engine::apply()`
  calls it for real, both before invoking the provider (persistence
  failure blocks the provider call entirely) and after recording the
  outcome.
- Both non-blocking findings were also closed: a dedicated
  `ConfirmedFailureNoMutation` duplicate-retry test was added, and a real
  `persist()` → `load()` → `classify()` integrated flow now exists,
  including a `last_observation` field so a genuinely reloaded `Observing`
  record can be classified from real persisted evidence.

### Round 2 — repair candidate (`5b53d4a`)

**Verdict: `PASS — G4 REPAIR ACCEPTED`.**

The second independent audit re-derived all findings from scratch (did not
trust the repair's own narrative), independently re-ran all twelve
`P0-TXN-*` tests against the contract text, and executed six adversarial
mutations directly against the tracked source (each temporarily applied,
run, and reverted): disabling the entry gate, removing the TOCTOU recheck,
skipping the intent-persist call, removing both `fsync` calls, collapsing
lost-response into safe retry, and widening the entry gate to let a
`ConfirmedFailureNoMutation` duplicate read as success. Five of six were
caught immediately by the existing test suite; the sixth (removing
`fsync`) was not — see the disclosed limitation below. No blocking or
non-blocking findings were recorded in round 2.

## Normative test status

```text
P0-TXN-001 — happy path                                    PASS
P0-TXN-002 — validation failure (incl. NB-1 unknown privilege)  PASS
P0-TXN-003 — authorization denied                           PASS
P0-TXN-004 — apply failure (clean + partial/uncertain)       PASS
P0-TXN-005 — observation failure does not commit             PASS
P0-TXN-006 — rollback success (Native/Emulated/BestEffort)   PASS
P0-TXN-007 — rollback failure (explicit + unconfirmed BestEffort)  PASS
P0-TXN-008 — terminal-state immutability                     PASS
P0-TXN-009 — idempotent retry / lost response                PASS
P0-TXN-010 — stale resource identity                         PASS
P0-TXN-011 — crash/restart recovery (all six classifications, now via real persist/load)  PASS
P0-TXN-012 — client disconnect preserves the audit record     PASS
```

`cargo test --workspace`: **157 passed, 0 failed** (75 pre-existing
G0–G3 tests unmodified + 82 new G4 tests: 43 engine-contract + 8
apply-persistence-integration + 8 persistence + 10 recovery + 9 state + 4
id). `cargo fmt --check` and `cargo clippy --workspace --all-targets
--all-features -- -D warnings` both clean at the accepted commit.

## Final transaction invariants established by G4

These are the accepted, load-bearing decisions this milestone freezes.
Later gates build on top of them; they are not to be silently reopened.

**State machine**

- Exactly the contract's 15 states (§14), exactly its transition table.
  `TransactionRecord::transition_to` is the only way `state` is ever
  mutated; terminal states (`Committed`, `RolledBack`, `Rejected`,
  `Failed`, `RollbackFailed`, `Expired`, `Cancelled`) reject every further
  transition unconditionally.
- `Cancelled`/`Expired` are legal *direct* transitions only from
  pre-mutation states. A cancellation/expiry request arriving during
  `Applying`/`Observing`/`RollingBack` is recorded as a typed fact
  (`cancellation_requested`/`deadline_expired`) without causing an
  immediate transition — the transaction always continues to a real,
  reconciled terminal outcome.

**Mutation boundary (Finding 1)**

- `provider.apply()` is reachable only from an explicit, narrow, typed
  entry condition: `Authorized`, or `Applying`/`Observing` with a
  genuine prior `ApplyRecord` proving a legitimate earlier attempt. Every
  other state — including every pre-Authorize state and every terminal
  state — is rejected before the provider is ever reached, not detected
  afterward via a failed state transition.

**Revision/TOCTOU authority (Finding 2, resolves G3's NB-2)**

- `revision` is owned exclusively by `ArbitrationStateSource`, never by a
  caller-supplied value or a value baked into a previously-authorized
  record. `apply()` unconditionally re-derives it immediately before any
  mutation, structurally — not as an optional step a caller could skip.
- `recovery::classify()` remains a pure classifier with no execution
  authority; `SafeToResume` is not itself mutation authority, and nothing
  in this codebase composes a classification result directly into
  `apply()` without passing back through this same unconditional recheck.

**Durable ordering (Finding 3, resolves G3's NB-3 for `RollbackKind`)**

- Apply-intent is durably persisted (temp-file `fsync`, atomic rename,
  directory `fsync`) *before* the provider is ever invoked; persistence
  failure at this step unconditionally prevents the provider call.
  Apply-outcome is durably persisted again immediately after.
- `PersistedTransactionRecord` is a deliberately bounded projection
  (schema-versioned, atomic, fails closed on an unrecognized version or a
  corrupt record) — not full-fidelity serialization of every nested type.

**Idempotency**

- `ConfirmedFailureNoMutation` is terminal (`Failed`) and stays that way —
  a duplicate `apply()` call against it is a typed rejection, never a
  silent `Ok(())` that could be misread as success.
- `ResponseLostOrUnknown` (the provider may have run, but the outcome was
  never durably recorded) can never be treated as safe to blindly retry —
  it requires `Observe` first, proven with a real fixture call-counter
  that a retry never invokes the provider a second time.

**Recovery**

- All six required classifications (`SafeToResume`, `MustObserve`,
  `MustRollback`, `AlreadyCommitted`, `StateAmbiguous`,
  `RequiresHumanRecovery`) are real, distinct outputs of `classify()`, now
  proven reachable from a genuinely persisted-then-reloaded record (not
  only from hand-built in-memory fixtures).

**G1/G2 authorization boundary (unchanged, reconfirmed)**

- `Validate` is not `Authorize`; `write_permitted` is not caller
  authorization; no field on `TransactionRecord` resembles authorization
  proof a privileged helper could be tempted to trust instead of its own
  real check. The privileged helper (established at G2) is untouched by
  G4 — confirmed empty diff.

## Disclosed limitation

Ordinary in-process `cargo test` runs cannot experimentally prove that the
`fsync`/`sync_all` durability barrier survives a real crash or power
loss — the OS page cache returns correct data to a reader regardless of
whether `fsync` actually ran, so no fast unit test can distinguish
"`fsync` executed" from "`fsync` silently removed." This was confirmed
directly during round 2's adversarial testing: removing both `sync_all`
calls from `persist()` caused zero test failures across the full
157-test suite.

This is **not** evidence the durability barrier is fake. Round 2
independently confirmed, by direct code inspection (not by test outcome),
that both `sync_all()` calls are real, unconditional, and on the sole
executed path every `persist()` call takes — one on the temp file before
`rename`, one on the containing directory after. The limitation is
disclosed here rather than silently assumed away: G4's crash-durability
claim rests on code inspection plus the atomic-rename behavior that *is*
testable (no partial file ever readable), not on an in-process test that
could ever observe a missing `fsync`. A later gate that needs experimental
proof of crash durability (e.g. real power-loss or `dm-flakey` testing)
must build that separately — it is out of scope for G4's fixture-only,
single-process test suite.

## Forward constraints for G5+

None of the following are G4 defects — they are explicit scope boundaries
this gate deliberately left for later gates, recorded here so they are not
silently assumed solved.

### FC-1 — `DiagnosticCost` is still a declared-but-unconsumed type

G3 introduced `guardian_provider_api::DiagnosticCost`/`CostLevel` as a
typed placeholder field on `CapabilityRecord`, explicitly deferring the
veto/scheduling logic to G5's Diagnostic Budget Manager. G4's
`TransactionRecord` does not read or reference `DiagnosticCost` anywhere —
a transaction's `risk_class` (`guardian_core::risk::Risk`) and a
capability's `diagnostic_cost` remain two independent, uncorrelated
dimensions after G4. **G5 must decide explicitly whether/how a
transaction's risk class and a diagnostic action's cost class interact**
(the contract's §19 examples are diagnostic-only — "severe I/O pressure
can veto an I/O-write-heavy trace" — not transaction-mutation-specific);
G5 must not assume G4 already wired this.

### FC-2 — No G4 type currently represents "budget denied" as a typed outcome

G4's `EngineError`/`ApplyOutcome`/`RollbackOutcome` enums are exhaustive
for the transaction-engine's own concerns (state, revision, persistence,
authorization) and contain nothing resembling "denied due to resource
pressure." G5's Diagnostic Budget Manager needs its own typed denial
reason (§19: "a denied diagnostic action produces an explainable reason,"
P0-DIAG-004) — it must not be retrofitted as a new `EngineError` variant
that would blur diagnostic-budget concerns into transaction-engine
concerns G4 deliberately kept separate.

### FC-3 — The Flight Recorder has no relationship to G4's persistence module

G4's `persistence` module is transaction-record-specific, bounded, and
schema-versioned for exactly the recovery-classification fields G4 needs
— it is not a general-purpose bounded/ring-buffer recorder. G5's Flight
Recorder (P0-REC-001..004: bounded memory, dropped-event counter, survives
storage failure, rejects a monitored-removable-device target) is a
distinct mechanism with different guarantees (bounded *memory*, not
durable-by-design) and must be built as its own module, not layered onto
`guardian_core::transaction::persistence`.

### FC-4 — PSI has no G3/G4 representation yet

Nothing in G0–G4 parses or models `/proc/pressure/*`. G5 is the first
gate that needs a PSI type at all — there is no existing G3/G4 enum or
struct to reuse or extend for pressure state; it is new ground, not a
gap in an existing model.

## Evidence index (referenced, not duplicated here)

```text
docs/guardian/30_TDD/GUARDIAN_G4_IMPLEMENTATION_HANDOFF.md
docs/guardian/30_TDD/GUARDIAN_G4_INDEPENDENT_REVIEW_HANDOFF.md
crates/guardian-core/src/transaction/{mod,id,state,apply,rollback,observation,arbitration_source,record,persistence,recovery,engine}.rs
crates/guardian-core/src/arbitration.rs (RollbackKind::FromStr addition, NB-3 closure)
crates/guardian-core/tests/transaction_{id,state,apply,persistence,recovery,engine}_contract.rs
crates/guardian-core/tests/transaction_apply_persistence_contract.rs
```
