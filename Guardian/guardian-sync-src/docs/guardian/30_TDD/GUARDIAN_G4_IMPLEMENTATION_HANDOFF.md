# Guardian Phase 0 Implementation Handoff
## G4 — Transaction Engine Only

**Audience:** Primary coding agent
**Scope:** **G4 — Transaction Engine** only
**Stop condition:** the normative G4 tests below are green, or the gate is
honestly reported partial/blocked with the specific missing evidence named.
Do **not** begin G5, real providers, the privileged helper, GUI/TUI/CLI, or
packaging.
**Governing contract:** `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
§2 (GP-04, GP-05, GP-06, GP-08, GP-10 especially), §14 (transaction state
machine), §15 (transaction observation contract), §16 (error model), §23
(persistent state layout), §36 (P0-TXN-001..012)
**Prerequisite:** G3 tagged at `phase0-g3-core-data-models` (commit
`d21d0c4f41f7032db969b0b50c20c72c17b836c5`). Confirm this tag exists and
`HEAD` descends from it before starting.

---

# 1. Mission

G4 turns Guardian's G3 data models into a real, deterministic transaction
lifecycle: every risky mutation becomes bounded, authorized, observable,
recoverable, and auditable, exactly as GP-05 requires. This is still not a
real-provider gate — everything is exercised against deterministic fixture
providers/adapters, matching G3's own testing discipline.

The desired result is a repository in which:

- a `TransactionRecord` and the canonical state machine (§18 below) exist
  as typed models in `guardian-core`, using exactly the contract's states
  and transitions — no invented states, no arbitrary `set_state`;
- `TransactionId` has its own deliberately-chosen identity semantics (§17),
  not inherited from `CapabilityId`'s domain-identity validator;
- every transaction genuinely follows Snapshot → Validate → Authorize →
  Apply → Observe → Confirm → Commit, or fails onto a defined path that
  reaches `REJECTED`/`FAILED`/`ROLLED_BACK`/`ROLLBACK_FAILED`, with real
  typed logic behind each step — not a rubber-stamp pipeline where every
  step trivially succeeds;
- G3's two carried-forward findings become real, resolved decisions: NB-1
  (unknown privilege/access blocks `Apply`, not silently ignored) and NB-2
  (a defined owner and mechanism for `revision`, not a caller-trusted
  number);
- TOCTOU revalidation immediately before `Apply` is real and tested, not
  merely validated once at transaction start;
- lost-response/duplicate-apply risk is addressed via `idempotency_key`
  (P0-TXN-009), not hand-waved;
- a persistence contract exists (schema, versioning, atomic write, restart
  recovery) sufficient to satisfy P0-TXN-011, without implementing
  production packaging;
- `P0-TXN-001..012` are green, or the gate is reported blocked with the
  specific missing evidence named;
- no G5 Diagnostic Budget Manager, no G7 production daemon integration, no
  G8 real provider, no client, no packaging exists anywhere in the result.

Then stop.

---

# 2. Read before changing code

1. `AGENTS.md`
2. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
   - §2 GP-04 (single-writer), GP-05 (every write is transactional), GP-06
     (fail closed), GP-08 (preserve evidence), GP-10 (explain decisions)
   - §4 Required repository layout (`transaction/` under `guardian-core`)
   - §10 Risk taxonomy (reused, not reinvented)
   - §13 Provider Arbitrator (G3, consumed here — do not modify it)
   - §14 Transaction state machine + transaction record
   - §15 Transaction observation contract
   - §16 Error model
   - §23 Persistent state layout
   - §36 P0-TXN-001..012
3. `docs/guardian/30_TDD/GUARDIAN_G3_IMPLEMENTATION_HANDOFF.md` and
   `GUARDIAN_G3_INDEPENDENT_REVIEW_HANDOFF.md` — G3's data models and the
   audit process this gate must survive the same way.
4. `docs/evidence/g3/G3_MILESTONE.md` — **read this in full before writing
   any code.** Its "Forward constraints for G4+" section (NB-1..NB-4) is
   binding on this handoff; §6 (NB-1), §7 (NB-2), §8 (NB-4), and §23 (NB-3)
   below are this handoff's resolution of those constraints and must not be
   silently reopened or ignored.
5. `docs/guardian/20_Control_Plane/Transaction_Engine.md`
6. `docs/guardian/20_Control_Plane/Privilege_and_Authorization.md`
7. `docs/adr/ADR-002-guardian-privilege-topology.md` — the G2 boundary
   this gate must not regress (§12 below).

---

# 3. Normative G4 contract IDs

The **only** normative test IDs in scope for G4 are `P0-TXN-001..012`,
mechanically confirmed as the contract's complete transaction-test group
(`grep -oE "P0-[A-Z]+-[0-9]+" docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md
| sort -u` — the full ID list contains no `P0-CAP-*`/`P0-PROV-*`/`P0-INC-*`
group, confirming G3's boundary, and the transaction group is exactly
`P0-TXN-001..012`, nothing more). Do not invent new IDs.

```text
P0-TXN-001 — happy path                    Transaction reaches COMMITTED only through valid state transitions.
P0-TXN-002 — validation failure             Invalid precondition ends in REJECTED and no apply occurs.
P0-TXN-003 — authorization denied           Denied authorization performs no apply.
P0-TXN-004 — apply failure                  Apply error reaches FAILED or rollback path according to whether state changed.
P0-TXN-005 — observation failure            Provider call success followed by failed health observation does not commit.
P0-TXN-006 — rollback success               Failed observation with supported rollback ends ROLLED_BACK.
P0-TXN-007 — rollback failure               Rollback failure ends ROLLBACK_FAILED.
P0-TXN-008 — terminal immutability          A terminal transaction cannot re-enter an active state.
P0-TXN-009 — idempotent retry               Same idempotency key cannot perform the same write twice.
P0-TXN-010 — stale resource identity        Resource replacement between validation/apply blocks apply.
P0-TXN-011 — daemon restart                 Persisted nonterminal transaction is recovered into a defined state after daemon restart.
P0-TXN-012 — client disconnect              Client disappearance does not lose the audit record.
```

The governing contract is judged **sufficient** for this gate — it
specifies the exact state machine, the exact transaction record shape, the
exact observation-policy shape, and 12 concrete acceptance tests. Do not
report `G4 BLOCKED — GOVERNING CONTRACT INSUFFICIENT` merely because some
implementation details (exact `TransactionId` format, exact persistence
schema version, exact revision-ownership mechanism) are left to this
handoff to specify — that is normal implementation latitude, not a contract
gap. Only escalate that status if inspection reveals a genuine textual
contradiction, not an open design choice this handoff already resolves.

---

# 4. Transaction state machine (§14 of the governing contract, verbatim states)

```text
CREATED
VALIDATING
VALIDATED
AUTHORIZING
AUTHORIZED
APPLYING
OBSERVING
COMMITTED

ROLLING_BACK
ROLLED_BACK

