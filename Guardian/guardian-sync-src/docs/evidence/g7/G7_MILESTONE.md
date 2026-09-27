# Guardian Phase 0/1 — G7 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Decision

```text
Gate:               G7 — Production Daemon
Governing:          docs/guardian/30_TDD/GUARDIAN_G7_IMPLEMENTATION_HANDOFF.md,
                     docs/adr/ADR-002-guardian-privilege-topology.md
Normative IDs:       P1-DMN-001..005, P1-SEC-001..004 (nine total) — ALL PASS
Status:              Accepted — PASS on final focused independent re-audit
                     ("PASS — G7 FINAL REPAIR ACCEPTED")
```

This record is written at publication time, after acceptance — it
summarizes the accepted result and preserves the audit history below
rather than rewriting it into a clean narrative that hides the two
real repair cycles the candidate went through.

## Accepted production topology

```text
guardian-core   = Rust LIBRARY crate only (crates/guardian-core). Never a
                  process. One narrow, additive extension this gate:
                  PolkitAction::GuardianBoundedWrite.
guardian-daemon = unprivileged production PROCESS (crates/guardian-daemon,
                  new src/bin/guardian-daemon.rs binary target on the
                  existing crate). Owns io.github.cliffthelin.Guardian1 —
                  serves exactly the frozen G0 contract
                  (ContractVersion, ServiceState) and nothing else.
guardian-helper = narrow privileged production PROCESS (new crate
                  crates/guardian-helper). Owns
                  io.github.cliffthelin.GuardianHelper1. Exposes exactly
                  two methods: GuardedWrite (the one Class A bounded
                  mutation) and CallCount (read-only evidence accessor).
```

## Direct client → helper invariant

For Guardian-owned privileged mutations, clients call `guardian-helper`
directly on `GuardianHelper1`. `guardian-daemon` has zero D-Bus
client/proxy construction of any kind anywhere in its source — confirmed
repeatedly across three independent audit passes via source review broader
than literal string matching (no aliases, wrappers, or generic IPC
abstractions found). `guardian-helper` independently resolves the real
D-Bus sender (`guardian_core::identity::resolve_caller_identity`,
unchanged G1 code) and independently performs real `CheckAuthorization`
(unchanged G1 `PolkitAuthorizer`) immediately before mutation. Forwarded
identity/authorization is never authoritative — there is no parameter in
`GuardedWrite`'s signature for either to occupy.

## Operation-class ownership

```text
Class A (Guardian-owned privileged mutation): entirely inside
  guardian-helper. Full G4 lifecycle (Snapshot -> Validate -> Authorize ->
  Apply -> Observe -> Confirm/Rollback) runs in-process against
  CounterAdapter, a genuinely idempotent typed fixture (keyed on the real
  transaction idempotency_key G4 already threads through ActionRequest).

Class B (provider-owned authorization): proved via a disposable,
  non-production prototype only — tests/vm/g7-class-b-prototype/, not
  merged into guardian-daemon. guardian-daemon's own production surface
  carries no Class B method; an earlier candidate's
  Guardian1.Transactions1/AttemptProviderDelegatedWrite was found by
  independent audit to be an unjustified permanent API addition and was
  removed (see Independent audit history below).

Class C (no-privilege / read-only / monitoring): guardian-daemon. A real,
  permanent, periodic (30s) monitoring tick evaluates G5's
  recorder_policy_for() against a real free-space probe and records a real
  Event into a real BoundedRecorder — genuine production wiring, not a
  fixture, but explicitly not a claim that G5 FC-2 is closed (see below).
```

## Persistent state — disjoint ownership

```text
/var/lib/guardian/daemon/  — owner guardiand:guardiand (real dedicated
                              unprivileged service account), sole writer
                              guardian-daemon.
/var/lib/guardian/helper/  — owner root:root, sole writer guardian-helper.
```

Confirmed via real, fresh VM evidence (`state-ownership.txt`,
`repaired-*` artifacts): `guardiand` genuinely cannot read helper's state
(`Permission denied`), and no transaction record ever appeared in both
directories. No shared mutable authorization or transaction state exists
between the two processes.

## P1-DMN-001..005 — all PASS

```text
P1-DMN-001 (boot start):        Real `sudo reboot`; both units active
                                 within seconds of a genuinely fresh boot
                                 (`uptime: up 0 min`), before any
                                 graphical/session-bus dependency.
P1-DMN-002 (restart preserves): Real graceful `systemctl restart`; counter
                                 state verified unchanged across restart,
                                 next operation continues from the correct
                                 value (no reset).
P1-DMN-003 (no desktop dep):    Headless VM, no desktop session exists at
                                 all; both units run under system.slice.
P1-DMN-004 (clean stop):        Real idle `systemctl stop`; every
                                 persisted record re-verified parseable
                                 and uncorrupted afterward.
P1-DMN-005 (crash recovery):    Real `kill -9` on a genuinely in-flight
                                 transaction (real 6s delayed Apply, real
                                 process kill mid-call); real recovery on
                                 restart durably resolves the transaction
                                 to a terminal state — see "Recovery" below
                                 for the full history of what this actually
                                 required.
```

