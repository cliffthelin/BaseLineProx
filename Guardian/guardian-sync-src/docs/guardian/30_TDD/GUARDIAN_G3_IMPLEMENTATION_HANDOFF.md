# Guardian Phase 0 Implementation Handoff
## G3 — Core Data Models Only

**Audience:** Primary coding agent
**Scope:** **G3 — Core Data Models** only
**Stop condition:** the normative G3 tests below are green (or the gate is
honestly reported partial/blocked with the specific missing evidence
named). Do **not** begin G4 (transaction engine), providers, real
Capability Registry/Provider Arbitrator *runtime* behavior against real
hardware, clients, or packaging.
**Governing contract:** `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
§10 (risk taxonomy), §11 (Capability Registry schema), §12 (Provider
interface contract), §13 (Provider Arbitrator), §16 (error model), §17
(Event schema), §18 (Incident schema), §36 (P0-REG-001/002 new, P0-REG-003/004
reused, P0-ARB-001..004, P0-EVT-001..004)
**Prerequisite:** G2 tagged at `phase0-g2-privilege-topology` (commit
`87502df8e41268aec4e94635d218c8b81c82189c`). Confirm this tag exists and
`HEAD` descends from it before starting.

---

# 1. Mission

G3 gives Guardian its internal typed language: what a capability is, who
provides it, who is allowed to write it right now, what an event is, and
how events correlate into an incident. This is a **deterministic, Layer 1
data-model gate** — no real provider, no real hardware, no transaction
execution, no VM required unless a coding agent introduces host-dependent
behavior that has no business being here (in which case, remove it or
defer it, per §14 of this handoff).

The desired result is a repository in which:

- `CapabilityRecord`, the `Provider` trait, and `ArbitrationDecision` exist
  as typed models per TDD contract §11–§13, in `guardian-core` and/or
  `guardian-provider-api` per the placement analysis required in §11 below;
- capability identity and provider identity are structurally distinct
  types — a capability's identity never depends on which provider currently
  realizes it;
- the Provider Arbitrator is deterministic: identical inputs (candidate
  providers, health, ownership, priority) always produce the identical
  `ArbitrationDecision`, proven by tests that specifically try to break
  this (reversed provider order, shuffled `HashMap` iteration, etc.);
- the single-writer rule (GP-04) is representable at the data-model level:
  observers vs. the current write owner are distinguishable, "no writer"
  is distinguishable from "ambiguous owner," and ambiguity fails closed
  (`write_permitted = false`), matching P0-ARB-002;
- authorization ownership is representable using G2's established
  three-way distinction (none / provider-owned authorization / Guardian
  polkit authorization) — never collapsed into a boolean "is Guardian
  privileged";
- `Event` and `Incident` exist per TDD contract §17/§18, with stable IDs,
  monotonic-plus-wall-clock timestamps, normalized correlation keys that
  still preserve the raw source reference, and incidents that link
  multiple events without deleting them;
- every model that crosses a serialization boundary has an explicit,
  tested representation for unknown/future enum values — Guardian fails
  closed on unknown, never silently maps unknown to safe/available/
  authorized;
- `P0-REG-001`, `P0-REG-002`, `P0-ARB-001..004`, `P0-EVT-001..004` are
  green; `P0-REG-003`/`P0-REG-004` are confirmed still green, reused
  unchanged from their existing `guardian-provider-api` implementation;
- no G4 transaction state machine, no real provider adapter, no GUI/TUI/CLI
  code, and nothing that weakens or reopens the G2 privilege topology
  exists anywhere in the result.

Then stop.

---

# 2. Read before changing code

1. `AGENTS.md`
2. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
   - §2 Governing principles (GP-01, GP-02, GP-04, GP-06, GP-08, GP-10 especially)
   - §4 Required repository layout
   - §9 polkit action taxonomy
   - §10 Risk taxonomy
   - §11 Capability Registry schema
   - §12 Provider interface contract
   - §13 Provider Arbitrator
   - §16 Error model
   - §17 Event schema
   - §18 Incident schema
   - §21 Boot availability model (feeds `CapabilityRecord.boot_availability`)
   - §36 P0-REG, P0-ARB, P0-EVT
3. `docs/guardian/20_Control_Plane/Capability_Registry.md`
4. `docs/guardian/20_Control_Plane/Provider_Arbitrator.md`
5. `docs/guardian/20_Control_Plane/Event_and_Incident_Model.md`
6. `docs/guardian/20_Control_Plane/Privilege_and_Authorization.md` (G2's
   authorization-ownership distinction, which G3 must represent, not
   redesign)
7. `docs/adr/ADR-002-guardian-privilege-topology.md` — the accepted G2
   decision and its constraint on any future helper↔core coordination.
8. `docs/evidence/g2/G2_MILESTONE.md` and
   `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md` — the concrete
   classifications G3's data model must express without loss across
   **two separate dimensions**: authorization ownership
   (`authorization_ownership`, wrapping the `AuthorizationMode` enum in an
   explicit known/unknown state) and privilege/access requirement
   (`privilege_requirement`) — see §5.

---

# 3. G3 normative contract IDs

These are the **only** normative test IDs in scope for G3. Do not invent
new `P0-*` IDs — the contract's full ID list was mechanically extracted
(`grep -oE "P0-[A-Z]+-[0-9]+"` against the governing contract) and contains
no `P0-CAP-*`/`P0-PROV-*`/`P0-INC-*` group. Sections 11 (Capability
Registry schema), 12 (Provider interface contract), 16 (Error model), and
18 (Incident schema) are normative **schema** requirements without their
own dedicated test-ID group; they are exercised through the tests below
plus ordinary focused unit/serialization tests that do not need a `P0-*`
label of their own (see §13).

```text
P0-REG-001 — provider unavailable        NEW this gate
P0-REG-002 — degraded provider           NEW this gate
P0-REG-003 — contract provenance         ALREADY GREEN — crates/guardian-provider-api/tests/provenance_contract.rs.
                                          Confirm still passing; do not reimplement.
