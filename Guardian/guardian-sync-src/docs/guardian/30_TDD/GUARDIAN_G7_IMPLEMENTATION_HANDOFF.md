# Guardian Phase 0/1 Implementation Handoff
## G7 — Production Daemon Only

# Revision note (preserved history — read before §1)

This handoff was revised once, before any G7 code was written, following an
independent planning review's verdict:

```text
FAIL — G7 ARCHITECTURAL ROLE AMBIGUITY
```

**Blocking finding that caused the FAIL:** the original handoff's TDD
sequence wired the entire G4 transaction engine
(Snapshot/Validate/Authorize/Apply/Observe/Confirm/Rollback) into the
unprivileged daemon binary, while `ADR-002` (Model B) requires clients to
call the privileged helper *directly* for Guardian-owned privileged
mutations, with the daemon never relaying a client's write request to the
helper. The original handoff never resolved how the daemon's transaction
engine would reach a privileged `Apply` step without reproducing exactly
the confused-deputy relay `ADR-002` built, measured, and rejected during
G2. This revision adds a new §2 that resolves that ambiguity explicitly,
before implementation, rather than leaving it to be discovered mid-build.

Five non-blocking findings from the same review are also addressed in this
revision: the direct-call invariant is now stated in this document itself
(not only by reference to `ADR-002`); the naming decision is extended to
D-Bus well-known names; unit startup/activation independence is stated
explicitly; the G6 evidence-stub prohibition is restated here rather than
left to cross-reference; and an explicit public-API growth guardrail is
added.

**No implementation existed under the original handoff** — this is a
planning-only correction. `ADR-002` itself was not amended: its accepted
text (the direct-call correction, the "process that performs the write
owns Snapshot/Validate/Apply/Observe" principle, and the
never-trust-forwarded-identity invariant) is sufficient to derive this
revision's answers. What was missing was this handoff's own translation
of those principles into a concrete per-operation-class architecture —
that gap is what this revision closes. `crates/guardian-core/src/
transaction/engine.rs`'s actual shape (free functions operating on `&mut
TransactionRecord`, no hidden singleton, no process affinity) was checked
directly and confirmed to already support running independent transaction-
engine instances in two different processes without any redesign — see §2.

# 1. Mission

Build the real, running production daemon: a systemd-managed service
registered on the system D-Bus, implementing the selected privilege
topology (ADR-002, Model B — unprivileged daemon + narrow privileged
helper), with persistent state that survives daemon restart and forced
termination without corruption.

G7 is mechanically derived from §38's own text:

```text
## G7 — Production daemon

Required:
- systemd unit;
- D-Bus service;
- persistent state;
- selected privilege topology implemented.

Tests:
P1-DMN-001..005
P1-SEC-001..004
```

Nine normative IDs total. Do not treat any other P1-* group (P1-SYS,
P1-PSI, P1-LGI, P1-UDS, P1-UPW, P1-ACC — all G8; P1-CLI/TUI/GUI/IND —
G9; P1-PKG — G9) as in scope here. §36's P0-* IDs are already
implemented (G0-G5, all tagged) and are not re-litigated by this gate.

# 2. Production topology, direct-call invariant, and operation classes (normative — read before §3)

This section is the architectural resolution the independent review
required. It is normative: the TDD sequence in §8 and the fail-closed
checklist in §7 both depend on it, and it must not be reinterpreted
per-operation during implementation.

## 2.1 Component naming — do not use "core" for the daemon process

Architectural shorthand such as "core" MUST NOT be used for the daemon
process anywhere in G7 evidence or code comments, because it collides
with the existing library crate name. Use these names exactly:

```text
guardian-core     = Rust LIBRARY crate only (crates/guardian-core).
                    Never a process. Holds transaction engine, budget,
                    psi, recorder, arbitration, event, incident,
                    identity, authorization modules — unchanged by G7.

guardian-daemon   = the unprivileged production daemon PROCESS.
                    Existing crate (crates/guardian-daemon), currently a
                    31-line G0 contract-only library with no binary
                    target. G7 adds a `src/bin/guardian-daemon.rs` (or
                    converts the crate to also produce a binary target)
                    that depends on guardian-core as a library.

guardian-helper   = the narrow privileged production helper PROCESS.
                    Does not exist yet. G7 creates a new crate
                    `crates/guardian-helper` producing a `guardian-helper`
                    binary, which also depends on guardian-core as a
                    library — it does NOT depend on guardian-daemon.