## P1-SEC-001..004 — all PASS

```text
P1-SEC-001 (hardening artifact): Real `systemd-analyze security`, captured
                                  separately per unit: guardian-daemon
                                  0.6 SAFE, guardian-helper 1.1 OK —
                                  numerically identical to G2's accepted
                                  Model B measurement for the same
                                  topology.
P1-SEC-002 (path access bounded): Real behavioral proof via
                                  `nsenter --mount` into the live service's
                                  own namespace: a write outside the
                                  declared path fails
                                  ("Read-only file system"); a write inside
                                  it succeeds.
P1-SEC-003 (no arbitrary shell):  Full real `gdbus introspect --recurse`
                                  plus source grep for RunCommand/
                                  Command::new/generic-exec patterns —
                                  none found on either bus name.
P1-SEC-004 (privilege denial):   Real, genuinely distinct unprivileged
                                  Linux identity (`guardiang7denied`,
                                  separate from the authorized
                                  `guardiang7caller`) denied by real
                                  polkit, called directly against
                                  GuardianHelper1.
```

## Real privilege evidence (independently reproduced twice, on separate fresh VMs)

```text
guardian-daemon: UID 999 (guardiand), Gid 986, CapInh/Prm/Eff/Bnd/Amb all
                 0000000000000000, NoNewPrivs=1.
guardian-helper: UID 0 (root — required by polkit's trusted-caller
                 constraint, per ADR-002, not a Guardian design choice),
                 CapInh/Prm/Eff/Bnd/Amb all 0000000000000000,
                 NoNewPrivs=1. No capability was granted "just in case."
```

## Recovery — the actual implementation, and what it took to get there

The accepted implementation does not merely classify a nonterminal
transaction and log it — it executes the real, G4-legal action for every
`RecoveryClassification` and durably persists the result, using only
G4's existing, unmodified `engine`/`persistence`/`recovery` functions:

```text
SafeToResume:          reconstruct from the bounded persisted record ->
                        fresh engine::snapshot -> engine::apply (from
                        exactly the Applying stage) -> if Observing,
                        continue through Observe/Confirm/Rollback.
MustObserve:            real engine::observe -> Confirm on
                        PostconditionMet, Rollback otherwise.
MustRollback:           real engine::rollback, handles both an
                        Observing-classified rollback and a genuine
                        crash-mid-rollback (persisted RollingBack) resume.
StateAmbiguous:         fails closed to the same rollback path as
                        MustRollback — never to a replayed Apply.
AlreadyCommitted:       kept as a documented, unreachable match arm (every
                        record with state==Committed is always terminal
                        and is always caught by the short-circuit first;
                        kept only for exhaustiveness against future G4
                        changes).
RequiresHumanRecovery:  reachable via RollbackFailed specifically
                        (excluded from the generic terminal
                        short-circuit, per G4's own classify() doc
                        comment naming RollbackFailed as needing
                        continued human attention — independently
                        corroborated by G4's own pre-existing,
                        already-accepted test
                        requires_human_recovery_when_rollback_failed).
                        No mutation, no invented transition, logged
                        loudly on every restart until a human resolves it
                        out-of-band.
```

**Durable convergence, proven both behaviorally (real VM) and by
automated test**: a real `kill -9` on a genuinely in-flight transaction,
followed by a real `systemctl restart`, durably resolves the record to
`Committed` (`last_observation=postcondition_met`) in one restart. Three
further real restarts produce zero additional recovery action and zero
re-mutation — confirmed both in the real VM journal (exactly one
`resolved -> Committed` line across four total restarts) and by the
automated test `repeated_restart_does_not_loop_forever_on_the_same_stuck_record`.

**`CounterAdapter` is genuinely idempotent**, keyed on the real
per-transaction `idempotency_key` G4's engine already threads through
`ActionRequest` — a retried `apply`/`rollback` for the same key is a
verified no-op, proven by `recovery_does_not_double_apply_on_resume` and
the symmetric rollback test.

### `SafeToResume` authorization invariant

Documented on `reconstruct_for_resume` in
`crates/guardian-helper/src/main.rs`, in substance:

> A persisted `Applying` transaction may be resumed without a new live
> caller authorization only because this binary's production call graph
> can durably persist a record in state `Applying` through exactly one
> path: `engine::apply`, reached only from `run_guarded_write` strictly
> after `engine::authorize` returned a real `Authorized` outcome for the
> real caller identity resolved from that caller's own live D-Bus
> connection. Resuming `apply` from a persisted `Applying` record is
> therefore continuation of that same, already-granted, durable
> authorization decision — not a new privileged operation, and not an
> authorization bypass. No alternate production code path may construct
> or durably persist an `Applying`-state record without first passing
> through a real, successful `engine::authorize` call; adding one
> invalidates this assumption and requires explicit security review.

Grounded in G1's unchanged caller/authorization semantics, G4's
transaction sequencing (`Authorized -> Applying` is the only legal path
in), and ADR-002's Model B (the helper independently resolves and
authorizes immediately before mutation). Protected by a structural
regression test (`exactly_two_apply_call_sites_and_the_client_facing_one_is_strictly_after_authorize`)
that scans the production source for exactly two `engine::apply` call
sites and confirms the client-facing one is textually ordered after its
own `authorize` call — a source-text tripwire deliberately positioned as
a *supplement* to the behavioral proof above, not a substitute for it.

## Class B disposable-prototype disposition

`tests/vm/g7-class-b-prototype/` — a standalone, non-workspace-member
Cargo project (own `[workspace]` block, own `Cargo.lock`, mirrors
`tests/vm/g2-model-b/`'s exact precedent), explicitly marked
NON-PRODUCTION/DISPOSABLE in its own module doc comment, owning a wholly
separate bus name (`io.github.cliffthelin.G7ClassBPrototype1`, never
`Guardian1`). Real, fresh-VM evidence: built, deployed under a transient
`systemd-run` unit, called twice by a real client binary (real counter
increments `1`, `2`). No production crate imports it; it is not a
workspace member; it does not appear in any packaging file (none exist
yet — G9 scope).

## G5 FC-2 — remains OPEN

`guardian-daemon`'s periodic monitoring tick genuinely calls
`recorder_policy_for()` against a real free-space probe and records a
real `Event` — real, permanent production wiring, not a fixture and not
tied to any client request. **This does not close FC-2.** Neither
`RecorderPolicy::Normal` nor `RecorderPolicy::MemoryFirst` drives a real
spill/retention sink in this build — none exists. Closure is explicitly
assigned to the first future gate that instantiates an actual
spill/retention path, not claimed here. Every log line and doc comment in
the accepted candidate states this explicitly.

## G4 FC-3 — deliberately independent, unchanged

The Flight Recorder and the Class A/B transaction persistence module
remain deliberately independent in this build — no code path in either
production binary references a transaction ID from a recorder event or
vice versa. This disposition is unchanged from G4's original framing and
is recorded here as the durable milestone location the G7 evidence report
committed to carrying it into.

## G8 forward constraint — provider idempotency

Documented on `CounterAdapter` in `crates/guardian-helper/src/main.rs`,
and recorded here as the durable milestone commitment:

> G7's `CounterAdapter` proves `SafeToResume`-style crash recovery is
> possible only for one bounded, Guardian-owned evidence operation — it
> does not prove every future provider automatically supports it. A
> future real G8 provider may only be wired into `SafeToResume`-style
> automatic Apply resumption after it has separately proven its own
> `apply` is genuinely idempotent against the transaction's real
> idempotency key (not merely "probably fine to retry"), and that any
> rollback it supports is equivalently bounded/safe/idempotent. A
> provider that cannot prove this must not inherit automatic resume
> merely because this evidence adapter supports it — it must use a more
> conservative recovery path (at minimum, `RequiresHumanRecovery`-equivalent
> treatment for its own `SafeToResume`-classified records).

## Evidence-hooks feature — non-default, evidence-only

`guardian-helper`'s `evidence-hooks` Cargo feature (gating
`GUARDIAN_HELPER_APPLY_DELAY_MS`, the artificial Apply-delay used only to
gather real crash-during-Apply VM evidence) is off by default and carries
no `[features] default = [...]` entry. Independently confirmed at the
**binary level**, not just by reading the manifest: a plain
`cargo build --release` produces a binary in which the literal env-var
string does not appear at all (`strings` on the compiled artifact). Not
reachable via D-Bus under any configuration. `guardian-daemon`'s
equivalent hook was removed entirely along with the Class B method it
belonged to.

## Non-blocking portability note — `chmod`-based recovery-failure tests

