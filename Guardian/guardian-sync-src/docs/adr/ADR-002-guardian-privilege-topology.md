# ADR-002: Guardian privilege topology

- Status: Accepted
- Date: 2026-08-31
- Governing gate: G2 — Privilege Topology

## Context

G1 established real caller identity resolution and real polkit
authorization inside a single process (`guardian-daemon`). G2 must decide,
with evidence rather than preference, whether Guardian's eventual
privileged write path should remain a single hardened daemon (Model A) or
split into an unprivileged core plus a narrow privileged helper (Model B),
per `docs/guardian/30_TDD/GUARDIAN_G2_IMPLEMENTATION_HANDOFF.md` and TDD
contract §25.

Both models were built as real prototypes, deployed as real systemd units
in a disposable Ubuntu 26.04.1 VM (`guardian-g2-vm`, multipass, destroyed
after evidence capture), and measured. Full raw evidence:
`docs/evidence/g2/MODEL_A_EVIDENCE.md`, `docs/evidence/g2/MODEL_B_EVIDENCE.md`,
`docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`, and the
`docs/evidence/g2/model-a/`, `docs/evidence/g2/model-b/` raw transcripts.

## Decision drivers

Least privilege; attack surface; confused-deputy risk; sandboxability;
provider compatibility; transaction compatibility; failure containment;
recovery behavior; observability; testability; operational complexity;
packaging complexity; future extension cost. No numerical scoring system is
used — the evidence and tradeoffs below are the basis for the decision, per
the governing handoff.

## Privilege Requirement Inventory summary

Full detail: `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`. Of 24
capability areas classified (read/write split into separate rows where
their privilege models differ, so counts are additive and mutually
exclusive): 9 need no privilege, 6 are provider-owned authorization (the
provider — UDisks, systemd1, NetworkManager, AccountsService — performs
its own polkit check; Guardian needs no elevated privilege), 1 is
Guardian's own bounded polkit-gated action (matching the G2 test
operation), and 8 are honestly marked unknown pending further research
(BPF/eBPF, thermald writes, NVML, fwupd, journald rotation, apt/package
state, generic hardware control, usbguard). **No capability area
researched this pass demonstrably requires Guardian to hold
root or a broad Linux capability for its own sake** — the root requirement
found below comes from a different source entirely (see next section).

## Model A — hardened privileged daemon

**Architecture:** one process (`guardian-model-a.service`), reusing G1's
`guardian_core::identity`/`guardian_core::authorization` unchanged. Real
caller resolved from the inbound D-Bus message; real `PolkitAuthorizer`
call; bounded typed write (`AttemptBoundedWrite(interactive: bool)`).

**The trusted-caller finding (applies to both models — read this first):**
started deliberately unprivileged (`User=svc-model-a`, empty
`CapabilityBoundingSet=`). Every call — including the one that should have
been granted — failed with a *real polkit error*:

```text
org.freedesktop.PolicyKit1.Error.NotAuthorized: Only trusted callers
(e.g. uid 0 or an action owner) can use CheckAuthorization() for subjects
belonging to other identities
```

Confirmed empirically (switching only `User=` from `svc-model-a` to `root`,
everything else unchanged, fixed it) that **any process performing
`CheckAuthorization` on behalf of a different subject must itself be a
trusted caller — uid 0, or the action's registered owner** — a hard polkit
constraint, not a Guardian design choice, and not something the bounded
write operation itself needs. This applies identically to Model B's
helper.

**Privileges:** `User=root`; `CapabilityBoundingSet=` empty. Verified via
`/proc/<pid>/status`: `CapPrm`/`CapEff`/`CapBnd`/`CapAmb` all
`0000000000000000`. Root, but zero Linux capabilities.

**systemd hardening:** started from the full TDD contract §24 directive
set; every directive present in the final unit was tested and kept because
it worked (round 1: 2.0 OK with the baseline set; round 2: 1.1 OK after
adding `ProtectClock=`, `SystemCallArchitectures=native`, `ProtectHostname=`,
`ProtectProc=invisible`, `ProcSubset=pid`, `PrivateNetwork=yes`,
`UMask=0077`, each individually confirmed compatible with the bounded
write). None disabled to make a test pass. Remaining exposure is `User=root`
(architectural, documented above) plus small residual items
(`SystemCallFilter` breadth, `RestrictAddressFamilies=~AF_UNIX` — required
for D-Bus itself) recorded as temporary, worth narrowing later.