clients           = GUI/TUI/CLI (G9) and, later, the production
                    indicator (G9, built on `ksni` per ADR-006). None of
                    these exist yet; G7 evidence stands in for "a
                    client" using minimal typed D-Bus calls, per §4/§8.
```

Record this decision as final in this gate's own evidence (a short note
in the G7 milestone, not a new ADR — the decision is mechanical, not
contested).

## 2.2 D-Bus name ownership

```text
io.github.cliffthelin.Guardian1  →  owned by guardian-daemon.
  This is the permanent public namespace selected at G0 (contract §7.1)
  and already bound to guardian-daemon's G0 skeleton
  (crates/guardian-daemon/src/lib.rs). It remains the client-facing,
  versioned, publicly documented interface. guardian-helper does NOT
  register objects under this name.

io.github.cliffthelin.GuardianHelper1  →  owned by guardian-helper.
  A new, separate well-known name — deliberately not a sub-path of
  Guardian1, because it is a distinct trust boundary with its own
  interface-major versioning lifecycle (contract §7.3), not an additive
  extension of the public contract. Its interface exposes only the
  narrow typed privileged-write methods described in §2.3, plus the
  test/observability-only accessors §4's evidentiary standard requires.
  It is real production surface (not evidence-only), but it is
  helper-specific, not part of Guardian1.
```

Neither name may gain a method/property/signal beyond what one of the
nine G7 normative IDs actually requires — see §2.8.

## 2.3 The direct-call invariant (stated here, not only by reference)

This is `ADR-002`'s Model B decision, restated as a normative G7
requirement in this handoff's own text:

```text
For Guardian-owned privileged mutations, clients call guardian-helper
directly, on io.github.cliffthelin.GuardianHelper1.

guardian-daemon MUST NOT relay a client's privileged write request to
guardian-helper. guardian-daemon has no code path that constructs a
call to GuardianHelper1's mutation method on a client's behalf.

guardian-helper independently resolves the actual D-Bus caller from its
own inbound connection, and independently performs the required real
polkit authorization (CheckAuthorization) immediately before mutation.

Identity or authorization state forwarded by any other process —
including guardian-daemon — is never authoritative for guardian-helper's
decision. guardian-helper may still consult guardian-daemon for
non-authoritative coordination context (see §2.6, Class B), but never
for who the caller is or whether they are authorized.
```

Why this matters mechanically, not just as policy: D-Bus does not forward
sender identity through a relay hop (`ADR-002`, confirmed empirically
during G2 — see `docs/evidence/g2/model-b/`). If `guardian-daemon` ever
called `GuardianHelper1`'s mutation method to satisfy a client's request,
`guardian-helper` would correctly and honestly resolve the caller as
`guardian-daemon`, not the original client — reproducing the exact
confused-deputy shape Model B was selected to avoid. This is why §7's
fail-closed checklist and §9's adversarial self-check both test for this
directly, and why the independent review handoff's §6a (added in this
revision) requires proving its absence, not merely its intended absence.

## 2.4 Operation classes

G7's own evidence only needs one bounded Class A operation and one
bounded Class B operation (see §4/§8) — real providers are G8. But the
architecture below applies to all future operations, and must be
documented now so G8+ providers are classified correctly as they arrive.

### Class A — Guardian-owned privileged mutation

```text
client
  │ direct typed call (GuardianHelper1)
  ▼
guardian-helper
  │ resolve actual D-Bus caller (own connection, not forwarded)
  ▼
  Snapshot / Validate (repeated at the privileged boundary — contract §14.2)
  ▼
  Authorize (real polkit CheckAuthorization, immediately before Apply)
  ▼
  Apply intent → Apply outcome (contract §14.1/§18.2 split preserved)
  ▼
  Observe → Confirm, or Rollback
```

`guardian-helper` instantiates its own local `TransactionEngine` call
sequence (the free functions in `crates/guardian-core/src/transaction/
engine.rs`, used as a library — this crate has no process affinity, see
the Revision note above) entirely within its own process. No stage of
this class ever executes in `guardian-daemon`.

### Class B — Provider-owned authorization

```text
client
  │
  ▼
guardian-daemon
  │ typed call to the provider's own stable D-Bus API
  ▼
