# Guardian Wave 1 — First Production Mutation — Milestone Record

## Status

**PASS, ACCEPTED.** Wave 1 — First Production Mutation is independently
accepted. This is a milestone acceptance record in the same sense as the
G0–G9 milestone records, for the separately-governed interstitial stage
established by TDD contract §50 (Wave 1 is not TDD-contract Phase 2 and
is not a renumbered G10 — see §50's own disambiguation rule).

The path to acceptance was not a single clean pass, and this record
preserves that history rather than compressing it into a "passed first
try" narrative — see "Complete audit-history summary" below. In short:
planning alone went through five independent review rounds and four
repair passes before acceptance; the accepted implementation was then
independently audited, found one real defect (`FAIL — JOBREMOVED RACE
UNSAFE`), was repaired narrowly, and the repair was independently
closed with `PASS WITH NON-BLOCKING FINDINGS`. Two genuine contract
conflicts and one implementability gap were discovered against real
Ubuntu 26.04.1/systemd/polkit behavior during this process and are
preserved here as findings, not edited away.

```text
Project display name:      Guardian Plane
Repository slug:           guardian-plane
GitHub repository:         github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
Planning baseline SHA:     a68c354997eb3801066071fb0a21fbe29d5ad655
                            ("docs: define Wave 1 first mutation contract")
Governing documents:       docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md §50
                            docs/guardian/30_TDD/GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md
Evidence VM:                guardian-g9 (multipass, Ubuntu 26.04 LTS,
                            polkitd 127-2ubuntu1)
```

## Scope implemented

Exactly the one governed Wave 1 capability:

```text
capability_id: "cups-restart"
  -> unit:      "cups.service"
  -> operation: Restart
  -> provider action: org.freedesktop.systemd1.manage-units
       details: unit=cups.service, verb=restart,
                polkit.message="Authentication is required to restart '$(unit)'." (literal, corrected by repair pass -- see W1-AUTH-007),
                polkit.gettext_domain=systemd
```

No other systemd unit, capability row, or operation was added.

## Architecture implemented

```text
real caller (any user)
  -> guardian-helper (RestartCapability D-Bus method, root, system bus)
  -> resolve_caller_identity (from guardian-helper's own inbound connection)
  -> restart_capability::resolve_capability("cups-restart") (fixed 1-row table)
  -> live precondition read (SystemdRestartAdapter::read_live_state)
       LoadState != not-found/masked; RefuseManualStart/Stop not set
  -> txn::engine::snapshot / generic validate+arbitrate (unmodified G4)
  -> authorize_provider_request(caller, ProviderAuthorizationRequest::
       SystemdRestart{capability}, interactive) -- real systemd
       manage-units policy, real caller, real four-field details
  -> txn::engine::apply -- durable intent, then real Manager.RestartUnit
  -> txn::engine::observe -- real JobRemoved wait + fresh ActiveState re-read
  -> txn::engine::confirm / BestEffort compensating restart
  -> Committed / RollbackFailed, durably persisted
```

`guardian-daemon` has no code path touching any of this (W1-TXN-001,
mechanically true: `restart_capability`/`run_restart_capability`/
`authorize_provider_request` exist only in `guardian-core`/`guardian-helper`).

## Normative ID status (30/30)

| ID | Status | Evidence |
|---|---|---|
| W1-MUT-001 | Implemented, tested, VM-evidenced | `authorization-transcripts.txt` (W1-VM-001); `40008000-0000-0000-18d3-197648356f39.txn` |
| W1-MUT-002 | Implemented, tested, VM-evidenced | `restart_capability::tests::rejects_an_unknown_capability_id`; `authorization-transcripts.txt` |
| W1-MUT-003 | **Repair pass: closed.** Precondition extracted to a pure, unit-tested predicate (`LiveUnitState::is_load_state_blocked`); real VM evidence confirms systemd reports `LoadState == "not-found"` for a genuinely nonexistent unit | `restart_capability.rs` tests; `w1_mut_003_004_evidence.md` |
| W1-MUT-004 | **Repair pass: closed.** Precondition extracted to a pure, unit-tested predicate (`LiveUnitState::refuses_manual_start_or_stop`); real VM evidence confirms systemd reports `RefuseManualStart == true` for a real unit configured that way | `restart_capability.rs` tests; `w1_mut_003_004_evidence.md` |
| W1-AUTH-001 | Implemented, tested, VM-evidenced | `wave1_authorization_contract.rs`; `authorization-transcripts.txt` (W1-VM-002) |
| W1-AUTH-002 | **Repair pass: closed.** Pure mapping already unit-tested; real VM evidence added — a real user with no registered polkit agent, `interactive=true`, against the real unmodified `PolkitAuthorizer`, produces the real `AuthenticationUnavailable` D-Bus error | `wave1_authorization_contract.rs`; `w1_auth_002_evidence.md` |
| W1-AUTH-003 | Implemented (reuses `AuthorizationUnavailableReason::InteractionRequiredButDisallowed`, existing P0-AUTH-003 semantics, unmodified) | `wave1_authorization_contract.rs` |
| W1-AUTH-004 | Implemented, tested (source-scan precedent in `main.rs` mirrors `GuardedWrite`'s own pattern exactly: `resolve_caller_identity(connection, &header)` from `guardian-helper`'s own inbound connection) | `main.rs::GuardianHelper::restart_capability` |
| W1-AUTH-005 | Implemented, tested | `wave1_authorization_contract.rs::polkit_action_gains_no_systemd_restart_variant`; VM: `checkauth-comparison.md` point (4) |
| W1-AUTH-006 | Implemented, tested | `wave1_authorization_contract.rs::no_conversion_exists_between_provider_authorization_request_and_polkit_action` |
| W1-AUTH-007 | **Repair pass: corrected and closed.** `polkit.message` now reproduces the literal `$(unit)` template (runtime capture is authoritative, per governed decision); native-vs-mediated VM re-capture shows exact semantic equality on every field | `wave1_authorization_contract.rs`; `checkauth-comparison.md` (Resolution) |
| W1-TXN-001 | Implemented, mechanically true (no code path) | inspection |
| W1-TXN-002 | Implemented (maps `Failed` Apply outcome to `ProviderUnavailable`) | `main.rs::run_restart_capability` |
| W1-TXN-003 | VM-evidenced (job-merging observed, not assumed) | `w1_vm_004.txt` |
| W1-REC-001 | Reused unmodified (`recovery::classify`'s pre-mutation branch) | existing `transaction_recovery_contract.rs` |
| W1-REC-002 | Reused unmodified | existing `transaction_recovery_contract.rs` |
| W1-REC-003 | **Repair pass: corrected and closed.** G4 durable Apply-dispatch-marker extension (TDD contract §50.x) added; real VM re-run of the identical kill-9 scenario now reaches `StateAmbiguous` → `RolledBack`, never `SafeToResume`/`Committed` | `wave1_vm005_finding.md` (Resolution); `transaction_recovery_contract.rs` |
| W1-REC-004 | Reused unmodified | existing `transaction_recovery_contract.rs` |
| W1-REC-005 | Reused unmodified | existing `transaction_recovery_contract.rs` |
| W1-REC-006 | Reused unmodified | existing `transaction_recovery_contract.rs` |
| W1-REC-007 | Implemented, VM-evidenced | `authorization-transcripts.txt` (W1-VM-006) |
| W1-REC-008 | Implemented, VM-evidenced | `authorization-transcripts.txt` / `40008000-0000-0001-18d3-2d73ccd6a68b.txn` |
| W1-REC-009 | **Repair pass: closed.** Direct, isolated real-VM proof: two `SystemdRestartAdapter::apply` calls with the same idempotency key against real `cups.service` produce exactly one real restart (`InvocationID` unchanged after the second call; journal shows one stop/start cycle) | `restart_capability.rs::tests::restart_unit_apply_is_idempotent_for_the_same_key_against_real_systemd` (`#[ignore]`, VM-run); `w1_rec_009_idempotency_evidence.md` |
| W1-VM-001 | Real VM evidence | `authorization-transcripts.txt` |
| W1-VM-002 | Real VM evidence | `authorization-transcripts.txt` |
| W1-VM-003 | Real VM evidence | `authorization-transcripts.txt` |
| W1-VM-004 | Real VM evidence | `w1_vm_004.txt` |
| W1-VM-005 | **Repair pass: corrected and closed.** Real VM re-run of the identical kill-9 scenario against the repaired engine now reaches the contract-required classification | `wave1_vm005_finding.md` (Resolution) |
| W1-VM-006 | Real VM evidence | `authorization-transcripts.txt`; `40008000-0000-0001-18d3-2d73ccd6a68b.txn` |
| W1-VM-007 | **Repair pass: corrected and closed.** Re-run against the corrected binary: native vs. mediated `CheckAuthorization` now match on every field, including `polkit.message` | `checkauth-comparison.md` (Resolution); `mediated_checkauth_fixed.txt` |

**Summary: 30/30 IDs have a disposition, all now closed by the original
pass or this repair pass.** 24 were fully implemented, tested, and (where
VM-scoped) evidenced without qualification in the original pass. This
repair pass closes the remaining 6: **W1-REC-003/W1-VM-005** (a genuine
G4 gap, closed by the disclosed durable-marker extension, TDD contract
§50.x) and **W1-AUTH-007/W1-VM-007** (a genuine `polkit.message` fidelity
defect, corrected to match the runtime-authoritative literal template)
were real, VM-confirmed contract conflicts, each adjudicated by the
project owner and repaired with real re-evidence, not silently resolved.
**W1-MUT-003/004, W1-AUTH-002, W1-REC-009** were implemented but
under-evidenced; each is now closed with either a real VM capture, a
direct isolated real-VM test, or a newly-extracted deterministic unit
test (see "Repair pass" section below for the full record and every
changed/added file).

## Recovery / SafeToResume result

**Repair pass**: every crash point in §8's table, including the
previously-unreachable in-flight-call point, now behaves exactly as
required. The genuinely-in-flight-call point (`W1-REC-003`/`W1-VM-005`)
required a disclosed, narrow G4 extension (TDD contract §50.x, a durable
Apply-dispatch marker) — `recovery.rs`/`engine.rs` are therefore *not*
byte-for-byte identical to the pre-Wave-1 G4 baseline, which is the
explicit, disclosed point of that extension. Every other crash point is
unaffected and continues to behave exactly as the unmodified G4 baseline
already guaranteed (proven by the full, extended
`transaction_recovery_contract.rs`/`transaction_apply_persistence_contract.rs`
suites, which add coverage for the new marker without changing any
pre-existing test's expected outcome). Full before/after evidence:
`wave1_vm005_finding.md`'s "Resolution" section.

## Systemd observation race — discovered and repaired

The full independent implementation audit (post-repair-pass-1) cleared
thirteen of fourteen audit areas but found one real, structural defect:

```text
FAIL — JOBREMOVED RACE UNSAFE
```

**Original unsafe ordering** (`SystemdRestartAdapter`,
`crates/guardian-helper/src/restart_capability.rs`): the `JobRemoved`
D-Bus signal subscription was established only inside the later, separate
`observe()` engine step — strictly *after* `RestartUnit` had already
returned, not before it was sent. D-Bus does not queue a signal for a
not-yet-installed match rule, so a sufficiently fast systemd job's
completion signal could be permanently missed. The code treated that miss
as `PostconditionNotMet`, which would have triggered an unnecessary
`BestEffort` compensating restart and reported a false ambiguous/failure
outcome for a restart that may have already succeeded cleanly.

**Final accepted ordering**:

```text
install/acknowledge JobRemoved match (real AddMatch D-Bus round trip)
  -> RestartUnit sent
  -> buffer any early JobRemoved signals (bounded, capacity 8, oldest-evicted)
  -> receive the returned job path
  -> correlate strictly by that exact job path (unrelated signals ignored)
  -> Observe (existing G4 phase, unchanged) consumes the correlated result
```

If the subscription cannot be established, `RestartUnit` is never
invoked — proven by
`subscription_failure_before_mutation_prevents_restart_unit`
(structural early-return, not merely a test-scenario coincidence).
Independently verified against the real, pinned zbus 5.19.0 source: the
arming call performs a real `org.freedesktop.DBus.AddMatch` method call
and returns only once the bus daemon has acknowledged it — confirmed
both by reading the crate source and by an independently-captured,
timestamped `busctl monitor` trace showing the `AddMatch` reply landing
283µs before `RestartUnit` was sent.

The identical corrected mechanism was applied to `rollback`'s own
`RestartUnit` call as well, since it shared the same race by
construction (same call shape, same missing-subscription defect) — not
unrelated scope expansion.

**Repaired and independently closed**:
`docs/evidence/wave1/w1_jobremoved_race_repeated_restart_evidence.md`,
`w1_race_repeat_cups_journal.txt`. Six deterministic race scenarios
(signal-before-reply, signal-after-reply, unrelated-early-signal,
multiple-buffered-signals, failed-target-job, no-matching-signal/bounded
timeout) plus a cross-talk test and a no-hang/deadlock-regression test
were added and independently re-run by the closure auditor. Real VM
evidence (independently reproduced twice by the closure auditor, not
merely read): 5 real `cups.service` restarts completing in ~0.15–0.17s
total wall-clock time, all correctly correlated, zero spurious
compensating restarts.

**Non-blocking hardening finding carried forward** (see "Hardening
backlog" below): the buffer correlates by job path only, though the
`JobRemoved` signal payload and the governed unit name are both already
known and could additionally be filtered by unit — narrowing an already
narrow (bounded, safe-failure-mode) theoretical eviction window further.
Not implemented at acceptance time, by explicit project-owner decision,
to avoid reopening an already-accepted candidate for a low-probability,
conservatively-failing edge case.

## Rollback / rollback-failure result

`RollbackKind::BestEffort` (a second `RestartUnit`) is used unconditionally
— never upgraded to `Native`. Real VM evidence (`W1-VM-006`) confirms a
genuine compensating-restart failure reaches the real `RollbackFailed`
terminal state, surfaces `GuardianErrorCategory::RollbackFailed` to the
caller, and never fabricates a `RolledBack` success.

## Package-fixture isolation

Confirmed by inspection (`debian/rules`, `debian/guardian.install`):

- `cargo build --release --workspace --locked` — no `--features
  evidence-hooks` anywhere in the packaging build, so the evidence-hooks
  code path is not merely inactive in the shipped binary, it is not
  compiled in at all.
- `guardian.install` lists exactly `io.github.cliffthelin.guardian.g7.policy`,
  the two existing `.conf` D-Bus policy files, and the indicator desktop
  file — no `.rules` file of any kind, and nothing referencing
  `wave1`/`cups-restart` was added to `debian/`.
- The evidence-only `60-wave1-evidence.rules` fixture was written only to
  `guardian-g9`'s own `/etc/polkit-1/rules.d/` (never checked into the
  repository as a packaged artifact) — a copy is preserved here, in
  `docs/evidence/wave1/60-wave1-evidence.rules`, purely as evidence, the
  same convention G7's own evidence directory uses for
  `50-guardian-g7.rules`.
- `git status`/`git diff --stat` against the baseline SHA confirms no file
  under `debian/` was touched by this implementation.

## Test count (final, accepted)

```text
Planning baseline (before any Wave 1 code):      304 passed, 0 failed
After implementation pass 1:                     319 passed, 0 failed
After repair pass 1 (dispatch marker,
  polkit.message, four evidence closures):        334 passed, 0 failed, 1 ignored
After repair pass 2 (JobRemoved race):            347 passed, 0 failed, 3 ignored
```

**Final, independently reproduced full-workspace validation** (run
unrestricted, including `guardian-gui`, in the `guardian-g9` VM where
`libadwaita-1-dev` is installed):

```text
cargo fmt --check                                             -> clean
cargo clippy --workspace --all-targets --all-features -- -D warnings -> clean, 0 warnings
cargo test --workspace                                        -> 347 passed, 0 failed, 3 ignored
```

`guardian-gui` could not be built on the plain host dev container in
this session (pre-existing `libadwaita-1` pkg-config gap, independently
confirmed via `git stash` against the unmodified planning baseline to be
a sandbox condition, not a Wave 1 regression) — the literal, unrestricted
command was nonetheless run and passed in the VM environment, which is
the validation of record for this milestone, not the host-excluded run.

The 3 ignored tests are real-system-bus-only tests, run explicitly
against `guardian-g9`'s real `cups.service` rather than as part of the
default `cargo test --workspace` run: the W1-REC-009 idempotency proof
(`restart_unit_apply_is_idempotent_for_the_same_key_against_real_systemd`),
the bounded-timeout race scenario F
(`no_matching_signal_is_bounded_and_reports_ambiguous`, exercises a real
20s timeout), and the repeated-fast-restart race-stress evidence test
(`repeated_real_restarts_are_all_correlated_and_never_ambiguous`).

## Files in this evidence directory

```text
WAVE1_MILESTONE.md            this file
wave1_vm005_finding.md        the W1-REC-003/W1-VM-005 contract conflict, in full
checkauth-comparison.md       the W1-VM-007 native-vs-mediated field comparison
authorization-transcripts.txt real busctl/gdbus call transcripts, W1-VM-001/002/003/006/007
w1_vm_004.txt                 concurrent-restart raw transcript
native_checkauth.txt          raw busctl monitor capture, native systemctl restart
mediated_checkauth.txt        raw busctl monitor capture, mediated RestartCapability call
guardian-helper-journal.txt   full guardian-helper.service journal across this evidence run
guardian-helper-status.txt    systemctl status snapshot
guardianhelper1-introspection.txt  real D-Bus introspection of the deployed interface
cups-journal.txt              cups.service journal excerpt (W1-VM-004 restart activity)
w1_vm_005_call_result.txt     the client-side error from the killed-mid-call request
60-wave1-evidence.rules       the evidence-only, never-packaged polkit fixture (W1-VM-007)
*.txn                         real persisted transaction records from this evidence run

-- added by repair pass 1 (dispatch marker / polkit.message) --
mediated_checkauth_fixed.txt  raw busctl monitor capture, mediated call against the corrected binary (W1-VM-007 re-run)
w1_vm005_fixed_txn.txt        the real, on-disk .txn record at the moment of the re-run kill-9, showing dispatch_marker=true
w1_vm005_fixed_journal.txt    guardian-helper journal for the re-run kill-9/recovery cycle, showing "resolved -> RolledBack"
w1_mut_003_004_evidence.md    W1-MUT-003/004 evidence closure (real nonexistent-unit / RefuseManualStart captures)
w1_auth_002_evidence.md       W1-AUTH-002 evidence closure (real no-agent AuthenticationUnavailable capture)
w1_auth_002_noagent_evidence.txt  raw capture for the above
w1_rec_009_idempotency_evidence.md  W1-REC-009 evidence closure (isolated real-VM idempotency proof)
w1_rec_009_cups_journal.txt   corroborating cups.service journal for the above (one restart, not two)

-- added by repair pass 2 (JobRemoved race) --
w1_jobremoved_race_repeated_restart_evidence.md  the JobRemoved-race repair's own real VM evidence (5 fast restarts, all correlated)
w1_race_repeat_cups_journal.txt  corroborating cups.service journal for the above
```

Note on the retained "2 ignored" figure in
`w1_jobremoved_race_repeated_restart_evidence.md`: the repair pass's own
evidence narrative states "2 ignored" for its local full-workspace run.
The final, independently-measured, and authoritative figure — confirmed
by the closure auditor by tallying every `test result:` line directly,
not by reading a printed summary — is **3 ignored**. Per the project
owner's instruction, the original evidence file is left intact rather
than edited after the fact; this note is the correction of record, and
this milestone's own "Test count" section above states the correct,
final figure.

## Repair pass 1 — summary and file-level record (G4 dispatch marker, polkit.message fidelity, four evidence closures)

Performed a narrow repair, per the project owner's adjudication of the two
genuine conflicts this candidate originally reported, plus closure of the
four under-evidenced IDs. No unrelated cleanup. No commit/push/tag (per
task instruction).

### Files changed

| File | Status | Why | Governing IDs |
|---|---|---|---|
| `crates/guardian-core/src/transaction/apply.rs` | Modified | `ApplyRecord` gains `dispatch_marker: bool` | W1-REC-003, W1-VM-005 |
| `crates/guardian-core/src/transaction/engine.rs` | Modified | `apply()` persists the dispatch marker before invoking the provider; entry gate refuses re-entry on a marker-set-but-`NotRecorded` record | W1-REC-003, W1-VM-005 |
| `crates/guardian-core/src/transaction/persistence.rs` | Modified | `PersistedTransactionRecord` carries `dispatch_marker` through serialize/deserialize/`from_record`/`to_recovery_snapshot`, backward-compatible default `false` | W1-REC-003, W1-VM-005 |
| `crates/guardian-core/src/transaction/recovery.rs` | Modified | `RecoverySnapshot` carries `dispatch_marker`; `classify_applying` returns `StateAmbiguous` for `NotRecorded` + marker set | W1-REC-003, W1-VM-005 |
| `crates/guardian-core/src/authorization.rs` | Modified | `ProviderAuthorizationRequest::details()`'s `polkit.message` is now the literal `$(unit)` template, not interpolated | W1-AUTH-007, W1-VM-007 |
| `crates/guardian-helper/src/main.rs` | Modified | `write_persisted`/`reconstruct_for_resume{,_restart}` thread `dispatch_marker` through; `restart_validate` calls the two new extracted predicates | W1-REC-003; W1-MUT-003/004 |
| `crates/guardian-helper/src/restart_capability.rs` | Modified | `LiveUnitState::is_load_state_blocked`/`refuses_manual_start_or_stop` extracted as pure predicates + unit tests; new isolated real-VM idempotency test (`#[ignore]`) | W1-MUT-003, W1-MUT-004, W1-REC-009 |
| `crates/guardian-core/tests/transaction_recovery_contract.rs` | Modified | 5 new tests for the dispatch-marker classification, including an exhaustive no-false-`SafeToResume` property test | W1-REC-003 |
| `crates/guardian-core/tests/transaction_apply_persistence_contract.rs` | Modified | 3 new tests: marker-set-is-ambiguous fixture, ordering proof through the real `engine::apply` path, known-failure regression guard | W1-REC-003 |
| `crates/guardian-core/tests/transaction_persistence_contract.rs` | Modified | 2 new tests: `dispatch_marker` round-trip, backward-compatible default for pre-extension records | W1-REC-003 |
| `crates/guardian-core/tests/wave1_authorization_contract.rs` | Modified | Updated expected `polkit.message` value to the literal `$(unit)` template | W1-AUTH-007 |
| `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` | Modified | New §50.x subsection governing the G4 extension; sixth revision-history entry | W1-REC-003, W1-AUTH-007 |
| `docs/guardian/30_TDD/GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md` | Modified | §8 correction note (durable-marker extension); §7/§10/§12 correction notes (literal `polkit.message`) | W1-REC-003, W1-AUTH-007 |
| `docs/evidence/wave1/wave1_vm005_finding.md` | Modified (appended) | "Resolution" section added after the preserved original finding | W1-REC-003, W1-VM-005 |
| `docs/evidence/wave1/checkauth-comparison.md` | Modified (appended) | "Resolution" section added after the preserved original finding | W1-AUTH-007, W1-VM-007 |
| `docs/evidence/wave1/WAVE1_MILESTONE.md` | Modified | This file — status, ID table, test count, files list, this section | all |
| `docs/evidence/wave1/w1_mut_003_004_evidence.md` | Added | W1-MUT-003/004 evidence closure | W1-MUT-003, W1-MUT-004 |
| `docs/evidence/wave1/w1_auth_002_evidence.md` | Added | W1-AUTH-002 evidence closure | W1-AUTH-002 |
| `docs/evidence/wave1/w1_auth_002_noagent_evidence.txt` | Added | raw capture | W1-AUTH-002 |
| `docs/evidence/wave1/w1_rec_009_idempotency_evidence.md` | Added | W1-REC-009 evidence closure | W1-REC-009 |
| `docs/evidence/wave1/w1_rec_009_cups_journal.txt` | Added | corroborating raw capture | W1-REC-009 |
| `docs/evidence/wave1/mediated_checkauth_fixed.txt` | Added | W1-VM-007 re-run raw capture | W1-AUTH-007, W1-VM-007 |
| `docs/evidence/wave1/w1_vm005_fixed_txn.txt` | Added | W1-VM-005 re-run raw `.txn` | W1-REC-003, W1-VM-005 |
| `docs/evidence/wave1/w1_vm005_fixed_journal.txt` | Added | W1-VM-005 re-run raw journal | W1-REC-003, W1-VM-005 |

Nothing under `debian/`, no client code, no other provider implementation,
no D-Bus policy/service file, and no `guardian-daemon` code path was
touched. `restart_capability::CAPABILITY_TABLE` (`cups-restart` →
`cups.service` → `Restart`) is unchanged.

## Repair pass 2 — summary and file-level record (JobRemoved race)

Performed a second, narrower repair, scoped by the project owner's
explicit adjudication, addressing exactly the full audit's
`FAIL — JOBREMOVED RACE UNSAFE` finding and nothing else. No G4,
authorization, persistence, capability-table, client, or packaging file
was touched.

### Files changed

| File | Status | Why | Governing IDs |
|---|---|---|---|
| `crates/guardian-helper/src/restart_capability.rs` | Modified | Replaced post-hoc `wait_for_job_removed`/`last_job` with pre-armed observation: `arm_job_removed_observation` (installs the `JobRemoved` match rule and confirms it via a real `AddMatch` round trip before `RestartUnit` is sent), a bounded `JobRemovedBuffer` (capacity 8, mutex+condvar, oldest-evicted), and exact-job-path correlation in `observe`/`rollback`; added `race_tests` module (6 deterministic scenarios A–F), a subscription-failure-blocks-mutation test, a cross-talk test, a no-hang/deadlock-regression test, and two new `#[ignore]`d real-VM tests | JobRemoved race (full-audit finding, not a numbered `W1-*` ID — a cross-cutting defect in the shared `apply`/`rollback` observation mechanism) |
| `crates/guardian-helper/Cargo.toml` | Modified | Added `[dev-dependencies]`: `guardian-testkit` (path), `futures-lite = "2"` — needed to host a private-bus fake systemd service for the deterministic race tests, per this project's existing `PrivateSessionBus` test convention | supports race tests above |
| `Cargo.lock` | Modified | Mechanical consequence of the `Cargo.toml` change (two new lockfile entries under `guardian-helper`'s dependency graph) | — |
| `docs/evidence/wave1/w1_jobremoved_race_repeated_restart_evidence.md` | Added | Real VM evidence: 5 real `cups.service` restarts in ~0.15–0.17s, all correlated, zero spurious compensation | JobRemoved race |
| `docs/evidence/wave1/w1_race_repeat_cups_journal.txt` | Added | Corroborating raw `cups.service` journal for the above | JobRemoved race |

The identical corrected mechanism was applied to `rollback`'s own
`RestartUnit` call in the same file, since it shared the identical
pre-repair race by construction — independently adjudicated by the
closure auditor as legitimate reuse of the corrected shared primitive,
not scope expansion, and confirmed to preserve `BestEffort`/
`RollbackFailed` semantics via a fresh, independent real-VM
rollback-failure reproduction (not merely the retained repair-pass-1
evidence).

## Complete audit-history summary

Wave 1's path to acceptance, in order, preserved in full rather than
compressed:

1. Missing Wave 1 governance discovered — no prior document in this
   repository used the term "Wave 1," and TDD contract §47 defined the
   next phase as read-only observability only, not mutation.
2. §50 amendment added, authorizing Wave 1 as a distinct, unnumbered
   interstitial stage between G0–G9 and TDD-contract Phase 2.
3. Independent review round 1 found and repaired a Phase-numbering
   ambiguity (§50's own text conflated Wave 1 with TDD-contract Phase 2)
   and an authorization-relay defect (a root-relayed `RestartUnit` call
   bypassed real per-user polkit authorization entirely — confirmed live
   in a VM).
4. Independent review round 3 found round 1's own fix defective: a new,
   Guardian-owned polkit action for a capability G2 already classified
   provider-owned silently converted that classification (Model A,
   rejected in favor of Model B — Guardian mediates, provider policy
   remains authoritative).
5. Independent review round 4 found round 3's Model B design
   unimplementable as worded — Guardian's existing `PolkitAction` type is
   a closed enum with no way to carry an arbitrary provider action id;
   repaired with a new, disjoint `ProviderPolkitAction`/
   `ProviderAuthorizationRequest` representation.
6. Independent review round 5 found round 4's fix detail-incomplete —
   checking the correct action id alone does not reproduce systemd's real
   authorization decision, since systemd's real request carries non-empty
   `unit`/`verb`/`polkit.message`/`polkit.gettext_domain` details a real
   admin policy rule can branch on; repaired by carrying the complete,
   internally-derived request.
7. Planning independently accepted:
   `PASS — WAVE 1 FIRST-MUTATION HANDOFF READY FOR IMPLEMENTATION`,
   committed and pushed as `a68c354997eb3801066071fb0a21fbe29d5ad655`.
8. Implementation exposed a genuine G4 gap: a real kill-9 during an
   in-flight `RestartUnit` call recovered as `NotRecorded` →
   `SafeToResume` (auto-replay) instead of the contract-required
   `StateAmbiguous`, because G4 had no durable way to distinguish
   "provider call never attempted" from "provider call may have escaped."
9. A disclosed, narrow G4 extension (the durable `dispatch_marker`,
   TDD contract §50.x) was added and independently verified, including a
   live re-run of the exact kill-9 scenario now reaching
   `StateAmbiguous` → `RolledBack`.
10. Fresh runtime evidence corrected the `polkit.message` detail from a
    pre-interpolated string to the literal, unsubstituted `$(unit)`
    template systemd actually sends — the runtime capture was adjudicated
    authoritative over the earlier planning evidence.
11. The full independent implementation audit cleared thirteen of
    fourteen areas but found one real defect:
    `FAIL — JOBREMOVED RACE UNSAFE` — the `JobRemoved` subscription was
    armed only after `RestartUnit` had already returned, permitting a
    fast job's completion signal to be missed.
12. The race was repaired narrowly, confined to the systemd adapter:
    arm-before-mutate ordering, bounded early-signal buffering, exact
    job-path correlation, and fail-closed behavior on subscription
    failure.
13. A focused closure audit independently verified the repair —
    including its own live timestamped `busctl` capture proving
    subscription-before-mutation, its own re-run of every deterministic
    race test, and its own fresh real-VM reproduction of both the fast-job
    case and the rollback-failure case — and returned
    `PASS WITH NON-BLOCKING FINDINGS`, with next action
    "Return to Wave 1 milestone acceptance/publication."

This progression — five planning review rounds, two implementation-phase
audits, three repair passes, each finding real defects against real
Ubuntu 26.04.1/systemd/polkit behavior rather than accepting a plausible
design on paper — is evidence of the gate process working as intended,
not a sign of a troubled feature. It is preserved here in full rather
than summarized away.

## Hardening backlog (non-blocking, carried forward — not Wave 1 acceptance blockers)

- **`JobRemoved` buffer unit-filtering.** The buffer correlates
  strictly by job path; the closure auditor found it does not
  additionally filter by unit name, though the signal payload carries it
  and the governed unit (`cups.service`) is known statically before
  `RestartUnit` is even called. Filtering by `unit == self.unit_name` in
  addition to job path would narrow the already-bounded, already
  safe-failing (an eviction can only produce a conservative `ambiguous`
  outcome, never a false success) theoretical eviction window further, at
  negligible cost. Not implemented at acceptance time — a candidate
  already independently accepted should not be reopened for a
  low-probability, conservatively-failing edge case.
- **Rollback-specific deterministic race coverage.** No dedicated
  fake-service test exercises scenarios A–F specifically against
  `rollback`'s own re-armed observation path (only `apply`/`observe` have
  dedicated fake-service race tests). Closed for acceptance by fresh,
  independent real-VM rollback-failure reproduction instead.
- **Listener-thread instrumentation.** Listener-thread cleanup is
  structurally bounded by the adapter's own connection lifetime
  (verified by reading the `Drop`/connection-teardown path and by a
  5-cycle no-hang test), but no direct OS-thread-count instrumentation
  was added to measure this directly.
- **Evidence-doc figure correction.** See the note under "Files in this
  evidence directory" above — one repair-pass evidence file states
  "2 ignored" where the final, correct figure is "3 ignored"; the
  original file is preserved unedited, with the correction recorded here
  and in this milestone's own "Test count" section.
- **Prior G9 hardening backlog** (tray glyph rendering, `PrivateSessionBus`'s
  unbounded read, the TUI's fixed `pkttyagent` wait, `StateDirectoryMode`,
  the ADR-006 ownership addendum — per `docs/evidence/g9/G9_MILESTONE.md`)
  remains open and unrelated to Wave 1; carried forward per the
  repository's existing backlog convention, not restated as a Wave 1
  finding.
