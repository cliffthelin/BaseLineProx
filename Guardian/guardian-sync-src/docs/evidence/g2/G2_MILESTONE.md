# Guardian Phase 0 — G2 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Validated commit and tag

```text
Final accepted commit:  87502df8e41268aec4e94635d218c8b81c82189c
G2 tag:                 phase0-g2-privilege-topology (annotated, points to 87502df)
```

`87502df` is intentionally later than the ADR-002 decision commit
(`cb46288`) — the independent G2 audit found four non-blocking
documentation/evidence findings against `cb46288`, those findings were
subsequently fixed in `87502df`, and a focused independent confirmation
pass verified `87502df` closes all four. The tag captures the
audited-and-corrected final state, not the pre-closure decision commit.

## Selected topology

**Model B — unprivileged Guardian core + narrow privileged helper.**

## Immutable architectural rules established by G2

```text
Core privilege:            guardian-core is unprivileged and never holds
                            root or elevated capabilities.
Helper privilege boundary: guardian-helper is the sole privileged process;
                            its surface is fixed and narrow (typed, bounded
                            operations only — no generic execution primitive).
Caller identity authority: guardian-helper always independently resolves
                            the real D-Bus caller from its own inbound
                            connection. It never accepts a caller identity
                            claim forwarded by guardian-core or any other
                            process.
Authorization authority:   guardian-helper always independently performs
                            real polkit CheckAuthorization immediately
                            before mutation. It never trusts an
                            "authorized=true" claim forwarded by
                            guardian-core.
Helper -> core consultation: permitted for non-authoritative coordination
                            only (e.g. future Provider Arbitrator
                            ownership, single-writer state, transaction
                            context, capability/observation state).
                            guardian-core's response may never establish
                            caller identity, authorization, or privileged
                            authority for the helper.
Provider-owned authorization: preferred wherever an existing authoritative
                            system service (UDisks, systemd1,
                            NetworkManager, AccountsService, etc.) already
                            performs its own authorization for an
                            operation — Guardian does not duplicate
                            privilege it can delegate.
Generic broker policy:     forbidden absolutely. No RunCommand/RunShell/
                            Execute/WriteFile/SetSysfs/CallDbus/
                            ExecuteProvider/Invoke or semantic equivalent
                            exists or may be added to guardian-helper.
```

## Linux capabilities and the UID-0 finding

Both G2 prototypes' privileged components (Model A's daemon and Model B's
helper) demonstrated **zero effective Linux capabilities** in real,
committed `/proc/<pid>/status` evidence (`CapInh`/`CapPrm`/`CapEff`/
`CapBnd`/`CapAmb` all `0000000000000000`).

**Important interpretation, preserved as a standing constraint on later
gates:** `UID 0` was independently required in both models for a real,
empirically confirmed reason distinct from Linux capabilities — polkit's
own `CheckAuthorization()` refuses to authorize a subject other than the
caller itself unless the calling process is a trusted caller (uid 0, or a
registered polkit action owner). This is a property of the authorization
mechanism, not of the bounded mutation itself. **Zero Linux capabilities
does not mean unprivileged** — `UID 0` retains DAC-bypass and polkit-trust
properties regardless of its capability set, and both ADR-002 and this
record treat the privileged helper as genuinely privileged.

## Independent review

- Full independent G2 audit: **PASS WITH NON-BLOCKING FINDINGS**.
- Post-audit findings closure: fixed in `87502df`.
- Focused findings confirmation: **PASS — G2 FINDINGS CLOSED / READY TO TAG**.

## Normative test status

```text
P0-PRIV-001 — Model A measurement        PASS (real Ubuntu 26.04.1 VM: systemd unit, systemd-analyze security, real capabilities, real polkit authorization/denial)
P0-PRIV-002 — Model B measurement        PASS (real Ubuntu 26.04.1 VM: core + helper units, systemd-analyze security, real capabilities, real polkit authorization/denial, real restart)
P0-PRIV-003 — topology decision record   PASS (ADR-002, evidence-driven, non-preselected, independently audited and confirmed)
```

## Why Model A lost (not because it was unsafe)

Model A's privileged daemon measured identically to Model B's privileged
helper (root, zero capabilities, `1.1 OK` systemd-analyze security score).
It lost because it structurally commits Guardian's entire future
codebase — including the large, read-heavy control/analysis surface the
TDD contract describes (Capability Registry, Provider Arbitrator, PSI
event engine, Diagnostic Budget, Flight Recorder, Event/Incident
correlation) — to running inside that one root-trusted process, forever,
by construction. Model B's unprivileged core measured genuinely safer
(`0.6 SAFE`, with a user namespace) and never needs to touch privilege as
it grows.

## Evidence index (referenced, not duplicated here)

```text
docs/adr/ADR-002-guardian-privilege-topology.md
docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md
docs/evidence/g2/MODEL_A_EVIDENCE.md
docs/evidence/g2/MODEL_B_EVIDENCE.md
docs/evidence/g2/model-a/            (raw systemd units, systemd-analyze output, process/capability transcripts, journal)
docs/evidence/g2/model-b/            (raw systemd units, systemd-analyze output, process/capability transcripts, journal, live D-Bus introspection)
docs/evidence/g2/g2-vm-setup.sh      (reproducible disposable-VM setup)
docs/guardian/30_TDD/GUARDIAN_G2_IMPLEMENTATION_HANDOFF.md
docs/guardian/30_TDD/GUARDIAN_G2_INDEPENDENT_REVIEW_HANDOFF.md
crates/guardian-daemon/tests/g2_privilege_topology_contract.rs   (Layer 1 proof)
tests/vm/g2-model-a/, tests/vm/g2-model-b/                       (evidence-gathering prototypes; not production code — see GUARDIAN_G3_IMPLEMENTATION_HANDOFF.md for prototype-vs-production status)
```
