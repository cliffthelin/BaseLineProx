# Guardian Phase 0 Implementation Handoff
## G2 — Privilege Topology Only

**Audience:** Primary coding agent  
**Scope:** **G2 — Privilege Topology** only  
**Stop condition:** a topology is selected with recorded evidence and an ADR, or the gate is honestly reported as blocked. Do **not** begin G3, providers, the transaction engine, clients, or packaging.  
**Governing contract:** `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §6.3, §24, §25, §36 (P0-PRIV-001..003), §38 (G2)  
**Prerequisite:** G1 tagged at `phase0-g1-identity-authorization` (commit `761bd4ae869c3e5d2168b8f9da47fbe797e89c62`). Confirm this tag exists and `HEAD` descends from it before starting.

---

# 1. Mission

Decide, with evidence rather than preference, how Guardian's privileged
boundary is actually structured — and stop there. This is not "make the
daemon root." It is a comparative architecture gate: build both candidate
prototypes far enough to measure them honestly, then select one (or report
that neither is safely decidable yet).

The desired result is a repository in which:

- both Model A and Model B prototypes exist, each far enough along to
  produce real measurements, not paper descriptions;
- a Privilege Requirement Inventory exists, classifying every known/planned
  Guardian capability by the privilege it actually needs;
- `systemd-analyze security` evidence exists for whichever prototype(s) run
  as a systemd service, captured from the real disposable VM, not asserted;
- Linux capabilities are justified individually, never granted because they
  "might be useful";
- the confused-deputy question for Model B is explicitly answered with
  evidence, not assumed away;
- `ADR-002-guardian-privilege-topology.md` records the decision, the
  rejected alternative, and the evidence for both;
- `P0-PRIV-001..003` are green, or the gate is reported blocked with the
  specific missing evidence named;
- no G3+ work, no real provider, no transaction engine, no client, and no
  generic privileged execution surface exists anywhere in the result.

Then stop.

---

# 2. Read before changing code

Read in this order:

1. `AGENTS.md`
2. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
   - §2 Governing principles (GP-01, GP-03, GP-04, GP-06, GP-10 especially)
   - §6 D-Bus contract (§6.4 no generic root command)
   - §7 Capability Registry contract
   - §8 Provider Arbitrator contract
   - §9 Transaction engine contract
   - §24 systemd service hardening
   - §25 Privilege topology decision gate
   - §36 P0-PRIV-001..003
   - §38 G2
3. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_CONTRACT_RESEARCH.md` §6 (privilege topology research), §17 (systemd resource control), §21 (fault-simulation stack)
4. `docs/guardian/20_Control_Plane/Privilege_and_Authorization.md`
5. `docs/guardian/20_Control_Plane/D-Bus_API_Contract.md`
6. `docs/guardian/20_Control_Plane/Transaction_Engine.md` (compatibility only — you are not implementing this)
7. `docs/guardian/10_Platform/systemd.md`, `docs/guardian/10_Platform/Polkit.md`, `docs/guardian/10_Platform/D-Bus.md`
8. `docs/guardian/90_Sources/wiki/ubuntu-systemd-service.md`, `ubuntu-systemd-exec.md`, `ubuntu-systemd-resource-control.md`, `ubuntu-polkit-resolute.md`, `ubuntu-dbus-daemon-resolute.md`
9. `docs/evidence/g1/G1_MILESTONE.md`, `docs/guardian/30_TDD/GUARDIAN_G1_IMPLEMENTATION_HANDOFF.md` §6–§8 (the authorization abstractions G2 must preserve)
10. `docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md` (for ADR house style)

Do not start G3 data models, the transaction engine, real providers, GUI/TUI/CLI, packaging, or recovery-target work in this batch.

---

# 3. Scope boundary

## In scope

- Two working prototypes, each capable of producing real measurements:
  - **Model A** — one Rust `guardian-daemon` process performing reads and
    typed writes, sandboxed via systemd, authorizing each write through
    real polkit (this already substantially exists from G0/G1 — extending
    it with a real systemd unit and hardening evidence is in scope).
  - **Model B** — an unprivileged Guardian core process plus a narrow,
    typed, D-Bus-activated privileged mechanism that performs only bounded
    writes, with the core never itself elevated.
