# Gate 2a health-lifecycle repair — evidence

Governing manifest:
`docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-manifest.toml`.
Governing TDD:
`docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-tdd.md`.

Reopened normative IDs: `P2-COR-003`, `P2-COR-004`. All other 17 Gate 2a
IDs (`P2-EVT-001..004`, `P2-COR-001/002/005/006/007`, `P2-INC-002..004`,
`P2-REC-001..005`) are unaffected and unmodified in their own right.

Produced on a fresh extraction of the working tree (baseline
`89ff50f0e0bcb7dcfc5df0438bddfe4e218219b7`, matching the manifest's
recorded `baseline_sha` exactly) inside the disposable `guardian-g9`
Ubuntu 26.04.1 multipass VM (full `libadwaita-1-dev` workspace build),
independent of the host workstation. The host workstation lacks
`libadwaita-1-dev`, so `cargo test --workspace`/`cargo clippy` cannot run
a full-workspace build there; `cargo fmt --check` (parse-only, no build)
was additionally confirmed clean on the host.

Note on files touched during this VM session: `systemd-logind` needed a
`sudo systemctl restart systemd-logind` inside the disposable VM after an
unrelated stale-session timeout was blocking `guardian-daemon`'s G2
privilege-topology D-Bus tests (`crates/guardian-daemon/tests/
g2_privilege_topology_contract.rs`) from completing — a VM-environment
condition, not a change caused by or related to this repair. No change
was made inside the VM's copy of the repository other than the two files
this repair's `allowed_scope` covers; the VM's repository copy itself is
disposable and is not the record of truth — the host working tree at
`/home/Cliff/SysProjects/Guardian` is.

## Baseline verification (before this repair's changes)

`cargo test --workspace` on the unmodified baseline extraction (original
`crates/guardian-core/src/correlation.rs` and `crates/guardian-core/
tests/correlation_contract.rs` restored from `git show
89ff50f0:<path>` before this run, then this repair's changes reapplied
afterward):

```
passed 389 failed 0 ignored 3
```

Matches the manifest's `expected_baseline` ("389 passed, 0 failed, 3
ignored (baseline_sha, before this repair's changes)") exactly. (This
also matches Gate 2b's own recorded post-Gate-2b total in
`docs/evidence/p2/GATE2B_EVIDENCE.md`, confirming no drift between that
gate's close and this repair's start.)

## Validation commands (after this repair's changes)

```
cargo fmt --check                                                        # exit 0, no diff
cargo clippy --workspace --all-targets --all-features -- -D warnings     # exit 0, 0 errors/warnings
cargo test --workspace                                                   # exit 0
```

Full-workspace test totals after this repair's changes:

```
passed 396 failed 0 ignored 3
```

396 = 389 (baseline) + 7 net-new tests, all in `crates/guardian-core/
tests/correlation_contract.rs` (28 `#[test]` functions at baseline → 35
after this repair). 0 failed, 3 ignored (unchanged from baseline — this
repair's `allowed_scope` never touches whatever pre-existing tests are
ignored elsewhere in the workspace).

The 7 net-new tests:

1. `p2_cor_004_flapping_faster_than_dwell_via_fresh_observations_produces_no_thrashing`
2. `r2_no_fresh_observation_means_no_promotion_from_wall_time_alone`
3. `r3_fresh_observation_unresolved_never_falsely_advances_or_corrupts`
4. `r4_fresh_health_observation_classify_matches_state_table`
5. `r4_event_driven_available_error_never_misclassified_as_good`
6. `r5_symmetric_recovery_fresh_observation_closes_incident`
7. `regression_second_real_bad_event_still_promotes_pending_candidate`

One pre-existing test, `p2_cor_003_debounced_available_to_unavailable_
opens_exactly_one_incident`, was rewritten in place (not counted as
net-new) to prove its own normative ID via the repaired, real-production
shape (R1) rather than the defective two-synthetic-Event proof it used
before this repair. `p2_cor_004_flapping_faster_than_dwell_produces_no_
thrashing` (the original Event-driven flap test) is unmodified and still
passes, alongside the new fresh-observation-driven flap test above (R6).