**Authorization:** identical code path to G1, unchanged.

**Security analysis:** attack surface is the entire daemon process — all
current and future Guardian logic (monitoring, correlation, diagnostics,
writes) shares one root-uid process. A memory-safety bug or
supply-chain-compromised dependency anywhere in that combined surface
inherits root's DAC-bypass and polkit-trust properties, even in code that
itself needs neither.

**Operational analysis:** simplest possible deployment — one binary, one
unit, one D-Bus name, one thing to monitor/restart. Lowest packaging
complexity of the two models. Observability is straightforward: one
journal stream, one process to attribute every decision to.

**Raw evidence:** `docs/evidence/g2/MODEL_A_EVIDENCE.md`,
`docs/evidence/g2/model-a/`.

## Model B — unprivileged core + narrow privileged helper

**Architecture — corrected from the handoff's illustrative diagram:** the
handoff's `client → core → helper` relay diagram is not safely realizable.
D-Bus does not forward sender identity through a relay hop — if `core`
relayed a request to `helper`, the helper would resolve `core`'s identity,
never the original client's, and any attempt to work around that by
forwarding a claimed UID would be the exact confused-deputy vulnerability
this gate exists to prevent. **The topology actually built and measured:**
clients call the helper *directly* for the bounded write; `core` is never
in the write path, and has no code path capable of relaying one.

**Helper contract:** confirmed via live `gdbus introspect` against the real
running service (`docs/evidence/g2/model-b/helper-live-introspection.txt`),
not a code read. Two classes of method:

- **Privileged operation:** `AttemptBoundedWrite(in b interactive)` — the
  sole method that performs the bounded mutation. Exactly one input
  argument, a boolean. No path, no uid, no argv, no opaque payload, no
  claimed-identity field anywhere in the interface.
- **Test/observability-only:** `MutationCount(out u)` and
  `LastOrderingTrace(out as)` — output-only accessors that let the Layer 1
  and Layer 2 evidence prove ordering (`received → identity_resolved →
  validated → authorized_checked → mutation_applied`) and mutation count.
  They perform no privileged mutation and expose no caller-controlled
  input. These exist to make G2's evidence verifiable; they are prototype
  instrumentation, not a claim about what belongs in a production helper's
  public API, and are not automatically carried forward as permanent
  surface.

**Privileges:** `core` — `User=svc-model-b-core` (uid 997), empty
`CapabilityBoundingSet=`, plus `PrivateUsers=yes` (safe to add here
specifically because `core` never calls polkit and has no real-UID-visibility
constraint). `helper` — `User=root` for the identical trusted-caller reason
as Model A; empty `CapabilityBoundingSet=`. Verified via `/proc/<pid>/status`
for both: all `Cap*` fields zero.

**systemd hardening:** identical directive set and methodology as Model A
for both units. `core`: **0.6 SAFE**. `helper`: **1.1 OK** — numerically
identical to Model A's entire daemon.

**Confused-deputy analysis:** closed by construction. The helper's real,
live interface has no parameter a relaying process could populate; the
Layer 1 test suite additionally proves two real distinct connections cannot
influence each other's authorization outcome
(`crates/guardian-daemon/tests/g2_privilege_topology_contract.rs`).

**Authorization:** identical code path to G1 and to Model A's daemon,
unchanged, running inside the helper.

**Security analysis:** the privileged component's exposure is *not lower*
than Model A's — same root requirement, same zero-capability profile, same
1.1 score. What changes is *how much code carries that exposure*: the
helper's surface is fixed at three narrow methods and does not grow as
Guardian gains features. `core` — where the actual bulk of Guardian's
architecture is expected to live (Capability Registry, Provider Arbitrator,
PSI event engine, Diagnostic Budget, Flight Recorder, Event/Incident
correlation — all read/monitoring-heavy per GP-02's read-by-default
principle) — measures genuinely safer (0.6, with a user namespace) and
never touches privilege as it grows.