REJECTED
FAILED
ROLLBACK_FAILED
EXPIRED
CANCELLED
```

Use exactly these states — do not rename, merge, or add states. Terminal
states (`COMMITTED`, `ROLLED_BACK`, `REJECTED`, `FAILED`,
`ROLLBACK_FAILED`, `EXPIRED`, `CANCELLED`) **must be immutable**
(P0-TXN-008): implement transitions as a function that rejects any attempt
to leave a terminal state, not as a bare public setter. No
`set_state(anything)` API may exist — only named transition methods
(`fn begin_validation(self) -> Result<...>`, etc.) that each encode their
own legal-predecessor check.

## 4.1 Legal transitions

Define the legal transition graph explicitly and reject illegal ones with
a typed error, not a panic:

```text
CREATED        → VALIDATING
VALIDATING     → VALIDATED | REJECTED
VALIDATED      → AUTHORIZING
AUTHORIZING    → AUTHORIZED | REJECTED
AUTHORIZED     → APPLYING
APPLYING       → OBSERVING | FAILED | ROLLING_BACK
OBSERVING      → COMMITTED | ROLLING_BACK | FAILED
ROLLING_BACK   → ROLLED_BACK | ROLLBACK_FAILED
(CREATED, VALIDATING, VALIDATED, AUTHORIZING, AUTHORIZED)
                → CANCELLED | EXPIRED   (explicit external cancellation / deadline;
                                          safe because no provider mutation has begun)
```

`APPLYING → ROLLING_BACK` covers the case where `Apply` itself reports a
failure that is known to have partially mutated state (§7 below).
`OBSERVING → ROLLING_BACK` covers the case where the provider call
succeeded but observation determined the postcondition was not met
(P0-TXN-005/006). A required test must prove at least one illegal
transition (e.g. `COMMITTED → APPLYING`) is rejected, not merely that legal
ones succeed.

**`CANCELLED`/`EXPIRED` are legal successors only of the pre-mutation
states listed above.** `APPLYING`, `OBSERVING`, and `ROLLING_BACK` are
deliberately absent from this predecessor list — see §17.4 below for why a
direct `APPLYING → CANCELLED`, `APPLYING → EXPIRED`, `ROLLING_BACK →
CANCELLED`, or `ROLLING_BACK → EXPIRED` transition is unsafe and must not
be implemented.

## 4.2 `TransactionRecord` (§14.1, verbatim fields — use guardian-core types
where a G3 type already exists for the concept)

```rust
TransactionRecord {
    transaction_id,       // new type, §17 below — NOT CapabilityId
    idempotency_key,      // §27 below
    action_type,          // typed, not a free string — see §22
    risk_class,            // guardian_core::risk::Risk, reused unchanged
    initiating_bus_name,
    initiating_session,
    provider_id,           // guardian_provider_api::ProviderId, reused unchanged
    capability_id,          // guardian_provider_api::CapabilityId, reused unchanged

    created_at,
    deadline,

    pre_state,              // snapshot, §19
    validation_results,     // §20
    arbitration_result,     // guardian_core::arbitration::ArbitrationDecision, reused unchanged
    authorization_result,   // §21 -- NOT a re-implementation of G1/G2's real authorization

    requested_change,       // typed per action_type, never opaque payload
    provider_request,
    provider_response,

    observation_policy,     // §23
    observations,

    commit_result,
    rollback_result,        // §25/§26

    incident_ids,           // Vec<guardian_provider_api::IncidentId>, reused unchanged
}
```

`arbitration_result` reusing G3's real `ArbitrationDecision` type directly
(not a copy/paraphrase) is required — this is exactly how NB-1/NB-2 get
resolved: the transaction record carries the *actual* G3 decision, including
its `revision`, so later code can check it against current state rather
than trusting a bare number.

---

# 5. G2 boundary preservation (read this before writing `authorization_result`)

G4 may include a transaction-visible state such as `Authorized` (it is
already in the canonical state machine, §4). This records **that the
transaction's authorization step concluded successfully** — it is not, and
must never become, a mechanism by which `guardian-core` performs real
authorization itself. Concretely:

- The transaction engine's "Authorize" step (§21) **coordinates** a request
  to whatever real authorizer exists (G1's `Authorizer` trait,
  `PolkitAuthorizer`, or — in this gate's deterministic fixtures — a test
  double implementing the same trait) and records the *outcome*. It does
  not reimplement or bypass real polkit `CheckAuthorization`.
- `authorization_result` on `TransactionRecord` is a record of what
  happened, not a capability that can be forged/replayed to skip real
  authorization on a later attempt. Each new `Apply` attempt against a
  privileged operation must still pass through the real, independent
  privileged-boundary check — see GP-05/§14.2 ("Validation is repeated at
  the privileged boundary immediately before apply").
- `ArbitrationDecision.write_permitted` (G3) continues to mean only
  "control-plane policy permits proceeding." Nothing in G4 may promote it,
  or `authorization_ownership = Known(GuardianOwnedAuthorization)`, to mean
  "the caller is authorized." Both remain what G2/G3 already established.
- If any G4 type has a field or method whose name or shape could plausibly
  be read as "authorization proof forwarded to the privileged helper"
  (e.g. anything the helper would be tempted to trust instead of
  performing its own real `CheckAuthorization`), that is a **G2 regression**
  — do not build it. The privileged helper's independent-authorization
  invariant, established at G1/G2 and unchanged through G3, is unchanged
  by G4 too.
- Background transactions cannot unexpectedly prompt for interactive
  authentication if G1's P0-AUTH-003 rule prohibits it in that context —
  reuse G1's existing `interactive` flag semantics on
  `AuthorizationRequest`, do not invent a second one.

---

# 6. NB-1 resolution — unknown privilege/access blocks `Apply`

**Required conceptual invariant:** `PrivilegeRequirement::Unknown` on the
capability a transaction targets → **no `Apply`.** Concretely: the
`Validate` step (§20) MUST check the target capability's
`privilege_requirement` (from its `CapabilityRecord`, obtained via the
snapshot, §19) and produce `REJECTED` (not `FAILED`, since this is a
precondition failure, matching P0-TXN-002's semantics) if it is `Unknown`.

Do not invent an exception where a provider-owned operation is assumed to
make Guardian-held privilege irrelevant, and therefore skip this check.
`authorization_ownership = Known(ProviderOwnedAuthorization)` and
`privilege_requirement = Unknown` are independent facts (G3, unchanged) —
a provider performing its own authorization does not tell you what OS-level
access the operation itself needs, and no G3 evidence proves that
"provider-owned authorization" implies "privilege requirement doesn't
matter." If a future gate discovers a real, typed, evidence-backed reason
this exception is safe for a specific capability class, that is a separate,
explicitly-justified decision for that gate to make — G4 does not manufacture
it here.

Required test: a transaction targeting a capability with
`privilege_requirement = Unknown` reaches `REJECTED` at `Validate`, never
reaches `APPLYING`, regardless of `authorization_ownership`'s value.

---

# 7. NB-2 resolution — revision ownership

**G4 owns `revision` generation, not the transaction caller.** This section
was corrected from an earlier draft that described G3's `arbitrate()` as
"the source of revision" — that is imprecise and must not guide the
implementation. Read §7.1 before writing code.

## 7.1 Actual dataflow — `arbitrate()` does not generate revision

G3's `arbitrate()` is a **pure function**: it accepts `ArbitrationInput`
(which already carries a `revision` field, supplied by its caller) and
returns an `ArbitrationDecision` that carries that same `revision` value
through unchanged. `arbitrate()` does not generate, validate, or have any
opinion about whether the `revision` it was given is authoritative — G3's
independent audit confirmed exactly this (revision is "only asserted," not
model-enforced, at the G3 layer), and G3's own milestone record (NB-2)
says this explicitly. **`arbitrate()` is not the source of revision.**

The correct dataflow is:

```text
G4-owned capability/arbitration state source
  → generates the current revision for a capability_id
  → G4 constructs ArbitrationInput using that revision
  → G3's arbitrate() computes the decision and carries the revision
    through, unchanged, into ArbitrationDecision
  → TransactionRecord's pre_state snapshots that decision (§19)
