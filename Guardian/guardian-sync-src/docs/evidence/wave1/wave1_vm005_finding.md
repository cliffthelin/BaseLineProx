# W1-VM-005 / W1-REC-003 — contract conflict discovered during implementation

**Status: reported, not silently resolved.** This is the primary contract
conflict this implementation pass surfaced. It is reported per AGENTS.md
("stop the affected path and report a contract issue") and the task's own
binding instruction ("If repository reality makes any normative requirement
impossible or materially ambiguous, STOP and report the contract conflict
rather than choosing a new architecture").

## What the contract requires

Handoff §8's crash-point table (and W1-REC-003) distinguishes two crash
points that both leave *some* record of an Apply attempt:

| Crash point | Required `ApplyOutcome` | Required `RecoveryClassification` |
|---|---|---|
| After durable intent persisted, before `RestartUnit` called | `NotRecorded` | `SafeToResume` |
| The `RestartUnit` D-Bus call itself was in flight when the crash occurred | `PartialOrUncertainMutation` | `StateAmbiguous` — "never `SafeToResume` for this specific point" |

W1-VM-005 requires real VM evidence of the second row: "guardian-helper
crashed mid-Apply (simulated `kill -9` at the right point where
`RestartUnit`'s call is genuinely in flight), real `StateAmbiguous`
classification reproduced (not `MustObserve`), not merely unit-tested."

## What the unmodified G4 engine actually does

`crates/guardian-core/src/transaction/engine.rs::apply` (unmodified, as
required by this handoff — §6/§10 disclose only `authorization.rs` and new
`guardian-helper` code as changed) persists the Apply-intent record with
`ApplyOutcome::NotRecorded` **immediately before** calling
`provider.apply(&action)`, and only persists a different `ApplyOutcome`
value **after** that call returns:

```rust
} else {
    record.apply_record = Some(ApplyRecord::intent_only(
        record.idempotency_key.clone(),
        clock,
    ));
}
persist(persist_dir, &PersistedTransactionRecord::from_record(record))
    .map_err(|error| EngineError::PersistenceFailed(error.to_string()))?;

let action = ActionRequest(record.idempotency_key.clone());
let outcome = match provider.apply(&action) {   // <-- the real RestartUnit call
    Ok(raw) => parse_apply_payload(&raw),
    Err(Unsupported) => ApplyOutcome::ConfirmedFailureNoMutation,
};
```

There is no durable write between "intent persisted" and "provider called
and returned" other than the intent write itself (`NotRecorded`). A process
kill strictly inside `provider.apply()`'s call window is therefore, by
construction, **durably indistinguishable** from a crash before the call
was ever attempted — both leave exactly `ApplyOutcome::NotRecorded` on
disk. `recovery::classify()`'s `classify_applying()` (also unmodified, also
required to stay that way) maps `NotRecorded` to `SafeToResume`:

```rust
None | Some(ApplyOutcome::NotRecorded | ApplyOutcome::ConfirmedFailureNoMutation) => {
    RecoveryClassification::SafeToResume
}
```

`ApplyOutcome::PartialOrUncertainMutation` — the value the contract requires
for this crash point — is only ever *written* by `parse_apply_payload` after
`provider.apply()` **returns** a value; it cannot be produced by a crash
that happens *during* the call, since nothing runs to write it in that case.

## Real VM evidence (not merely re-derived from source)

Built with `--features guardian-helper/evidence-hooks` (never part of the
production build — debian/rules never passes this flag) and
`GUARDIAN_HELPER_RESTART_APPLY_DELAY_MS=8000`, on `guardian-g9`:

1. Issued a real `RestartCapability("cups-restart", false)` call as
   `wave1allowed` (authorized). The call's own D-Bus connection reported
   `Message recipient disconnected from message bus without replying`,
   confirming the process was genuinely mid-call when killed.
2. At `21:38:04`, `kill -9`'d the running `guardian-helper` process
   (confirmed via `journalctl`: `Main process exited, code=killed,
   status=9/KILL`) — timed to land inside the 8-second delay this
   implementation's `SystemdRestartAdapter::restart_unit()` inserts before
   the real `Manager.RestartUnit` D-Bus call, under the same evidence-hooks
   discipline `CounterAdapter`'s own G7 evidence already established.
3. The durable, real, on-disk transaction record at the moment of the
   crash (`docs/evidence/wave1/40008000-0000-0000-18d3-11a31b23c0e8.txn`):

   ```
   state=applying
   apply_outcome=not_recorded
   ```

4. Restarted `guardian-helper` (`systemctl start guardian-helper`).
   Real recovery log line: `[guardian-helper] recovery:
   transaction_id=40008000-0000-0000-18d3-11a31b23c0e8 resolved ->
   Committed`. The record's final durable state:

   ```
   state=committed
   apply_outcome=confirmed_success
   last_observation=postcondition_met
   ```

This is real, reproduced evidence — not a hypothetical — that a genuine
`kill -9` strictly during the in-flight `RestartUnit` call is classified
`SafeToResume` (and automatically resumed to `Committed`, re-issuing
`RestartUnit`) by the real, unmodified G4 recovery/engine machinery, **not**
`StateAmbiguous` as the accepted handoff requires for this crash point.

## Why this was not silently worked around

Three ways of closing this gap were considered and rejected as
out-of-scope for this implementation pass:

1. **Modify `engine.rs`** to add a durable "call now in flight" write
   between the intent persist and the provider call. Rejected: §6/§10
   explicitly disclose `authorization.rs` and new `guardian-helper` code as
   the *only* changed production surfaces; `engine.rs` is required to
   remain unmodified, and this would be a real, if small, change to G4's
   own persistence sequencing that needs its own review, not a Wave-1-local
   decision.
2. **Pre-write a durable `ApplyOutcome::PartialOrUncertainMutation` marker
   from `guardian-helper` before calling `engine::apply`.** Rejected on
   inspection: `engine::apply`'s own entry logic treats any pre-existing
   non-`NotRecorded` `apply_record` outcome as evidence of a *prior*
   attempt and short-circuits to `Err(MustObserveBeforeRetry)` without ever
   calling `provider.apply()` at all — this would prevent the real
   `RestartUnit` call from ever being made, not just mark it correctly.
3. **Silently accept `SafeToResume`'s actual behavior as good enough**
   (the mechanism is arguably safe in practice, since a second
   `RestartUnit` call for the same unit is real, evidenced job-merging
   idempotent behavior — §8's own text notes exactly this: "Apply
   idempotent? Yes"). Rejected: the accepted handoff is explicit and
   emphatic that `SafeToResume` must **never** be claimed for this specific
   crash point regardless of whether a retry would happen to be safe — "no
   special-casing is introduced for this capability" cuts the other way
   too: this implementation must not decide, on its own authority, that the
   general classifier's actual (safe-in-this-instance) behavior overrides
   the contract's explicit, named requirement for this crash point.

## Disposition

This is reported as a genuine tension between two binding requirements of
the accepted contract: (a) reuse the G4 transaction engine and recovery
classifier completely unmodified, and (b) reproduce the exact
`StateAmbiguous` classification the contract's own crash table assigns to a
genuinely-in-flight-call crash. Given the real, unmodified engine's actual
persistence sequencing, (a) and (b) are not simultaneously achievable for
Wave 1's own implementation surface as scoped. A governed decision is
needed on which requirement yields — most plausibly, either accepting
`SafeToResume`'s real behavior for this specific crash point (with a
documented capability-level justification, mirroring the `SafeToResume`
authorization-invariant precedent already established for
`GuardedWrite`/`CounterAdapter`), or a small, explicitly-scoped G4 engine
change (a durable "call in flight" intent marker, written and read only by
`engine::apply`/`classify_applying`) under its own gate.

No workaround was implemented. `run_restart_capability`'s Apply step calls
the real, unmodified `txn::engine::apply` exactly once, with no additional
durable writes around it beyond what `engine.rs` itself performs.

---

## Resolution (repair pass, governed decision applied)

**The project owner adjudicated this conflict explicitly: do not weaken
W1-REC-003. Add the minimum durable G4 metadata needed to distinguish the
two pre/post-dispatch cases** — the second alternative this finding itself
proposed above ("a small, explicitly-scoped G4 engine change: a durable
'call in flight' intent marker, written and read only by
`engine::apply`/`classify_applying`"), now implemented as a disclosed,
narrow, Wave-1-required extension to G4. See
`docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §50.x
("G4 extension: durable Apply-dispatch marker") for the full governance
record of what changed and why, and why this is a genuine gap in the
original G4 design rather than a Wave-1-specific hack.

### What changed (production code)

- `crates/guardian-core/src/transaction/apply.rs`: `ApplyRecord` gained one
  new durable field, `dispatch_marker: bool` (defaults `false` in
  `ApplyRecord::intent_only`).
- `crates/guardian-core/src/transaction/engine.rs`: `apply()` now performs
  **three** durable persists instead of two — Apply-intent (unchanged),
  then a new durable dispatch-start-marker persist (`dispatch_marker =
  true`) immediately before `provider.apply(&action)` is invoked, then the
  existing Apply-outcome persist after the call returns. A
  `NotRecorded`-with-`dispatch_marker`-already-set `apply_record` on entry
  is also now refused with `MustObserveBeforeRetry` (defense in depth,
  alongside the classifier fix below).
- `crates/guardian-core/src/transaction/persistence.rs`:
  `PersistedTransactionRecord` gained `dispatch_marker: bool`
  (`from_record`/`to_recovery_snapshot`/`serialize`/`deserialize` all
  updated; absent on disk defaults to `false` for backward compatibility
  with records written before this extension).
- `crates/guardian-core/src/transaction/recovery.rs`: `RecoverySnapshot`
  gained `dispatch_marker: bool`; `classify_applying` now returns
  `StateAmbiguous` (not `SafeToResume`) when `apply_outcome` is
  `NotRecorded`/absent **and** `dispatch_marker` is `true`.

`engine.rs`/`recovery.rs` are therefore *not* unmodified relative to G4 as
originally tagged — that is the explicit, disclosed point of this
extension, not an oversight. Nothing about G4 changes outside this narrow
Apply-dispatch-observability question: the state machine's 15 states and
legal-transition graph, the six `RecoveryClassification` variants, and
every other classification branch are byte-for-byte unchanged.

### Before/after crash classification (this exact crash point)

| | Before (original finding) | After (this repair) |
|---|---|---|
| Durable record at crash | `state=applying`, `apply_outcome=not_recorded` | `state=applying`, `apply_outcome=not_recorded`, `dispatch_marker=true` |
| `recovery::classify` | `SafeToResume` | `StateAmbiguous` |
| `resolve_recovered_restart` action | Resume `apply` (re-issues `RestartUnit`), reaching `Committed` | Best-effort compensating rollback (`RollbackKind::BestEffort`), reaching `RolledBack` |

### Real VM re-evidence (not merely new unit tests)

Re-ran the identical W1-VM-005 procedure from the original finding above,
against `guardian-g9`, with the repaired binary (`--features
guardian-helper/evidence-hooks`, `GUARDIAN_HELPER_RESTART_APPLY_DELAY_MS=8000`):

1. Issued a real `RestartCapability("cups-restart", false)` call as
   `wave1allowed`. The call again failed with `Message recipient
   disconnected from message bus without replying`, confirming the process
   was genuinely mid-call when killed.
2. `kill -9`'d the running `guardian-helper` process while inside the
   8-second pre-`RestartUnit` delay (confirmed via `journalctl`:
   `Main process exited, code=killed, status=9/KILL`).
3. The durable, real, on-disk transaction record at the moment of the
   crash (`docs/evidence/wave1/w1_vm005_fixed_txn.txt`,
   `transaction_id=40008000-0000-0000-18d3-2a530e14b82a`):

   ```
   state=applying
   apply_outcome=not_recorded
   dispatch_marker=true
   ```

   — the dispatch marker is durably set, exactly as designed, distinguishing
   this from the pre-dispatch case.
4. `systemd`'s own `Restart=on-failure` immediately restarted
   `guardian-helper` (real recovery log,
   `docs/evidence/wave1/w1_vm005_fixed_journal.txt`):

   ```
   [guardian-helper] recovery: transaction_id=40008000-0000-0000-18d3-2a530e14b82a resolved -> RolledBack
   ```

   The record's final durable state:

   ```
   state=rolled_back
   apply_outcome=not_recorded
   dispatch_marker=true
   rollback_result=confirmed_restored
   ```

This is real, reproduced evidence that the identical `kill -9`-during-
in-flight-`RestartUnit` scenario that previously reached `Committed` (an
automatic, unsafe replay of `RestartUnit`) now reaches `RolledBack` via
`StateAmbiguous`'s fail-closed best-effort-rollback path — never
`SafeToResume`, never a silent automatic replay. Note this is the same
"disclosed as such, never presented as a true rollback" `BestEffort`
compensating-restart semantics W1-REC-007 already establishes for other
`StateAmbiguous`/`MustRollback` cases in this same capability family — a
compensating restart is itself a real, idempotent, evidenced-safe recovery
action for this specific unit, it is simply no longer reached via the
wrong (`SafeToResume`) classification.

### Automated test coverage added

- `crates/guardian-core/tests/transaction_recovery_contract.rs`: five new
  tests, including the exhaustive
  `no_ambiguous_applying_snapshot_ever_classifies_as_safe_to_resume`
  property test.
- `crates/guardian-core/tests/transaction_apply_persistence_contract.rs`:
  `crash_boundary_2b_dispatch_marker_set_but_outcome_never_recorded_is_state_ambiguous`,
  `dispatch_marker_is_durable_before_provider_apply_is_ever_invoked`
  (proves the ordering guarantee through the real, wired `engine::apply`
  path, not a hand-built fixture), and
  `crash_boundary_4b_apply_failure_durable_outcome_survives_independent_reload`.
- `crates/guardian-core/tests/transaction_persistence_contract.rs`:
  `dispatch_marker_round_trips_through_persistence` and
  `absent_dispatch_marker_field_defaults_to_false_for_backward_compatibility`.
- All pre-existing G4/recovery tests pass unmodified (the
  `Applying`+`NotRecorded`+no-marker fixtures already in
  `crates/guardian-helper/src/main.rs`'s test module are, by construction,
  now exactly the requirement-1 regression proof: crash strictly before the
  dispatch marker retains pre-dispatch `SafeToResume` semantics).