**Operational analysis:** more moving parts — two extra systemd units, two
extra D-Bus well-known names, two extra service users, more D-Bus policy to
audit. Genuinely higher packaging and initial-setup complexity than Model
A, confirmed by the actual setup effort this pass required (a corrected
D-Bus policy iteration was needed mid-session — see
`docs/evidence/g2/g2-vm-setup.sh`).

**Raw evidence:** `docs/evidence/g2/MODEL_B_EVIDENCE.md`,
`docs/evidence/g2/model-b/`.

## Direct comparison

| Dimension | Model A | Model B |
|---|---|---|
| Least privilege (privileged component) | root, 0 capabilities | root, 0 capabilities — **identical** |
| Attack surface of privileged component | entire daemon (all current + future logic) | fixed 3-method helper only |
| Confused-deputy risk | N/A (single process) | closed by construction (no claim parameter exists); requires the direct-call correction above |
| Memory-safety blast radius if compromised | root-equivalent for all Guardian code | root-equivalent only for the small fixed helper; `core`'s much larger surface is uid-997, zero-capability, user-namespaced |
| IPC exposure | one D-Bus name | two D-Bus names, two policy surfaces |
| Serialization/parser exposure | one interface's worth | two interfaces' worth (though `core`'s is trivially small — one read method) |
| Sandboxability (measured) | 1.1 OK | 0.6 SAFE (core) / 1.1 OK (helper) |
| Provider compatibility | unaffected either way — 6/24 areas are provider-owned regardless of topology | same |
| Transaction compatibility | see below | see below |
| Failure containment | see below | see below |
| Recovery behavior | untested this pass (helper's identical evidence stands in) | real: ~2s auto-restart, new identity, in-memory state resets |
| Observability | one journal stream, trivially attributable | two journal streams; still clearly attributable per this pass's evidence, marginally more correlation work |
| Testability | Layer 1 tests reused unchanged from G1 | Layer 1 tests required one new structural pattern (dual real connections) — done, in `g2_privilege_topology_contract.rs` |
| Operational complexity | lowest | higher — confirmed by this pass's own setup friction |
| Packaging complexity | one unit | three units |
| Future extension cost | every new feature, even read-only, inherits root's exposure | only genuinely privileged writes touch the helper; the much larger monitoring/correlation surface (per TDD contract's own module list) never does |

## Transaction compatibility (analysis only — G4 not implemented)

Both models: **the process is the natural owner of Snapshot/Validate/Apply/
Observe** for whichever component performs the write (the daemon for Model
A, the helper for Model B) — this pass's real crash-restart evidence shows
in-memory state does not survive a crash for either model, so **G4 must
persist transaction records externally (`/var/lib/guardian`, per TDD
contract §23), regardless of topology** — this was a real, not merely
reasoned, finding.

`Authorize` is owned by whichever component calls `CheckAuthorization` —
the daemon (A) or the helper (B); in both cases this is the same component
that performs `Apply`, so there is no cross-process authorization/apply
split to reason about for either model as currently evidenced.

`Rollback` ownership: unresolved by this pass for both models equally —
neither prototype implements a real rollback, and TDD contract §9
"snapshot" is not built until G4. Recorded as a deferred risk (below), not
a differentiator between models.

`core` (Model B) never owns transaction state, consistent with GP-01
(orchestrate, don't reimplement) — it has no write capability to own state
for.

## Single-writer compatibility

Both models: a single process (daemon or helper) holds the sole write
capability for the bounded test action; no evidence of two processes both
believing they own write authority was found for either, because in both
models exactly one systemd-managed process exists that can perform the
write at all — there is no Model-B scenario this pass built where `core`
and `helper` could both attempt the same write, since `core` has no write
method whatsoever. This question becomes materially harder once multiple
*capability areas* each get their own write path in later gates, and is
recorded as a deferred risk requiring re-analysis then, for both models
equally.

Restart evidence (helper, real): after `kill -9` + `Restart=on-failure`
auto-restart, exactly one process existed at any observed point in time —
no overlapping-writer window was observed, though a genuinely adversarial
window (kill signal arriving mid-`Apply`) was not specifically engineered
this pass and remains a reasoned-about, not directly tested, scenario for
both models.

## Failure containment

| Scenario | Model A | Model B |
|---|---|---|
| Core crash | N/A (no separate core) | `core` crash: reads unavailable; writes (via helper) unaffected — real, not tested this pass but architecturally obvious given `core`'s isolation from the write path |
| Privileged daemon/helper crash | daemon down, all Guardian function unavailable (real evidence: helper's identical `Restart=on-failure` recovers in ~2s, applies to A by code-identity) | helper down: writes unavailable, reads via `core` unaffected — genuine containment benefit, not exercised directly this pass but structurally guaranteed by process independence |
| IPC/D-Bus disconnect | client retries against the one name | client retries against whichever name it needs; a disconnect from `core` doesn't affect `helper` reachability or vice versa |
| polkit unavailable | real, from G1 hardening pass: `ProviderUnavailable`, not misreported as denial | identical code path, identical typed result, in the helper |
| provider unavailable/hung | not exercised this pass (no real provider integrated yet in either model) | same |
| systemd restart | real: ~2s, new PID, new bus identity, in-memory state reset | same, demonstrated on the helper |
| duplicate process | not engineered/tested (see single-writer note above) | same |
| machine reboot mid-operation | reasoned only, not executed: systemd would restart the unit(s) post-boot per `[Install]`/`WantedBy=`; no in-flight state exists to be ambiguous given no persistent transaction store exists yet in either model | same reasoning applies |

Model B's structural containment advantage (a helper crash does not take
reads down, and vice versa) is real but was not independently exercised
this pass beyond the helper's own restart test — recorded honestly as
partially evidenced, not fully demonstrated for the cross-component
independence claim specifically.

## Privilege-creep checkpoint

**Model A, cumulative:** `CapabilityBoundingSet=` empty (verified via
`/proc` — real zero, not merely declared) + `User=root` (architectural,
required) + the round-2 hardening set. After combining everything: the
process is root with the DAC-bypass and polkit-trust properties that
implies, and *no* capability-gated privilege beyond that. This is not
unrestricted root in the Linux-capability sense, but it **is** unrestricted
in the sense that matters for this specific process: everything Guardian
ever runs in this one process inherits UID 0's kernel-level trust,
including future code that itself needs none of it. The privilege-creep
risk for Model A is structural, not incremental — it isn't that exceptions
accumulate over time (none did this pass), it's that *all* future code
shares the one root process by construction.

**Model B, cumulative:** `helper` — identical combination to Model A
(root, zero capabilities) but scoped to exactly three methods; adding this
does not, by itself, indicate creep, because the helper's surface is fixed
and small. `core` — uid 997, zero capabilities, user-namespaced,
`PrivateNetwork=yes`: after combining everything, `core` can do
essentially nothing beyond serve its one read-only D-Bus method. Neither
component shows creep this pass. The structural privilege-creep risk for
Model B is different in kind: the risk is pressure, over time, to add
*more* methods to the helper (or to route more operations through it)
rather than keeping `core` genuinely privilege-free — this is a real,
named risk for future gates to watch, not evidence of creep having already
happened.

## Decision

**Selected topology: Model B (unprivileged core + narrow privileged
helper), with the direct-client-to-helper write path correction recorded
above superseding the handoff's illustrative relay diagram.**

## Why Model A lost

Model A is not unsafe — its measured exposure (1.1) is identical to Model
B's helper, and it is operationally and packaging-wise simpler. It lost
because the privilege-minimization goal this gate exists to serve is not
about the score of the privileged component (which is the same either way,
for a hard reason — polkit's own trust requirement — neither model can
improve on) but about *how much code* carries that component's exposure.
Model A structurally commits Guardian's entire future codebase — including
the explicitly read-heavy, monitoring-and-correlation-first majority of the
architecture the TDD contract describes (Capability Registry, Provider
Arbitrator, PSI, Diagnostic Budget, Flight Recorder, Event/Incident model)
— to running inside the one root process, forever, by construction. Model
B's real, measured evidence (0.6 SAFE for the unprivileged core, with a
user namespace) shows that surface can instead run somewhere that never
touches privilege at all. Given GP-02 (read-only by default) is a stated
governing principle and most of Guardian's planned code is exactly the kind
of thing GP-02 describes, this is not a marginal or aesthetic difference —
it is the actual difference the least-privilege decision driver is meant to
capture.

The operational/packaging cost Model B pays for this is real (confirmed
directly by this pass's own setup friction) but bounded and one-time —
paid once at packaging/deployment design time, not accumulating with every
future feature the way Model A's structural cost does.

## Consequences

- The future production `guardian-daemon` becomes `guardian-core`
  (unprivileged) plus a new, small `guardian-helper` binary/unit. This is a
  binary-split decision, not yet a production implementation — no such
  binaries exist yet; only the G2 prototypes do.
- Any future privileged write operation gets its own typed, individually
  polkit-authorized method on `guardian-helper`, following exactly the
  bounded-method discipline demonstrated this pass (TDD contract §6.4; G2
  handoff §10).
- `guardian-helper` must run as root for the polkit trusted-caller reason
  documented above; this is not expected to change without a different
  authorization mechanism than real polkit `CheckAuthorization`, which is
  out of scope to redesign here.
- Clients must be able to reach both `guardian-core` (reads) and
  `guardian-helper` (writes) directly on the system bus. The security
  invariant this protects is narrower than "core is never involved in a
  write": **`guardian-helper` must never depend on `guardian-core`
  forwarding the client's identity or authorization claim.** The helper
  must always independently resolve the real caller from its own inbound
  D-Bus connection and independently perform the required polkit
  authorization immediately before mutation — regardless of what else it
  consults. What is forbidden is a relay of *client identity/authorization
  authority* through core (`core` says `uid=1000, authorized=true` →
  `helper` trusts it); a future `helper → core` consultation for
  non-authoritative coordination (e.g. Provider Arbitrator ownership,
  single-writer state, transaction context, capability/observation state)
  is not foreclosed by this decision, provided `core`'s response is never
  treated as establishing caller identity, authorization, or privileged
  authority — the helper remains solely responsible for validating
  whatever conditions must hold immediately before its own mutation. This
  distinction is architectural guidance for G3/G4, not an implementation
  of Provider Arbitrator or transaction coordination now.
- G3's Capability Registry, Provider Arbitrator, and later gates' PSI event
  engine, Diagnostic Budget, Flight Recorder, and Event/Incident model
  belong in `guardian-core`, not `guardian-helper`, consistent with this
  decision's rationale.
- Packaging (a later gate) must ship and coordinate three systemd units
  (this pass's prototype naming, `guardian-model-a/b-*`, is prototype-only
  and not the production unit naming).

## Deferred risks / unknowns

- **Rollback ownership** is unresolved for both models — deferred to G4,
  where it must be resolved before any real destructive write ships,
  regardless of this decision.
- **Single-writer enforcement across multiple capability areas** was not
  exercisable with only one bounded test action; must be re-evaluated once
  G3/G4 introduce multiple concurrent write paths.
- **The 8 `unknown` capability areas** in the Privilege Requirement
  Inventory (BPF/eBPF, thermald writes, NVML, fwupd, journald rotation,
  apt/package state, generic hardware control, usbguard) could, if any
  turns out to need a broad capability or root beyond the polkit-trust
  reason already found, materially change this comparison for that
  specific capability area — this decision covers the areas actually
  researched, not a blanket guarantee about all future Guardian features.
- **`core`'s `PrivateUsers=yes`** was not attempted for the helper (a
  deliberate, documented choice this pass, not a tested incompatibility) —
  worth real investigation later, since if user-namespace isolation could
  somehow coexist with polkit's real-UID trust check, it would further
  reduce the helper's residual exposure.
- **Mid-`Apply` crash windows** and **machine-reboot mid-operation** were
  reasoned about, not directly engineered/tested, for both models.
- **Cross-component failure independence** (helper crash not affecting
  `core`'s reads, and vice versa) is architecturally expected but was not
  independently exercised this pass beyond the helper's own restart test.