- The Privilege Requirement Inventory (§10 below).
- systemd hardening evidence for both prototypes, captured for real in the
  disposable VM.
- Linux capability justification, per capability, per prototype.
- Confused-deputy analysis for Model B specifically.
- Transaction-compatibility analysis (who would own snapshot/authorize/
  apply/observe/rollback under each model) — analysis, not implementation.
- Failure-containment analysis across both models for the scenarios in §18
  of this handoff.
- `ADR-002-guardian-privilege-topology.md`.

## Out of scope for this batch

- Implementing the transaction engine (G4) — analyze compatibility only.
- Implementing the Capability Registry or Provider Arbitrator (G3) beyond
  whatever minimal typed shape is needed to host a bounded G2 test write.
- Any real provider (systemd unit management, UDisks, PSI, etc.) beyond a
  single harmless bounded test write per prototype, matching G1's `guardian.test.*`
  pattern.
- GUI/TUI/CLI clients, packaging, recovery-target integration.
- Choosing packaging/install mechanics beyond what's needed to host the
  prototypes in the VM.
- Any change to G0's public D-Bus surface (`ContractVersion`, `ServiceState`)
  or G1's `AuthorizationOutcome`/`AuthorizationError` types beyond what §15
  below requires for Model B's helper boundary.

A later-gate feature that looks easy is still out of scope (AGENTS.md,
"Gate discipline").

---

# 4. Normative tests

From TDD contract §36:

### P0-PRIV-001 — Model A measurement
Hardened privileged-daemon prototype has documented required privileges and
security review.

### P0-PRIV-002 — Model B measurement
Split-privilege prototype has documented required privileges and security
review.

### P0-PRIV-003 — decision record
One topology is selected with a written comparison — or the gate is reported
blocked with the evidence still missing named explicitly (§22 below).

These are evidence/documentation tests, not unit tests in the P0-AUTH sense.
"Documented" means: captured from a real disposable VM run, not modeled or
asserted. A `systemd-analyze security` score that was never actually run is
not evidence.

---

# 5. Privilege Requirement Inventory (build this first)

Before writing either prototype's hardening manifest, classify every known
or planned Guardian capability area. For each, state one of:

```text
no privilege
provider-owned authorization — Guardian calls another already-authoritative
    privileged service that performs its own authorization (e.g. UDisks'
    PowerOff() does its own polkit check internally); Guardian itself needs
    no elevated privilege for this area beyond being an ordinary D-Bus client
Guardian polkit authorization — Guardian's own method is polkit-gated, but the
    underlying action requires no further OS-level privilege once authorized
specific device/file access
specific Linux capability
root/system privilege
unknown — requires host research
```

The `provider-owned authorization` category matters and is not
interchangeable with `Guardian polkit authorization`: many "system-management"
capability areas may turn out to need *zero* privilege from Guardian at
all, because the authoritative provider already gates the write itself.
Conflating the two categories would understate how many areas can avoid
elevating Guardian's own process, in either model. Check each provider's
actual D-Bus interface for its own authorization annotations/behavior
before defaulting to `Guardian polkit authorization`.

Cover at minimum, from TDD contract §26 and the broader capability areas
named in the governing research:

```text
systemd/service management        (start/stop/restart units, read unit state)
cgroups                            (resource limits, transient scopes)
PSI                                 (read /proc/pressure/*)
UDisks                              (drive/block topology, eventual PowerOff())
BPF/eBPF                            (deferred — mark unknown if untested)
thermald                            (read policy; write deferred)
power-profiles-daemon               (read active profile; HoldProfile eventual)
UPower                              (read battery/UPS/power devices)
NVML/NVIDIA                         (deferred — mark unknown if untested)
fwupd                               (deferred — mark unknown if untested)
NetworkManager                      (deferred — mark unknown if untested)
journald                            (read; rotation/capacity policy eventual)
AccountsService                     (read session list; SetSession eventual)
apt/package state                   (deferred — mark unknown if untested)
hardware control (generic)          (mark unknown; no blanket device access)
I/O Guardian (storage power-off)    (deferred; UDisks-mediated)
USB Security / usbguard             (deferred — mark unknown if untested)
```

