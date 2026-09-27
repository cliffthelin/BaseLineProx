# G7 — Production Daemon: Repair Evidence

Repairs the four blocking findings of the independent G7 implementation
audit. Preserves everything the audit independently validated: direct
`client → guardian-helper` topology, no daemon relay, helper-owned Class A
transactions, daemon-owned Class B transactions, disjoint persistent-state
directories, independent real caller resolution, real polkit
authorization, root helper with empty Linux capability sets, unprivileged
daemon, and existing systemd hardening. None of that was touched.

## Original audit verdict

```text
FAIL — G7 TRANSACTION/RECOVERY CONTRACT VIOLATED
```

Four blocking findings: (1) startup recovery classified nonterminal
transactions but never resolved them, violating contract §14.2; (2)
`Guardian1.Transactions1`/`AttemptProviderDelegatedWrite` was an
unjustified permanent public-API addition; (3) G5 FC-2 was claimed closed
but `RecorderPolicy`'s two branches produced no real behavioral
difference; (4) zero automated tests existed for meaningful pure-Rust
logic added in G7.

## Repair 1 — recovery executes, not just classifies

`crates/guardian-helper/src/main.rs`'s `recover_on_startup` now calls
[`resolve_recovered`] for every nonterminal persisted record, which
executes the real G4-legal action for its classification using only
G4's existing, unmodified `engine`/`persistence`/`recovery` functions —
never a new state, never a shortcut transition the state machine doesn't
already allow.

### Recovery classification → action matrix

```text
AlreadyCommitted        -> no action (already resolved; the fact that
                            AlreadyCommitted is now even reachable is
                            itself part of this repair -- see below)
SafeToResume             -> reconstruct the minimal record G4's bounded
                            persistence contract actually captured;
                            re-run engine::snapshot (fresh, real) to
                            satisfy apply()'s MissingSnapshot
                            precondition; re-run engine::apply from
                            exactly the Applying stage it was legitimately
                            in; if the result reaches Observing, continue
                            through observe -> confirm/rollback; persist
                            after every step
MustObserve               -> reconstruct at Observing; run engine::observe
                            (real, fresh); confirm on PostconditionMet,
                            rollback otherwise; persist after every step
MustRollback / StateAmbiguous -> reconstruct at the persisted state;
                            run engine::rollback (idempotent, see below);
                            persist the result
RequiresHumanRecovery      -> deliberately not automated -- durably logged
                            (journald) and left nonterminal; this *is*
                            "clearly represent that disposition" for the
                            one classification G4 itself says no
                            automatic action is safe for
```