provider (UDisks / systemd1 / NetworkManager / AccountsService / ...)
  │ provider performs its OWN polkit authorization —
  │ Guardian requires no elevated privilege for this class
  ▼
provider applies the change; guardian-daemon observes the result
```

`guardian-daemon` instantiates its own local `TransactionEngine` call
sequence for this class. `Authorize` here means "the provider's own
authorization gate was invoked and its result recorded" — `guardian-
daemon` never calls `CheckAuthorization` itself for Class B, because it
holds no privileged action to authorize; the provider's own action
ownership is what `contract` §9's polkit action taxonomy and G2's
Privilege Requirement Inventory (`docs/evidence/g2/
PRIVILEGE_REQUIREMENT_INVENTORY.md`, 6/24 areas provider-owned) already
established. **This class does not route through `guardian-helper`
merely because `guardian-helper` exists** — see §2.8.

The precise mechanism by which a real provider's own authorization
correctly attributes the action to the original client (rather than to
`guardian-daemon`) is provider-specific and depends on that provider's
own D-Bus API (e.g. a `Subject` parameter it resolves itself, or a
capability that is authorized against the daemon's own fixed identity
because the action is intentionally daemon-attributable, not
client-attributable). **This is explicitly out of scope for G7** to fully
resolve for every future provider — G7 has no real providers (G8's job).
G7 only needs to establish and evidence the class boundary and the rule
that Class B never touches `guardian-helper`; the per-provider identity
question is a G8 concern for whichever real provider first needs it,
consistent with `ADR-002`'s own scoping.

### Class C — No-privilege / read-only

```text
client → guardian-daemon → (local computation, or a provider's read-only
                              method)
```

No `TransactionEngine` instance is used — G4's engine models writes only
(contract §14 is a *transaction* state machine). Entirely within `guardian-
daemon`. This is the class G0's existing skeleton already models
(`GuardianContract::service_state()` etc.).

## 2.5 Transaction stage ownership — differs by class, shown separately

**Class A (Guardian-owned privileged mutation) — every stage inside `guardian-helper`:**

```text
Snapshot:            guardian-helper
Validate:             guardian-helper
Authorize:            guardian-helper (real CheckAuthorization)
Apply intent:         guardian-helper
Apply outcome:        guardian-helper
Observe:              guardian-helper
Confirm:              guardian-helper
Commit/Rollback:      guardian-helper
```

**Class B (provider-owned authorization) — every stage inside `guardian-daemon`; `Apply` delegates to the provider's own already-authorized method:**

```text
Snapshot:             guardian-daemon (via provider read API)
Validate:             guardian-daemon
Authorize:             delegated — recorded as "provider-authorized",
                       guardian-daemon performs no CheckAuthorization call