Mark unknowns honestly rather than guessing. An honest "unknown — requires
host research" is acceptable evidence for this gate; a fabricated
classification is not (AGENTS.md, "No placeholders").

This inventory is the primary input to both models' capability-bounding
sections below — do not skip it to save time.

---

# 6. Model A — hardened privileged daemon

```text
clients
  │
  ▼
system D-Bus
  │
  ▼
guardian-daemon
(runs with elevated/system privileges)
  │
  ▼
providers/kernel/system services
```

Build/extend a real systemd service unit for `guardian-daemon` in the
disposable VM. Evaluate, with real evidence:

- What privilege does it *actually* need for the bounded G2 test write
  (reuse a `guardian.test.*`-style action, same pattern as G1)? Do not
  assume unrestricted root — start from `CapabilityBoundingSet=` empty and
  add capabilities only when a real failure proves one is needed.
- Whether Linux capabilities can replace full root for the inventoried
  capability areas from §5. `CAP_SYS_ADMIN` is not "minimal privilege" —
  treat it as functionally equivalent to root and require explicit,
  itemized justification if proposed at all.
- systemd sandbox/hardening compatibility (§11 below) — every directive
  from TDD contract §24, tested for real, not asserted.
- Blast radius: what can a compromised `guardian-daemon` process do, given
  the capability set actually configured?
- D-Bus/public-surface risk: does the daemon's public method surface stay
  exactly as typed/bounded as G0/G1 established?
- Provider access: does this model let each provider adapter (future work)
  reach its target without broadening the daemon's own privilege further
  than the inventory in §5 justifies?
- Transaction/rollback implications (§17 below).
- Operational simplicity and recovery behavior (§18 below).
- Observability: can an operator/reviewer tell, from logs/journal/D-Bus
  introspection alone, what the daemon is doing and why a request was
  denied — or does diagnosing a problem require attaching a debugger?
- Testability: how much of this model's behavior can Layer 1 (private-bus,
  mocked) tests actually exercise versus requiring the VM every time?
- Future extension cost: when a later gate needs a new privileged
  operation, does adding it to this model require touching hardening/
  capability configuration again, or does the existing boundary already
  accommodate it?

## Model A required real evidence

- Real systemd unit file, run in the disposable VM.
- Real `systemd-analyze security guardian-daemon.service` output, captured
  raw.
- Real capability set tested (not merely declared) — prove the daemon
  actually works with the proposed `CapabilityBoundingSet=`/`AmbientCapabilities=`,
  not just that it starts.

---

# 7. Model B — unprivileged core + narrow privileged mechanism

```text
clients
  │
  ▼
Guardian control/core
(unprivileged)
  │
  ▼
typed narrow privileged boundary
  │
  ▼
privileged helper/mechanism
  │
  ▼
providers/kernel/system services
```

Build a real second systemd-activatable unit (the helper) plus the
unprivileged core, in the disposable VM. Evaluate, with real evidence:

- The exact helper D-Bus surface: a fixed, small set of typed methods
  mirroring the same bounded pattern as G0/G1's `guardian.test.*` actions —
  never a generic argv/command passthrough (§9 below is explicit about
  this).
- Whether the helper independently verifies caller authorization via real
  polkit (it must — see §14/§15 below), or trusts a claim forwarded by the
  core.
- Privilege minimization: what is the helper's actual capability set,
  measured the same way as Model A's in §6?
- Helper compromise blast radius, compared directly against Model A's daemon
  blast radius for the same inventoried capabilities.
- Helper lifecycle: on-demand D-Bus activation vs. always-running — test
  both if genuinely undecided, or justify one.
- Transaction coordination, rollback ownership, state synchronization,
  crash consistency (§17/§18 below) — this is the area most likely to make
  Model B harder than it looks; do not hand-wave it.