```

**A transaction caller must never supply the authoritative revision.** Any
API surface that lets a transaction's initiator pass in a `revision` value
that G4 then trusts is a defect — `revision` must originate only from the
G4-owned state source described in §7.2.

## 7.2 Required `ArbitrationStateSource` abstraction

Define a G4-owned fixture abstraction conceptually equivalent to:

```rust
trait ArbitrationStateSource {
    fn current_revision(&self, capability_id: &CapabilityId) -> Revision;
    fn current_candidates(&self, capability_id: &CapabilityId) -> Vec<CandidateProvider>;
}
```

(Exact API is implementation latitude — the point is that G4 has its own
authoritative state source, distinct from anything a test or a caller
constructs by hand.) G4's transaction engine calls this source to obtain
`revision` and the current candidate set, builds `ArbitrationInput` from
them, and only then calls G3's `arbitrate()`. For this gate's deterministic
fixtures, the state source MAY be implemented as a small in-memory registry
that G4's own tests control directly (bump its internal counter to prove
the recheck below actually blocks the write) — this does not need to be
the production capability-registry implementation (that belongs to
whichever future gate builds the real registry service).

**Test discipline requirement:** a test proves the revision mechanism by
changing the *authoritative fixture state* (e.g. calling a method on the
`ArbitrationStateSource` fixture that bumps its internal revision counter,
or changes its candidate set) and then observing that G4's own code — not
the test — re-derives a different `revision` through the normal
`Validate`/`Apply` code path. **A test that directly mutates
`transaction.arbitration_result.revision` and calls that proof is not
acceptable** — that only proves two structs compare unequal, not that the
revision mechanism is real (this is exactly the weakness G3's independent
audit found in the G3-level test, and this handoff must not let G4 repeat
it at a higher layer).

## 7.3 Required recheck points

- `Validate` MUST call the state source afresh and re-run arbitration,
  comparing the freshly-computed `revision` against the one captured in
  `pre_state`. A mismatch is a precondition failure → `REJECTED`
  (P0-TXN-002), and, if the resource identity itself changed, specifically
  exercises P0-TXN-010.
- `Apply` MUST re-check `revision` **immediately before mutation** (§10's
  TOCTOU requirement) via the same state source — not rely on the
  `Validate`-time check alone. A changed `revision` between `Validate` and
  `Apply` blocks `Apply` and transitions per §4.1, never proceeds.
- Restart/recovery (§20) MUST re-derive current `revision` from the state
  source at recovery time — it must never trust a `revision` value read
  back from disk as still current without re-comparison. **The persisted
  `revision` inside a recovered `TransactionRecord` is historical
  precondition evidence only — never current truth.**

Required tests: (a) `revision` unchanged between `Validate` and `Apply` →
transaction proceeds; (b) the `ArbitrationStateSource` fixture's
authoritative state is changed between `Validate` and `Apply` (simulating a
concurrent ownership change), and `Apply` is blocked as a result of G4's
own recheck — not by a test directly editing a `revision` field.

---

# 8. `TransactionId` semantics (NB-4 resolution)

Do not reuse `CapabilityId`'s dotted-domain validator. `TransactionId` is a
**generated record identity**, not a semantic domain identity — it answers
"which specific transaction attempt is this," not "what capability/provider
concept does this name." Required properties: unique, persistent, stable
once created, serializable, safe across restart, never derived from `Vec`
position or discovery order.

Implement `TransactionId` as its own newtype (not the `stable_id!` macro
used for `CapabilityId`/`ProviderId`/`EventId`/`IncidentId` in G3) wrapping
a ULID or UUIDv4-shaped string — pick one and justify it in the completion
report (a ULID is lexicographically sortable by creation time, which is
useful for audit-log ordering; a UUIDv4 has no such property but is simpler
and has no host-clock dependency; either is acceptable, do not agonize).
Validate only that the wrapped string matches the chosen format's shape —
do not impose `CapabilityId`'s letter-led/lowercase/dotted rule on it.

**While implementing this, also resolve whether `EventId`/`IncidentId`
should be corrected to use the same generated-record-identity pattern
instead of the `stable_id!` domain-identity macro (G3 NB-4).** This handoff
requires an explicit decision, documented in the completion report, choosing
one of:

- (a) leave `EventId`/`IncidentId` exactly as G3 built them (acceptable if
  this gate's fixtures never need to construct one from a generated
  UUID/ULID-shaped value — confirm this is actually true before choosing
  it, don't assume it);
- (b) correct `EventId`/`IncidentId` in a small, separate, explicitly-labeled
  commit (not silently folded into the main G4 feature commits) to use the
  same generated-record-identity pattern as `TransactionId`.

Do not modify `crates/guardian-provider-api/src/ids.rs` as an incidental
side effect of building `TransactionId` — if (b) is chosen, it is a
deliberate, separately-reviewable change with its own justification, per
`G3_MILESTONE.md`'s explicit instruction not to let this spread by
accident.

---

# 9. Transaction preconditions (§14.2, §36 P0-TXN-002/010)

`Validate` must check, at minimum, before allowing `AUTHORIZING`:

- capability still exists and is not `Availability::Unavailable`;
- provider identity matches what `Snapshot` captured (else P0-TXN-010);
- `ArbitrationDecision.write_permitted` is (still, freshly-computed) true
  for this capability/provider, including the `revision` recheck (§7);
- `authorization_ownership` is `Known(...)` — not `Unknown` (an unknown
  authorization architecture already fails closed at G3's own arbitration
  layer, but `Validate` must not rely solely on a `pre_state` snapshot that
  could be stale; recompute or re-verify);
- `privilege_requirement` is not `Unknown` (§6);
- rollback capability is disclosed (`RollbackKind` present on the decision)
  — required by §14.2 ("Rollback capability is disclosed before
  authorization"), not merely present in a struct field nobody reads;
- the provider (fixture) actually supports the requested action type
  (`MutableCapabilityAdapter` returns something other than `Unsupported`
  for a dry inspect/validate call, per G3's typed shape).

Missing or unknown safety-critical prerequisites fail closed → `REJECTED`.
Not every field needs to be independently mandatory if the governing
contract doesn't require it (e.g. `initiating_session` may legitimately be
absent for a non-interactive background transaction) — use judgment, but
the safety-relevant items above are non-negotiable per GP-06.

---

# 10. TOCTOU — explicit revalidation points

`Snapshot → Validate → Authorize → time passes → Apply` — state may change
at every step. This handoff requires:

- a **fresh** re-check of `revision`/ownership immediately before `Apply`
  begins (§7) — not the `Validate`-time value reused;
- a defined behavior for each of: provider disappears between `Validate`
  and `Apply`; ownership changes between `Validate` and `Apply`; an
  external writer appears between `Validate` and `Apply`; the resource
  identity itself changes (P0-TXN-010); the authorization context becomes
  stale (e.g. a long deadline elapses — see `deadline` on
  `TransactionRecord`); the (fixture) helper "restarts" mid-transaction
  (simulate this as a fixture behavior, not a real process restart);
  the (fixture) core "restarts" mid-transaction (§11 below covers the
  real recovery-on-restart case; this item is about a fixture explicitly
  modeling loss of in-memory helper state between steps).
- each of the above must be a real test with a real, specific expected
  outcome (block `Apply`, or transition to a specific failure state) — not
  a single generic "TOCTOU is handled" claim.

---

# 11. Snapshot contract (§19 informal name; §14.1's `pre_state`)

`Snapshot` must capture enough to support later rollback/recovery:
`transaction_id`, `capability_id`, `provider_id`, the `ArbitrationDecision`
(including `revision`), prior resource state (whatever the fixture provider
reports via `inspect()`), `rollback_kind`, `risk_class`, and a timestamp.
Snapshot failure (fixture configured to fail) MUST prevent `Apply` — no
fake empty snapshot where rollback is later claimed as supported. Required
test: a snapshot-fails fixture never reaches `APPLYING`.

---

# 12. Validate contract

Established in §9 above. Validation is **not** authorization — it
establishes that transaction assumptions remain true; it does not decide
whether the caller may proceed. Keep the two steps and their typed results
distinct on `TransactionRecord` (`validation_results` vs.
`authorization_result`).

---

# 13. Authorize contract

Preserve G1/G2 ordering: `Authorize` strictly before `Apply` — no mutation
occurs before a real authorization outcome is obtained. The transaction
engine coordinates the request (§5); it does not replace the privileged
boundary. Denied authorization (P0-TXN-003) performs no apply and reaches
`REJECTED`. Interactive-vs-background behavior must remain explicit and
reuse G1's existing `interactive` flag — no new prompting mechanism.

---

# 14. Apply contract

`Apply` must be typed, bounded, and provider-specific through G3's typed
`MutableCapabilityAdapter` shape — never `RunCommand`/`RunShell`/arbitrary
argv/arbitrary file or sysfs path/opaque privileged payload, exactly as G2's
forbidden-pattern list already establishes and G3's `ActionRequest` already
enforces structurally (it is a typed placeholder, not a generic string
carrying arbitrary meaning — if G4 needs richer typed action payloads than
G3's placeholder `ActionRequest(String)`, define a real typed
`action_type`-specific payload here, but keep each variant narrow and
enumerable, never a generic "opaque bytes" field).

Apply failure (P0-TXN-004): the transition target depends on whether state
is known to have changed — reaches `FAILED` if nothing changed, or enters
`ROLLING_BACK` if the fixture reports a partial/uncertain mutation. This
distinction must be a real, tested fixture behavior (configurable "apply
fails cleanly" vs. "apply fails after partially mutating"), not asserted
in prose only.

Use only deterministic fixture adapters (§25 below) — no real provider
integration.

---

# 15. Observe contract (§15 of the governing contract)

After `Apply`, the engine must **not** assume success merely because the
provider call returned success (§15, verbatim: "A provider returning
'method call succeeded' MUST NOT automatically mean the transaction
succeeded"). Define, per transaction, an `observation_policy`:
`expected_properties`, `forbidden_properties`, `minimum_observation_duration`,
`maximum_observation_duration`, `health_checks[]`, `commit_condition`,
`rollback_condition` — all present as typed fields, not a free-form check
function with no inspectable shape. `observe()` on the fixture adapter
returns a real, distinguishable match/mismatch/ambiguous outcome (P0-TXN-005).
Do not implement G5's Diagnostic Budget Manager here — no PSI-driven cost
scheduling, no diagnostic escalation logic; `Observe`'s job in G4 is purely
"did the expected state occur," using the fixture's reported state.

---

# 16. Confirm contract

`Confirm` answers whether the observed result satisfies the transaction's
postcondition strongly enough to commit — keep "provider call succeeded"
structurally distinct from "desired state confirmed" (two different fields/
states, not one boolean). If confirmation fails, the rollback policy (§17
below) must be explicit and reached, not left ambiguous.

---

# 17. Rollback contract (§25/§26 of the requester's brief, using G3's `RollbackKind`)

Reuse G3's `RollbackKind` (`Native | Emulated | BestEffort | None`)
unchanged. Define behavior for each, and — **this is a required repair to
an earlier draft of this handoff, which described a `BestEffort`-ambiguous
outcome that neither the canonical state machine (§4) nor P0-TXN-006/007
can actually represent** — resolve the ambiguity via a typed evidence field,
never by inventing a new transaction state.

## 17.1 The contradiction this section resolves

An earlier draft said `BestEffort` rollback's unconfirmed outcome "must not
be forced into either `ROLLED_BACK` or `ROLLBACK_FAILED`." But §4's
canonical state machine permits only `ROLLING_BACK → ROLLED_BACK |
ROLLBACK_FAILED`, and §4 explicitly forbids adding states. These two
requirements cannot both hold literally. **Do not add a
`ROLLBACK_AMBIGUOUS` (or similarly-named) transaction state to resolve
this** — §4's state list is fixed by the governing contract and is not
reopened here.

## 17.2 Required resolution: fail-closed state, typed evidence

Unless the governing TDD contract is found to specify a different mapping
(§14/§15 do not), use **fail-closed** semantics at the transaction-state
level, with a separate typed field carrying the finer-grained evidence:

```rust
enum RollbackOutcome {
    ConfirmedRestored,
    ConfirmedFailed,
    AttemptedUnconfirmed,
    NotSupported,
}
```

(Exact naming is implementation latitude; the four distinctions above are
required.) Mapping to the canonical transaction state:

```text
RollbackOutcome::ConfirmedRestored    → transaction state ROLLED_BACK
RollbackOutcome::ConfirmedFailed      → transaction state ROLLBACK_FAILED
RollbackOutcome::AttemptedUnconfirmed → transaction state ROLLBACK_FAILED
RollbackOutcome::NotSupported         → transaction state ROLLBACK_FAILED
```

**`ROLLBACK_FAILED` at the transaction-state level does not narrowly mean
"the provider definitively reported restoration failure."** For
state-machine purposes it means *"Guardian cannot positively establish
successful rollback."* This is deliberate and required: a transaction
consumer that only reads the coarse state must never be able to mistake an
unconfirmed `BestEffort` attempt for confirmed success — fail-closed at the
state level is what prevents that. The finer-grained truth (confirmed
provider failure vs. genuinely unknown outcome) is preserved losslessly in
`rollback_result: RollbackOutcome` on `TransactionRecord`, which any
consumer that needs the distinction (e.g. future incident-severity
classification) reads directly instead of inferring it from the coarse
state.

Per-`RollbackKind` behavior:

- **Native**: the fixture provider genuinely restores prior state from the
  snapshot and confirms it → `RollbackOutcome::ConfirmedRestored` →
  `ROLLED_BACK` (P0-TXN-006).
- **Emulated**: Guardian synthesizes restoration from the captured snapshot
  itself (e.g. re-`Apply`ing the inverse typed action) and confirms it →
  `ConfirmedRestored` → `ROLLED_BACK`. Model this as a real, distinct code
  path in the fixture, not silently identical to Native.
- **BestEffort**: rollback is attempted; if the fixture can positively
  confirm restoration → `ConfirmedRestored` → `ROLLED_BACK`; if the fixture
  cannot confirm it → `AttemptedUnconfirmed` → `ROLLBACK_FAILED` (fail
  closed at the state level, per §17.2 above) with `rollback_result =
  AttemptedUnconfirmed` preserving that this was an unconfirmed attempt,
  not a proven failure.
- **None**: the transaction must expose, structurally, that rollback
  cannot be guaranteed — `RollbackOutcome::NotSupported`, and a
  `RollbackKind::None` transaction must never report `ROLLED_BACK`. A
  `VERY_HIGH`-risk action (TDD contract §10) with `RollbackKind::None` is
  exactly the case §10's "never automated by default; explicit user
  acknowledgement required" language exists for — this handoff does not
  build that policy layer (that's a client/UI concern, later gates), but
  the transaction *model* must make the fact inspectable so a later gate
  can enforce policy on it.

## 17.3 Required rollback tests

At minimum, one test per row:

```text
Native rollback confirmed        → ROLLED_BACK, rollback_result = ConfirmedRestored
Emulated rollback confirmed      → ROLLED_BACK, rollback_result = ConfirmedRestored
BestEffort rollback confirmed    → ROLLED_BACK, rollback_result = ConfirmedRestored
BestEffort rollback unconfirmed  → ROLLBACK_FAILED, rollback_result = AttemptedUnconfirmed
Rollback provider explicit failure → ROLLBACK_FAILED, rollback_result = ConfirmedFailed
RollbackKind::None                → never ROLLED_BACK; rollback_result = NotSupported
```

The `BestEffort rollback unconfirmed` and `Rollback provider explicit
failure` rows both land on transaction state `ROLLBACK_FAILED` but must be
distinguishable via `rollback_result` — a test asserting only the
transaction state for either row is insufficient; both `rollback_result`
and the transaction state must be asserted.

**Rollback failure remains a first-class state** (P0-TXN-007,
`ROLLBACK_FAILED`). Do not collapse "Apply failed, rollback succeeded" with
"Apply failed, rollback failed," or "Apply succeeded, Confirm failed,
rollback failed" — the last of these represents an unresolved incident
requiring recovery, and must be distinguishably represented (via
`rollback_result` plus a linked `incident_ids` entry) so a future
Event/Incident integration (§21 below) can surface it, without G4 itself
implementing that surfacing.

## 17.4 Cancellation and expiry while `APPLYING` or `ROLLING_BACK` is in progress

**This section resolves a genuine gap in an earlier draft of §4.1, which
permitted `(any nonterminal) → CANCELLED | EXPIRED` without qualification.**
Read literally, that rule would let `APPLYING → CANCELLED`, `APPLYING →
EXPIRED`, `ROLLING_BACK → CANCELLED`, and `ROLLING_BACK → EXPIRED` all be
implemented as direct transitions. That is unsafe: `CANCELLED` and
`EXPIRED` are terminal (§4, "Terminal states MUST be immutable"), and a
transaction may be marked immutably terminal while an external provider
mutation is already in flight, its result unknown, or a rollback attempting
to undo it is itself unresolved. This would let a cancellation or deadline
event erase the reconciliation obligation that §18–§20 otherwise go to
considerable length to preserve (Apply-intent vs. Apply-outcome, the
crash-boundary recovery table, `state-ambiguous`/`must-observe`
classifications). A cancellation or deadline request cannot retroactively
un-invoke a provider call already in flight, and it cannot make a
`ROLLING_BACK` restoration attempt disappear.

**Required invariant:** a cancellation or expiry *request* arriving while
the transaction is `APPLYING`, `OBSERVING`, or `ROLLING_BACK` MUST NOT by
itself cause an immediate transition to `CANCELLED` or `EXPIRED`. The
transaction must continue through its normal governed path — `APPLYING →
OBSERVING | FAILED | ROLLING_BACK`, `OBSERVING → COMMITTED | ROLLING_BACK |
FAILED`, `ROLLING_BACK → ROLLED_BACK | ROLLBACK_FAILED` — exactly as it
would without the request, until the transaction reaches one of those
ordinary reconciled terminal/near-terminal outcomes. Only the request
itself is durably recorded immediately (so it cannot be lost and so a
human/audit consumer can see it was asked for).

**Required representation:** record the request as a typed fact on
`TransactionRecord` — conceptually `cancellation_requested: Option<Instant>`
and/or `deadline_expired: bool` (exact naming is implementation latitude;
do not add a new transaction state to represent "requested but not yet
safe to honor"). This flag/field is orthogonal to the state machine, the
same way `rollback_result: RollbackOutcome` is orthogonal to it (§17.2) —
it carries evidence, it does not gate or short-circuit the legal
transitions in §4.1.

**Required reconciliation rule, once a normal terminal/near-terminal
outcome is reached:**

- If the transaction reaches `FAILED` with no mutation having occurred
  (§14's clean-failure case), or reaches `ROLLED_BACK` (mutation was
  undone and confirmed), reconciliation is complete and no obligation
  remains — the engine MAY report the transaction's outward-facing terminal
  state as `CANCELLED`/`EXPIRED` instead of `FAILED`/`ROLLED_BACK` **only**
  if a cancellation/expiry request is on record, since no unresolved
  external effect exists either way. (Whether to do this relabeling at all,
  versus always keeping `FAILED`/`ROLLED_BACK` as the state and surfacing
  the request only via the typed field, is implementation latitude — pick
  one and be consistent. What is not latitude is reaching `CANCELLED`/
  `EXPIRED` *before* this reconciliation is known.)
- If the transaction instead reaches `COMMITTED` or `ROLLBACK_FAILED`, the
  cancellation/expiry request is preserved as audit context only
  (`cancellation_requested`/`deadline_expired` remain set) and the
  transaction's true reconciled terminal state stands. A pending
  cancellation or an elapsed deadline must never overwrite or bypass a
  state that carries a real, unresolved-or-successful mutation outcome.
- A cancellation/expiry request arriving during `CREATED`, `VALIDATING`,
  `VALIDATED`, `AUTHORIZING`, or `AUTHORIZED` (before `Apply` begins, per
  §4.1's unqualified predecessor list) is unaffected by this section and
  may transition directly to `CANCELLED`/`EXPIRED` as before — no mutation
  is possible yet. Confirm the fixture/authorization plumbing genuinely
  guarantees no delayed asynchronous `Apply` can still occur after that
  transition (e.g. a background authorization callback that resolves after
  the transaction is already `CANCELLED` must be rejected, not silently
  allowed to proceed to `Apply`).
- A deadline elapsing does not, by itself, mean "stop trying to determine
  what happened" — it means "do not begin a *new* operation." It cannot
  make an already-started external side effect disappear or exempt the
  engine from the same Observe-before-any-conclusion discipline §18.4
  requires for ordinary recovery.

**Required tests**, at minimum one per row:

```text
cancellation requested during CREATED/VALIDATING/…/AUTHORIZED → CANCELLED (no Apply ever occurs)
expiry requested during CREATED/VALIDATING/…/AUTHORIZED       → EXPIRED (no Apply ever occurs)
cancellation requested during APPLYING  → transaction does NOT immediately become CANCELLED;
                                            it continues to a governed outcome (FAILED/OBSERVING/
                                            ROLLING_BACK) and the request is preserved as evidence
