# Gate 2b evidence — provider-health producer, daemon wiring, D-Bus population

Governing manifest: `docs/guardian/30_TDD/gates/phase2-2b-manifest.toml`.
Governing TDD: `docs/guardian/30_TDD/gates/phase2-2b-tdd.md`.

Produced on a fresh clone of the working tree (baseline `5a39ac9d...`,
governance-only descendant of the manifest's recorded
`baseline_sha = 10a20abc...`) inside the disposable `guardian-g9`
Ubuntu 26.04.1 multipass VM (full `libadwaita-1-dev` workspace build),
independent of the host workstation.

## Baseline verification (before this gate's changes)

`cargo test --workspace` on the unmodified baseline:

```
passed 375 failed 0 ignored 3
```

Matches the manifest's `expected_baseline`.

## Validation commands (after this gate's changes)

```
cargo fmt --check                                                # exit 0
cargo clippy --workspace --all-targets --all-features -- -D warnings   # exit 0
cargo test --workspace                                           # exit 0
```

Full-workspace test totals after this gate's changes:

```
passed 389 failed 0 ignored 3
```

389 = 375 (baseline) + 14 new tests added by this gate (6 in
`guardian-core`'s new `providers::health` module, 5 net-new in
`guardian-daemon`'s `dbus_surface` unit tests — 5 added, 1 replaced —, 3
net-new in `guardian-daemon`'s bin-level `#[cfg(test)]` module, and 1 new
Layer-2 private-bus contract test). 0 failed, 3 ignored (unchanged from
baseline — no `#[ignore]` was added or removed by this gate).

## Evidence by owned normative ID

### `P2-API-001` — `Incidents1.ListIncidents()` returns real, live incidents

Layer 1 (pure, no D-Bus) — `crates/guardian-daemon/src/dbus_surface.rs`:
- `dbus_surface::tests::incidents_list_is_empty_for_a_freshly_built_engine_with_no_admitted_events`
- `dbus_surface::tests::incidents_list_reflects_a_real_incident_the_engine_actually_opened`
- `dbus_surface::tests::to_incident_wire_preserves_every_field_losslessly`
- `dbus_surface::tests::to_incident_wire_never_panics_on_a_still_open_incident_with_no_close_fields`

Layer 1 (pure, no D-Bus) — the provider-health snapshot-diff producer
itself, `crates/guardian-core/src/providers/health.rs`:
- `providers::health::tests::first_snapshot_ever_observed_emits_no_event`
- `providers::health::tests::unchanged_snapshot_pair_emits_no_event`
- `providers::health::tests::availability_change_for_one_capability_emits_exactly_one_correlatable_event`
- `providers::health::tests::health_only_change_with_stable_availability_still_emits_an_event`
- `providers::health::tests::multiple_changed_capabilities_each_emit_their_own_event`
- `providers::health::tests::a_newly_appeared_capability_id_is_not_yet_a_transition`