- Packaging/install complexity relative to Model A.
- systemd ordering/recovery: what happens if the helper is activated but
  the core has crashed, or vice versa?
- Auditability: can a transaction/incident record unambiguously attribute
  an action to a real caller through both hops?
- Observability: can an operator/reviewer distinguish "core denied it,"
  "helper denied it," and "helper was unreachable" from logs alone, or does
  the two-process split obscure which component made which decision?
- Testability: how much of the confused-deputy and authorization-boundary
  behavior can Layer 1 mocked tests actually cover versus requiring the VM?
- Future extension cost: does adding a new privileged operation later mean
  extending the helper's typed surface (bounded, reviewable) or does it
  pressure the design toward a broader/more generic method to avoid
  repeating the helper's setup cost?

## Model B required real evidence

- Real second systemd unit (or D-Bus-activation service file) for the
  helper, run in the disposable VM.
- Real `systemd-analyze security` output for the helper unit.
- Real proof the helper performs its own `CheckAuthorization` against real
  polkit using the real caller identity — not a value forwarded by the core
  (§14/§15, and adversarial questions 1–2 in the review handoff's
  "Adversarial question audit" section).
- Real capability set tested for the helper, same rigor as Model A.

## Explicitly forbidden in Model B (and Model A)

```text
RunCommand(string)
RunShell(string)
Execute(argv)
generic root RPC
```

or any semantic equivalent. A different method name does not exempt a
design from this rule — the following are exactly as forbidden as
`RunCommand`, because each still lets the caller drive unbounded privileged
behavior through its arguments rather than through a fixed, individually
authorized operation:

```text
WriteFile(path, bytes)
SetSysfs(path, value)
CallDbus(service, path, method, args)
ExecuteProvider(name, opaque_payload)
Invoke(action_name, arbitrary_json)
```

Every helper method must be individually typed (fixed operation, fixed
argument shape — no path/payload/argv parameter that lets the caller choose
*what* gets touched or *what* gets run) and individually authorized (its
own polkit action id, not a shared "perform this generic operation" grant).
When reviewing a candidate helper method, ask: does this method's argument
shape let a caller reach anywhere in the filesystem, device tree, or D-Bus
namespace it wants, merely by varying an argument? If yes, it is a generic
broker regardless of its name.

---

# 8. Confused-deputy analysis (Model B — mandatory)

G1 established that Guardian authorizes the real D-Bus caller, never a
client-supplied claim. If Model B exists, this invariant must survive the
extra hop:

- Does the helper trust the core's assertion of who the caller is? If so,
  this is a confused-deputy vulnerability — a compromised or buggy core
  could authorize itself as any caller.
- Does the helper instead independently resolve the real caller identity
  (its own `resolve_caller_identity` call against its own inbound
  connection) and perform its own `CheckAuthorization`? This is the
  required design unless a stronger alternative is proven equivalent with
  evidence (e.g., a cryptographically bound capability token minted by a
  process itself already fully re-verified per-call — do not invent this
  without evidence it is actually necessary and actually safe).
- Is there a TOCTOU window between the core's decision and the helper's
  apply — e.g., could the caller's authorization be revoked or the caller
  disconnect between the two hops in a way that leaves the helper acting on
  stale authority? Concretely: if the helper independently re-resolves and
  re-authorizes per G1's identity-lifetime rule (§8 above), this window
  should already be closed by construction — confirm that in the analysis
  rather than asserting it.
- What happens on a duplicate or retried request — e.g. the core times out
  waiting for the helper's acknowledgment and retries, but the helper's
  first apply actually succeeded? Does the design risk a double-apply, and
  is that risk assessed even though full idempotency-key handling is G4's
  job (TDD contract §9.3), not G2's to implement?
- Is authorization, once obtained at one hop, still verifiably valid at the
  moment the other hop actually mutates state — or could it be presented
  as valid there without ever having been independently checked at that
  specific hop?
- Never forward `uid`, `username`, or `authorized=true` from the
  unprivileged core to the helper and trust it. This is the exact
  client-supplied-identity problem G1 solved at the client/daemon boundary;
  Model B reintroduces it one hop later unless explicitly re-solved.