Two automated tests (`rollback_failure_during_recovery_is_surfaced_not_silently_successful`,
`persist_failure_during_recovery_does_not_crash_and_does_not_fabricate_a_durable_record`)
induce real failures via Unix DAC permission denial (`fs::set_permissions`
making a file/directory genuinely read-only), not a production code hook.
This was independently verified reliable under the actual test-execution
identity (a genuine non-root user, confirmed via `id`/`whoami` during the
final audit, with the underlying OS mechanism separately reproduced
outside the test suite). **Running this suite as root may cause these two
tests to fail** (not silently pass falsely) — root bypasses DAC
permission checks (`CAP_DAC_OVERRIDE`) by default, so the induced write
would likely succeed anyway, and the tests' specific-outcome assertions
would then correctly fail rather than mask anything. CI should run
`cargo test --workspace` as a non-root user, or otherwise preserve real
Unix permission semantics for these two tests, to avoid spurious failures
unrelated to the code under test. Not redesigned now — noted as a CI
environment assumption, not a defect.

## Test-count progression

```text
Pre-G7 baseline:                    189 passed, 0 failed
After first repair (recovery
  execution, API removal, FC-2
  correction, initial coverage):    204 passed, 0 failed (+15)
After final repair (full
  classification-branch and
  failure-path coverage):           212 passed, 0 failed (+8)
```

## Final validation

```text
cargo fmt --check:                                                        clean
cargo clippy --workspace --all-targets --all-features -- -D warnings:      clean
cargo clippy --workspace --all-targets --features guardian-helper/evidence-hooks -- -D warnings: clean
cargo test --workspace:                                                    212 passed, 0 failed
```

## Independent audit history (preserved, not collapsed)

```text
Round 1 — initial implementation audit
  Verdict: FAIL — G7 TRANSACTION/RECOVERY CONTRACT VIOLATED
  Four blocking findings: recovery classified nonterminal transactions but
  never executed a resume/termination action; Guardian1.Transactions1/
  AttemptProviderDelegatedWrite was an unjustified permanent production
  API addition; G5 FC-2 was claimed closed on the basis of two log
  branches with no real behavioral difference; zero automated tests
  existed for meaningful pure-Rust logic added in G7 (189 unchanged).
  Direct-call topology, privilege separation, and real-system security
  evidence were independently found sound and were preserved unchanged
  through every subsequent round.

Round 2 — repair + focused re-audit
  Repair: real recovery execution wired (classification -> action ->
  durable state) using only G4's existing engine functions;
  Guardian1.Transactions1 removed, Class B moved to a disposable
  prototype; FC-2 closure claim withdrawn, replaced with an honest
  "evaluated, not closed" disposition; 15 new tests added (189 -> 204).
  Re-audit verdict: FAIL — G7 TEST COVERAGE STILL INSUFFICIENT.
  Two narrower blocking findings: four of six RecoveryClassification
  dispatch branches (MustObserve, MustRollback, StateAmbiguous,
  RequiresHumanRecovery) had zero direct test coverage, and no test
  exercised a genuine failure during recovery itself; the SafeToResume
  authorization-safety invariant was real (independently verified true)
  but was not documented anywhere.

Round 3 — final repair + final focused re-audit
  Repair: full classification-branch coverage added (including the
  RollbackFailed -> RequiresHumanRecovery reachability fix, corroborated
  by G4's own pre-existing accepted test suite), two real
  failure-injection tests added, the SafeToResume authorization invariant
  documented at the exact point a future maintainer would edit, the G8
  provider-idempotency forward constraint recorded, the misleadingly-named
  AlreadyCommitted test renamed (204 -> 212).
  Final verdict: PASS — G7 FINAL REPAIR ACCEPTED. Zero blocking findings.
  One non-blocking portability note (chmod-under-root), recorded above.
```

## Evidence index (referenced, not duplicated here)

```text
docs/guardian/30_TDD/GUARDIAN_G7_IMPLEMENTATION_HANDOFF.md
docs/guardian/30_TDD/GUARDIAN_G7_INDEPENDENT_REVIEW_HANDOFF.md
docs/evidence/g7/G7_DAEMON_HELPER_EVIDENCE.md (original candidate evidence,
  preserved with a revision note pointing to the repair)
docs/evidence/g7/G7_REPAIR_EVIDENCE.md (both repair rounds, in full)
docs/evidence/g7/*.service, *.conf, *.policy, *.rules (real systemd/D-Bus/
  polkit configuration used across every evidence pass)
docs/evidence/g7/*-security.txt, *-journal.txt, *-introspection.txt,
  state-ownership.txt, post-reboot-privilege.txt (raw real-VM artifacts)
tests/vm/g7-class-b-prototype/ (disposable Class B evidence, non-production)
crates/guardian-helper/src/main.rs (production Class A binary)
crates/guardian-daemon/src/bin/guardian-daemon.rs (production Class C
  binary)
```
