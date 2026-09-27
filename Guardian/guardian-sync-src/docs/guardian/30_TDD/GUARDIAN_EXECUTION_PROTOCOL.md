---
title: "Guardian Execution Protocol"
kind: "tdd-protocol"
status: "active"
last_reviewed: "2026-09-06"
tags:
  - tdd
  - protocol
  - gates
---
# Guardian Execution Protocol

This is the universal, per-task procedure for governed Guardian work. It
does not restate `AGENTS.md` (TDD discipline, gate discipline, privilege
rules, evidence/completion-report requirements, stop-on-contract-
ambiguity, etc.) — read `AGENTS.md` first; everything here assumes it.
This file exists so a task prompt only has to state *today's delta*: the
gate manifest and its linked gate TDD carry ownership, scope, and
acceptance evidence.

**Rule of placement**, used throughout this repository's governance
material: universal procedure → this file; gate-specific ownership/
boundaries → the gate's manifest (`docs/guardian/30_TDD/gates/*.toml`);
observable required behavior → the gate's TDD (`docs/guardian/30_TDD/
gates/*-tdd.md`); optional/non-blocking concern →
`GUARDIAN_HARDENING_BACKLOG.md`; today's requested work → the task
prompt itself. Nothing normative lives in more than one of these places.

## Procedure

1. **Load the assigned gate manifest and TDD.** Read exactly one
   `docs/guardian/30_TDD/gates/<gate>-manifest.toml` and the concise
   gate TDD it references (`tdd_file`). Do not load or act on any other
   gate's manifest.
2. **Verify baseline.** Confirm the working tree is at the manifest's
   `baseline_sha` (or a descendant it names as acceptable) and that
   running the manifest's `validation_commands` against the unmodified
   baseline matches the expected counts the manifest/task states. If it
   does not match, stop and reconcile before making any change.
3. **RED → GREEN where implementation is involved.** Activate or write
   the failing test for the manifest's `owned_normative_ids` before
   writing the corresponding production code. Do not write production
   code first and backfill a test.
4. **Build a Contract Collision Table before editing any code.** See
   "Contract Collision preflight" below. This step is mandatory and
   comes before the first production-code edit, not after.
5. **Stop rather than invent a reconciliation.** If the Contract
   Collision Table (or anything else encountered during the work)
   surfaces two authoritative requirements assigning incompatible
   ownership, privilege, lifecycle, module, or gate responsibility: stop
   the affected path and report the collision. Do not silently pick a
   side.
6. **Stay inside the assigned gate's scope.** Touch only the manifest's
   `allowed_scope`; never touch its `forbidden_scope` or another gate's
   files, even when a fix looks trivial or obviously correct.
7. **Enumerate actual Git changes at completion.** Run the real
   diff/status yourself (`git status`, `git diff --stat`) — do not
   reconstruct the changed-file list from memory of what you intended to
   touch. Independent reviewers MUST derive the actual changed-file set
   from Git, review every actual changed file, and treat the
   implementer's inventory as navigation rather than evidence.
   Reviewers MUST rerun the gate's required validation/evidence rather
   than relying on reported results.
8. **Validate.** Run every command in the manifest's
   `validation_commands` and record the actual output/counts.
9. **Return evidence by normative ID.** For each ID in
   `owned_normative_ids`, cite the specific test(s) or artifact that
   proves it — never a narrative summary in place of a citation.
10. **Route non-blocking findings to the hardening backlog, not the
    active gate.** A real but non-blocking defect, gap, or improvement
    found along the way goes into `GUARDIAN_HARDENING_BACKLOG.md`, not
    into scope-creep on the current gate and not silently dropped.
11. **Obey the commit/tag state the manifest's `commit_policy`
    requests** (normally: leave uncommitted for independent review).
    Do not commit, tag, or push beyond what the manifest and the task
    prompt explicitly authorize.

## Contract Collision preflight (mandatory)

Before editing any code for the assigned gate, produce this table for
every requirement the current gate actually owns (not the whole
repository's history):

| Requirement | Owner | Module/path | Potential conflict | Contract resolution |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

**Binding rule:** if two authoritative requirements assign incompatible
ownership, privilege, lifecycle, module, or gate responsibility — STOP.
Do not invent a reconciliation.

This preflight exists specifically to catch defects like TDD-contract
Phase 2's `P2-REC-003` library-vs-daemon logging collision *before*
implementation, not after: the published handoff described a
`CapacityRejected` outcome's observability mechanism in a way that did
not state which crate performs the daemon-shaped `eprintln!` I/O,
letting an implementer place it inside `guardian-core` (a library crate)
— a real layering/gate-ownership violation, caught only by independent
review after the fact. A Contract Collision Table completed before
editing would have surfaced "counter + log line" assigned to one
requirement ID spanning two different gates' owned modules as a
conflict to resolve before writing code, not after.