Apply intent:         guardian-daemon (intent to call the provider)
Apply outcome:        guardian-daemon (the provider's returned result)
Observe:              guardian-daemon
Confirm:              guardian-daemon
Commit/Rollback:      guardian-daemon (rollback = the provider's own
                       compensating action if any, or `ROLLBACK_FAILED`
                       recorded honestly per contract §14.2 if none exists)
```

This answers the review's central question directly: **yes, more than one
process-local `TransactionEngine` instance is safe**, because the engine
is a set of free functions with no hidden shared/global state (confirmed
by reading `engine.rs` directly, not assumed), and because every
individual operation has exactly one authoritative owning process for its
own `Apply` — `ADR-002`'s single-writer analysis ("no Model-B scenario
this pass built where `core` and `helper` could both attempt the same
write") generalizes cleanly across classes: no operation is ever a
candidate for `Apply` in more than one process. Every P0-TXN invariant
(contract §14.2) is preserved unmodified for both classes; nothing about
G4's accepted state machine, record shape, or invariants changes. This is
a process-boundary decision for where an unmodified engine instance runs,
not an engine redesign.

**P1-DMN-002 (restart) and P1-DMN-005 (crash recovery) note:** for Class A
evidence, "daemon restart"/"forced termination" in these two IDs means
**`guardian-helper`'s** restart/termination, since `guardian-helper` is
the process that owns the nonterminal transaction state for that class
(contract §14.2: "Daemon restart must recover or clearly terminate
nonterminal transaction state" — generically worded before Model B
existed as a process split; it binds whichever process is the actual
transaction owner). G7's evidence for P1-DMN-002/005 MUST be gathered
against `guardian-helper` with a real Class A transaction genuinely
in-flight at the moment of restart/kill, not against an idle `guardian-
daemon`. `guardian-daemon`'s own restart behavior for Class B/C state is
separately evidenced too, since it owns Class B's transaction lifecycle —
both are required, and must not be conflated as a single test.

## 2.6 State ownership

```text
guardian-daemon state:
  Owns: Class B/C data — provider read caches, correlation state,
        Class B transaction records.
  Location: /var/lib/guardian/daemon/
  UID/GID: the unprivileged daemon's own service account (final name
           decided in §2.1's evidence note), group `guardian`.
  Permissions: 0700 on the state directory (StateDirectory=, contract
               §23); guardian-daemon is the sole writer.

guardian-helper state:
  Owns: Class A transaction records (the privileged-mutation lifecycle).
  Location: /var/lib/guardian/helper/
  UID/GID: root (per ADR-002's polkit trusted-caller requirement),
           group `guardian`.
  Permissions: 0700 on the state directory; guardian-helper is the sole
               writer. Never world-writable, never group-writable.

transaction records:
  Authoritative writer: exactly one per record — guardian-helper for
    Class A, guardian-daemon for Class B. Never both; the two classes
    write to disjoint directories (above), so no file is ever a target
    for two writers.
  Allowed readers: the owning process only, for the raw persisted file.
  Corruption/recovery ownership: each process recovers its own state on
    its own restart, using G4's unmodified persistence/recovery module
    (`crates/guardian-core/src/transaction/{persistence,recovery}.rs`) —
    no shared recovery logic needs to reason about the other process's
    files.

read-sharing model (if guardian-daemon needs Class A status for
correlation/display):
  guardian-daemon MUST NOT read guardian-helper's state directory or
  transaction files directly — that would create a second reader of
  root-owned state without an authorization boundary, and risks silently
  becoming a second writer later. Instead, if a future feature needs
  Class A transaction status visible to guardian-daemon (e.g. for a GUI
  history view), guardian-helper exposes a narrow, read-only, typed
  accessor method on GuardianHelper1 (e.g. `TransactionStatus(in s
  transaction_id) -> ...`) that guardian-daemon calls like any other
  client. This keeps `guardian-helper` the sole authoritative writer and
  reader of its own state, and turns "sharing" into "another typed D-Bus
  call," not filesystem access. G7 does not need to build this accessor
  unless one of the nine normative IDs requires it (none currently do);
  this paragraph exists so it is not accidentally solved later by
  granting guardian-daemon filesystem read access instead.
```

Forbidden explicitly, per this section: world-writable state; a shared
mutable file with two writers; `guardian-daemon` writing root-authoritative
transaction state; `guardian-helper` trusting `guardian-daemon`-written
authorization state.

## 2.7 Unit / startup relationship

```text
guardian-daemon.service and guardian-helper.service are independent
systemd units. Neither Requires= nor BindsTo= the other.

Both are always-running (WantedBy=multi-user.target), not D-Bus-
activated on demand — P1-DMN-001 (boot start, before graphical login)
requires the daemon to already be running at boot, and P1-DMN-003 (no
desktop dependency) requires it to run without any session bus; on-
demand D-Bus activation would satisfy neither cleanly and is not used.

No startup ordering dependency is introduced between the two units.
guardian-helper does not need guardian-daemon to be up to serve a Class A
request (the client calls it directly), and guardian-daemon does not need
guardian-helper to be up for Class B/C operations. This mirrors ADR-002's
own found failure-containment property (a helper crash does not take
reads down, and vice versa) — introducing an ordering dependency here
would be pure convenience, not a real requirement, and is explicitly not
done (contract §39's own caution against unjustified shortcuts applies).

Each unit's failure semantics are independent: guardian-helper down means
Class A writes are unavailable but Class B/C and reads continue via
guardian-daemon; guardian-daemon down means Class B/C and reads are
unavailable but a client can still reach guardian-helper directly for
Class A, per the direct-call invariant in §2.3.
```

## 2.8 Guardrails carried into this section

```text
Provider-owned authorization (Class B) remains provider-owned. It does
not route through guardian-helper merely because guardian-helper exists.
This must remain compatible with G2's Privilege Requirement Inventory and
with however G8 wires real providers.

G7 must not add incidental permanent public D-Bus API surface —
on either Guardian1 or GuardianHelper1 — beyond what one of the nine
normative IDs actually requires. Any evidence-only test interface used to
prove a lifecycle claim (e.g. a bounded test write method, an
observability-only accessor) must be clearly documented as such and must
not silently become permanent client-facing surface without a real
future requirement driving it.

tests/vm/g6-daemon-evidence-stub is evidence-only (G6's own explicit
marking: NON-PRODUCTION / DISPOSABLE / G6-EVIDENCE-ONLY /
NOT-A-G7-DAEMON-SKELETON, restated here because a reader starting from
G7's own handoffs should not have to cross-reference G6's to find this
rule). It MUST NOT be copied, promoted, extended, or otherwise used as
the basis for guardian-daemon's or guardian-helper's skeleton. Both G7
binaries are built fresh from this handoff's own TDD sequence (§8).
```

# 3. G7 is primarily an integration/wiring gate, not a from-scratch logic gate

Read this before writing code. The hard business logic G7 depends on
already exists, is already tested, and is not to be redesigned:

- Transaction engine, persistence (`persist`/`load`/`load_all`), and
  crash recovery model: `crates/guardian-core/src/transaction/`
  (`engine.rs`, `persistence.rs`, `recovery.rs`, `apply.rs`,
  `observation.rs`, `rollback.rs`) — G4, tagged
  `phase0-g4-transaction-engine`. Per §2.5, each of `guardian-helper`
  (Class A) and `guardian-daemon` (Class B) instantiates this engine
  independently, in-process, unmodified.
- Diagnostic Budget Manager, PSI parsing model, bounded recorder:
  `crates/guardian-core/src/{budget,psi,recorder}.rs` — G5, tagged
  `phase0-g5-diagnostic-safety`.
- Capability Registry, Provider Arbitrator, event/incident model:
  `crates/guardian-core/src/{arbitration,event,incident}.rs` — G3,
  tagged `phase0-g3-core-data-models`.
- Caller identity resolution and polkit authorization:
  `crates/guardian-core/src/{identity,authorization}.rs` — G1, tagged
  `phase0-g1-identity-authorization`. Per §2.3, `guardian-helper` is the
  only process that calls this for Class A; `guardian-daemon` never
  calls `CheckAuthorization` for Class B (the provider does).
- Privilege topology decision and its full evidence base: `ADR-002`, G2
  prototypes referenced there (`crates/guardian-daemon/tests/
  g2_privilege_topology_contract.rs`) — G2, tagged
  `phase0-g2-privilege-topology`.

G7's job is to wire this already-tested logic into two real running
services and prove, under real systemd/D-Bus/crash conditions (not unit
tests alone), that the wiring itself — including the process-boundary
placement resolved in §2 — is correct. Do not reimplement or redesign
any of the above modules "while you're in there."

# 4. Naming decision — final (see §2.1/§2.2 for the full resolution)

`crates/guardian-core` is the existing **library crate name** holding
the shared business logic listed in §3. `ADR-002`'s own prose uses "the
future production `guardian-core`" to mean the **unprivileged daemon
binary** Model B calls for — §2.1 resolves this collision by never
reusing "core" for the process; the process is called `guardian-daemon`
throughout this handoff and all G7 evidence.

- `crates/guardian-daemon` (currently a thin, 31-line library exporting
  only the G0 read-only contract skeleton — `INTERFACE_NAME`,
  `OBJECT_PATH`, `GuardianContract` with `service_state() ==
  "contract-only"`) is the home for the **unprivileged daemon binary**.
  It already depends on `guardian-core` (the library) and already has the
  G0/G1/G2 contract test suites in `tests/`. It already owns
  `io.github.cliffthelin.Guardian1` (§2.2).
- A **new** crate `crates/guardian-helper` is created for the privileged
  binary — it does not exist yet. It owns
  `io.github.cliffthelin.GuardianHelper1` (§2.2).

# 5. Required tests (§37, normative)

```text
P1-DMN-001 — boot start
  guardian-daemon starts successfully under systemd before graphical
  login. guardian-helper's own boot-start behavior is evidenced
  separately for the same reason — both are always-running units (§2.7).

P1-DMN-002 — restart
  Daemon restart preserves required persistent state. Per §2.5, gather
  this against guardian-helper for a genuinely in-flight Class A
  transaction, and separately against guardian-daemon for Class B/C
  state — do not test only one process and generalize to both.

P1-DMN-003 — no desktop dependency
  Both guardian-daemon and guardian-helper run without GNOME/Xfce/
  session bus.

P1-DMN-004 — clean stop
  Stop completes without leaving corrupt transaction persistence, for
  whichever process was the transaction owner of the test operation
  (§2.5).

P1-DMN-005 — crash recovery
  Forced termination (real `kill -9`) does not corrupt persisted state.
  Same per-class distinction as P1-DMN-002.

P1-SEC-001 — hardening review
  `systemd-analyze security` artifact exists for BOTH units — they are
  separate trust boundaries (§2.1) and must not share one hardening
  claim.

P1-SEC-002 — path access
  Neither service can write outside its own declared writable path
  (§2.6) except through authoritative external provider APIs (Class B).

P1-SEC-003 — no arbitrary shell API
  Public interface (Guardian1 and GuardianHelper1 alike) remains free of
  generic command execution.

P1-SEC-004 — privilege denial
  An unauthorized client's direct call to GuardianHelper1's Class A test
  write method is rejected — this must be a genuinely different,
  unprivileged identity, not the same privileged test harness merely
  omitting a flag, and must go directly to guardian-helper (§2.3), never
  routed through guardian-daemon.
```

Every one of these is a real-system claim (systemd behavior, real
process kill/restart, real `systemd-analyze security` output, a real
unauthorized D-Bus call denied) — none is provable by `cargo test`
alone. This gate's evidentiary standard is G1/G2/G6's precedent, not
G3/G4/G5's: real disposable-VM execution, screenshots/transcripts with
provenance, no mocks substituting for the real systemd/D-Bus/polkit
stack. Follow the `*-vm-setup.sh` + `*_EVIDENCE.md` pattern already
established in `docs/evidence/g1/`, `docs/evidence/g2/`, and
`docs/evidence/g6/`.

# 6. Scope boundary

## In scope

- `guardian-daemon` binary (unprivileged, per ADR-002 and §2.1): systemd
  unit, D-Bus service registration on `io.github.cliffthelin.Guardian1`
  (the real system bus, not just a private test bus), wiring the
  Class B/C path — transaction engine + persistence + budget + recorder +
  arbitration modules — into a real running process, per §2.4/§2.5.
- `guardian-helper` binary (privileged, per ADR-002 and §2.1): systemd
  unit, D-Bus service registration on
  `io.github.cliffthelin.GuardianHelper1`, one narrow, individually-
  authorized, typed Class A write method for evidence purposes — no
  generic command execution, no shell-out (§40's forbidden-shortcuts list
  applies in full).
- Real crash/restart/stop persistence behavior, tested against each real
  running service per §2.5/§5 (kill -9, systemctl restart, systemctl
  stop — not simulated), evidenced separately per process.
- `systemd-analyze security` hardening pass and its artifact, for both
  units separately.
- Real polkit-backed authorization denial test against the live
  `guardian-helper` service, called directly by an unprivileged test
  identity (P1-SEC-004) — this is the production-wiring counterpart to
  G1's already-tested authorization logic, not a new authorization
  design.

## Out of scope (do not implement here)

- Any real provider (systemd unit inspection, PSI, logind, UDisks,
  UPower, AccountsService) beyond what's needed to prove the daemon
  itself boots/runs/persists — all real providers are G8. Class B in §2.4
  is architecture only in G7; its evidence uses a minimal bounded stand-in
  the way G2's Model B evidence did, not a real provider integration.
- CLI, TUI, GUI, or the production indicator — all G9. `ksni` (G6's
  selection) is not wired into a real production indicator here; G7
  produces the daemon/helper pair a `ksni`-based client will eventually
  talk to, not the client itself.
- Packaging (`.deb`, install/uninstall/purge semantics) — G9.
- Any change to `guardian-core`'s (library) G0-G5 modules' own logic
  unless a genuine, narrowly-scoped integration bug is found while
  wiring them in — if so, document the bug and the minimal fix
  separately from the wiring work, and do not use "wiring" as cover for
  unrelated refactoring.
- Re-deciding the privilege topology. `ADR-002` (Model B) is accepted
  and tagged; G7 implements it — including this handoff's §2 resolution
  of how it maps to G4's transaction engine — it does not re-litigate it.
- Resolving, for every future provider, exactly how Class B's per-
  provider identity attribution works (§2.4) — that is a G8 concern for
  whichever real provider needs it first.
- Promoting `tests/vm/g6-daemon-evidence-stub` into either binary's
  skeleton (§2.8).
- Any incidental growth of `Guardian1` or `GuardianHelper1` beyond what
  the nine normative IDs require (§2.8).

# 7. Forward constraints from G4-G6 that apply here

Carried forward deliberately, not dragged in wholesale — only the ones
this gate can actually act on:

- **G5's FC-2 (`RecorderPolicy` runtime wiring)**: G5 built and tested
  `RecorderPolicy`/`recorder_policy_for()` as an isolated decision type,
  explicitly *not* wired into a real recorder+budget runtime path, with
  G5's own milestone naming the first gate that builds such a runtime
  path as the one responsible for ensuring the policy decision is
  actually consumed, not merely present. **G7 is that gate** for the
  daemon-level wiring — the recorder instance `guardian-daemon` runs must
  actually call `recorder_policy_for()` and act on its result, not just
  hold an unused `RecorderPolicy` type in scope. (The recorder is a
  Class C/monitoring concern and lives in `guardian-daemon`, not
  `guardian-helper`, per §2.4.)
- **G5's FC-1 (recorder byte boundedness)**: G5 proved a bounded
  *queue* (capacity-bounded), not a byte-size bound. If G7's real
  `guardian-daemon` wiring introduces long-running production capture
  with variable-size payloads, this gate must determine whether a
  byte-level bound is now required and make it explicit — do not
  silently assume G5 already proved this.
- **G4's FC-3 (Flight Recorder has no relationship to G4's persistence
  module)**: relevant if G7's `guardian-daemon` wiring brings the
  recorder and the Class B/C transaction persistence module into the same
  running process for the first time — check whether they need to
  interact (e.g., recorder evidence referencing a transaction ID) or must
  remain deliberately independent, and document the decision either way.
  `guardian-helper`'s Class A persistence has no recorder instance at all
  (the recorder is a `guardian-daemon`-side concern) — this constraint
  does not apply to `guardian-helper`.

**Explicitly not carried into G7** (considered and excluded, not
overlooked): G6's FC-G6-1 (simplicity-rule underspecification) concerns
future *candidate-selection* gates, not daemon wiring — not applicable
here. G6's FC-G6-2 (session-scoped production launch) concerns the
future *indicator client's* launch mechanism — that is G9's concern when
the production indicator is built on top of `ksni`, not G7's.

# 8. Fail-closed checklist

- A `guardian-helper` crash or forced kill must never leave a Class A
  transaction in a state that looks committed but wasn't, or
  applied-but-unrecorded — P1-DMN-005 must be evidenced against a real
  `kill -9` of `guardian-helper` with a real in-flight Class A
  transaction, not a graceful shutdown standing in for it, and not
  against `guardian-daemon` (which does not own Class A state).
- `guardian-helper` must reject an unauthorized write even if
  `guardian-daemon` is compromised or malicious — per `ADR-002`'s own
  stated invariant and §2.3's restatement. Verify this is actually true
  of the real wiring, not just asserted: confirm no code path in
  `guardian-daemon` constructs a call to `GuardianHelper1`'s mutation
  method, and confirm a direct call to `guardian-helper` (bypassing
  `guardian-daemon` entirely) is still correctly authorized or correctly
  rejected.
- `guardian-daemon` must never write to `guardian-helper`'s state
  directory, and `guardian-helper` must never read or trust anything
  `guardian-daemon` wrote as if it were caller identity or authorization
  evidence (§2.6).
- No component may call `sudo`, run as root wholesale, or expose a
  generic command-execution method — §40's forbidden-shortcuts list
  applies without exception. `guardian-daemon` does not run as `root`
  merely because it is systemd-managed (§2.1/§2.6 UID assignment).
- Provider-owned authorization (Class B) is never routed through
  `guardian-helper` merely because `guardian-helper` exists (§2.8).

# 9. TDD sequence

1. Record the naming decision (§2.1/§4) and the topology/operation-class
   decision (§2) in this gate's own evidence — a short note, not a new
   ADR, since both are mechanical derivations from `ADR-002` and G4's
   already-accepted engine shape, not contested design choices.
2. Build the minimal `guardian-helper` binary first (it is the smaller,
   more security-critical surface): real systemd unit (`User=root`,
   `CapabilityBoundingSet=` empty, per `ADR-002`), real D-Bus service
   registration on `GuardianHelper1`, one narrow typed Class A write
   method, wiring in the already-tested transaction engine +
   persistence run entirely in-process (§2.5), real polkit
   `CheckAuthorization` call (not simulated) immediately before Apply.
3. Build the minimal `guardian-daemon` binary: real systemd unit
   (unprivileged service account, per §2.1/§2.6), real D-Bus service
   registration on `Guardian1`, wiring in a separate transaction-engine
   instance for the Class B/C evidence path (§2.5) — this does **not**
   call `guardian-helper`'s mutation method; it exercises Class B's
   provider-delegated `Authorize`/`Apply` shape against a minimal bounded
   stand-in, the same evidentiary pattern G2's Model B used.
4. Write and run the P1-SEC-004 adversarial test: a genuinely different,
   unprivileged test identity calls `GuardianHelper1` directly and is
   correctly denied; separately, confirm `guardian-daemon` has no code
   path that could have relayed the original client's request instead
   (§2.3, §8).
5. Set up a real disposable Ubuntu 26.04.1 VM (matching G1/G2/G6
   precedent) and gather real evidence for P1-DMN-001..005 and
   P1-SEC-001..004 in that order, per §5's per-process distinctions.
6. Run `systemd-analyze security` against both real units separately;
   capture both artifacts.
7. Write the completion report per §12 below, then hand off to
   independent review.

# 10. Adversarial self-check before reporting done

- Does `guardian-helper` actually survive `systemctl restart` /
  `kill -9` with a non-terminal Class A transaction genuinely in flight,
  or was this only tested with an idle process? (Testing `guardian-daemon`
  instead of `guardian-helper` for this claim is itself a finding, not a
  substitute.)
- Does `guardian-daemon` ever call `GuardianHelper1`'s mutation method on
  a client's behalf, even conditionally or as a fallback? If yes, this
  reproduces the rejected relay and must be removed before reporting
  done.
- Does `guardian-helper` actually verify the caller's identity itself
  from its own inbound connection, or does it trust a claim forwarded by
  `guardian-daemon`?
- Does `guardian-daemon` read or depend on `guardian-helper`'s state
  directory contents anywhere, even for a read-only status feature?
  (§2.6 forbids this — use a typed accessor call instead, and only if a
  normative ID actually requires it.)
- Is `RecorderPolicy` actually consumed by `guardian-daemon`'s real
  recorder instance, or merely constructed and discarded (repeating G4's
  own audit-caught mistake of a precondition type existing in isolation
  without being wired into the real call path)?
- Does `systemd-analyze security`'s score reflect the units as they will
  actually ship, for BOTH units separately, or a looser development-only
  configuration for either?
- Did any G8/G9 material (a real provider, a CLI/TUI/GUI, packaging) get
  implemented under cover of "needed to test the daemon"?
- Was `tests/vm/g6-daemon-evidence-stub` copied, extended, or otherwise
  used as either binary's skeleton?
- Did `Guardian1` or `GuardianHelper1` grow any method/property/signal
  not required by one of the nine normative IDs?

# 11. Completion states

Report exactly one, honestly:

```text
G7 CANDIDATE — READY FOR INDEPENDENT AUDIT
G7 PARTIAL — REQUIRED EVIDENCE INCOMPLETE
G7 BLOCKED — GOVERNING CONTRACT INSUFFICIENT
```

# 12. Completion report

State plainly:

1. What was built (crate/binary names — must match §2.1/§4 exactly,
   systemd unit paths, both D-Bus service names).
2. Real evidence for each of the nine normative IDs, with VM
   setup/reproduction script, environment details, and provenance-
   labeled transcripts/artifacts — no ID may be marked PASS on unit-test
   evidence alone, and P1-DMN-002/004/005 must show which process
   (`guardian-daemon` or `guardian-helper`) each piece of evidence was
   gathered against, per §5.
3. Direct evidence that the direct-call invariant (§2.3) holds in the
   real running system — not just that it was intended.
4. Which G4/G5/G6 forward constraints (§7) were addressed and how.
5. Explicit confirmation that G8 providers, G9 clients/packaging, and
   the production indicator were not implemented here.
6. `cargo fmt --check` / `cargo clippy --workspace --all-targets
   --all-features -- -D warnings` / `cargo test --workspace` results,
   with the exact before/after passed count (189 passed, 0 failed is
   the pre-G7 baseline).