P0-REG-004 — drift detection             ALREADY GREEN — same file. Confirm still passing; do not reimplement.

P0-ARB-001 — single writer               NEW this gate
P0-ARB-002 — ambiguous owner             NEW this gate
P0-ARB-003 — owner change invalidates transaction   NEW this gate (data-model level only —
                                          this is "a stale arbitration input must be
                                          detectable," not G4's transaction machine)
P0-ARB-004 — rollback disclosure         NEW this gate

P0-EVT-001 — monotonic ordering          NEW this gate
P0-EVT-002 — normalized key              NEW this gate
P0-EVT-003 — raw reference preserved     NEW this gate
P0-EVT-004 — incident linking            NEW this gate
```

Out of scope for G3 (do not implement, do not write tests that assume
their runtime behavior exists): `P0-TXN-*` (G4), `P0-DIAG-*`/`P0-REC-*`
(G5), `P0-IND-*` (G6), `P0-PRIV-*` (G2, already tagged).

---

# 4. Capability vs. provider — the identity boundary (§10 of the requester's brief)

This is the single most important structural rule in this gate.

**A capability describes what Guardian understands can be done. A provider
describes how that capability is currently realized on this machine.**
`capability_id` and `provider_id` MUST be separate, independently stable
identifier types — never the same string, never one derived from the
other, never positional.

```text
capability_id:  storage.device.poweroff     (stable — never changes)
provider_id:    udisks2                     (can change if Guardian ever
                                              gains an alternative realization)
```

A future provider change for a capability must **not** make historical
incidents, transactions, or policy that reference `capability_id` appear
to describe a different capability. Write a test that proves this: change
which provider offers a capability mid-scenario and assert every reference
that used the old `capability_id` is unaffected.

Capability IDs use dotted, domain-first, stable naming
(`domain.resource.operation`), matching the pattern already implied by the
polkit action taxonomy (§9 of the governing contract:
`guardian.storage.power-off`, `guardian.service.pause`, etc.) — e.g.
`system.service.restart`, `storage.device.poweroff`,
`system.pressure.io.observe`, `power.profile.read`, `power.profile.hold`.
Do not derive capability identity from a provider's D-Bus interface name,
UI label, discovery order, or a randomly generated UUID (P0-scoped
adversarial question §39.8/§39.9 below).

---

# 5. `CapabilityRecord`

Per TDD contract §11, the canonical representation MUST contain at least
the fields the contract lists. The contract's schema does not itself split
authorization from privilege/access requirement into two named fields, nor
does it separate a known authorization architecture from not yet knowing
one — both splits are this handoff's requirement (§5 below), needed
because a single `authorization_mode` field cannot losslessly represent
the G2 inventory (see the dimensional-separation discussion immediately
below the field list):

```rust
CapabilityRecord {
    capability_id,
    provider_id,
    provider_version,
    availability,
    health,
    read_support,
    write_support,
    authorization_ownership,  // Dimension A — Knowledge<AuthorizationMode>: who owns
                               // authorization, when that is established (§5 below)
    privilege_requirement,    // Dimension B — what OS privilege/access is required (§5 below)
    boot_availability,
    interface_kind,
    interface_name,
    interface_hash,
    diagnostic_cost,
    last_observed_at,
}
```

Design each field as a real type, not a raw string, wherever the contract
already defines the value set:

- `availability`: `AVAILABLE | DEGRADED | UNAVAILABLE | UNSUPPORTED |
  UNKNOWN` (§11). **`UNKNOWN` MUST NOT be rendered as healthy** — write a
  test that asserts this directly (any code path that treats `UNKNOWN` as
  equivalent to `AVAILABLE` must fail a test).
- `health`: `HEALTHY | WARNING | ERROR | STALE | UNKNOWN` (§11,
  "Recommended" — if the coding agent narrows this set, document why in
  the completion report; do not silently drop states).
- `read_support` / `write_support`: distinct booleans or a small typed
  pair — never a single `active` flag. A capability can be observable by
  many callers while writable by at most one (GP-04); the type must make
  "can observe" structurally different from "can mutate," and both
  different again from "currently owns mutation" (that last one lives on
  `ArbitrationDecision.current_owner`, not here — see §7).
- Authorization ownership and privilege/access requirement are **two
  independent dimensions of `CapabilityRecord` and MUST be represented by
  two separate typed fields, never folded into one enum.** They answer two
  different questions, and the G2 inventory's own 24 rows prove neither
  question determines the other (see the worked example below) —
  collapsing them loses information the inventory took real research to
  establish. Within Dimension A itself, *whether an `AuthorizationMode` is
  even known yet* is a further, epistemic split — see below.

  **Dimension A — `authorization_ownership`: *who performs/owns
  authorization, when that is actually known?*** `AuthorizationMode` itself is a governed
  enum with **exactly three values** reflecting G2's established, audited
  distinction — do not add a fourth value to this enum, including an
  `Unknown` variant, unless the governing TDD contract is shown to require
  that exact shape (none is currently known to):
  ```text
  AuthorizationMode {
      NoAuthorizationRequired,          (G2 inventory: "no privilege" rows)
      ProviderOwnedAuthorization,       (G2 inventory: "provider-owned authorization" —
                                          the provider itself performs its own polkit check;
                                          Guardian needs no elevated privilege)
      GuardianOwnedAuthorization,       (G2 inventory: "Guardian polkit authorization" —
                                          Guardian's own action is polkit-gated)
  }
  ```
  This enum MUST NOT answer "what OS privilege does this require?" and
  MUST NOT mean "the current caller is authorized" — it describes the
  capability's authorization *architecture* when that architecture is
  actually established, nothing about a specific caller or request (see
  §12 for why this distinction is a hard G2 boundary, not a style
  preference).

  **`AuthorizationMode` is not the whole of Dimension A.** Whether
  Guardian has even *established* which `AuthorizationMode` applies is a
  separate, epistemic question — "do we know who owns authorization for
  this capability yet?" — and G2's own inventory proves this question has
  a real "not yet" answer for eight capability areas (see the correction
  below). `CapabilityRecord`'s actual authorization-ownership field MUST
  therefore wrap the three-value enum in an explicit knowledge state,
  never let "unknown" collapse into one of the three architectural values:
  ```rust
  enum Knowledge<T> {
      Known(T),
      Unknown,
  }

  // CapabilityRecord field:
  authorization_ownership: Knowledge<AuthorizationMode>,
  ```
  The exact Rust type/name is not prescribed — `Knowledge<AuthorizationMode>`,
  a dedicated `AuthorizationOwnershipState` enum with `Known(AuthorizationMode)`/
  `Unresearched` variants, or an equally explicit design are all acceptable.
  A bare `Option<AuthorizationMode>` is acceptable **only** if `None` is
  explicitly documented and serialized as "unknown/unresearched," and the
  doc comment makes unmistakably clear that `None` is never to be read as
  "no authorization required" — prefer a named wrapper over a bare
  `Option` specifically because it makes that misuse structurally harder,
  not just discouraged in prose.

  **`Unknown`/`Unresearched` is epistemic, not a fourth authorization
  architecture.** `AuthorizationMode::NoAuthorizationRequired` means
  "Guardian has established that this capability needs no authorization."
  `Knowledge::Unknown` (or equivalent) means "Guardian has not established
  which of the three `AuthorizationMode` values applies." These are not
  interchangeable, and code MUST NOT use one as shorthand for the other in
  either direction.

  **Dimension B — a separate `privilege_requirement` field (or equivalent
  typed model): *what OS-level privilege/access does the operation
  itself require, independent of who authorizes it?*** The governing
  contract does not prescribe an exact enum for this dimension, so the
  handoff requires one that preserves the G2 inventory's distinctions
  without loss:
  ```text
  NoDirectPrivilege                (no Guardian-held OS privilege/access needed)
  SpecificFileOrDeviceAccess       (a narrow, named filesystem/device path)
  SpecificLinuxCapability          (a named, narrow capability)
  RootOrSystemPrivilege            (no narrower alternative found/researched)
  Unknown                          (requires host research — see below)
  ```
  This is the same category set the G2 inventory itself already uses
  (`docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`'s own
  classification header) — reuse those category names rather than
  inventing new ones.

  **These two fields are genuinely independent — do not assume one
  determines the other.** Worked example directly from the G2 inventory:
  `power-profiles-daemon (HoldProfile)` is
  `authorization_ownership = Known(GuardianOwnedAuthorization)` (Guardian's
  own polkit action gates it) but its `privilege_requirement` is
  `NoDirectPrivilege` (no further OS privilege is needed once authorized)
  — **`GuardianOwnedAuthorization` does not imply `RootOrSystemPrivilege`.**
  Likewise, `UDisks PowerOff` is
  `authorization_ownership = Known(ProviderOwnedAuthorization)` with
  `privilege_requirement = NoDirectPrivilege` — **`ProviderOwnedAuthorization`
  does not imply `RootOrSystemPrivilege` either.** Conversely, G2's own
  bounded test operation demonstrates a case where
  `authorization_ownership = Known(GuardianOwnedAuthorization)` while the
  underlying privileged *helper process* runs as root for the polkit
  trusted-caller reason (a fact about process topology, not about this
  capability's own privilege requirement) — do not conflate a capability's
  `privilege_requirement` with the ambient privilege of whatever process
  happens to execute it either; if that distinction matters for a specific
  capability, it must be representable, not assumed away.

  `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`'s 24 rows are a
  direct, ready-made fixture set for testing that every row is
  representable **without information loss across both dimensions** —
  not that every row maps onto `authorization_ownership` alone. **Correction
  to an earlier draft of this handoff:** the inventory's 8
  `unknown — requires host research` rows are recorded with a *single*
  classification column, not a per-dimension breakdown — the inventory
  does **not** establish a known `AuthorizationMode` for these 8 rows
  (`BPF/eBPF`, `thermald (write policy)`, `NVML/NVIDIA`, `fwupd`,
  `journald (rotation/capacity policy)`, `apt/package state`, `generic
  hardware control`, `USB Security / usbguard`). Fixtures MUST NOT
  manufacture a known authorization owner for these 8 rows from
  architectural preference or general platform knowledge — they must map
  to `authorization_ownership = Unknown` **and** `privilege_requirement =
  Unknown` simultaneously, unless a specific row's own recorded evidence
  text explicitly proves an authorization owner (none currently do; if a
  future evidence-research pass proves one, update that row's mapping then,
  not this handoff). Required test coverage:
  - all 9 `no privilege` rows preserve `authorization_ownership =
    Known(NoAuthorizationRequired)`;
  - all 6 `provider-owned authorization` rows preserve
    `authorization_ownership = Known(ProviderOwnedAuthorization)`;
  - the 1 `Guardian polkit authorization` row preserves
    `authorization_ownership = Known(GuardianOwnedAuthorization)`;
  - all 8 `unknown — requires host research` rows map to
    `authorization_ownership = Unknown` **and** `privilege_requirement =
    Unknown` — both dimensions unknown, since the inventory proved neither
    for these rows;
  - no row is forced into a false known state on either dimension merely
    because the fixture-building code found it convenient.

  **Never represent `ProviderOwnedAuthorization` as "Guardian is
  privileged."** These remain different (governing brief §16). Likewise,
  never represent `RootOrSystemPrivilege` as implying
  `GuardianOwnedAuthorization` — a root/system-privilege requirement and
  who owns the authorization decision for it are also different claims.
- `boot_availability`: `EARLY_BOOT | SYSTEM_BUS | PRE_LOGIN | USER_SESSION
  | DESKTOP_ONLY | OPTIONAL` (§21). A capability may declare more than one
  level if it becomes available at different points.
- `diagnostic_cost`: may be a placeholder/minimal type this gate — the
  full `DiagnosticCost` structure (§19) belongs to G5's Diagnostic Budget
  Manager. Do not build G5's veto logic here; just ensure the field exists
  and is typed, not a raw number with no unit.

---

# 6. `Provider` trait and provider model

Per TDD contract §12:

```rust
trait Provider {
    fn identity(&self) -> ProviderIdentity;
    fn provenance(&self) -> ProviderProvenance;
    async fn probe(&self) -> ProbeResult;
    async fn capabilities(&self) -> Vec<CapabilityRecord>;
    async fn health(&self) -> ProviderHealth;
    async fn subscribe_events(&self) -> EventStream;
}
```

`ProviderProvenance` already exists in `guardian-provider-api` (P0-REG-003/
004) — reuse it unchanged. Build `ProviderIdentity`, `ProbeResult`, and
`ProviderHealth` alongside it, consistent with its existing style
(explicit `unknown` handling via `FromStr`/parse errors, not panics).

A mutable capability adapter MUST be able to express `inspect()`,
`validate(action)`, `snapshot(action)`, `apply(action)`, `observe
(expectation)`, `rollback(snapshot)` — as trait methods or an associated
trait. **Do not implement real bodies for these against real hardware in
G3.** Only the typed shape and an explicit `Unsupported` result for
operations a given provider doesn't support (§12, "Not every provider must
support every operation. Unsupported operations MUST return an explicit
typed `Unsupported` result.") — test this with a fixture provider that
deliberately supports only a subset.

Test fixtures (deterministic, in `guardian-testkit` or test-only modules)
should include at least two fixture providers ("provider A", "provider B")
offering overlapping and non-overlapping capabilities, with independently
controllable health/availability, so arbitration tests (§7) have something
real to arbitrate over. **Do not implement UDisks, NetworkManager,
systemd, NVML, UPower, or thermald adapters — those belong to G8 (§31 of
the governing brief).**

---

# 7. `ArbitrationDecision` and the Provider Arbitrator

Per TDD contract §13, the arbitrator answers: *"Which provider is
authoritative for this capability right now, and is Guardian allowed to
write it?"*

```rust
ArbitrationDecision {
    capability_id,
    candidate_providers,
    authoritative_provider,
    current_owner,
    ownership_basis,
    conflicts,
    write_permitted,
    rollback_kind,
    risk_class,
    decision_reason,
}
```

- `rollback_kind`: `NATIVE | EMULATED | BEST_EFFORT | NONE` (§13). This
  must be disclosed as part of the decision itself (P0-ARB-004) — not
  something a caller has to separately ask the provider for.
- `risk_class`: reuse the risk taxonomy directly (`OBSERVE | LOW |
  MODERATE | HIGH | VERY_HIGH`, §10) — do not create a second risk enum.
  If a shared `Risk` type does not yet exist in `guardian-core`, create it
  there and have this field use it; anything downstream (events,
  incidents, future transactions) reuses the same type (governing brief
  §18: "Do not create competing risk enums in different crates").
- `current_owner`: must be able to express **no writer**,
  **Guardian-owned writer**, **provider-owned writer** (e.g. thermald
  owning CPU thermal control while Guardian only observes), **external
  writer** (something outside Guardian's model entirely), and **conflict**
  — not collapsed into "provider exists ⇒ provider owns writes"
  (governing brief §14). A capability having a candidate provider is not
  the same claim as that provider currently holding write ownership.

## Arbitration invariants (§13, all five are testable requirements, not prose)

1. Two providers MUST NOT simultaneously receive write ownership for the
   same exclusively-owned capability — **P0-ARB-001**.
2. Ambiguous ownership fails closed: `write_permitted = false` —
   **P0-ARB-002**. Do not silently pick one candidate arbitrarily when
   ambiguity exists; that would be exactly the "unknown silently becomes
   safe" failure the governing brief's §28 forbids.
3. Provider absence can produce a degraded read-only capability but never
   a guessed write owner. Test: remove the sole candidate provider and
   assert the resulting `ArbitrationDecision` has `write_permitted =
   false`, not a stale/guessed owner.
4. `decision_reason` must be inspectable by clients — assert it is a real,
   non-empty, structured value (not just "reason: string" with no
   guarantee it's populated).
5. A provider ownership change invalidates stale arbitration/precondition
   state — **P0-ARB-003**, at the data-model level only. This gate does
   **not** implement G4's transaction machine; it must only prove that an
   `ArbitrationDecision` (or whatever state a future transaction would
   have captured as its precondition) carries enough identity/versioning
   that "this precondition is now stale because ownership moved" is
   mechanically detectable, e.g. via a monotonic arbitration
   epoch/generation number or an equivalent. Do not build `VALIDATING` →
   `APPLYING` runtime transitions here.
6. If arbitration is asked whether Guardian may write a capability whose
   `authorization_ownership` is `Unknown` (§5/§10), the decision MUST fail
   closed: `write_permitted = false`, exactly as for ambiguous ownership
   (item 2) — unless the governing contract is shown to specify a
   stricter or otherwise different representation. Unknown authorization
   ownership is not evidence of safety; it is an open question, and an
   open question about who may authorize a write must never be resolved
   by defaulting to "yes." This is data-model/arbitration behavior only —
   it must not become privileged authorization logic, and it does not
   replace the privileged helper's own independent authorization at the
   mutation boundary (§12).

## Determinism (governing brief §26/§27)

Given identical candidate-provider input, arbitration MUST produce the
identical decision every run. Required adversarial tests:

- reverse the order candidate providers are supplied — decision must not
  change;
- if internal bookkeeping uses a `HashMap`, prove iteration order
  differences don't change the outcome (e.g. run the arbitration function
  many times with a hasher that randomizes each run, or explicitly
  construct two logically-identical-but-differently-ordered inputs);
- no random selection, no "first in discovery order wins," no similarity
  matching on display names — everything resolves via explicit
  `capability_id`/`provider_id` values only.

---

# 8. `Event` and `Incident`

Per TDD contract §17:

```rust
Event {
    event_id,
    timestamp_monotonic,
    timestamp_wall,
    source_provider,
    event_type,
    resource_refs,
    severity,
    normalized_key,
    raw_reference,
    attributes,
}
```

- Monotonic time MUST be used wherever ordering/duration matters
  (**P0-EVT-001**) — test that wall-clock adjustment (simulate the clock
  jumping backward) does not reorder events whose monotonic timestamps are
  correctly ordered.
- `normalized_key` lets equivalent volatile log/event variants share one
  key (**P0-EVT-002**) — e.g. two slightly different raw journald lines
  for "the same" disk-full condition normalize to one key — **without**
  destroying the link back to each event's own `raw_reference`
  (**P0-EVT-003**). Write a test with two distinctly-worded raw sources
  that share a normalized key and assert both raw references remain
  independently retrievable.
- `severity` should reuse the risk taxonomy type (§10) where the concepts
  align, or a clearly distinct, explicitly justified severity type if the
  governing docs distinguish them — do not silently conflate risk (what an
  *action* costs) with severity (what an *observation* means) without
  checking `docs/guardian/20_Control_Plane/Event_and_Incident_Model.md`
  first.

Per TDD contract §18:

```rust
Incident {
    incident_id,
    opened_at,
    closed_at,
    status,
    summary,
    confidence,
    primary_resource,
    event_ids,
    evidence,
    candidate_causes,
    recommended_actions,
    transaction_ids,
    outcome,
}
```

Incident invariants (§18, each individually testable):

- an incident does not replace source events — `event_ids` are
  **references**, not copies; the underlying events remain independently
  retrievable (governing brief §24: "typed references such as event IDs...
  not... pointer-by-array-position or fragile implicit relationships");
- correlation can be updated as evidence arrives — appending an
  `event_id` to an existing open incident must not require destroying and
  recreating the incident or losing its `incident_id`;
- confidence changes are recorded, not silently overwritten — if
  `confidence` changes, the change itself should be attributable/traceable
  (does not require a full audit-log implementation this gate, but the
  model must not make "what did we believe before" unrecoverable);
- user actions and Guardian transactions can be linked via
  `transaction_ids` — this gate only needs the reference *shape* to exist;
  G4 populates it for real;
  incidents can close (`status`, `closed_at`) without a known root cause —
  test that `candidate_causes` may legitimately be empty at close time and
  this is not treated as an error state.

**P0-EVT-004** ("Multiple correlated events can be linked into one
incident without deletion") is the direct test anchor for the incident
correlation invariants above — write it against real fixture events, not
against a trivial one-event incident.

## Confidence model (governing brief §23)

Prefer a small, deterministic, explainable representation over an
arbitrary floating-point percentage unless
`docs/guardian/20_Control_Plane/Event_and_Incident_Model.md` or the TDD
contract explicitly calls for a numeric scale. If no governing document
specifies the concrete representation, propose a minimal ordered enum
(e.g. `Hypothesis | Probable | Confirmed`, or whatever terminology the
control-plane doc already uses) and justify the choice in the completion
report rather than inventing floating-point precision nothing downstream
needs.

---

# 9. Provenance (feeds capability/provider/event/incident evidence, builds on G0)

`docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §6 already
establishes the source-authority hierarchy (D-Bus/library → kernel
interface → structured CLI → scraped CLI). G3 must make this reusable
wherever a model needs to answer "where did this fact come from" —
`CapabilityRecord.interface_*` fields, `Event.source_provider`/
`raw_reference`, and `Incident.evidence` all need it. **Rank indicates
authority/preference, not automatic correctness** (governing brief §22) —
do not write a test or a comment implying a lower-ranked source is
presumed false.

Reuse `ProviderProvenance` (already implemented, P0-REG-003/004) as the
provider-level provenance type; extend or compose it for
event/incident-level evidence references rather than building a second,
incompatible provenance type from scratch.

---

# 10. Unknown handling (governing brief §28)

Unknown is a valid state, not an error to paper over. But "unknown" means
something different depending on which dimension — and, within Dimension
A, which *kind* of unknown — is asking. Three distinct rules apply, not
one blanket rule:

**Rule 1 — `AuthorizationMode` itself: exactly three governed states, no
wire-level fourth.** The enum contains exactly `NoAuthorizationRequired |
ProviderOwnedAuthorization | GuardianOwnedAuthorization` — do not add an
`Unknown`/`Unrecognized` variant to *this specific enum* unless a review of
`docs/guardian/20_Control_Plane/Privilege_and_Authorization.md` and the
governing TDD contract turns up an explicit requirement for one (none is
known to exist as of this handoff). An unrecognized wire/serialized token
for the `AuthorizationMode` payload itself (e.g. `"authorization_mode":
"future_mode_xyz"`) MUST NOT become any of the three governed states — it
MUST produce a typed parse/deserialization error and the caller fails
closed (the record is rejected/unusable). This is a **malformed/unsupported
value**, not an absence of knowledge, and must be distinguishable from
Rule 2 below in both code and tests. If the governing contract is later
found to require an explicit fourth `AuthorizationMode` variant instead,
follow the contract — but the implementation handoff and the
independent-review handoff must describe the *same* rule; do not let one
document imply a runtime fourth variant on this enum while the other
implies a parse-error-only scheme.

**Rule 2 — `authorization_ownership` (the `Knowledge<AuthorizationMode>`
wrapper, §5): `Unknown` is a legitimate, first-class runtime state, not a
parsing fallback.** This is a genuinely different case from Rule 1: Rule 1
is about an *invalid/unrecognized* `AuthorizationMode` token; Rule 2 is
about Guardian *never having established* which valid `AuthorizationMode`
applies at all (the wire representation is absent, or explicitly marked
unresearched — e.g. a missing field, an explicit `"unknown"` sentinel, or
whatever wire shape the serialization design settles on). This case
deserializes cleanly to `Knowledge::Unknown` — it is **not** an error,
**not** a parse failure, and **not** the same code path as Rule 1's
malformed-token rejection. Conflating the two (treating "we never
researched this" the same as "the wire sent us garbage") loses exactly the
distinction this repair exists to preserve.

**Rule 3 — `privilege_requirement` (Dimension B) and every other governed
enum in this gate (`availability`, `health`, `boot_availability`,
`rollback_kind`, `current_owner`, incident `status`, event `severity`) —
`Unknown` is a legitimate runtime variant, not just a wire-parsing
fallback.** `privilege_requirement` specifically carries `Unknown` as one
of its five governed states (§5) because the G2 inventory itself has 8
rows that are genuinely unresearched — that is real information, not an
error condition, and must survive into the runtime model as `Unknown`, not
merely be rejected at deserialization time. For these enums:

- deserializing a value the current binary doesn't recognize MUST produce
  an explicit `Unknown`/parse-failure outcome, never silently default to a
  "safe" or "available" or "authorized" variant (unless the governing
  contract explicitly defines that specific mapping — none currently do);
- write at least one test per governed enum that feeds it an unrecognized
  string/discriminant and asserts the result is the explicit unknown case,
  not a panic and not a silent default.

**The two dimensions' unknown states are independent, and Dimension A's
two kinds of unknown are independent of each other too.** A capability may
legitimately have `authorization_ownership = Known(ProviderOwnedAuthorization)`
while `privilege_requirement = Unknown` (not yet researched) — Guardian
knows who owns authorization for this operation but hasn't finished
characterizing its lower-level access requirement. The reverse is also
possible if research ever proceeds in that order. Do not let one
dimension's unknown-ness force the other dimension into `Unknown` or into
a parse error. And within Dimension A itself:
`authorization_ownership = Known(NoAuthorizationRequired)` (an established
architectural fact) and `authorization_ownership = Unknown` (no
established fact yet) MUST remain distinct at every layer — construction,
serialization, arbitration (§12 below), and test assertions. Neither may
ever be used as shorthand for the other.

This mirrors `guardian-provider-api`'s existing `FromStr`-with-explicit-
unknown pattern (`(value != "unknown").then(...)` for optional provenance
fields) — follow that established style rather than inventing a new one.

---

# 11. Crate boundaries

TDD contract §4's illustrative tree places `capability/`, `arbitration/`,
`transaction/`, `incident/`, `diagnostics/`, `errors/`, and `identity/` as
submodules of `guardian-core`, with `guardian-provider-api` as the
separate provider-facing crate. The contract explicitly allows deviation
("exact crate names may change... but the architecture MUST preserve
separation equivalent to") — and the repository already has one
precedent: `ProviderProvenance` (conceptually provider-facing) lives in
`guardian-provider-api`, not under a `guardian-core` submodule, because it
is a provider-contract concern, not shared internal state.

Apply the same judgment, not the tree verbatim:

- `guardian-core`: `Risk` (shared, §10), `Event`, `Incident`,
  `ArbitrationDecision` (the *decision* type — internal, cross-cutting,
  used by anything that needs to know "who owns this write right now"),
  the shared identifier types (`CapabilityId`, `ProviderId`, `EventId`,
  `IncidentId`), and whatever error-model additions §16 requires beyond
  what `guardian-core::error` already has.
- `guardian-provider-api`: `CapabilityRecord`, the `Provider` trait,
  `ProviderIdentity`, `ProbeResult`, `ProviderHealth`, and anything a
  *provider implementation* needs to speak — provider-facing contract
  types, consistent with `ProviderProvenance`'s existing placement.

Before writing code, review the current contents of both crates (`find
crates/guardian-core/src crates/guardian-provider-api/src -type f`) and
justify the actual placement chosen against this repository's existing
structure in the completion report — do not silently follow this
handoff's suggestion if inspection reveals a better fit; do not silently
deviate without explaining why either.

Do not create new tiny crates merely for modularity theater (governing
brief §30).

---

# 12. G2 is a constraint on G3, not background context

G3 must not reopen or weaken anything G2 established. Specifically:

- `ArbitrationDecision`/Provider Arbitrator data lives in the unprivileged
  control-plane domain (`guardian-core`) — nothing built in this gate runs
  in, or grants privilege to, a helper process.
- A future privileged helper (per ADR-002) may eventually *consult*
  arbitration/ownership state produced here for non-authoritative
  coordination. **This gate must not build that consultation mechanism,
  and must not build anything that lets an `ArbitrationDecision` or
  similar core-owned value be mistaken for proof of caller identity or
  authorization.** If any G3 type has a field or method whose name or
  shape could plausibly be read as "authorization result" (e.g. anything
  resembling `authorized: bool` on a core-owned decision struct), that is
  a **G2 regression** — rename or restructure it. Both
  `authorization_ownership` and `privilege_requirement` on
  `CapabilityRecord` (§5) describe *properties of the capability itself*
  — what kind of authorization it needs (or that this is not yet known),
  and what OS privilege/access it requires — never *whether the current
  caller has been authorized* or *what privilege the current process
  holds*. This holds even when `authorization_ownership` is
  `Known(GuardianOwnedAuthorization)`: that value means only "Guardian
  owns the authorization mechanism for this capability," never "the
  current caller passed that authorization." Keep that distinction sharp
  in both types and their doc comments; this applies equally to both
  fields.
- Do not implement any D-Bus-exposed method in this gate. G3 is internal
  typed models only; nothing here changes the G0 public surface
  (`ContractVersion`, `ServiceState`) or the G2 helper's bounded write
  surface.

---

# 13. Non-`P0-*` focused tests are expected and required

Sections 11, 12, 16, and 18 of the governing contract are schema
requirements without their own `P0-*` test-ID group (§3 above). Do not
treat "no ID exists" as "no test required." Write ordinary, clearly-named
focused tests for:

- serialization round-trips for every model that crosses a boundary
  (§14 below);
- the capability/provider identity separation proof (§4);
- the unknown-handling proof for each governed enum, including the three
  distinct rules in §10: `AuthorizationMode`'s exactly-three-states-plus-
  parse-error rule (Rule 1), `authorization_ownership`'s legitimate
  `Knowledge::Unknown` state (Rule 2), and `privilege_requirement`'s
  runtime `Unknown` variant (Rule 3) — these are three separate proofs,
  and Rule 1's parse-error path must be tested distinctly from Rule 2's
  clean-deserialize-to-`Unknown` path;
- the `authorization_ownership` ⇄ G2-inventory-classification mapping
  proof and the separate `privilege_requirement` ⇄ G2-inventory-
  classification mapping proof (§5) — these are two proofs, not one, and
  neither satisfies the other; both must correctly leave all 8 unresearched
  rows unknown on both dimensions;
- the ten adversarial/model tests in §16.1 proving the dimensions, and
  Dimension A's two kinds of unknown, do not leak into or imply each
  other.

Name these tests descriptively (matching this repository's existing style,
e.g. `capability_identity_survives_provider_change`,
`unrecognized_availability_value_is_explicit_unknown_not_a_panic`) so a
reviewer can see what's being proven without needing a `P0-*` cross-
reference for every single test.

---

# 14. Serialization and host evidence

G3 models will eventually cross process/D-Bus/persistence/log boundaries.
This gate requires:

- a stable representation for each governed enum (explicit
  discriminants/strings, not derive-default `Debug` formatting relied on
  as a wire format);
- explicit unknown-value handling on deserialization (§10);
- round-trip tests (serialize → deserialize → equal) for every model that
  is expected to cross a boundary.

**Do not expose these internal models on the public D-Bus surface in this
gate** — internal typed models and any future public wire contract remain
separate unless a later gate's governing contract explicitly says
otherwise (governing brief §25).

**No VM is required for this gate.** G3 is pure data-model semantics —
Layer 1 only. If, during implementation, a coding agent finds itself
writing behavior that depends on real host semantics (real D-Bus, real
polkit, real filesystem state), that is a signal the work has drifted out
of G3's scope — either remove it, or explicitly defer it to the gate that
actually owns it (G8 for real providers, G4 for real transactions) and say
so in the completion report. Do not quietly add a VM requirement to make
such code "pass."

---

# 15. TDD sequence (governing brief §35)

For each normative contract item in §3, follow strict red→green:

1. write the failing test for one specific normative behavior;
2. run it, confirm it fails for the right reason (not a compile error
   unrelated to the behavior under test);
3. implement the smallest correct model/logic that makes it pass;
4. run the focused test, confirm green;
5. run `cargo test --workspace`, confirm no regression;
6. move to the next item.

Do not build every model first and backfill tests. Preserve evidence of
this sequence in commit history (small, test-then-implementation-shaped
commits) or, at minimum, in the completion report's TDD-order narrative.

---

# 16. Adversarial self-check before reporting done

## 16.1 Authorization/privilege dimension tests (required, in addition to §16.2)

These ten are required focused tests, not optional adversarial thought
experiments — write them, do not merely reason about them:

1. `authorization_ownership = Known(NoAuthorizationRequired)` is
   distinguishable from `authorization_ownership = Unknown` — they are
   different values, must compare unequal, and must not collapse to the
   same serialized wire representation.
2. an unknown/unresearched authorization owner (`authorization_ownership
   = Unknown`) never becomes `Known(NoAuthorizationRequired)` anywhere —
   not in construction, not in serialization, not in arbitration.
3. all eight `unknown — requires host research` G2 inventory rows (§5)
   map to `authorization_ownership = Unknown`, and remain so unless a
   specific row's own recorded evidence text explicitly proves an owner —
   fixtures must not manufacture a known owner for any of the eight from
   general platform knowledge or architectural preference.
4. all eight of the same rows map to `privilege_requirement = Unknown`.
5. a known `provider-owned authorization` row (e.g. `UDisks PowerOff`)
   round-trips through serialization as `authorization_ownership =
   Known(ProviderOwnedAuthorization)`.
6. a known `Guardian polkit authorization` row (`power-profiles-daemon
   HoldProfile`) round-trips through serialization as
   `authorization_ownership = Known(GuardianOwnedAuthorization)`.
7. an unsupported/future serialized `AuthorizationMode` token (e.g.
   `"authorization_mode": "future_mode_xyz"`) returns a typed
   parse/deserialization failure — distinct from, and not silently
   converted to, `authorization_ownership = Unknown` (§10 Rule 1 vs.
   Rule 2).
8. `authorization_ownership = Unknown` serializes/deserializes to a wire
   form distinct from `Known(NoAuthorizationRequired)`'s wire form — the
   round-trip test for one must not accidentally pass for the other.
9. changing only the authorization-ownership knowledge state (e.g.
   `Unknown` → `Known(...)` as research resolves it) does not alter
   `capability_id`. (This generalizes the earlier "changing
   `authorization_ownership` does not alter `provider_id`" requirement —
   also required, and covered by item 9's fixture if constructed to vary
   both.)
10. arbitration fails closed (`write_permitted = false`) when the
    `authorization_ownership` relevant to a proposed write is `Unknown`
    (implementation §7, arbitration invariant 6) — this test must remain
    data-model/arbitration behavior only, and must not implement or
    simulate G4's transaction machine or any privileged authorization
    logic.

Also retain, as part of this same test group: `privilege_requirement =
RootOrSystemPrivilege` does not imply `authorization_ownership =
Known(GuardianOwnedAuthorization)` (construct a fixture where a provider
requires root-level access but performs its own authorization —
`authorization_ownership` must remain `Known(ProviderOwnedAuthorization)`),
and the two dimensions' fields serialize/deserialize independently across
every combination of known/unknown on each side.

## 16.2 General adversarial self-check

Before writing the completion report, deliberately try to break your own
implementation against each of these (this list is shared verbatim with
the independent reviewer — do not skip any):

1. reverse candidate-provider order — does arbitration choose differently?
2. same capability offered by two providers — is authority selection
   deterministic and explained via `decision_reason`?
3. the active writer disappears — does `current_owner` correctly become
   "no writer," not a stale reference?
4. two providers each claim exclusive write ownership of the same
   capability — is the conflict explicit (P0-ARB-001), not silently
   resolved to whichever was processed last?
5. is a read-only observer ever representable as, or mistakable for, a
   writer?
6. is `ProviderOwnedAuthorization` ever representable as, or mistakable
   for, "Guardian is privileged"?
7. does an unknown privilege/authorization value silently become "safe"
   anywhere?
8. does any capability/event/incident ID regenerate randomly on reload
   instead of being stable?
9. does a capability's ID change when its provider changes?
10. does an `Event` ever lose its `source_provider`/provenance when
    normalized?
11. does an `Incident` ever store a mutable object reference or array
    position instead of a stable `event_id`?
12. does deserializing an enum value from a newer, hypothetical future
    version crash instead of yielding an explicit unknown?
13. does an unavailable provider ever cause silent fallback to a
    lower-authority writer without that being visible in
    `decision_reason`?
14. if you modeled "external writer" at all, does Guardian's arbitrator
    ever try to silently claim ownership over it?
15. does anything resembling a future privileged helper trust an
    `ArbitrationDecision` (or any other core-owned value) as authorization
    proof? (Should be structurally impossible — confirm by inspection,
    not just by test, since this is a design property as much as a
    runtime one.)
16. does any core data model gain a privileged-mutation method? (Should be
    structurally impossible — G3 has no privileged code path at all.)
17. did any `Transaction`/`Apply`/`Rollback` *runtime* logic leak in,
    beyond the ID/reference plumbing explicitly required by §7/§8?
18. did a real provider call (UDisks, NetworkManager, systemd, etc.) leak
    into a test fixture instead of using a deterministic fake?

---

# 17. Completion states

Report exactly one, honestly:

```text
G3 CANDIDATE — CORE MODELS READY FOR INDEPENDENT AUDIT
G3 PARTIAL — CONTRACT TESTS INCOMPLETE
G3 BLOCKED — GOVERNING CONTRACT INSUFFICIENT
G3 BLOCKED — MODEL CONFLICT DISCOVERED
```

Do not report `CANDIDATE` if any normative test from §3 is red, skipped,
or asserts against a mock that doesn't actually exercise the behavior
under test.

---

# 18. Completion report

Include, at minimum: which normative tests are green with exact names/IDs;
crate-placement decisions and justification (§11); **both** the
`authorization_ownership` model's mapping (explicitly showing which of the
24 rows are `Known(...)` and which are `Unknown`, and confirming all 8
unresearched rows landed on `Unknown`, not a manufactured `Known` value)
and the separate `privilege_requirement` model's mapping against all 24
Privilege Requirement Inventory rows, reported as two distinct tables, not
one combined claim; determinism-test results (§7); the §16.1 and §16.2
adversarial self-check results item-by-item; confirmation that
`P0-REG-003`/`004` remain green unmodified; full `cargo fmt --check` /
`cargo clippy --workspace --all-targets --all-features -- -D warnings` /
`cargo test --workspace` output; and an
explicit statement of what was deferred to G4 or G8 and why.

Then stop. Do not begin G4. Do not tag G3 — independent review happens
first, exactly as it did for G0, G1, and G2.