Report this analysis explicitly in the ADR, with a clear statement of
whether Model B closes this risk and how.

---

# 9. Authorization outcome semantics must survive the topology

G1 established a hard separation:

```text
AuthorizationOutcome   — a real decision (Authorized / Denied / Unavailable)
AuthorizationError     — a failure to obtain a decision at all (ProviderUnavailable / Internal)
```

G2 must not collapse these, and must not introduce a third category that
conflates them. If Model B's helper is unreachable (crashed, not yet
activated, D-Bus activation failed), that is a **new** kind of failure —
"helper unavailable" — and must have its own deterministic typed semantics,
analogous to `AuthorizationError::ProviderUnavailable`, not silently reused
as `AuthenticationUnavailable` or `NotAuthorized`. Decide and document the
exact mapping if Model B is pursued far enough to need one; this is
consistent with, not identical to, the G1 mapping.

---

# 10. Single-writer rule and write ownership

Guardian's architecture requires a single authoritative writer per mutable
capability (TDD contract §8, Provider Arbitrator). For G2's purposes,
answer — without implementing G4 — for each model:

- Does the daemon/core own transaction state, or does the helper?
- Does a helper apply writes but never decide policy (the helper should be
  a mechanism, not a policy-maker — TDD contract's orchestration principle,
  GP-01)?
- Who performs rollback?
- Who owns locks preventing two writers from touching the same capability
  concurrently?
- What happens if the helper crashes after `Apply` but before acknowledging
  the core?
- What happens if the core dies while the helper is mid-mutation?
- After a restart of either component (systemd `Restart=` firing, a manual
  restart, or a crash-and-recover cycle), do both the core and the helper
  believe they hold write authority for the same capability simultaneously
  — a distinct question from "does a restart spawn two writer processes,"
  since a single surviving process pair can still both believe they are
  the authoritative writer if that state isn't reset/re-derived on restart.

---

# 11. systemd hardening comparison

For both candidates, evaluate every directive from TDD contract §24 against
Guardian's actual required accesses — do not blindly enable everything:

```text
NoNewPrivileges=
CapabilityBoundingSet=
AmbientCapabilities=
PrivateTmp=
PrivateDevices=
ProtectSystem=
ProtectHome=
ProtectKernelTunables=
ProtectKernelModules=
ProtectKernelLogs=
ProtectControlGroups=
RestrictAddressFamilies=
RestrictNamespaces=
RestrictRealtime=
RestrictSUIDSGID=
LockPersonality=
MemoryDenyWriteExecute=
SystemCallFilter=
DevicePolicy=
DeviceAllow=
ReadWritePaths=
ReadOnlyPaths=
```

For each directive actually tested, record:

```text
hardening directive → security value → Guardian capability affected → compatible / incompatible / requires exception
```

