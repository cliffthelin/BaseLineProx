# Guardian Phase 1 Implementation Handoff
## G8 — Initial Providers Only

# 1. The central planning finding — read this before anything else

**G8's actual normative contract, mechanically re-derived from the
governing TDD contract's own text (not assumed from prior planning
conversation), requires zero real privileged provider writes.**

§26 is titled *"Initial **read-only** providers for Phase 1"* — the
section header says it directly. Every one of the six required providers
is scoped explicitly to reads/observation in that section's own text:

```text
1. systemd provider   — list/inspect selected units; unit state; startup/
                         failure metadata; "no production write required
                         yet."
2. PSI provider        — CPU/memory/I/O pressure; threshold event source
                         (inherently read-only telemetry).
3. logind provider      — list current inhibitors / "System Blockers"
                         (read-only).
4. UDisks provider      — drive/block topology; read CanPowerOff; read
                         sibling identity; "production PowerOff() deferred
                         until I/O Guardian phase."
5. UPower provider      — display device; battery/UPS enumeration where
                         available (inherently read-only).
6. AccountsService provider — enumerate availability; discover user/
                         session context; "production session write
                         deferred until system-management phase."

Optional if cheap: power-profiles-daemon read-only ownership state.
```

§27 (UDisks invariants) and §28 (Session-provider invariants) go further
and are explicit: for `PowerOff()`, *"tests MUST already exist proving"*
six specific safety preconditions, but *"the production write
implementation may remain deferred"*; for session writes, Guardian must
enumerate/validate sessions and prefer `SetSession()`, but *"the actual
session write remains deferred from Phase 1."*

Mechanically re-deriving the normative test list (§37) independently
confirms this: **all nineteen G8 IDs are read, parse, enumerate, detect,
or reject-before-write in nature** — see §3's matrix. Not one of them
asserts a successful mutation, a rollback, or a crash-during-Apply
scenario. This is the single fact every other section of this handoff is
built around, and it is why most of G7's newly-binding forward
constraints (single-writer-across-real-write-paths, `SafeToResume`
eligibility, per-write transaction ownership) are **not yet triggered by
G8** — they apply the moment a real write exists, and G8 does not
introduce one. This handoff still does the required *planning* work for
the two writes G8's own contract text explicitly anticipates
(`PowerOff()`, session `SetSession()`), because §27/§28 require the
validation/rejection *logic and tests* to exist now — it does not
implement either write.

# 2. Mission

