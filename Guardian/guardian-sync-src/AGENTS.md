# AGENTS.md — Guardian Repository Instructions

## Scope

These instructions govern all coding agents working in the Guardian repository.

Guardian is an Ubuntu 26.04.1 system-control plane. It will eventually perform privileged and recovery-sensitive operations. Architectural shortcuts that would be harmless in an ordinary desktop application are not acceptable here.

## Startup workflow for a governed gate task

Added 2026-09-06 (procedural realignment; does not change any rule
below). When a task assigns a specific gate:

1. Read this file (`AGENTS.md`) — the rules below always apply.
2. Read `docs/guardian/30_TDD/GUARDIAN_EXECUTION_PROTOCOL.md` — the
   short, universal per-task procedure (baseline verification, RED→GREEN,
   the mandatory Contract Collision preflight, scope discipline,
   evidence-by-ID, commit-state discipline).
3. Load exactly one assigned gate manifest under
   `docs/guardian/30_TDD/gates/*-manifest.toml` — it states that gate's
   owned normative IDs, allowed/forbidden scope, dependencies, required
   test layers, validation commands, and commit policy.
4. Read that manifest's linked, concise gate TDD file
   (`docs/guardian/30_TDD/gates/*-tdd.md`) — required observable behavior
   and acceptance evidence for that gate only.
5. Consult the large historical handoffs/ADRs under `docs/guardian/30_TDD/`
   and `docs/adr/` only when the manifest/TDD references them or when
   resolving a genuine ambiguity — they remain the authoritative
   planning/history/reference record, not an obligatory checklist to
   re-read on every implementation turn.

This does not apply to a gate that predates this workflow and has no
manifest yet (G0–G9, Wave 1, Phase 2 Gate 2a) — those remain governed
exactly as their own accepted handoffs specify.

## Source-of-governance order

When instructions appear to conflict, use this order:

1. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
2. Current assigned gate handoff under `docs/guardian/30_TDD/`
3. Accepted ADRs
4. `docs/guardian/00_Project/GUARDIAN_MASTER_SPEC.md`
5. Guardian wiki interpretation pages
6. External-source snapshots
7. Canonical external provider documentation

If an external provider contract appears to contradict Guardian documentation, do not silently choose one. Record the discrepancy as a contract/source-drift issue.

## Required lookup workflow

Before implementing behavior that depends on Ubuntu, systemd, D-Bus, polkit, UDisks, AccountsService, PSI, NetworkManager, or another external provider:

1. Open `docs/guardian/LOOKUP_MAP.md`.
2. Read the relevant Guardian feature/module page.
3. Read the relevant platform/provider page.
4. Follow the local external-source snapshot.
5. Recheck the canonical URL when the implementation depends on exact provider semantics and network access is available.
6. Link the resulting test/ADR/code comment to the governing Guardian concept or source where useful.

Do not guess an external provider contract.

## TDD rule

Write or activate the failing acceptance/contract test before production implementation for the assigned behavior.

All tests required by the currently assigned gate must pass before that gate is reported complete.

Never:
- delete a required test to obtain green;
- weaken a required assertion without a contract change;
- mark a failing required test ignored/skipped to claim gate completion;
- change expected behavior merely because the first implementation behaves differently.

If the contract itself is wrong or ambiguous, stop the affected path and report a contract issue.

## Gate discipline

Work only on the gate explicitly assigned in the current handoff.

Do not opportunistically implement later gates or deferred modules.

A later-gate feature that looks easy is still out of scope.

## Privilege rules

The following are prohibited unless a later governing contract explicitly changes them:

- running GUI/TUI/indicator clients as root;
- invoking `sudo` from GUI/TUI/indicator clients;
- exposing a public `RunCommand`, `RunShell`, arbitrary argv execution, or equivalent privileged command broker;
- trusting a client-supplied UID, PID, username, role, or `is_admin` flag as authorization evidence;
- bypassing polkit/provider arbitration for a system write;
- silently falling back to a more privileged path because a preferred provider failed.

All privileged public operations must be typed and bounded.

## System-provider rules

Preferred integration order:

1. native D-Bus/library API;
2. kernel interface (`/proc`, `/sys`, udev/netlink where applicable);
3. structured CLI;
4. scraped CLI only when no stronger supported interface exists.

Do not shell out to a CLI if the assigned provider contract requires a stable native API.

## Safety rules

Guardian fails closed for writes when:
- provider ownership is ambiguous;
- capability availability is unknown;
- preconditions changed;
- resource identity is stale;
- authorization is ambiguous or denied;
- rollback semantics are misrepresented;
- external contract drift affects the requested operation.

Do not convert UNKNOWN into HEALTHY.

Do not treat `/dev/sdX` or similar volatile names as persistent hardware identity.

## Evidence preservation

Guardian's normalized/deduplicated views never justify deleting authoritative raw journal evidence.

Critical recorder state must remain bounded.

Never make monitored removable storage the required live destination for Guardian's own critical incident recorder.

## No placeholders

Do not add fake production implementations, TODO-return-success behavior, or placeholder provider results that masquerade as working functionality.

A real explicit `Unsupported`/`Unavailable` result is preferred to a fake implementation.

Scaffolding is allowed only when it compiles, is truthful about availability, and is required by the current gate.

## Dependencies

Prefer Ubuntu-packaged or well-established open-source dependencies appropriate for Ubuntu 26.04.1.

Before adding a runtime dependency:
- explain why the standard library/current workspace/existing Ubuntu API is insufficient;
- check license and maintenance status;
- avoid adding a large framework for a small capability.

Test-only dependencies such as private D-Bus mocking or hardware mocking are allowed when they directly support the TDD contract.

## Commands and environment

Use the repository's documented toolchain and scripts.

Do not modify the host globally merely to make a test pass.

System-level tests that require real D-Bus, polkit, cgroups, display sessions, or destructive fault injection belong in the designated disposable Ubuntu 26.04.1 VM layer.

## Documentation and ADRs

When a gate requires an architectural decision, add/update the required ADR.

An ADR must include:
- context;
- decision;
- alternatives considered;
- evidence/tests;
- consequences;
- rollback/migration implications where relevant.

Do not rewrite historical accepted ADR rationale to hide an earlier decision; supersede it.

## Source contract drift

Provider fixtures should preserve provenance where the TDD contract requires it.

If installed D-Bus introspection or policy differs from the known fixture:
- report the drift;
- do not silently regenerate the fixture and continue;
- determine whether Guardian contracts/tests/ADRs require change.

## Completion report

Every coding-agent completion report must include:

### Governing scope
- assigned gate/batch;
- governing TDD sections/tests.

### Files changed
- added;
- modified;
- deleted.

### Tests
- commands run;
- passed/failed/skipped counts;
- any required test not executed and why.

### Evidence
- introspection fixtures;
- ADRs;
- security reports;
- provider provenance;
- VM evidence where applicable.

### Contract compliance
- deferred work not implemented;
- shortcuts explicitly avoided;
- any contract ambiguity or source drift found.

### Git state
- commit/hash if the workflow permits commits;
- untracked/uncommitted files;
- unrelated pre-existing changes left untouched.

A gate is not complete merely because the code compiles.