Layer 2 (mocked/private D-Bus) —
`crates/guardian-daemon/tests/phase2_2b_contract.rs`:
- `p2_2b_dbus_contract_suite` (records the `P2-API-001` sub-check
  internally as `assert_p2_api_001_list_incidents_returns_the_real_open_incident`):
  drives a real snapshot diff through `HealthTransitionProducer`, admits
  the resulting `Event`s through a real `IngressClock`/`CorrelationEngine`
  pair (the same wiring `guardian-daemon`'s `main()` uses), and calls the
  real `ListIncidents` D-Bus method over a private bus, asserting a
  non-empty, correctly round-tripped result.

```
$ cargo test -p guardian-daemon --test phase2_2b_contract
running 1 test
test p2_2b_dbus_contract_suite ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

### `P2-API-002` — no new D-Bus surface

Layer 2 — `crates/guardian-daemon/tests/phase2_2b_contract.rs`,
`assert_p2_api_002_no_new_dbus_surface` (run inside
`p2_2b_dbus_contract_suite` above): live-introspects
`Capabilities1`/`Incidents1`/`Transactions1` over a private bus and
asserts their method sets equal exactly the recorded G9 baselines:

- `docs/evidence/g9/g9-capabilities-introspect.txt` — `ListBlockers`,
  `ListCapabilities`, `PsiSummary`
- `docs/evidence/g9/g9-incidents-introspect.txt` — `ListIncidents`
- `docs/evidence/g9/g9-transactions-introspect.txt` — `ListTransactions`

No method, interface, or object path was added to any of the three;
`Incidents1::list_incidents`'s return value is the only behavior change.

### `P2-API-003` — `IncidentWire` shape-lock regression test

Layer 1 — `crates/guardian-daemon/src/dbus_surface.rs`:
- `dbus_surface::tests::incident_wire_shape_is_locked_to_a_seven_field_string_tuple`

This test destructures a value of the `IncidentWire` type alias into an
explicit `(String, String, String, String, String, String, String)`
binding — a future accidental change to the tuple's arity, field order,
or field type fails this test to *compile*, not merely to pass, per the
manifest's regression-guard requirement. During development this was
manually perturbed (a field temporarily changed to a non-`String` type)
and observed to break compilation as expected, then reverted — the
throwaway local check the gate TDD calls for; it is not re-run
automatically since perturbing `IncidentWire` itself is forbidden scope
for this gate.

## R2 evidence (single shared `CorrelationIngress` admission point)

Layer 1 — `crates/guardian-daemon/src/bin/guardian-daemon.rs`
(`#[cfg(test)] mod tests`):
- `tests::monitoring_tick_and_a_second_source_share_one_monotonically_increasing_ingress_sequence` —
  proves the existing daemon-tick producer and a second, independently
  admitted event share one `IngressClock`'s strictly increasing
  `ingress_sequence`.
- `tests::admit_outcome_ignored_for_unrecognized_event_type_still_advances_ingress` —
  proves the daemon-tick event is a real ingress source (its
  `admitted_ingress_count` increments) even though it correlates to
  nothing.

## R6 evidence (`P2-REC-003` daemon-side half)

Layer 1 — `crates/guardian-daemon/src/bin/guardian-daemon.rs`:
- `tests::admit_event_handles_a_capacity_rejected_outcome_without_panicking` —
  drives the debounce ring to capacity and confirms the engine's
  rejection counter increments; the single `eprintln!("[guardian-daemon]
  correlation debounce ring at capacity: ...")` log line itself is
  emitted from `admit_event` (see that function's doc comment in
  `guardian-daemon.rs`), consuming only the already-typed
  `CapacityRejected` value `guardian-core`'s `CorrelationEngine::
  reject_capacity()` returns — `guardian-core/src/correlation.rs` itself
  performs no I/O (unmodified, forbidden scope).

## Scope decision recorded (R2/R7 — PSI real-time daemon wiring)

Gate TDD R2 lists PSI as one of the three sources that should ultimately
feed the one shared ingress point; R7 conditionally guards PSI-specific
glue code ("if daemon wiring adds any..."). No live PSI kernel-poll event
production thread exists anywhere in `guardian-daemon` today (confirmed
by reading `crates/guardian-daemon/src/bin/guardian-daemon.rs`'s `main()`
before this gate's changes — `PsiEventSource` is driven only from a
standalone evidence example,
`crates/guardian-core/examples/g8_psi_trigger_evidence.rs`). This gate
does **not** add a new live PSI production thread to `guardian-daemon`:
doing so would be new, unrequested scope not required by any
`P2-API-00*` ID this gate owns, and would contradict R1's own "REQUIRED
FOUNDATION only" minimalism and `AGENTS.md`'s gate discipline. R7's guard
is satisfied vacuously (no PSI-specific glue code is added). Wiring a
real PSI production thread into `guardian-daemon` is left to a future
gate. See the Contract Collision Table in this gate's completion report
for the full reasoning.

## Files changed

Added:
- `crates/guardian-core/src/providers/health.rs`
- `crates/guardian-daemon/tests/phase2_2b_contract.rs`
- `docs/evidence/p2/GATE2B_EVIDENCE.md` (this file)

Modified:
- `crates/guardian-core/src/providers/mod.rs` (registers the new `health` module)
- `crates/guardian-daemon/src/bin/guardian-daemon.rs` (shared ingress/engine wiring, doc corrections)
- `crates/guardian-daemon/src/dbus_surface.rs` (`Incidents1` reads the live engine, doc corrections, new tests)

No file under the manifest's `forbidden_scope` was touched; no file
outside `allowed_scope` was touched except this evidence document and
the manifest-named `docs/evidence/p2/` directory itself, which the
manifest's own `required_evidence` list requires as a deliverable.