expiry requested during APPLYING        → same, for EXPIRED
cancellation requested during ROLLING_BACK → transaction does NOT immediately become CANCELLED;
                                               rollback continues to ROLLED_BACK/ROLLBACK_FAILED
expiry requested during ROLLING_BACK       → same, for EXPIRED
cancellation/expiry requested, transaction reaches COMMITTED → COMMITTED stands; request recorded
                                                                 as context only, not honored
```

---

# 18. Lost response / duplicate apply (P0-TXN-009)

## 18.1 The unsafe claim this section repairs

An earlier draft of this handoff said a duplicate `idempotency_key` with a
recorded `APPLYING` (or later) state should prevent a second `Apply` and
*return the existing result*. That is unsafe as written, because a durable
`APPLYING` state can mean at least three different realities, and the
handoff must not conflate them:

```text
A. APPLYING persisted, crash before the provider was invoked at all
   → mutation did NOT occur

B. provider invoked, mutation occurred, process crashed before the
   result was persisted
   → mutation DID occur, outcome unrecorded

C. provider invoked, mutation outcome uncertain (response lost)
   → unknown whether mutation occurred
```

**`state == APPLYING` is not proof that `Apply` occurred, and is not
sufficient grounds to return a successful prior result.** Any handoff text
implying otherwise is corrected by this section.

## 18.2 Required repair: separate Apply-intent from Apply-outcome

The transaction persistence model MUST distinguish, as two separately
persisted facts:

- **Apply-intent durably recorded** — "Guardian was about to attempt
  `Apply`" (persisted *before* the provider is invoked, §19.1 below);
- **Apply-outcome durably recorded** — "Guardian knows what happened."

Conceptual shape (exact representation is implementation latitude; it may
live inside `provider_request`/`provider_response`, a dedicated field on
`TransactionRecord`, or a small dedicated type — the distinctions below are
required, the exact struct/enum names are not):

```rust
ApplyRecord {
    idempotency_key,
    attempt_started_at,
    outcome: ApplyOutcome,
}