Terminal records (already `Committed`/`RolledBack`/`Rejected`/`Failed`/
`RollbackFailed`/`Expired`/`Cancelled`) are skipped before classification
is even attempted — reprocessing an immutable terminal record on every
restart forever was itself a defect in the original candidate (it
misclassified some terminal shapes via `classify`'s catch-all).

### Never repeats an ambiguous Apply — `CounterAdapter` is now genuinely idempotent

The independent audit's own re-run showed `apply()`'s idempotency-key
short-circuit only protects against a second *engine* call — the
*adapter* underneath it was never actually idempotent. Repaired: `apply`
and `rollback` on `CounterAdapter` are now keyed on the real per-attempt
idempotency key G4's engine already threads through `ActionRequest`
(`record.idempotency_key`, unchanged G4 wiring) — a retried `apply` or
`rollback` for the same key is a genuine no-op, proven by a dedicated test
(`recovery_does_not_double_apply_on_resume`) that pre-applies a key
directly against the adapter, then resumes, and asserts the counter did
not move a second time.

### Persist after every step, not only inside `apply()`

The audit's central finding: a genuinely successful, fully-confirmed
transaction and a transaction that crashed before `Observe` were
byte-identical on disk (both `state=observing`), because `persist()` was
only ever called from inside `engine::apply()`. Repaired: `guardian-helper`
now calls G4's existing, unmodified `persistence::persist()` after every
meaningful step (`observe`, `confirm`, `rollback`) via a shared
`persist_now` helper — no G4 code changed, only new call sites using
G4's already-public API.

### Before/after persisted-record examples (real, from the repaired candidate's fresh VM run)

**Before this repair** (original candidate, any successful transaction):

```text
state=observing
apply_outcome=confirmed_success
(no last_observation field -- never captured)
```

**After this repair** (repaired candidate, real successful transaction,
captured fresh):

```text
state=committed
apply_outcome=confirmed_success
last_observation=postcondition_met
```

**A genuinely crashed transaction, real `kill -9` during a real 6-second
delayed Apply, immediately after the crash:**

```text
state=applying
apply_outcome=not_recorded
```

**The identical transaction, real, after exactly one real
`systemctl restart`:**

```text
state=committed
apply_outcome=confirmed_success
last_observation=postcondition_met
```

### Proof that repeated restarts resolve rather than loop forever

Real, fresh VM sequence: crash during a real in-flight Apply, then four
real consecutive `systemctl restart` cycles (one that performs the
recovery, three more afterward). Full recovery-related journal across all
four restarts:

```text
[guardian-helper] recovery: transaction_id=40008000-...-40e12be8a48a resolved -> Committed
```

That line appears **exactly once** — the three subsequent restarts
produced zero recovery log lines, because the record was already terminal
and correctly skipped. The counter (`3`) was identical before and after
all three follow-up restarts — no re-mutation. Automated proof of the
same property: `repeated_restart_does_not_loop_forever_on_the_same_stuck_record`
(calls `recover_on_startup` three times against one fixture record,
asserts it reaches a terminal state and stays there).

### Durability guarantees not weakened

`apply()`'s unconditional entry-precondition gate, the immediate-pre-Apply
TOCTOU revalidation, the durable Apply-intent-before-outcome ordering, and
terminal-state immutability are all G4's original, completely unmodified
code — the repair only adds new callers of `snapshot`/`apply`/`observe`/
`confirm`/`rollback`/`persist` from exactly the states G4's own
`is_legal_transition` table already permits (confirmed by reading
`crates/guardian-core/src/transaction/state.rs` directly before
implementing: `Applying -> Observing|Failed|RollingBack` are the only
legal successors, `Applying -> Cancelled/Expired` is explicitly and
permanently forbidden by G4's own design — the repair never attempts it).

## Repair 2 — `Guardian1.Transactions1` removed from production

`crates/guardian-daemon/src/bin/guardian-daemon.rs` no longer serves any
object beyond `/io/github/cliffthelin/Guardian1` with the frozen G0
`GuardianContract` (`ContractVersion`, `ServiceState` only — confirmed via
fresh, independent `gdbus introspect --recurse` after a real reboot,
included in `repaired-guardian1-introspection.txt`). `StandInProviderAdapter`,
the Class B transaction engine instantiation, and the `AttemptProviderDelegatedWrite`
method no longer exist anywhere in the production crate.

Class B's architecture is now evidenced by `tests/vm/g7-class-b-prototype/`
— a standalone, non-workspace-member Cargo project (mirrors
`tests/vm/g2-model-b/`'s exact precedent: its own `[workspace]`+`[package]`,
never added to the root workspace's `members`), explicitly marked
NON-PRODUCTION/DISPOSABLE in its own module doc comment, owning a
genuinely separate bus name (`io.github.cliffthelin.G7ClassBPrototype1`,
never `Guardian1`). Real fresh-VM run: built, deployed under a transient
`systemd-run` unit, called twice by a real client binary (`1`, `2` —
real, distinct counter increments), confirming the same daemon-owned,
helper-absent, provider-delegated-authorization pattern the original
candidate demonstrated — without it being permanent production API.

## Repair 3 — G5 FC-2 claim corrected

The original candidate's `RecorderPolicy::Normal`/`MemoryFirst` branches
inside the (now-removed) Class B method produced no real behavioral
difference beyond a log line — the audit correctly found this did not
meet FC-2's bar. The repair does not manufacture a spill subsystem to
force closure. Instead:

- The `recorder_policy_for()` evaluation moved out of the removed Class B
  method into a genuine, permanent, periodic (`30s`) no-privilege
  monitoring tick (`monitoring_tick` in `guardian-daemon.rs`) — real
  production runtime path, Class C per the G7 handoff's own
  classification, not tied to any client request or evidence-only method.
- Every log line and every doc comment now states explicitly: **FC-2
  remains open.** No spill/retention sink exists for either policy
  branch in this build. Closure is assigned to the first gate that
  instantiates an actual spill/retention path — not claimed here.
- Real fresh-VM evidence: `[guardian-daemon] monitoring tick: ... policy=Normal free_space=Sufficient (FC-2 not closed: no spill sink wired)`, captured independently of any client call, ticking on its own.

**G4 FC-3** (`Flight Recorder and transaction persistence remain
deliberately independent`) is unchanged and still correct — no code path
in either binary references a transaction ID from a recorder event or
vice versa. This disposition will be carried into the eventual
`G7_MILESTONE.md` verbatim when G7 is published; recording that
commitment here per the audit's non-blocking finding.

## Repair 4 — automated Layer-1 tests added

```text
Before repair: 189 passed, 0 failed (0 in either new G7 crate)
After repair:  204 passed, 0 failed
  +11 in crates/guardian-helper (adapter read/write/idempotent-apply/
       idempotent-rollback/saturating-boundary; recovery resume-to-terminal;
       recovery-does-not-double-apply; already-terminal-untouched;
       repeated-restart-does-not-loop-forever; corrupt-record-does-not-crash)
  +4  in crates/guardian-daemon (free-space probe sufficient/cleanup;
       monitoring tick records a real event; recorder bound respected
       across many ticks)
```

All new tests use `std::env::temp_dir()` fixtures — no VM, no privilege,
no systemd required to run them (`cargo test --workspace`).

## Evidence hooks — reassessed

`GUARDIAN_HELPER_APPLY_DELAY_MS` is now gated behind a Cargo feature
(`evidence-hooks`, off by default) on `guardian-helper`; the corresponding
code block does not exist at all in a plain `cargo build --release`
(confirmed: the feature was required explicitly for this repair's own VM
build). `GUARDIAN_DAEMON_APPLY_DELAY_MS` no longer exists at all —
removed along with the Class B method it belonged to (`guardian-daemon`
has no Apply path left in production). Not attacker-controlled via D-Bus
either way — only a local systemd `Environment=` directive (admin-only)
can set the underlying variable, and now only when the crate was
explicitly built with `--features evidence-hooks`.

## Fresh real-VM evidence (repaired candidate)

Disposable Ubuntu 26.04 LTS VM (`guardian-g7-repair-vm`), independently
built (`--features guardian-helper/evidence-hooks` for this pass only),
deployed, evidenced, torn down (stopped/deleted/purged) within this
repair. Re-proved:

```text
Real reboot: both units active within seconds of `uptime: up 0 min`.
Privilege (post-reboot, /proc/<pid>/status): daemon UID 999, helper UID 0,
  all Cap{Inh,Prm,Eff,Bnd,Amb}=0 for both, NoNewPrivs=1 for both --
  identical to every prior measurement.
Class A direct call: guardiang7caller -> GuardedWrite -> real grant (1);
  guardiang7denied -> real NotAuthorized denial.
Restart continuity: counter 1 -> restart -> next call -> 2.
Helper-unavailable fail-closed: stopped guardian-helper, direct call ->
  real ServiceUnknown, counter unchanged.
Guardian1 introspection: ContractVersion/ServiceState ONLY -- confirmed
  Transactions1 is gone.
Crash-during-real-in-flight-Apply -> real kill -9 -> ONE real restart ->
  durable Committed state, last_observation=postcondition_met.
Four total restarts after the crash -> exactly one recovery log line,
  counter unchanged across the following three -- no loop, no re-mutation.
Class B disposable prototype: built, deployed under a transient
  systemd-run unit on its own bus name, two real client calls -> 1, 2.
systemd-analyze security: daemon 0.6 SAFE / helper 1.1 OK -- unchanged.
```

Raw artifacts: `repaired-guardian-daemon-security.txt`,
`repaired-guardian-helper-security.txt`, `repaired-combined-journal.txt`,
`repaired-guardian1-introspection.txt`,
`repaired-guardianhelper1-introspection.txt`.

## Validation

```text
cargo fmt --check:      clean
cargo clippy --workspace --all-targets --all-features -- -D warnings: clean
cargo test --workspace: 204 passed, 0 failed
```

## Scope audit

No G8 real providers implemented (Class B's stand-in remains a minimal
typed fixture, now in a disposable prototype rather than production). No
G9 clients/CLI/TUI/GUI/indicator. No change to G0-G6 accepted artifacts.
`tests/vm/g6-daemon-evidence-stub` untouched. `guardian-core`'s only
change across the entire G7 candidate remains the one narrow, additive
`PolkitAction::GuardianBoundedWrite` variant (unchanged by this repair).

## Teardown

`guardian-g7-repair-vm` stopped, deleted, and purged; `multipass list`
confirms no instances remain.

## Second repair round — closes the focused re-audit's two remaining blockers

A focused independent re-audit of the repair above found two further
blocking findings, both narrow: (1) `resolve_recovered`'s automated
coverage only exercised `SafeToResume` and the terminal short-circuit —
`MustObserve`, `MustRollback`, `StateAmbiguous`, and
`RequiresHumanRecovery` had zero direct test coverage, and no test
exercised a genuine failure during recovery itself; (2) the safety
invariant making `SafeToResume`'s resumed `Apply` call safe without a
fresh live-caller authorization was real (independently verified true by
the re-audit) but was not written down anywhere.

### `AlreadyCommitted` dead-branch disposition

Independently reconfirmed by the re-audit and left in place as a **kept,
documented, unreachable match arm** — not removed, because `classify()`'s
own signature is not going away and a future G4 change that made
`AlreadyCommitted` reachable from a genuinely nonterminal state should not
silently start hitting a `todo!()`/removed arm. `resolve_recovered`'s doc
comment now explains exactly why the arm is unreachable via this
function's own call to `classify()`: every record with `state ==
Committed` is always terminal and is always caught by the terminal
short-circuit first. The misleadingly-named existing test was renamed
`recovery_skips_a_committed_record_via_the_terminal_short_circuit_not_the_classify_arm`
to describe what it actually exercises.

### `RequiresHumanRecovery` made genuinely reachable

Tracing `classify()`'s own match arms found `RequiresHumanRecovery`'s
catch-all (`_ =>`) only ever fires for already-terminal states — and the
original terminal short-circuit intercepted every terminal state before
`classify()` ran, making `RequiresHumanRecovery` **also** unreachable, the
same defect as `AlreadyCommitted`. Fixed by excluding `RollbackFailed`
specifically from the generic terminal short-circuit —
`classify()`'s own doc comment names `RollbackFailed` as the one
meaningful terminal state needing continued human attention ("an
unresolved rollback with no further automated path"), and `RollbackFailed`
is not explicitly matched by any of `classify()`'s other arms, so it falls
through to `RequiresHumanRecovery` as G4's own documented intent already
implied. No new terminal state was invented; `RollbackFailed` was already
a real G4 state, and `resolve_recovered`'s `RequiresHumanRecovery` arm
attempts no transition at all — the record is left exactly as persisted,
logged loudly on every restart (deliberately, unlike genuinely-resolved
terminal states) until a human resolves it out-of-band.

### `resolve_recovered` restructured for correct failure semantics

Introduced `finish_recovery(&TransactionRecord) -> Result<RecoveryOutcome, String>`:
a recovery action is judged successful if the record reached **any**
terminal state (`Committed`, `RolledBack`, `Failed`, `RollbackFailed` all
count — recovery's job is reaching a durable, unambiguous disposition, not
making the underlying business operation succeed), and an error only if
the record is still nonterminal afterward (a genuine engine-level
problem). This correctly distinguishes "the operation itself failed
(rolled back) but recovery succeeded" from "recovery itself did not
resolve the record" — the previous version conflated these by propagating
every `observe_then_resolve`/`rollback` `Err` as a hard recovery failure
even when the rollback it represented had completed successfully and
durably.

### New tests (8 added; 1 renamed, not counted as new)

```text
must_observe_confirms_without_replaying_apply
  -- state=Observing, apply_outcome=ConfirmedSuccess, no observation yet;
     confirms Apply is never invoked (counter unchanged before Observe),
     resolves to Committed, durably persisted with
     last_observation=postcondition_met, second restart is a no-op.

must_rollback_executes_and_does_not_replay_apply
  -- state=Observing with a real PostconditionNotMet observation; confirms
     rollback actually executes (counter decrements), Apply is not
     replayed, resolves to durable RolledBack, repeated recovery converges
     (does not roll back a second time).

must_rollback_resumes_directly_from_a_crash_during_rollback_itself
  -- state=RollingBack (crash mid-rollback, not merely before one started);
     confirms resumption completes the rollback to RolledBack.

state_ambiguous_fails_closed_to_rollback_not_apply
  -- state=Observing with a real Ambiguous observation; confirms the
     fail-closed policy (rollback, never a replayed Apply) and convergence
     on repeated recovery. Policy was not changed to simplify the test.

requires_human_recovery_never_mutates_and_never_invents_a_transition
  -- state=RollbackFailed; confirms no mutation, no invented transition
     (state remains exactly RollbackFailed), and that three consecutive
     recovery attempts all safely produce the same loud disposition.

rollback_failure_during_recovery_is_surfaced_not_silently_successful
  -- real (not code-hook-injected) failure: makes the counter file and its
     directory genuinely read-only so CounterAdapter's own real
     write_atomic fails; confirms the honest RollbackFailed outcome is
     reached, never a false RolledBack success.

persist_failure_during_recovery_does_not_crash_and_does_not_fabricate_a_durable_record
  -- real read-only transactions directory; confirms no panic, the
     in-memory operation still completes, and — critically — the durable
     on-disk record is NOT falsely updated to Committed when the persist
     call actually failed (the stale on-disk state is itself the honest,
     surfaced signal; a later restart safely re-runs Observe/Confirm,
     which is idempotent).

exactly_two_apply_call_sites_and_the_client_facing_one_is_strictly_after_authorize
  -- structural regression guard for the SafeToResume authorization
     invariant (see below): scans this file's own production source (not
     its test module) and fails loudly if a third `engine::apply` call
     site appears, or if the client-facing call site is ever reordered
     before its own `authorize` call.
```

```text
Before this round: 204 passed, 0 failed (11 in guardian-helper, 4 in guardian-daemon)
After this round:  212 passed, 0 failed (+8: 19 in guardian-helper, 4 unchanged in guardian-daemon)
```

### `SafeToResume` authorization invariant — exact text and location

Added as a doc comment on `reconstruct_for_resume` in
`crates/guardian-helper/src/main.rs` (the function that sets
`record.state` directly to a persisted value, which is the exact point a
future maintainer changing recovery or `apply` would be editing):

> A persisted `Applying` transaction may be resumed by `resolve_recovered`
> without a new *live* caller authorization only because this binary's
> production call graph can durably persist a record in state `Applying`
> through exactly one path: `engine::apply`, reached only from
> `run_guarded_write` strictly *after* `engine::authorize` returned a real
> `AuthorizationOutcome::Authorized` for the real caller identity
> `resolve_caller_identity` resolved from that caller's own live D-Bus
> connection (G1's accepted identity/authorization semantics, unchanged;
> ADR-002's Model B: the helper independently resolves and authorizes the
> caller immediately before mutation). Resuming `apply` from a persisted
> `Applying` record is therefore continuation of that same,
> already-granted, durable authorization decision — not a new privileged
> operation, and not an authorization bypass. G4's own transaction
> sequencing places `Authorize` strictly before `Applying` becomes
> reachable at all (`Authorized -> Applying` is the only path in), and
> `engine::apply` itself never re-checks `authorization_outcome` — in the
> normal flow or here — because the state machine position is the proof.
>
> No alternate production code path may construct or durably persist an
> `Applying`-state `TransactionRecord` without first passing through a
> real, successful `engine::authorize` call. Adding one invalidates this
> recovery-authorization assumption and requires explicit security review
> before merging.

Protected by the regression test named above (`exactly_two_apply_call_sites_...`).

### G8 idempotency forward constraint — exact text and location

Added as a doc comment on `CounterAdapter` in the same file:

> This adapter proves `SafeToResume`-style crash recovery is possible for
> one bounded, Guardian-owned evidence operation — it does not prove every
> future provider automatically supports it. A future real G8 provider may
> only be wired into `SafeToResume`-style automatic Apply resumption after
> it has separately proven its own `apply` is genuinely idempotent against
> the transaction's real idempotency key (not merely "probably fine to
> retry"), and that any rollback it supports is equivalently
> bounded/safe/idempotent. A provider that cannot prove this must not
> inherit automatic resume merely because this evidence adapter supports
> it — it must use a more conservative recovery path (at minimum,
> `RequiresHumanRecovery`-equivalent treatment for its own
> `SafeToResume`-classified records). This constraint must be carried into
> the eventual `G7_MILESTONE.md`.

### Closed areas — confirmed untouched by this round

`Guardian1.Transactions1`, `AttemptProviderDelegatedWrite`, the disposable
Class B prototype, daemon→helper relay, generic privileged helper API, and
the G5 FC-2-remains-open disposition are all unchanged by this repair
round — this round touched only `crates/guardian-helper/src/main.rs`'s
recovery dispatch and its documentation. Identity resolution and normal
polkit sequencing (`run_guarded_write`) are byte-for-byte unchanged except
for the doc comments added above.

### VM evidence — not rerun, and why

Production *recovery mechanism* is unchanged: the same G4 `engine`
functions, called in the same order, from the same states, with the same
persistence calls. What changed is (a) how a recovery action's success is
judged (`finish_recovery`, a pure refactor of already-covered control
flow — the happy path's actual outcome is identical), and (b) which
persisted shapes get routed to `RequiresHumanRecovery` instead of being
silently skipped (`RollbackFailed`) — a pure-Rust classification-routing
change with no systemd/D-Bus/polkit dimension at all. Every new behavior
this round introduces is now covered by a real-engine, real-filesystem
unit test (temp directories, genuine `fs::set_permissions` failures where
needed — not mocks). The previously-accepted real-VM crash-recovery
evidence (real `kill -9` during a real in-flight Apply, real
`systemctl restart`, real durable `Committed` result) exercises exactly
the code path that is unchanged by this round and is not invalidated by
it. No VM was launched for this repair round.

### Validation (this round)

```text
cargo fmt --check:                                    clean
cargo clippy --workspace --all-targets --all-features -- -D warnings: clean
cargo clippy --workspace --all-targets --features guardian-helper/evidence-hooks -- -D warnings: clean
cargo test --workspace:                                212 passed, 0 failed
```