Build G8's six real, read-only provider adapters against `guardian-daemon`
(the unprivileged process — see §5's Class C framing), proving the
`Provider` trait shape (`guardian_provider_api::provider::Provider`,
already accepted at G3) against real Linux subsystems for the first time,
and populate the Capability Registry with real (not fixture) data.
Additionally, build and test — but do not wire to a real mutation — the
validation/rejection logic §27/§28 require for the two explicitly-deferred
future writes.

# 3. Normative IDs — exact, mechanically re-derived matrix

| ID | Exact requirement (verbatim, §37) | Provider/domain | Pure test (Layer 1)? | Private bus/mock (Layer 2/3)? | Real VM (Layer 4)? |
|---|---|---|---|---|---|
| P1-SYS-001 | Systemd provider can inspect an allowed unit through its provider interface | systemd | Yes — parsing/adapter logic | Yes — `dbusmock` systemd1 template | Yes — real unit read |
| P1-SYS-002 | Missing unit returns typed unavailable/not-found behavior | systemd | Yes | Yes | Yes — real absent-unit case |
| P1-SYS-003 | GUI/TUI/CLI test confirms clients do not execute systemctl directly | systemd (client boundary) | Yes — source/binary audit | N/A | N/A — no G9 clients exist yet; see §16 |
| P1-PSI-001 | CPU PSI parses valid data | PSI | Yes | N/A (no D-Bus; kernel interface) | Yes — real `/proc/pressure/cpu` |
| P1-PSI-002 | Memory PSI parses `some`/`full` | PSI | Yes | N/A | Yes — real `/proc/pressure/memory` |
| P1-PSI-003 | I/O PSI parses `some`/`full` | PSI | Yes | N/A | Yes — real `/proc/pressure/io` |
| P1-PSI-004 | VM PSI trigger path produces an event without busy polling | PSI | Yes — event-source logic | N/A | Yes — real poll/epoll-driven trigger |
| P1-PSI-005 | Missing PSI produces explicit unsupported/unavailable state | PSI | Yes | N/A | Yes — real kernel without PSI compiled in, or real permission-denied case |
| P1-LGI-001 | Inhibitors normalize into Guardian blocker records | logind | Yes | Yes — `dbusmock` login1 template | Yes — real inhibitor via `systemd-inhibit` |
| P1-LGI-002 | Empty result is healthy, not provider error | logind | Yes | Yes | Yes — real no-inhibitor case |
| P1-UDS-001 | Drive/block relationships are preserved | UDisks | Yes | Yes — `dbusmock` udisks2 template | Yes — real topology |
| P1-UDS-002 | Shared physical parent/sibling information is visible | UDisks | Yes | Yes | Yes — real multi-partition device |
| P1-UDS-003 | Changing `/dev` name does not make Guardian treat the same hardware identity as automatically unrelated | UDisks | Yes | Yes | Yes (Layer 3 `umockdev` re-enumeration is the primary proof; VM confirms end to end) |
| P1-UDS-004 | Removal produces an event and invalidates stale resource references | UDisks | Yes | Yes | Yes — real/`umockdev` removal |
| P1-UPW-001 | Display device is read when present | UPower | Yes | Yes — `dbusmock` upower template | Yes — real display device |
| P1-UPW-002 | Desktop without battery remains healthy with "not present" | UPower | Yes | Yes | Yes — real batteryless VM |
| P1-ACC-001 | AccountsService is discovered | AccountsService | Yes | Yes — `dbusmock` accounts template | Yes — real discovery |
| P1-ACC-002 | Valid graphical sessions are enumerated through the selected session-discovery adapter | AccountsService | Yes | Yes | Yes — real session enumeration |
| P1-ACC-003 | Invalid session identifier fails validation before any write | AccountsService | Yes — validation logic, no write exists to precede | Yes | Yes — real invalid-ID rejection |

Nineteen IDs total. `P1-SYS-*` (3), `P1-PSI-*` (5), `P1-LGI-*` (2),
`P1-UDS-*` (4), `P1-UPW-*` (2), `P1-ACC-*` (3). No ID in this list asserts
a mutation.

# 4. Provider set — mechanically confirmed, deliberately minimal

Exactly the six providers §26 names, in the priority order that section
lists them. `power-profiles-daemon` read-only ownership state is
explicitly optional (*"if cheap"*) — **deferred by default**; it maps to
no normative ID, and per §26's own closing line (*"No additional provider
is required for Phase 1 completion"*), adding it is not required to
satisfy this gate. If a later gate's planning finds a concrete need, it
can be added then with its own justification.

**Explicitly excluded, confirmed against the contract, not merely
assumed**: NetworkManager, thermald, GPU/NVML, fwupd, package management,
usbguard, and any other attractive capability — none appear in §26's
required list, none map to a §37 P1-* ID, and several (thermald, fwupd)
are among G2's own explicitly `Unknown`-privilege areas (§6 below)
that must not be touched without host research this gate does not
perform.

# 5. Component roles (unchanged from G7 — restated for this gate's context)

```text
guardian-core (library)  = provider adapter implementations live here,
                            alongside the already-accepted Capability
                            Registry (`arbitration.rs`) and provider-api
                            traits (`guardian-provider-api`). Never a
                            process.
guardian-daemon (process) = owns every G8 provider adapter and the
                            Capability Registry population — this is
                            Class C (no-privilege / read-only / monitoring)
                            work per the G7 handoff's own classification,
                            and it stays there. No G8 provider read
                            requires guardian-helper.
guardian-helper (process) = untouched by G8. No G8 normative ID requires
                            a privileged mutation, so no G8 work adds a
                            method to GuardianHelper1 or introduces a
                            second Class A capability.
```

# 6. Provider-by-provider contracts

For each: what is read, what is *planned but not implemented* (where
applicable), the interface layer used (all six use the top of the
accepted hierarchy — native D-Bus, or the kernel interface for PSI — no
justification for a lower layer is needed because none is used), and the
G2 privilege classification each already carries.

## 6.1 systemd

```text
Capability IDs:        systemd.unit.<unit-name> (one CapabilityRecord per
                        allowed/inspected unit — allowlist, not "any unit
                        string a caller supplies").
Read operations:        unit state (ActiveState/SubState), startup/
                        failure metadata (via org.freedesktop.systemd1
                        Manager/Unit interfaces).
Write operations:       None in G8. §26 states this explicitly ("no
                        production write required yet").
Authoritative backend:  systemd1 itself (native D-Bus,
                        org.freedesktop.systemd1).
Authorization mode:     N/A this gate (no write). If a future gate adds a
                        typed StartUnit/StopUnit-class capability, it is
                        provider-owned authorization per G2's existing
                        inventory (systemd performs its own polkit check
                        on job methods) — not routed through
                        guardian-helper.
Privilege requirement:  NoDirectPrivilege for the reads this gate
                        implements (unit inspection needs no elevated
                        caller privilege on a correctly-policed bus).
Transaction owner:      N/A — Class C, no transaction engine involved.
Rollback capability:    N/A this gate.
Observation method:     N/A this gate (reads are not observed/confirmed,
                        they are simply read).
Failure mapping:        missing unit -> Unsupported (capability does not
                        exist for that unit, not a provider outage);
                        systemd1 absent entirely -> ProviderUnavailable.
Availability detection: real probe against org.freedesktop.systemd1's
                        presence on the system bus.
Single-writer implications: none this gate — no write path exists.
SafeToResume eligibility:   N/A — no Apply exists to classify.
Real-system evidence required: real unit read, real missing-unit case
                        (P1-SYS-001/002); P1-SYS-003 is a client-boundary
                        audit (source/binary inspection that no G8 or
                        future client shells out to `systemctl`), not a
                        provider-behavior test — deferred in practice
                        until G9 clients exist to audit, noted honestly
                        rather than fabricated now (see §16).

Adversarial self-check for "a typed StartUnit for one explicitly modeled
unit is not permission to expose generic execution": not applicable this
gate — no StartUnit-class capability is built at all in G8. This note is
carried forward for whichever future gate adds one.
```

## 6.2 PSI

**Normative for this gate (repair of the planning review's non-blocking
finding #2):** `crates/guardian-core/src/psi.rs` is the accepted G5 PSI
implementation (`parse_resource`, `read_resource`, `classify`,
`PressureSeverity`, `ThresholdMonitor`/`ThresholdEvent`, and the existing
threshold semantics). G8 **MUST reuse it and MUST NOT fork, duplicate, or
rewrite** any of it. G8's PSI work is *only*: (a) production wiring of
this already-accepted logic to the real `/proc/pressure/*` path in place
of the injected-fixture inputs G5's own tests used, and (b) whatever
runtime/provider-adapter integration (event-source plumbing, `Provider`
trait implementation, `CapabilityRecord` population) the nineteen G8
normative IDs actually require. If implementation discovers a genuine
defect in the accepted G5 PSI logic while wiring it, **stop and report it
as a prior-gate regression** — following exactly this project's own
established discipline (e.g. how G7 treated `guardian-core`'s G0-G5
modules) — rather than silently changing G5 behavior from inside G8.

```text
Capability IDs:         psi.cpu, psi.memory, psi.io.
Read operations:         parse /proc/pressure/{cpu,memory,io}; expose as
                        an event source for threshold crossings (feeds
                        G5's already-accepted PressureSeverity model —
                        this gate is the first to source it from a real
                        kernel read instead of an injected fixture; see
                        §14).
Write operations:        None — PSI has no write concept at all, ever.
Authoritative backend:   the kernel itself, via /proc/pressure/* — the
                        top of the interface hierarchy for this domain by
                        construction; no D-Bus API exists to prefer over
                        it.
Authorization mode:      N/A — pure read of a world-readable (on a
                        correctly configured system) kernel interface.
Privilege requirement:   NoDirectPrivilege.
Transaction owner:       N/A.
Rollback capability:     N/A.
Observation method:      N/A (telemetry, not a mutation to observe).
Failure mapping:         file absent / kernel PSI not compiled in ->
                        Unsupported (P1-PSI-005); permission denied (rare,
                        but distinct) -> ProviderUnavailable, not
                        Unsupported — the capability may exist but be
                        unreachable, a different fact.
Availability detection:  real file-existence + read-permission probe.
Single-writer implications: none — no write path.
SafeToResume eligibility:    N/A.
Real-system evidence required: real parse of all three real files;
                        P1-PSI-004's "without busy polling" requirement
                        needs a real poll/epoll-based (or
                        pressure-file-notification, i.e. `poll()` on the
                        PSI fd, which the kernel natively supports)
                        event source proven in a real VM — a busy-loop
                        implementation would technically pass parsing
                        tests but fails this specific normative
                        requirement; call this out explicitly in
                        implementation review.
```

## 6.3 logind ("System Blockers")

```text
Capability IDs:         logind.inhibitors.
Read operations:         list current inhibitors via
                        org.freedesktop.login1 Manager.ListInhibitors;
                        normalize into {what, who, why, mode, uid, pid}
                        per contract §29.
Write operations:        Explicitly out of scope this gate. §5 of this
                        handoff's own instruction set asked whether G8
                        acquires inhibitors, not merely observes them —
                        mechanically re-checked: contract §29 says only
                        "expose inhibitors," §26 lists logind only as
                        "list current inhibitors." Acquiring a Guardian-
                        owned inhibitor is not required by any G8
                        normative ID and is not built this gate.
Authoritative backend:   logind itself (native D-Bus).
Authorization mode:      N/A this gate (read-only).
Privilege requirement:   NoDirectPrivilege.
Transaction owner:       N/A.
Rollback capability:     N/A.
Observation method:      N/A.
Failure mapping:         logind absent -> ProviderUnavailable, and
                        contract §29 requires this to degrade the page/
                        command without blocking Guardian startup at all
                        — a stronger requirement than the generic
                        provider-unavailable pattern; implementation must
                        not let this failure be fatal to daemon startup.
Availability detection:  real probe against org.freedesktop.login1.
Single-writer implications: none.
SafeToResume eligibility:    N/A.
Real-system evidence required: real inhibitor list via
                        `systemd-inhibit`-created real inhibitor
                        (P1-LGI-001), real empty-list healthy case
                        (P1-LGI-002).
```

## 6.4 UDisks2

```text
Capability IDs:         udisks.drive.<drive-id>, udisks.block.<block-id>
                        (topology-preserving, per §27 — never a bare
                        `/dev/sdX` string as identity).
Read operations:         drive/block/partition/filesystem/mount topology;
                        CanPowerOff; sibling identity via shared Drive
                        object.
Write operations:        PowerOff() is explicitly deferred by contract
                        §26/§27 to "the I/O Guardian module phase." NOT
                        implemented in G8. What IS required this gate,
                        per §27's own text ("tests MUST already exist
                        proving"): the pure-Rust validation/rejection
                        logic and Layer 1 tests for:
                          - CanPowerOff == false rejects;
                          - sibling drives are discovered;
                          - stale object identity rejects;
                          - device removal between validation and apply
                            rejects;
                          - the action is marked user-initiated only;
                          - affected siblings are returned to the client
                            before authorization.
                        This is real, required G8 work — but it is
                        validation/precondition logic exercised against
                        fixture/mock topology data, never a real
                        `PowerOff()` D-Bus call. No transaction engine
                        instantiation, no helper involvement, no real
                        mutation.

                        **Normative for this gate (repair of the planning
                        review's non-blocking finding #1):** the G8
                        production UDisks adapter **MUST NOT contain any
                        callable implementation capable of issuing a real
                        `PowerOff()` call** — not merely "no test invokes
                        one." Do not implement the method "for
                        completeness" even if left uncalled by every G8
                        test; the validation/precondition logic above must
                        be provable and complete without any function in
                        the production codebase that could invoke the real
                        mutation. If an evidence-only `PowerOff()`
                        experiment is ever genuinely needed for a future
                        gate, it belongs in a disposable prototype (the
                        `tests/vm/g2-model-b/`/`tests/vm/g7-class-b-prototype/`
                        precedent), never in `guardian-core`'s or
                        `guardian-daemon`'s production UDisks adapter
                        module.
Authoritative backend:   UDisks2 itself (native D-Bus,
                        org.freedesktop.UDisks2).
Authorization mode:      Provider-owned, confirmed by G2's own accepted
                        Privilege Requirement Inventory (`UDisks
                        PowerOff()` row: "UDisks' own Drive.PowerOff()
                        requires and performs its own polkit check...
                        Guardian itself needs no privilege escalation for
                        this specific write") — this classification is
                        reused, not re-derived, since G2 already
                        evidenced it. Not applicable to G8's actual reads
                        at all (no authorization concept for reads).
Privilege requirement:   NoDirectPrivilege for the reads this gate
                        implements.
Transaction owner:       N/A this gate for any real Apply (none exists).
                        The future PowerOff() write, when implemented,
                        is Class B (provider-owned authorization) per the
                        G7 handoff's own classification — daemon-local
                        transaction ownership, no helper involvement,
                        exactly as G2 already established.
Rollback capability:     Deliberately not assumed. §27 does not claim
                        PowerOff has a meaningful rollback, and physical
                        power-off is a strong candidate for "no real
                        rollback exists" — this must be determined
                        honestly by whichever future gate implements the
                        write, not asserted now. This handoff explicitly
                        does not manufacture a rollback story for an
                        unimplemented action.
Observation method:      N/A this gate.
Failure mapping:         device absent -> Unsupported (P1-UDS-002-style,
                        by analogy — no literal ID for this exact case,
                        but the pattern is consistent); UDisks2 absent
                        entirely -> ProviderUnavailable; stale object path
                        (device removed between calls) -> PreconditionFailed
                        or Conflict, decided at implementation time using
                        the existing 17-category taxonomy, not a new one.
Availability detection:  real probe against org.freedesktop.UDisks2.
Single-writer implications: none triggered this gate (no real write
                        path). Recorded here as forward planning only:
                        when PowerOff() is eventually implemented, UDisks2
                        itself is the authoritative external writer for
                        drive power state — Guardian must never treat
                        itself as authoritative over a drive another
                        component (a desktop's own "Safely Remove"
                        action, for instance) might act on concurrently;
                        this is exactly the ownership-ambiguity class G2's
                        arbitration model exists for, to be exercised for
                        real at that future gate, not this one.
SafeToResume eligibility:    N/A this gate — no Apply exists to classify.
                        Forward note for the future implementing gate:
                        per G7's binding forward constraint, PowerOff
                        does not inherit SafeToResume merely because
                        G7's evidence adapter proved the pattern works for
                        a trivial counter — physical power-off's crash-
                        during-Apply semantics (was the drive powered off
                        or not, when the process died mid-call, and is
                        re-invoking PowerOff safe or dangerous against
                        already-removed media) must be proven on their
                        own terms before any automatic resume is
                        permitted. Until proven, the conservative default
                        is a `RequiresHumanRecovery`-equivalent path.
Real-system evidence required: real topology (P1-UDS-001/002), real
                        `umockdev` re-enumeration under a new `/dev` name
                        for the same physical identity (P1-UDS-003), real/
                        umockdev removal producing an invalidation event
                        (P1-UDS-004).
```

## 6.5 UPower

```text
Capability IDs:          upower.display-device,
                        upower.device.<device-id>.
Read operations:          display device properties when present; battery/
                        UPS/power-device enumeration where available.
Write operations:         None — §26 lists no write for UPower, no §37 ID
                        implies one, and nothing in prior gate evidence
                        classifies any UPower write as in scope. Treated
                        purely as telemetry, exactly as this task's own
                        framing suggested and as independently confirmed.
Authoritative backend:    UPower itself (native D-Bus,
                        org.freedesktop.UPower).
Authorization mode:       N/A.
Privilege requirement:    NoDirectPrivilege.
Transaction owner:        N/A.
Rollback capability:      N/A.
Observation method:       N/A.
Failure mapping:          no battery present -> a real, healthy Health
                        state with an explicit "not present" fact
                        (P1-UPW-002) — NOT Unavailable/Unsupported; the
                        provider is healthy, the device category simply
                        does not exist on this machine. UPower absent
                        entirely -> ProviderUnavailable.
Availability detection:   real probe against org.freedesktop.UPower.
Single-writer implications: none.
SafeToResume eligibility:     N/A.
Real-system evidence required: real display device read where present
                        (P1-UPW-001), real batteryless-desktop VM
                        confirming the healthy "not present" case
                        (P1-UPW-002).
```

## 6.6 AccountsService

```text
Capability IDs:           accounts.session-discovery.
Read operations:           discover provider availability; enumerate
                        installed/valid graphical sessions; validate a
                        requested session identifier against that real
                        enumeration.
Write operations:          Session mutation (SetSession()) is explicitly
                        deferred by contract §28 to "the system-management
                        phase." NOT implemented in G8. What IS required
                        this gate, per §28's own text: enumerate valid
                        installed sessions; validate requested session
                        IDs (P1-ACC-003's "fails validation before any
                        write" — real validation logic, exercised against
                        real/mock enumerated data, with no write to
                        precede since none exists yet); prefer
                        SetSession() over SetXSession()/.dmrc in the
                        adapter's own design even though neither write is
                        called this gate (so the future implementing gate
                        does not have to re-litigate this); never accept
                        an unvalidated session string as a future
                        privileged-write target.

                        **Normative for this gate (repair of the planning
                        review's non-blocking finding #1):** the G8
                        production AccountsService adapter **MUST NOT
                        contain any callable implementation capable of
                        issuing a real `SetSession()` call** (or
                        `SetXSession()`) — not merely "no test invokes
                        one." Do not implement either method "for
                        completeness" even if left uncalled by every G8
                        test; the enumeration/validation logic above must
                        be provable and complete without any function in
                        the production codebase that could invoke the real
                        mutation. Same disposable-prototype-only rule as
                        UDisks above applies to any future evidence-only
                        session-write experiment.
Authoritative backend:     AccountsService itself (native D-Bus,
                        org.freedesktop.Accounts).
Authorization mode:        For the future SetSession() write: provider-
                        owned authorization, per the same reasoning
                        pattern as UDisks (AccountsService performs its
                        own polkit check on account-mutation methods) —
                        this must be *verified*, not assumed, by whichever
                        future gate implements the write; recorded here
                        as the expected classification pending that
                        verification, not as an already-evidenced fact
                        the way UDisks PowerOff's classification is
                        (G2 evidenced UDisks specifically; it did not
                        evidence AccountsService SetSession).
Privilege requirement:     NoDirectPrivilege for the reads this gate
                        implements.
Transaction owner:         N/A this gate.
Rollback capability:       Not assumed. Undetermined until the future
                        implementing gate researches AccountsService's
                        actual session-mutation semantics.
Observation method:        N/A this gate.
Failure mapping:           AccountsService absent -> ProviderUnavailable;
                        invalid session ID -> InvalidRequest (P1-ACC-003),
                        never silently accepted or coerced to a default.
Availability detection:    real probe against org.freedesktop.Accounts
                        (P1-ACC-001).
Single-writer implications: none triggered this gate.
SafeToResume eligibility:      N/A this gate. Same forward note as UDisks:
                        must be proven on its own terms by the
                        implementing gate, never inherited automatically.
Real-system evidence required: real provider discovery (P1-ACC-001), real
                        session enumeration (P1-ACC-002), real invalid-ID
                        rejection (P1-ACC-003).
```

# 7. Interface hierarchy compliance

All six providers use the top of the accepted hierarchy (native D-Bus, or
the kernel interface for PSI, which has no D-Bus equivalent to prefer
over). No provider in G8's scope requires falling back to structured or
scraped CLI parsing — if implementation discovers a real gap forcing a
lower-layer choice for any of the six, that must be disclosed and
justified in the completion report, not silently substituted.

# 8. Single-writer analysis — not yet triggered, and why

G2 deferred deeper single-writer analysis explicitly until "multiple
concurrent write paths" exist (`ADR-002`'s own deferred-risk note). G8, as
mechanically re-derived above, introduces **zero** real write paths — the
existing G4 transaction engine plus G3 arbitrator, both already accepted
and already proven sufficient for the one real write path G7 built
(`guardian-helper`'s Class A `GuardedWrite`), remain architecturally
untouched and untested-further by this gate because nothing new exercises
them. **The precondition for "single-writer becomes real" has not yet
arrived.** This is recorded honestly rather than forcing a premature
"G8 requires a broader mechanism" or "the existing arbitrator is proven
sufficient for N writers" claim neither direction is evidenced for yet.
The two deferred-write capabilities (UDisks `PowerOff`, AccountsService
`SetSession`) are exactly where this analysis becomes real — carried
forward explicitly as the trigger condition for whichever future gate
implements either.

# 9. `SafeToResume`/idempotency — not yet triggered, and why

Symmetric with §8: G7's binding forward constraint ("a future real G8
provider may only be wired into `SafeToResume`-style automatic Apply
resumption after it has separately proven its own `apply` is genuinely
idempotent...") applies to real Apply operations. G8 implements none.
Nothing in this gate inherits or needs to earn `SafeToResume` eligibility.
The constraint remains fully binding and unweakened for whichever future
gate implements `PowerOff()` or `SetSession()` — restated here, not
resolved here.

# 10. Transaction ownership

No write-capable operation exists in G8's scope, so no per-write
Snapshot/Validate/Authorize/Apply/Observe/Confirm/Rollback matrix applies.
All six providers' read paths run entirely within `guardian-daemon`
(Class C), using the already-accepted `Provider` trait (`probe`,
`capabilities`, `health`, `subscribe_events`) — no `TransactionRecord`,
no `MutableCapabilityAdapter` instantiation, no persistence directory
involvement. `guardian-helper` is untouched.

# 11. Capability Registry — becomes materially real this gate

G8 is correctly where the registry stops being populated by G3's fixture
data and starts being populated by real provider reads. For each of the
six providers, implementation must populate a real `CapabilityRecord` per
discovered capability with genuinely observed (not hardcoded) values for:
`availability`, `health`, `read_support` (true), `write_support` (false
for every G8-scope capability — see §1), `authorization_ownership`
(`Knowledge::Unknown` is honest and acceptable where not yet evidenced,
per G3's own accepted discipline — do not fabricate `Known` values),
`privilege_requirement` (`NoDirectPrivilege` for every read this gate
adds, evidenced, not assumed), `interface_kind` (`DBus` for five, and for
PSI the closest accurate value — `KernelInterface`, already a real
`InterfaceKind` variant — not `DBus`), and `last_observed_at`. Capability
Registry = what exists; Provider Arbitrator = who may write and under
what conditions — G8 only ever populates the former, since nothing in
this gate's scope has a "who may write" question to answer.

# 12. Public D-Bus boundary — no expansion required

None of the nineteen normative IDs require a new `Guardian1` D-Bus method
— they are provider-adapter correctness claims, provable via Layers 1-4
without any client-facing exposure. `Guardian1` remains exactly
`ContractVersion`/`ServiceState`, frozen since G0, unchanged again this
gate. Populating the Capability Registry is internal `guardian-daemon`
state; exposing it to clients (a future `Guardian1.Capabilities1`-shaped
interface, per contract §7.1's own illustrative namespace shape) is
correctly G9's job, when real CLI/TUI/GUI/indicator clients exist to
consume it — building that exposure now, with no consumer, would be
exactly the "incidental permanent API growth" G7's own accepted guardrail
forbids repeating.

# 13. G2 `Unknown` privilege-area disposition

None of G8's six required domains touches any of G2's eight `Unknown`
areas (BPF/eBPF, thermald write policy, NVML/NVIDIA, fwupd, journald
rotation/capacity, apt/package state, generic hardware control, USB
Security/usbguard) — mechanically cross-checked against
`docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md` directly. **All
eight remain deferred, untouched, unresearched by this gate** — recorded
here explicitly rather than silently ignored, and explicitly not
researched merely to make this section look complete (none is required
for G8's actual scope).

# 14. G5/G7 forward-constraint dispositions

```text
G5 FC-2 (RecorderPolicy runtime wiring): remains OPEN. G8 introduces no
  real spill/retention sink — nothing in this gate's scope builds one.
  Any future PSI-driven or provider-driven diagnostic capture path must
  not silently claim this closed; if a future gate within G8's
  implementation genuinely needs a real spill target (unlikely, since PSI
  read paths are not diagnostic-capture actions), that gate must
  re-evaluate FC-2 explicitly, not inherit an assumption.
G4 FC-3 (Flight Recorder / transaction persistence deliberately
  independent): unchanged. G8 introduces no transaction persistence use
  at all (no writes), so this cannot be newly implicated this gate.
G7 forward constraints (SafeToResume/idempotency; direct-call
  architecture; single-writer-across-real-writes): see §8/§9 above —
  restated as still-binding, not yet triggered, not weakened.
```

# 15. Error taxonomy mapping

Reuses the existing 17 `GuardianDbusError` categories unchanged — no new
category is introduced or needed for G8's scope:

```text
ProviderUnavailable  -> provider daemon absent from the bus entirely
                        (systemd1/login1/UDisks2/UPower/Accounts probe
                        fails; PSI file unreadable for permission
                        reasons).
Unsupported           -> the capability genuinely does not exist for this
                        host/device (missing unit, missing battery,
                        kernel PSI not compiled in) — never conflated
                        with a provider outage.
InvalidRequest         -> a caller-controllable value fails validation
                        before anything is attempted (P1-ACC-003's
                        invalid session ID).
PreconditionFailed / Conflict -> reserved, forward-looking, for the
                        future PowerOff/SetSession implementing gate's
                        stale-identity/ownership-conflict cases — not
                        exercised by any real G8 code path, since none
                        writes.
```

Do not collapse a genuine provider outage into `NotAuthorized`, and do
not collapse "this hardware category doesn't exist" into a provider
failure — both distinctions are load-bearing for P1-PSI-005/P1-UDS's
absent-device handling and P1-UPW-002 specifically.

# 16. Testing ladder

```text
Layer 1 (pure Rust): parsing (PSI files, D-Bus property shapes), capability-
  record population logic, the UDisks PowerOff/AccountsService SetSession
  validation-and-rejection logic §27/§28 require, failure-taxonomy
  mapping. No system bus, no real hardware.
Layer 2 (private D-Bus / dbusmock): first real use of python3-dbusmock in
  this project — G0-G7 never needed to simulate a third-party provider's
  own protocol behavior (G1/G2's private-bus tests simulated Guardian's
  own interfaces, not systemd1/UDisks2/etc.). Simulate: provider appears/
  disappears, owner changes, method timeout, malformed response,
  unsupported member, stale proxy — per contract §35's own Layer 2 list,
  applied to each of the five D-Bus-backed providers (not PSI, which has
  no D-Bus surface).
Layer 3 (umockdev): first real use of umockdev in this project. Required
  specifically for P1-UDS-003 (volatile `/dev` name re-enumeration) and
  P1-UDS-004 (removal) — hotplug/removal/re-enumeration-under-a-new-name
  scenarios are exactly what umockdev exists for and are impractical to
  prove any other way without real removable hardware.
Layer 4 (disposable Ubuntu 26.04.1 VM): required for every provider's
  real-system confirmation per §3's matrix — real system bus, real
  systemd/login1/UDisks2/UPower/Accounts, real `/proc/pressure/*`. The
  grounding differs precisely by provider (repair of the planning
  review's non-blocking finding #3 — do not cite all six uniformly as
  contract-sourced):
    - UDisks and AccountsService: §35 **explicitly names** "UDisks
      behavior" and "AccountsService behavior" as required Layer 4 items
      — direct contract text.
    - systemd: real-system evidence is **explicitly grounded through
      §41**'s Ubuntu 26.04.1 VM validation list, which names "systemd" as
      a required item.
    - PSI, logind, and UPower: Layer 4 confirmation for these three is
      **required by this project's established evidence practice**
      (every prior gate proved real system behavior in a VM, never
      accepted mock-only evidence for a normative ID concerning real
      system state) **and by §41's general "mandatory gate evidence"
      closing line** — not because §35 literally names these three by
      domain. This is a citation-precision correction only; the
      requirement itself is not weakened — real VM confirmation remains
      required for all six providers.
Layer 5 (physical hardware): not required for G8. No normative ID in
  §3's matrix depends on it — P1-UDS-002/003 (siblings, volatile names)
  are provable via `umockdev` fixtures and/or a real multi-partition VM
  disk, not physical removable media. If implementation genuinely cannot
  establish a claim without physical hardware, that must be reported as
  a planning/implementation blocker, not worked around by assumption.
```

Do not let VM/manual evidence substitute for Layer 1-3 coverage where
those layers can genuinely establish the claim (parsing, mock-protocol
behavior, and umockdev-provable hotplug/removal are all Layer 1-3
concerns) — matching this project's own established discipline from every
prior gate.

# 17. Real-system evidence plan (Layer 4 specifics)

```text
provider present / absent:        every provider, both states.
provider restart:                  not required by any G8 normative ID —
                                    P1-DMN-style restart-recovery claims
                                    belong to G7 (already evidenced) and
                                    do not re-apply to read-only Class C
                                    providers with no persisted state.
permission denied:                 PSI file unreadable case (P1-PSI-005's
                                    "unavailable" may include this).
capability unsupported:            missing unit, missing battery, no PSI.
external writer active:            not exercisable this gate — no real
                                    write path exists to observe
                                    contention against (see §8).
ambiguous ownership:                same — not exercisable this gate.
operation succeeds / postcondition
  observed / rollback succeeds /
  rollback unavailable / crash
  during operation / restart
  recovery:                        not applicable — no G8 operation is a
                                    mutation. Explicitly not fabricated.
```

Any claim this section does not name is not required for G8 and must not
be manufactured to appear complete.

# 18. Scope boundary — explicit exclusions

Out of scope for G8, confirmed against the contract (not merely asserted):
GUI/TUI/CLI production work; production indicator; real `PowerOff()`/
`SetSession()` writes (both explicitly deferred by §26/§27/§28 to later
phases); broad NetworkManager control; thermal control; GPU management;
fwupd workflows; package/update management; I/O Guardian migration;
usbguard/USB Security; Phase 2 incident intelligence; adaptive recovery;
`power-profiles-daemon` (optional, deliberately deferred per §4); any
expansion of the permanent public `Guardian1` API (§12); resolution of
any of G2's eight `Unknown` privilege areas (§13); any new error category;
any change to `guardian-helper` or the Class A write path.

# 19. Completion states

Report exactly one, honestly:

```text
G8 CANDIDATE — READY FOR INDEPENDENT AUDIT
G8 PARTIAL — REQUIRED EVIDENCE INCOMPLETE
G8 BLOCKED — GOVERNING CONTRACT INSUFFICIENT
```

# 20. Completion report requirements

State plainly: what was built (crate/module names, exactly which
`CapabilityRecord`s are populated); real evidence for all nineteen
normative IDs with VM/mock setup and provenance; which of §14's forward
constraints were touched and how; explicit confirmation that no real
write (`PowerOff`, `SetSession`, or any other) was implemented; explicit
confirmation the public `Guardian1` surface is unchanged; `cargo fmt
--check`/`clippy`/`cargo test --workspace` results with the exact
before/after count (212 passed, 0 failed is the pre-G8 baseline).