## Evidence by reopened normative ID

### `P2-COR-003` — debounced Available→Unavailable opens exactly one incident (repaired)

- `crates/guardian-core/tests/correlation_contract.rs::
  p2_cor_003_debounced_available_to_unavailable_opens_exactly_one_incident`
  — rewritten to the real production shape: one real `Event`
  (`health_event`, shaped like `HealthTransitionProducer`'s edge-triggered
  output) admits to `DebouncePending`; a later call to
  `CorrelationEngine::advance_health_dwell` with
  `FreshHealthObservation::Bad` (not a second/cloned `Event`) advances the
  candidate past `health_min_dwell` and opens exactly one `Incident`. A
  further real `Bad` `Event` links to the same incident (`IncidentUpdated`,
  same ID); a further fresh `Bad` re-observation, with no pending
  candidate left to advance, is a safe no-op (`AdmitOutcome::Ignored`
  path inside `advance_health_dwell`), never opening a second incident.
  `engine.open_incidents().len() == 1` at the end.

### `P2-COR-004` — flapping faster than dwell produces no thrashing (repaired)

- `crates/guardian-core/tests/correlation_contract.rs::
  p2_cor_004_flapping_faster_than_dwell_produces_no_thrashing` (unmodified
  original) — Event-driven flap (alternating `Unavailable`/`Available`
  every 100ms against 500ms dwell) still never opens an incident.
- `crates/guardian-core/tests/correlation_contract.rs::
  p2_cor_004_flapping_faster_than_dwell_via_fresh_observations_produces_no_thrashing`
  (new) — the same guarantee re-expressed (R6) via
  `advance_health_dwell`-driven fresh re-observations: alternating
  `FreshHealthObservation::Good`/`Bad` every 100ms against 500ms dwell,
  starting from one real seed `Event`, never opens an incident.
  `engine.open_incidents().len() == 0` at the end in both tests.

## Evidence for the repair's other requirements (R1–R7)

- **R1** (fresh observation advances dwell, not a second `Event`): proven
  by the repaired `p2_cor_003` test above.
- **R2** (no fresh observation ⇒ no promotion from wall time alone):
  `r2_no_fresh_observation_means_no_promotion_from_wall_time_alone` —
  a pending candidate is left untouched (`DebouncePending`,
  `debounce_candidate_count() == 2`, `open_incidents().len() == 0`) after
  10 real ingress-clock seconds elapse via an *unrelated* capability's
  admission, with no `advance_health_dwell` call for the pending
  capability itself.
- **R3** (unknown/absent/unclassifiable never falsely advances or
  corrupts): `r3_fresh_observation_unresolved_never_falsely_advances_or_corrupts`
  — exercises `FreshHealthObservation::Unresolved` (standing in for
  "absent from the snapshot"), `Availability::Unknown`, and
  `Health::Unknown` in sequence against one pending candidate; the
  candidate remains pending and its original `first_seen` is provably
  untouched (a subsequent genuine fresh `Bad` re-observation at the
  originally-scheduled elapsed time still promotes normally).
- **R4** (`health_direction`/`FreshHealthObservation::classify` use both
  dimensions; `Available+Error` no longer misclassifies as `Good`):
  `r4_fresh_health_observation_classify_matches_state_table` (unit-level,
  full state table) and `r4_event_driven_available_error_never_misclassified_as_good`
  (through the real `Event`-admission path via `classify()` in
  `crates/guardian-core/src/correlation.rs`, using the new
  `HEALTH_HEALTH_TO_ATTR`/`health_event_with_health` test fixture) — an
  `Available`+`Error` event against an already-open incident yields
  `AdmitOutcome::Ignored` (neither a false recovery nor a false further-Bad
  link); the incident stays open, exactly one, with `event_ids.len() == 0`
  unaffected by the unresolved event (the incident itself was opened via a
  fresh re-observation, which links no `Event` at all — see
  "Design note" below).