Every intentionally omitted or weakened protection needs a documented
reason (TDD contract §24, restated). Run `systemd-analyze security` on each
real unit as comparative evidence — not as an absolute score. Explain what
caused the score, which findings actually matter for Guardian's real
capability needs (per §5's inventory), which cannot be improved because of
a legitimate requirement, and which exceptions are temporary (will be
revisited) versus architectural (permanent, justified).

---

# 12. Linux capabilities

Investigate whether narrow capabilities can replace broader privilege for
the inventoried areas in §5. Do not grant a capability merely because it
looks useful. Candidates worth investigating (not a preapproved list):

```text
CAP_SYS_ADMIN       — treat as functionally equivalent to root; requires
                       exceptional, itemized justification if proposed at all
CAP_SYS_RESOURCE
CAP_SYS_NICE
CAP_NET_ADMIN
CAP_DAC_READ_SEARCH
CAP_DAC_OVERRIDE
CAP_SYS_PTRACE
```

Every proposed capability, for either model, needs: which inventoried
capability area requires it, why a narrower alternative doesn't suffice,
and what a compromised process with only that capability could still do.

## Privilege creep is an architectural signal, not just a per-item cost

Justifying each capability, hardening exception, or `ReadWritePaths=`
addition individually is necessary but not sufficient. Before writing the
ADR's decision, review the *accumulated* set of exceptions for whichever
model is trending toward selection: if the individually-justified
exceptions, taken together, add up to something functionally close to
unrestricted access, that is itself a finding against the model — it means
the granular-justification process was satisfied while the actual
minimization goal was not. Watch specifically for a pattern like:

```text
need one privileged operation      → grant/root justified for it
need another filesystem path       → ProtectSystem= weakened
need one more device                → PrivateDevices= disabled
need one more subsystem             → a broad capability added
tests now pass                      → architecture declared complete
```

Each step above might individually satisfy this handoff's per-item
justification requirement while the cumulative result is not meaningfully
different from the daemon simply running unrestricted. If this pattern
appears in the evidence for either model, say so explicitly in the ADR
rather than letting the per-item justifications stand in for an honest
cumulative assessment.

---

# 13. Transaction compatibility (analysis only — do not implement G4)

For each model, answer, with architectural reasoning grounded in the actual
prototype built:

```text
who owns snapshot
who owns authorization
who applies
who observes
who decides rollback
how crash recovery works
```

The privilege topology must not make G4's `Snapshot → Validate → Authorize
→ Apply → Observe → Confirm → Commit/Rollback` sequence unsafe or
impossible later. If a model cannot plausibly support this sequence safely,
that is a real strike against it, not a detail to defer.

---

# 14. Failure containment

Compare both models across:

```text
core crashes
privileged process crashes
helper crashes
D-Bus disconnects
provider hangs
provider returns unknown result
polkit unavailable
systemd restarts component
machine reboots mid-operation
```

For each, state the likely safety consequence per model. Prefer designs
that fail closed (TDD contract GP-06) and make recovery observable rather
than silent. Where a scenario cannot be tested without real system risk on
the disposable VM (e.g. actual reboot mid-operation), reason from systemd's
documented restart/ordering semantics and say explicitly that it was
reasoned about rather than executed, rather than fabricating a test result.

---

# 15. Test architecture — Layer 1

Suitable for, and REQUIRED to cover, without a real bus, root, or VM:

- privilege-boundary API shape (the helper's typed method signatures, if
  Model B is built far enough to have one);
- the typed request/response contract for any helper method;
- proof that no generic execution method exists in the shape (structural,
  same style as G1's `AuthorizationRequest` having no client-claimable
  field);
- error propagation for a mocked helper failure (helper-unavailable,
  helper-returned-malformed-response) — analogous to G1's
  `AuthorizationError` tests;
- confused-deputy tests: construct a request where the "core" claims an
  identity the "helper" did not itself resolve, and prove the helper's own
  authorization check — not the claim — determines the outcome (mirrors
  G1's `p0_auth_001_caller_identity_cannot_be_spoofed` pattern, one hop
  further out);
- authorization-decision plumbing reused/extended from G1 where applicable;
- crash-state model tests (e.g., a state machine that models "helper
  acknowledged Apply but core has not observed" and proves recovery logic
  reaches a safe terminal state) — model-level, not a full G4
  implementation.

## Test architecture — Layer 2 (disposable Ubuntu 26.04.1 VM)

Required, not optional, for:

- real systemd units for whichever prototype(s) are built;
- real service user/group;
- real capabilities (`CapabilityBoundingSet=`/`AmbientCapabilities=` tested,
  not just declared);
- real sandbox/hardening directives from §11, tested individually where
  feasible;
- `systemd-analyze security`, captured raw;
- real system D-Bus activation (for Model B's helper, if built);
- real polkit boundary check at the helper (Model B);
- helper/daemon process ownership and restart behavior, observed for real;
- file/device access experiments proving the configured hardening actually
  permits/denies what §5's inventory expects.

No topology may be declared accepted based only on mocked privilege
behavior. If VM access is unavailable when this handoff is picked up,
complete the Layer 1 analysis and design work, then report exactly which
Layer 2 evidence remains missing — do not report G2 candidate/decided
status on Layer 1 alone (same discipline as the G1 handoff §5).

---

# 16. Primary workstation safety

Real privilege-topology experiments belong in a disposable Ubuntu 26.04.1
VM only. Do not modify the primary development workstation's systemd
units, polkit policy, capabilities, users/groups, or service ownership to
produce G2 evidence — this rule carried over unchanged from the G1 handoff
§13 and AGENTS.md, and applies with extra force here because G2
experimentation involves real privilege escalation mechanics.

---

# 17. G2 public-surface protection

G0's production public D-Bus contract remains exactly `ContractVersion` and
`ServiceState`. G2 must not expand it casually. If topology testing
genuinely requires additional IPC (e.g. a bounded test write to measure
Model A/B), prefer a clearly test-scoped interface (matching G1's
`AuthProbe1` precedent — test-file-only or non-workspace-member VM harness
code, never `guardian-daemon`'s production `src/`) until the architecture
itself is accepted. Any *permanent* helper API proposed as part of the
Model B design must be presented in the ADR with its own exact typed
contract and an explicit statement that it still requires its own future
security review before shipping — G2 selecting Model B does not itself
authorize implementing that permanent API.

---

# 18. The decision artifact

Write `docs/adr/ADR-002-guardian-privilege-topology.md`, following
`docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md`'s house style
(Context / Decision / Alternatives considered / Evidence and tests /
Consequences / Rollback and migration), expanded to include:

```text
Context
Decision drivers
Model A (description, evidence, measurements)
Model B (description, evidence, measurements)
Security comparison (least privilege, attack surface, confused-deputy risk,
    sandboxability — named per model, not left implicit)
Operational comparison (provider compatibility, recovery behavior,
    observability, testability, packaging complexity, future extension
    cost — named per model, not left implicit)
Capability requirements (the §5 inventory, referenced or embedded)
systemd hardening evidence (§11 table)
D-Bus/polkit implications (§8/§9 findings)
Transaction compatibility (§13 findings)
Failure containment (§14 findings)
VM evidence (pointers to captured artifacts under docs/evidence/g2/)
Rejected alternatives
Decision
Consequences
Deferred risks
```

The decision must be evidence-based. Do not force a topology selection
merely to advance the roadmap — §22 below is the legitimate alternative.

---

# 19. Evidence

Create G2 evidence under `docs/evidence/g2/`, mirroring the G1 evidence
structure (`G2_LAYER1_EVIDENCE.md`, `G2_LAYER2_EVIDENCE.md`, a VM setup
script, raw transcripts/`systemd-analyze security` output). Preserve enough
evidence for an independent reviewer to distinguish real host measurement
from analysis/reasoning, and to distinguish a genuinely tested hardening
directive from one merely declared in a unit file. Never fabricate host
evidence. Clearly mark any untested item as untested.

---

# 20. Completion statuses

Return exactly one:

```text
G2 CANDIDATE — TOPOLOGY SELECTED, READY FOR INDEPENDENT AUDIT
G2 PARTIAL — HOST EVIDENCE INCOMPLETE
G2 BLOCKED — NO SAFE TOPOLOGY YET
G2 BLOCKED — CONTRACT CONFLICT
```

`G2 BLOCKED — NO SAFE TOPOLOGY YET` is a legitimate, acceptable outcome if
the evidence does not support a safe decision — do not manufacture a
"winner" to avoid reporting it.

---

# 21. Completion report

Follow the AGENTS.md "Completion report" structure, plus:

- the full §5 Privilege Requirement Inventory as captured;
- the §11 hardening-directive table for each model actually tested;
- explicit P0-PRIV-001..003 pass/not-yet-proven table;
- which evidence was captured on this workstation (Layer 1) vs. in the
  disposable VM (Layer 2);
- if any Layer 2 evidence could not be captured, say so plainly rather than
  reporting G2 candidate/decided status;
- confirmation that no G3+ work, no real provider beyond a bounded test
  write, and no generic privileged execution surface exists in the result.

Do not tag a G2 milestone yourself. Stop and hand off for independent
review per `docs/guardian/30_TDD/GUARDIAN_G2_INDEPENDENT_REVIEW_HANDOFF.md`.