enum ApplyOutcome {
    NotRecorded,
    ConfirmedSuccess,
    ConfirmedFailureNoMutation,
    PartialOrUncertainMutation,
    ResponseLostOrUnknown,
}
```

No new transaction state is added for this (§4's state list is unchanged) —
`ApplyOutcome` is evidence carried inside the existing `APPLYING`/
`OBSERVING`/terminal states' associated data, not a new state.

## 18.3 Required idempotency-key behavior on retry

For a duplicate `idempotency_key`, behavior depends on which `ApplyOutcome`
is durably known:

- **Known completed Apply** (`ApplyOutcome::ConfirmedSuccess` or another
  terminal known outcome): do not invoke provider `Apply` again; return/
  recover the recorded transaction outcome directly.
- **Apply may have happened, outcome unknown**
  (`ApplyOutcome::PartialOrUncertainMutation` or `ResponseLostOrUnknown`,
  or an `ApplyRecord` whose `attempt_started_at` is recorded with
  `outcome: NotRecorded` and no further evidence): do **not** blindly
  re-`Apply`, and do **not** pretend success. Classify per §18.4/§20 as
  `must-observe` or `state-ambiguous` and use the recovery contract — never
  fabricate a `COMMITTED` result merely because an `APPLYING` marker
  exists.
- **Apply definitely did not happen**: only when durable evidence
  *positively proves* the provider was never invoked (i.e., no
  Apply-intent record exists yet, or the Apply-intent record itself proves,
  by construction, that the call could not have been made — e.g. a
  crash-before-invocation scenario the persistence ordering in §19.1 makes
  provable) may the engine safely resume before `Apply`. Do not infer "did
  not happen" merely from the *absence* of a recorded response — absence
  of evidence is exactly case C above (`ResponseLostOrUnknown`), not proof
  of non-occurrence.

## 18.4 Lost-response recovery must attempt observation before any retry

When Apply-outcome is unknown (`PartialOrUncertainMutation` /
`ResponseLostOrUnknown`), the preferred recovery behavior, where the
provider supports meaningful observation, is:

1. **Observe** current resource state before any retry decision.
2. If observation proves the intended postcondition was met: continue
   recovery toward `Confirm`/`Commit` **without** a second `Apply` call.
3. If observation proves the mutation did not occur, and re-`Apply` is
   otherwise safely allowed by the transaction's preconditions (§9):
   resume under the transaction's governed rules (i.e., proceed to a real
   `Apply`, since this is now case "definitely did not happen").
4. If observation cannot determine state: classify `state-ambiguous`
   (§20). Do not silently retry `Apply` merely because observation was
   inconclusive.

## 18.5 What P0-TXN-009 actually requires and guarantees

The normative requirement remains exactly: *same `idempotency_key` → the
same Guardian transaction/write must not execute provider `Apply` twice.*
Required test, corrected from the earlier draft: simulate provider applies
mutation → response is lost → transaction retries with the same
`idempotency_key`. Required assertions:

- fixture `apply()` call count == 1 (the core P0-TXN-009 guarantee);
- **the retry does not report `COMMITTED` merely because an `APPLYING`
  marker exists** — it must either genuinely `Observe`/recover existing
  state (§18.4) or classify `state-ambiguous`, according to what the
  fixture can actually establish.

**Scope limitation, preserved explicitly:** G4 guarantees only that
*Guardian's own transaction engine* does not knowingly call `Apply` twice
for the same `idempotency_key` against its own fixture adapters. G4 does
**not** claim that all real providers guarantee exactly-once mutation —
provider-specific idempotency semantics (whether a real provider's own API
is safe to retry, offers its own operation-identity tokens, etc.) are
explicitly deferred to G8, which must evaluate each real provider's actual
semantics before assuming this guarantee extends to it.

## 18.6 Required crash-before-Apply adversarial test

Separate from the lost-response test above, add: persist an Apply-intent
marker → simulate a crash **before** the fixture's `apply()` is ever
invoked → restart/recovery. Required: the engine must not report the
mutation as successful, and must not classify the transaction as
"already committed." The correct recovery classification follows the final
persistence design (§19.1): if the persistence ordering can *prove* `Apply`
was never invoked (e.g. the Apply-intent record itself, or its absence,
demonstrates this by construction), `safe-to-resume` is appropriate; if it
cannot prove that, `state-ambiguous` is the safer classification. The
handoff's persistence-ordering section (§19.1) must specify exactly which
evidence makes this distinction provable.

---

# 19. Persistence contract (§23 of the governing contract)

Define, without implementing production packaging:

- **When first persisted**: at minimum, a transaction must be durably
  recorded before `Apply` begins (so a crash during/after `Apply` can be
  recovered/detected, §20) — persisting only at `COMMITTED` is insufficient.
- **Atomic write strategy**: write-to-temp-file-then-rename, or an
  equivalent atomicity guarantee — no partial-record risk from a crash
  mid-write.
- **Schema/version**: every persisted record carries an explicit schema
  version field; deserializing a record from a newer/unknown schema
  version must fail closed (typed error), never silently misinterpret
  fields (mirrors G3's Rule-1/Rule-3 unknown-handling discipline).
- **Restart load**: on startup, all persisted nonterminal transactions are
  read back (P0-TXN-011).
- **Corrupt record behavior**: a corrupt/unparseable persisted record must
  not be treated as safe-to-resume — it surfaces as a distinct
  "requires recovery/human handling" outcome (§20), never silently
  discarded or silently treated as committed/rolled-back.
- **Partial write behavior**: covered by the atomic-write requirement
  above — a partial write must never be readable as a seemingly-valid
  record.
- For this gate, a local filesystem fixture under a test-controlled
  temporary directory is sufficient — do not wire up real
  `/var/lib/guardian` paths or systemd `StateDirectory=` (that's packaging,
  out of scope), but the *contract* (schema, atomicity, versioning) must be
  real and tested, not simulated only in memory with no serialization at
  all.

## 19.1 Required durable ordering around Apply (feeds §18's recovery distinctions)

The handoff requires an explicit durable ordering, at minimum equivalent
to:

```text
1. persist transaction + pre_state
2. persist that Apply is about to be attempted (the Apply-intent record, §18.2)
3. fsync/atomic durable completion of step 2
4. invoke provider Apply
5. persist provider result / Apply-outcome (§18.2)
6. Observe
```

The exact storage mechanism may differ, but **a crash at every boundary
must have a defined recovery interpretation**:

```text
crash before step 2 completes    → no Apply-intent record exists (or it did not durably
                                    complete) → Apply provably never invoked → safe-to-resume