- **R5** (symmetric recovery/closure via fresh observation):
  `r5_symmetric_recovery_fresh_observation_closes_incident` — after
  opening via R1's repaired path, one real recovery `Event`
  (`Availability::Available`) starts a `Good`-direction candidate via the
  pre-existing `admit_health_with_open_incident` logic; a later fresh
  `FreshHealthObservation::Good` re-observation (not a second recovery
  `Event`) advances it past dwell and closes exactly one `Incident`.
- **R6**: see `P2-COR-004` above.
- **R7** (regression: other 17 IDs unaffected; Event-driven path remains
  valid): full `correlation_contract.rs` suite green, with all 17
  non-reopened IDs' tests untouched by this repair's diff (see "Files
  changed" below — no edits outside the P2-COR-003/004 section and the
  shared test helpers/imports); plus
  `regression_second_real_bad_event_still_promotes_pending_candidate`,
  an explicit test proving a second real `Bad` `Event` (not a
  fresh-observation call) still promotes a pending candidate exactly as
  it did before this repair.

## Design note: fresh-observation-opened incidents carry no linked `EventId`

An incident opened via `CorrelationEngine::advance_health_dwell` (the new
fresh-observation path) has `event_ids.len() == 0` at the moment it
opens — there is no real `Event` behind a fresh re-observation to link,
and by rule (`AGENTS.md` "No placeholders") this repair never fabricates
one merely to populate `event_ids`. Provenance for this promotion is
still recorded, textually, in the incident's `evidence` field (e.g.
"capability ... debounced transition to Unavailable (fresh
re-observation, no second Event manufactured)") — the same mechanism
`Incident::evidence` already uses elsewhere for backreference text. A
later real `Event` for the same capability still links normally via the
pre-existing `admit_health_with_open_incident`/`admit_psi` paths,
unaffected by this repair.

## Contract compliance

- Deferred work not implemented here (recorded as a forward pointer in
  the manifest/TDD only): Gate 2b's own downstream repair (`Event`
  Availability+Health provenance, daemon fresh-snapshot-driven
  `capability_registry_tick` wiring, and `phase2_2b_contract.rs`'s
  `build_engine_with_one_real_open_incident` fixture replacement). None
  of `crates/guardian-daemon/**` or `crates/guardian-core/src/providers/
  health.rs` was read or touched in this pass, per the manifest's
  `forbidden_scope`.
- The two parked Gate 2c files (`docs/guardian/30_TDD/gates/
  phase2-2c-manifest.toml`, `docs/guardian/30_TDD/gates/phase2-2c-tdd.md`)
  were explicitly out of `forbidden_scope`, not read, and remain exactly
  as they were in the pre-existing working tree — their modified state
  predates this task and is not part of this repair's diff (see "Files
  changed" below).
- No contract ambiguity or source drift encountered. The one
  implementation-time decision this repair TDD explicitly left open — the
  exact typed shape for the fresh-observation entry point — was resolved
  as `FreshHealthObservation` (a 3-variant `Good`/`Bad`/`Unresolved` enum)
  plus `CorrelationEngine::advance_health_dwell(capability_id,
  observation, ingress_clock, ingress_sequence) -> AdmitResult`, chosen
  specifically because (per the TDD's own stated reason for rejecting the
  earlier `HashSet<CapabilityId>` shape) it can distinguish "still Bad"
  from "still Good" from "absent/unresolved" for a pending *recovery*
  candidate, satisfying R3/R5 together.

## Files changed by this repair (distinguishing from the parked Gate 2c edits)

This repair's own changes:

