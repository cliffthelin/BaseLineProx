# Guardian Phase 0 Independent Review Handoff
## G5 — Diagnostic Safety Only

This document is authoritative for the independent review of a G5
implementation candidate. Use it in place of restating the architecture in
a review prompt — the prompt should describe only the candidate SHA and
any delta from this document's expectations.

# 1. Baseline verification

- Confirm the exact baseline commit (should be `phase0-g4-transaction-engine`,
  `5b53d4a1c4e7dd467fe965bc0bc22484a6f26d72`, or a later commit the task
  explicitly names) and the candidate commit.
- Confirm `phase0-g4-transaction-engine` and every earlier gate tag
  (`phase0-g0-public-contracts`, `phase0-g1-identity-authorization`,
  `phase0-g2-privilege-topology`, `phase0-g3-core-data-models`) are
  ancestors of the candidate commit and unmoved.
- Confirm no `phase0-g5-*` tag exists yet (independent review precedes
  tagging).

# 2. Governing material to read

- `AGENTS.md`
- `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §19, §20, §21,
  §36 (P0-DIAG/P0-REC definitions), §39, §45
- `docs/guardian/30_TDD/GUARDIAN_G5_IMPLEMENTATION_HANDOFF.md` (this
  gate's authoritative implementation handoff — the candidate must match
  its required behavior, or explicitly and correctly deviate with cause)
- `docs/evidence/g4/G4_MILESTONE.md` — the accepted G4 state and its
  forward constraints FC-1..FC-4

# 3. Required verdict

Use exactly one of:

```text
PASS
PASS WITH NON-BLOCKING FINDINGS
FAIL — <short, specific label>
```

A `FAIL` label should name the actual defect class (e.g.
`FAIL — DIAGNOSTIC BUDGET FAILS OPEN`, `FAIL — RECORDER UNBOUNDED`,
`FAIL — TRANSACTION BOUNDARY VIOLATED`) — do not reuse G4's exact FAIL
labels unless the same defect class is genuinely present.

# 4. Normative contract audit

Independently re-derive, from the contract text itself (not from the
implementation handoff's paraphrase), what each of these requires, then
confirm a real test proves it:

```text
P0-DIAG-001 P0-DIAG-002 P0-DIAG-003 P0-DIAG-004 P0-DIAG-005
P0-REC-001 P0-REC-002 P0-REC-003 P0-REC-004
```

For each: exact test name, what it actually exercises, whether that is
strong enough to prove the contract requirement (not merely a test that
happens to pass), and whether the assertion could ever fail given a real
defect (a fixture "test" that can't fail is not evidence).

# 5. Diagnostic Budget fail-closed audit

- Does an unrecognized/future pressure-state or cost-class value ever
  default to `Permitted`? Construct a value the implementation's match
  arms don't explicitly enumerate (if the enum is exhaustive and closed,
  confirm that by reading it — an exhaustive Rust `enum` with no catch-all
  arm is itself the fail-closed proof; if there is a catch-all `_ =>`
  arm, check exactly what it resolves to).
- Does `P0-DIAG-004`'s denial reason genuinely distinguish *why* a
  diagnostic was denied (I/O vs. memory vs. disk-space vs. other), or does
  everything collapse into one generic "denied" value that technically
  type-checks but doesn't satisfy "explainable reason"?
- Does `P0-DIAG-003` (disk-full degradation) actually change recorder
  *behavior* (memory-first policy), or does it only produce a `Denied`
  result indistinguishable from an ordinary budget veto? These are
  different contract requirements — confirm they're not conflated into
  one code path that happens to satisfy both tests by coincidence.
- Does `P0-DIAG-005`'s cheaper-alternative selection logic operate over a
  real multi-candidate input, or is it a single hard-coded two-option
  example that would not generalize?

# 6. Diagnostic-vs-transaction scope boundary audit (the G5-specific
   analogue of G4's mutation-boundary audit)

This is the highest-priority structural check for G5, mirroring G4's §5
mutation-ordering audit.

- Confirm which of Option A (diagnostic-only scope, `guardian-core`'s
  transaction engine untouched) or Option B (explicit, narrow,
  contract-justified transaction-mutation gating) the candidate chose.
  The completion report must state this explicitly — if it doesn't,
  that alone is a finding.
- If Option A: confirm by diff that `crates/guardian-core/src/transaction/`
  is genuinely untouched (`git diff --stat <G4-tag>..<candidate> --
  crates/guardian-core/src/transaction/` should be empty). Any change
  there without an explicit, cited contract justification is out-of-scope
  drift.
- If Option B: confirm the cited contract section actually says what the
  candidate claims it says (read it yourself, do not trust the
  paraphrase), and confirm the change does not alter any already-accepted
  G4 invariant from `docs/evidence/g4/G4_MILESTONE.md` — specifically:
  `apply()`'s entry-precondition gate, the unconditional TOCTOU recheck,
  and the intent/outcome persistence ordering must remain exactly as
  accepted. A budget check, if added, must be a precondition evaluated
  *before* the transaction engine is ever invoked (analogous to
  `Validate` preceding `Authorize`), never folded inside `apply()` itself
  in a way that could weaken or bypass Finding 1/2/3's repairs.

# 7. PSI fixture model audit

- Confirm the parser handles CPU's missing `full` line as an explicit,
  distinctly-tested case — not merely "happens to work" because the
  parser is lenient about missing fields generally. Find the specific
  test; read it; confirm it constructs CPU-shaped input with no `full`
  line and asserts a specific, intentional outcome.
- Confirm a malformed PSI line produces a typed parse error, never a
  panic, and never silently resolves to "zero/no pressure" (a fail-open
  defect for a safety-relevant pressure signal).
- Confirm counter monotonicity is actually tested with a real ascending
  (or ascending-with-wrap, if the implementation handles wrap) sequence
  of `total=` values, not asserted by construction only.
- Confirm the threshold-event-triggering test genuinely proves a
  transition is detected (e.g. below-threshold sample followed by
  above-threshold sample produces exactly one event, not zero and not a
  flood), and that the teardown test genuinely exercises whatever
  stop/drop mechanism exists — not merely that the type implements
  `Drop` without any test invoking it.
- Confirm no test in this file makes a real read of `/proc/pressure/*` or
  any other real host path — grep for `/proc/pressure`, `std::fs::read`
  against non-fixture paths, or similar.

# 8. Recorder bounded-behavior audit

- **P0-REC-001**: write a real adversarial check — push substantially
  more entries than the configured capacity and assert the buffer's
  length never exceeds that capacity at any point during the push
  sequence (not only at the end).
- **P0-REC-002**: confirm the dropped-event counter is real, publicly
  observable state, and force enough overflow to prove it increments by
  exactly the right amount (off-by-one errors here are a classic defect
  class — check the exact arithmetic, not just "greater than zero").
- **P0-REC-003**: force the recorder's persistence step to fail (e.g. an
  injectable fallible sink, or a real filesystem failure analogous to
  G4's blocked-directory trick) and confirm the in-memory push/record
  operation still succeeds and nothing panics.
- **P0-REC-004**: confirm the removable-device rejection is enforced via
  a real, injectable "is this target removable" fact — not hard-coded to
  a single always-false or always-true fixture that makes the test
  trivially pass without proving the rejection logic actually branches
  correctly. Try constructing both a removable-marked and a
  non-removable-marked target and confirm the two cases produce different
  outcomes.
- Confirm no test writes to a real, non-test-controlled filesystem path
  (`/var/lib/guardian`, real `/proc`, etc).

# 9. G4/G3/G2/G1/G0 regression audit

- `git diff --stat <G4-tag>..<candidate>` for every file outside a new
  G5-scoped module/test path — anything touching
  `crates/guardian-core/src/transaction/`,
  `crates/guardian-core/src/{arbitration,authorization,identity,event,
  incident,risk}.rs`, `crates/guardian-provider-api/`, or
  `crates/guardian-daemon/` needs an explicit, individually-justified
  reason (most plausible: `DiagnosticCost`/`CostLevel` consumption reading
  those types without modifying them — confirm read-only usage, not a
  redefinition).
- Re-run the full pre-G5 test suite (157 tests as of the G4 milestone) and
  confirm zero regressions, not just a passing aggregate count.

# 10. Scope-leak audit (G6/G7/G8/G9)

- No GUI/TUI/CLI code.
- No real D-Bus provider adapter (systemd, PSI-as-a-real-read, logind,
  UDisks, UPower, AccountsService — all G8).
- No systemd unit, no D-Bus service registration, no packaging.
- No privileged-helper changes.
- No public D-Bus interface expansion.

# 11. Adversarial questions (mirror the implementation handoff's §10,
    verify each independently — do not just re-read the candidate's own
    self-check answers)

1. real host leakage
2. fail-open pressure
3. silent permit on unrecognized state
4. unbounded recorder growth
5. dropped-counter drift/off-by-one
6. persistence failure propagating as a recorder crash or a lost push
7. removable-device bypass via a default/fallback path
8. G4 transaction-boundary violation
9. G6/G7/G8/G9 leakage
10. explainability — generic "denied" instead of a real distinguishing
    reason

For each, state whether you executed a real scratch/adversarial mutation
(temporarily edit the tracked source, run tests, observe, revert — confirm
`git status --porcelain=v1` clean afterward) or reasoned by inspection,
mirroring the G4 audits' evidentiary standard. Do not accept the
candidate's own claimed self-check results as a substitute for your own
execution.

# 12. Validation

```text
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Report the actual results, independently summed across every test binary
— do not trust a printed total.

# 13. Required report

Include, at minimum: full changed-file reconciliation against the
candidate's own reported inventory (enumerate independently via
`git diff --name-status`, do not sample); §6's scope-boundary
determination and independent verification of it; the P0-DIAG/P0-REC
matrix (ID, test, what it proves, strong enough Y/N, result); the PSI
fixture model's audit results (§7); the recorder audit results (§8);
which adversarial checks were real mutations vs. inspection-only (§11);
prior-gate regression confirmation (§9); scope-leak confirmation (§10);
exact validation output (§12); blocking findings (file, contract/test,
problem, evidence, why it matters, required correction — "None" if none);
non-blocking findings (same format, or "None"); and exactly one
recommended next action from:

```text
Tag G5 and prepare G6 gate.
Repair G5 and re-review.
Reconsider diagnostic/transaction boundary model.
Resolve G5 model ambiguity before G6.
```

Then stop. Do not tag G5. Do not begin G6. Do not push unless the task
explicitly instructs it.