crash between step 2 and step 4  → Apply-intent record exists, durably fsynced, but the
                                    provider was never called → Apply provably never invoked
                                    (the durable ordering guarantees step 4 cannot have run
                                    without step 3 completing first) → safe-to-resume
crash during step 4              → the provider call was in flight when the crash occurred;
                                    whether the external mutation happened is INHERENTLY
                                    UNCERTAIN from Guardian's own persistence alone — classify
                                    state-ambiguous / must-observe (§18.4), never safe-to-resume
                                    and never already-committed
crash between step 4 and step 5  → the provider call completed (or the process believes it
                                    might have) but the outcome was never durably recorded →
                                    ResponseLostOrUnknown → must-observe (§18.4)
crash after step 5               → Apply-outcome is durably known → recovery proceeds directly
                                    from the recorded outcome (Observe if outcome is
                                    ConfirmedSuccess with no observation yet recorded, etc.)
```

**Do not claim persistence can prove whether an external mutation occurred
when the crash happened during the external call itself (step 4).** That
interval is inherently uncertain unless the specific provider offers its
own idempotency/operation-identity mechanism — which is explicitly deferred
to G8 (§18.5). G4's obligation is only that its own persistence ordering
makes every *other* boundary provable, and that the one inherently
uncertain boundary is classified `state-ambiguous`/`must-observe`, never
guessed as either extreme.

Required tests: at minimum one test per crash boundary listed above (5
tests), each constructing a persisted-state fixture representing that exact
crash point and asserting the correct recovery classification.

---

# 20. Crash/restart recovery (P0-TXN-011)

G2's real-host evidence established that privileged-helper memory resets
across restart — transaction truth cannot depend solely on in-memory state.
On recovery, Guardian must be able to distinguish, for each recovered
nonterminal transaction:

```text
safe to resume            (nonterminal, no Apply attempted yet — re-run Validate/Authorize)
must observe               (Apply attempted, no Observe result recorded — re-run Observe only)
must rollback               (Apply attempted, Observe failed/ambiguous, rollback not yet attempted)
already committed            (Apply + Observe + Confirm all recorded successful — nothing to do)
state ambiguous                (Apply attempted, response lost, no Observe possible from fixture)
requires human/recovery handling (corrupt record, or ROLLBACK_FAILED with no further automated path)
```

This gate does not need to solve every real-provider recovery scenario —
fixture adapters are sufficient — but the **state model** must support
these six distinctions as real, representable outcomes of a recovery
function, each with its own test using a persisted record constructed to
represent that exact scenario (not just the general "restart recovers
transactions" claim). Required test set: at minimum one test per
distinction above (6 tests), each constructing a specific persisted-record
fixture and asserting the recovery function classifies it correctly.

---

# 21. Event/Incident integration (using G3 models, unchanged)

Transaction state changes may emit `guardian_core::event::Event`s — e.g.
transaction started, authorization denied, apply started, apply failed,
observation mismatch, rollback started, rollback failed, transaction
committed. Reuse G3's `Event`/`normalize_key` unchanged; do not fork them.
Transaction failures (especially `ROLLBACK_FAILED`) may reference or create
incident-compatible evidence (an `Incident` linking the relevant events) —
but do not implement a correlation *engine* here (that's G5/G7 scope); a
direct, explicit link from a known failure to a known incident is
acceptable, an inferred/fuzzy correlation system is not.

---

# 22. Provenance

A `TransactionRecord` should retain enough provenance to explain which
capability, which provider, which arbitration decision (the actual
`ArbitrationDecision`, not a summary), which snapshot, and which
observations led to the outcome. `initiating_bus_name`/`initiating_session`
may be present per §14.1, but do not duplicate G1's sensitive caller
identity into the transaction record beyond what the contract's own field
list already specifies — preserve the privacy-minimization discipline G1
established (real caller resolution stays inside the authorization
boundary; the transaction record is an audit trail, not a caller-identity
store).

---

# 23. Serialization boundaries (NB-3 resolution)

Identify which G4 types genuinely cross a real boundary in this gate:
`TransactionRecord` (persistence, §19) definitely does. `Event`/`Incident`
references inside it reuse G3's existing (partial) serialization — do not
expand G3's enum serialization coverage merely for symmetry unless a
specific G4 type actually needs it (e.g. if `TransactionRecord` persists a
`RollbackKind` value, and `RollbackKind` currently has `Display` but no
`FromStr` per G3's NB-3, **this gate must add the missing `FromStr`**,
since persistence is exactly the real boundary NB-3 anticipated — this is
not "adding for symmetry," it is closing a real gap this gate's own
persistence contract exposes). For every type that does cross a boundary:
explicit stable wire representation, schema version awareness, round-trip
tests, typed parse failures for unknown values (matching each type's
established unknown-handling rule from G3, do not invent a new rule per
type). No `Debug`-format persistence anywhere.

---

# 24. Fail-closed checklist

At minimum, verify and test that none of the following silently becomes
"safe"/"authorized"/"valid"/"committed":

```text
unknown authorization ownership       (G3, reused — reconfirm still fails closed through G4's Validate)
unknown privilege requirement          (§6 — new G4 invariant)
unknown provider health
ambiguous writer                        (G3, reused)
external writer                          (G3, reused)
stale revision                            (§7)
provider unavailable
unsupported operation
snapshot failure                            (§11)
authorization failure                        (§13)
observation ambiguous                          (§15)
corrupt persistent state                        (§20)
```

---

# 25. Provider fixtures only

All G4 tests use deterministic fake providers/adapters implementing G3's
`Provider`/`MutableCapabilityAdapter` traits, with configurable behavior
for: snapshot succeeds/fails; validate succeeds/fails; authorize succeeds/
fails (via a fixture `Authorizer`, reusing G1's trait); apply succeeds/
fails; apply succeeds but response is lost (for §18's idempotency test);
observe matches/mismatches/is ambiguous; rollback succeeds/fails/is
best-effort-ambiguous; provider disappears mid-transaction; arbitration
revision changes mid-transaction. **No real UDisks/systemd/NetworkManager/
NVML/UPower/thermald/fwupd integration anywhere.**

---

# 26. TDD sequence

Strict: failing test → minimal implementation → focused pass → full
workspace pass, for each normative item. Every `P0-TXN-*` test must have a
real load-bearing failure mode — prove this the same way G3's independent
audit did: after implementing, deliberately mutate the implementation in a
`/tmp` scratch copy (never the tracked tree) for at least the adversarial
items in §27, confirm the relevant test(s) fail, then discard the mutation.
Report which mutations were performed and what they caught in the
completion report, matching G3's evidentiary standard.

---

# 27. Adversarial self-check before reporting done

1. mutation before authorization — does anything reach `Apply` without
   passing through `Authorize`?
2. stale arbitration revision accepted — does `Apply` proceed if `revision`
   changed since `Validate`?
3. caller-controlled revision trusted — can a test construct a
   `TransactionRecord` with an arbitrary `revision` and have it accepted
   without re-derivation?
4. unknown privilege permitted — does a `PrivilegeRequirement::Unknown`
   capability ever reach `APPLYING`?
5. unknown authorization permitted — does a `Knowledge::Unknown`
   capability ever reach `APPLYING`?
6. ambiguous ownership permitted — does `Ownership::Conflict` ever reach
   `APPLYING`?
7. snapshot omitted — can `Apply` proceed with no recorded `pre_state`?
8. rollback claimed but impossible — does a `RollbackKind::None` decision
   ever get silently treated as though rollback succeeded?
9. apply-success/reply-loss/retry duplicate — does retrying an
   `idempotency_key` whose response was lost cause a second real `Apply`
   call to the fixture?
10. provider disappears between `Validate` and `Apply` — is this detected,
    or does `Apply` proceed against a vanished provider?
11. core "crashes" after `Apply` (simulated) — does recovery correctly
    classify the transaction per §20, not silently drop it?
12. helper "crashes" after `Apply` (simulated) — same question from the
    privileged-boundary side.
13. restart loses a transaction — does every persisted nonterminal
    transaction actually get re-loaded, or can one silently vanish?
14. corrupt persisted record treated as safe — does a deliberately corrupted
    record ever classify as "already committed" or "safe to resume"?
15. illegal state transition — does the state machine reject
    `COMMITTED → APPLYING` (or similar) rather than silently allowing it?
16. rollback failure hidden — does `ROLLBACK_FAILED` ever get collapsed
    into `FAILED` or `ROLLED_BACK` in any code path?
17. best-effort rollback reported as success — does `RollbackKind::BestEffort`
    ever force a `ROLLED_BACK` result the fixture couldn't actually confirm
    (must be `ROLLBACK_FAILED` + `rollback_result = AttemptedUnconfirmed`,
    §17.2)?
18. `Debug`-format persistence — does any persisted record rely on `Debug`
    output as its wire format?
19. real provider leakage — does any fixture or test accidentally call a
    real system D-Bus service?
20. G5/G8 scope leakage — does any code implement diagnostic-budget logic,
    a real provider adapter, or client-facing surface?
21. `APPLYING` marker treated as proof of successful mutation — does any
    recovery path report `COMMITTED`, or return a "success" result, based
    solely on the presence of an `APPLYING`/Apply-intent record with no
    durable Apply-outcome (§18.2/§18.3)?
22. crash before provider invocation misclassified — does the
    crash-before-`Apply` test (§18.6) ever get classified as
    "already committed" or report the mutation as successful?
23. response loss causes a second fixture `Apply` call — does the
    lost-response retry test (§18.5) show `apply()` called more than once?
24. response loss treated as success without `Observe` — does any recovery
    path skip §18.4's required `Observe`-before-retry step and simply
    assume success?
25. revision proof by test mutation — does any G4 test prove the revision
    recheck by directly setting `transaction.arbitration_result.revision`
    rather than by changing the `ArbitrationStateSource` fixture's
    authoritative state and letting G4's own code re-derive a different
    value (§7.2)?
26. cancellation requested during `APPLYING` — does the transaction ever
    become `CANCELLED` before the Apply-outcome is reconciled (§17.4)?
27. expiry requested during `APPLYING` — same question for `EXPIRED`
    (§17.4)?
28. cancellation requested during `ROLLING_BACK` — does the transaction
    ever become `CANCELLED` before rollback reaches `ROLLED_BACK`/
    `ROLLBACK_FAILED` (§17.4)?
29. expiry requested during `ROLLING_BACK` — same question for `EXPIRED`
    (§17.4)?

---

# 28. Completion states

Report exactly one, honestly:

```text
G4 CANDIDATE — TRANSACTION ENGINE READY FOR INDEPENDENT AUDIT
G4 PARTIAL — CONTRACT TESTS INCOMPLETE
G4 BLOCKED — GOVERNING CONTRACT INSUFFICIENT
G4 BLOCKED — TRANSACTION SAFETY MODEL CONFLICT
```

Do not report `CANDIDATE` if any `P0-TXN-*` test is red, skipped, or
asserts against a fixture that cannot fail.

---

# 29. Completion report

Include, at minimum: which normative tests are green with exact names/IDs
(all 12 `P0-TXN-*`); the state-machine transition table actually
implemented, compared against §4.1; `TransactionId` format chosen and why
(§8); the `EventId`/`IncidentId` decision made (§8, option a or b, and
why); the exact revision-ownership mechanism built, including confirmation
that the `ArbitrationStateSource` fixture (not caller-supplied input, not
direct test mutation of a `revision` field) is what tests actually exercise
(§7); the `RollbackOutcome` mapping actually implemented and the six
required rollback tests' results (§17.3); the `ApplyOutcome`/Apply-intent
model actually implemented, the five persistence-ordering crash-boundary
tests' results (§19.1), and the crash-before-`Apply` test's result (§18.6);
where `PrivilegeRequirement::Unknown` is checked and by which function
(§6); the persistence schema version and atomic-write mechanism (§19); the
six recovery-classification tests and their results (§20); the
cancellation/expiry-during-mutation model actually implemented and its
seven required tests' results (§17.4); the §27 adversarial self-check
results item-by-item (all 29 items), including which were executed as real
scratch mutations vs. reasoned by inspection (mirror G3's
audit-survivable standard, don't just claim it); full `cargo
fmt --check` / `cargo clippy --workspace --all-targets --all-features --
-D warnings` / `cargo test --workspace` output; and an explicit statement
of what was deferred to G5 or G8 and why.

Then stop. Do not begin G5. Do not tag G4 — independent review happens
first, exactly as it did for G0 through G3.