- `crates/guardian-core/src/correlation.rs` (modified) — `HEALTH_HEALTH_TO_ATTR`
  constant; `health_direction()` signature widened to `(Availability,
  Health) -> Option<HealthDirection>` with the corrected state table;
  `classify()` reads the optional `health_to` attribute (defaults to
  `Health::Healthy` when absent, preserving today's real-production
  behavior since Gate 2b does not emit this attribute yet); new
  `FreshHealthObservation` enum + `classify()` associated function; new
  `CorrelationEngine::advance_health_dwell()` public method;
  `open_new_incident()` refactored to delegate to a new, provenance-generic
  `open_new_incident_at()` core (shared by the `Event`-driven and
  fresh-observation-driven opening paths).
- `crates/guardian-core/tests/correlation_contract.rs` (modified) — new
  `health_event_with_health()` test fixture; `p2_cor_003` rewritten to the
  repaired real-production shape; 7 net-new tests (R2/R3/R4×2/R5/R6/R7,
  listed above).
- `docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-manifest.toml`,
  `docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-tdd.md`
  (pre-existing, authored before this execution turn as this repair's own
  governance files — read, not modified, by this execution).
- `docs/evidence/p2/GATE2A_HEALTH_LIFECYCLE_REPAIR_EVIDENCE.md` (this
  file, new).

Explicitly NOT part of this repair, pre-existing in the working tree
before this task began, and left untouched:

- `docs/guardian/30_TDD/gates/phase2-2c-manifest.toml` (parked Gate 2c
  preflight edit, modified before this task started)
- `docs/guardian/30_TDD/gates/phase2-2c-tdd.md` (parked Gate 2c preflight
  edit, modified before this task started)

## Git state (original repair pass)

Left uncommitted per the manifest's `commit_policy` ("leave-uncommitted-
for-independent-review"). `git status --short` at the end of this task:

```
 M crates/guardian-core/src/correlation.rs
 M crates/guardian-core/tests/correlation_contract.rs
 M docs/guardian/30_TDD/gates/phase2-2c-manifest.toml
 M docs/guardian/30_TDD/gates/phase2-2c-tdd.md
?? docs/evidence/p2/GATE2A_HEALTH_LIFECYCLE_REPAIR_EVIDENCE.md
?? docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-manifest.toml
?? docs/guardian/30_TDD/gates/phase2-2a-health-lifecycle-repair-tdd.md
```

The two `phase2-2c-*` modified files and the untracked
`phase2-2a-health-lifecycle-repair-manifest.toml`/`-tdd.md` pair predate
this execution turn (the parked Gate 2c preflight edits, and this
repair's own already-authored governance files, respectively) and are not
part of this repair's actual code/test/evidence diff. Gate 2b repair was
not started. No commit was made.

---

# Addendum: audit-driven confidence-classification correction

**This section supersedes nothing above — it records a separate, later
correction to the same repair candidate, per this project's
"supersede, don't hide" convention.** Everything above this line remains
the accurate record of the original repair pass (R1–R7, the
fresh-observation dwell mechanism). This addendum covers a distinct,
independently-audited defect found in that same still-uncommitted
candidate: `health_direction()`'s target-state classification was
correct (`Available+Warning` → `Bad`, `Degraded` → `Bad`, `Available+
Error` → unresolved), but the *confidence* attached to an opened
incident was not carried from that classification — every `Bad`-direction
incident-open call site hardcoded `Confidence::Confirmed`, regardless of
which transition actually produced it.

## The audited defect

Governed (repair TDD, "Target-state classification vs. incident
confidence" section):

```
Available → Unavailable → Confirmed
Healthy → Warning       → Probable
sustained Degraded      → Unknown
```

Before this correction, `HealthDirection` was a bare two-variant enum
(`Good`/`Bad`) with no confidence information. Every incident-open call
site that received `HealthDirection::Bad` — `admit_health_candidate`'s
Event-driven open, and `advance_health_dwell`'s fresh-observation-driven
open — independently hardcoded `Confidence::Confirmed` as a literal
argument, because the classification result reaching that call site
carried no confidence signal to use instead. Net effect: `Degraded` and
`Available+Warning` both opened incidents at `Confidence::Confirmed`
instead of `Confidence::Unknown`/`Confidence::Probable`.

## The typed repair (smallest appropriate boundary)

`HealthDirection::Bad` gained a payload: `Bad(Confidence)`
(`crates/guardian-core/src/correlation.rs`). `health_direction()` now
selects the governed tier at classification time — the single point that
already knows which transition produced the `Bad` result — and every
downstream site (`DebounceCandidate::target`, both incident-open call
sites in `admit_health_candidate` and `advance_health_dwell`) reads the
carried `Confidence` out of the enum payload instead of hardcoding or
re-deriving one. No confidence is computed anywhere except
`health_direction()` itself; nothing downstream infers confidence from a
bare `Bad`.

Concretely:

- `Availability::Unavailable` → `HealthDirection::Bad(Confidence::Confirmed)`
- `Availability::Degraded` → `HealthDirection::Bad(Confidence::Unknown)`
- `Availability::Available` + `Health::Warning` → `HealthDirection::Bad(Confidence::Probable)`
- `Availability::Available` + `Health::Error`/`Stale`/`Unknown` → `None` (unresolved, unchanged)

`FreshHealthObservation::classify()`, `admit_health_with_open_incident`,
and `admit_health_candidate`'s direction-equality checks were updated to
match `HealthDirection::Bad(_)` (direction-only, ignoring the payload)
where they only ever needed to know "is this actionable," and to bind
`confidence` explicitly at the two sites that actually open an incident.
The candidate stored in the debounce ring (`DebounceCandidate::target`)
now stores the full `direction` value (not a re-synthesized
`HealthDirection::Bad`), so the confidence recorded at the moment a
capability was first classified survives unchanged through dwell to
whichever call site later promotes it — Event-driven or
fresh-observation-driven, opened symmetrically either way.

## RED evidence

Four focused tests were added to
`crates/guardian-core/tests/correlation_contract.rs` (new section titled
"Gate 2a health-lifecycle repair -- audit-driven confidence-
classification correction", inserted between the R5 and R7 sections),
run against the pre-fix candidate before any source change:

```
running 4 tests
test confidence_available_to_unavailable_opens_with_confirmed_confidence ... ok
test confidence_available_error_cannot_open_or_close_incident ... ok
test confidence_sustained_degraded_opens_with_unknown_confidence ... FAILED
test confidence_available_warning_opens_with_probable_confidence ... FAILED

---- confidence_sustained_degraded_opens_with_unknown_confidence stdout ----
assertion `left == right` failed: sustained Degraded has no §4.2-governed
confidence tier -- must open honestly as Confidence::Unknown, never a
hardcoded Confirmed
  left: Confirmed
 right: Unknown

---- confidence_available_warning_opens_with_probable_confidence stdout ----
assertion `left == right` failed: Healthy->Warning is §4.2's named
Probable transition -- must open as Confidence::Probable, never a
hardcoded Confirmed
  left: Confirmed
 right: Probable

test result: FAILED. 2 passed; 2 failed; 0 ignored; 0 measured; 35 filtered out
```

Two of the four (`confidence_available_to_unavailable_opens_with_
confirmed_confidence`, `confidence_available_error_cannot_open_or_
close_incident`) pass both before and after this correction — the
pre-fix candidate already got `Unavailable→Confirmed` right (the
hardcoded value happened to match) and already correctly left
`Available+Error` unresolved (a defect the *prior* repair pass, not this
one, had already closed). They are retained as governed regression
coverage for the two adjacent cases this correction must not disturb,
not as evidence of a defect in the candidate this correction targets.

After the fix, all four are GREEN (see "Final validation" below).

## Confidence results for the four governed cases (post-fix)

| Case | Test | Result |
|---|---|---|
| sustained `Degraded` | `confidence_sustained_degraded_opens_with_unknown_confidence` | opens `Confidence::Unknown` |
| `Available` + `Warning` | `confidence_available_warning_opens_with_probable_confidence` | opens `Confidence::Probable` |
| `Available` → `Unavailable` | `confidence_available_to_unavailable_opens_with_confirmed_confidence` | opens `Confidence::Confirmed` |
| `Available` + `Error` | `confidence_available_error_cannot_open_or_close_incident` | never opens or closes an incident (`AdmitOutcome::Ignored` both with no prior candidate and against an already-open incident) |

## Regression validation

All previously-reviewed lifecycle behavior from the original repair pass
(R1–R7 above) was re-run unmodified and remains GREEN with unchanged
meaning — none of those tests' bodies were edited by this correction:
`p2_cor_003_debounced_available_to_unavailable_opens_exactly_one_
incident`, both `p2_cor_004_*` flap tests, `r2_no_fresh_observation_
means_no_promotion_from_wall_time_alone`, `r3_fresh_observation_
unresolved_never_falsely_advances_or_corrupts`,
`r4_fresh_health_observation_classify_matches_state_table`,
`r4_event_driven_available_error_never_misclassified_as_good`,
`r5_symmetric_recovery_fresh_observation_closes_incident`,
`regression_second_real_bad_event_still_promotes_pending_candidate`, and
all 17 non-reopened Gate 2a IDs' tests. Also unaffected: `p2_cor_005`'s
and `p2_cor_001`'s own `Confidence::Confirmed` assertions (PSI-path and
cross-reference tests, neither touched by this correction's `Health`
branch changes).

## Parked Gate 2c integrity

`docs/guardian/30_TDD/gates/phase2-2c-manifest.toml` and
`phase2-2c-tdd.md` were not read and not touched during this correction
pass. `git status --short`/`git diff --name-status` on the host working
tree confirm both remain in the same pre-existing `M` (modified-before-
this-session) state noted in the original evidence above — present, in
the working tree's diff, but not part of this correction's own change
set, which is exactly `crates/guardian-core/src/correlation.rs` and
`crates/guardian-core/tests/correlation_contract.rs`, plus this evidence
file.

## Final validation (this correction)

Run on a fresh tar-transfer of the working tree (uncommitted changes
included) into the disposable `guardian-g9` Ubuntu 26.04 multipass VM
(full `libadwaita-1-dev` workspace build, `guardian-gui` included),
independent of the host:

```
cargo fmt --check                                                        # exit 0, no diff
cargo clippy --workspace --all-targets --all-features -- -D warnings     # exit 0, 0 errors/warnings (guardian-gui built clean)
cargo test --workspace                                                   # exit 0
```

```
passed 400 failed 0 ignored 3
```

400 = 396 (post-original-repair total, recorded above) + 4 net-new
confidence-classification tests. 0 failed. 3 ignored, unchanged from
every prior recorded total in this file. `cargo fmt --check` was also
independently confirmed clean on the host.

## Files changed by this correction

- `crates/guardian-core/src/correlation.rs` — `HealthDirection::Bad`
  gained a `Confidence` payload; `health_direction()` selects the
  governed tier per transition at classification time; both
  incident-open call sites (`admit_health_candidate`,
  `advance_health_dwell`) read the carried confidence instead of
  hardcoding `Confidence::Confirmed`; `DebounceCandidate::target` now
  stores the full classified `direction` (carrying its confidence)
  rather than a bare `HealthDirection::Bad`; direction-only equality
  checks updated to `matches!(_, HealthDirection::Bad(_))` where they
  don't need the payload.
- `crates/guardian-core/tests/correlation_contract.rs` — 4 new tests
  (listed above), inserted between the R5 and R7 sections.
- `docs/evidence/p2/GATE2A_HEALTH_LIFECYCLE_REPAIR_EVIDENCE.md` (this
  addendum).

Left uncommitted, same as the original repair pass. No commit, push, or
tag was made.
