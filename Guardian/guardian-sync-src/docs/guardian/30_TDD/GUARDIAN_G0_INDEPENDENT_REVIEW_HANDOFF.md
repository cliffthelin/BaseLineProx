# Guardian G0 Independent Review Handoff
## Read-only contract audit after the primary coding agent completes Bootstrap + G0

**Recommended reviewer:** Claude Code in plan/read-only review mode, or another independent coding agent  
**Do not modify code during the first review pass.**

---

# Mission

Audit the primary agent's Bootstrap + G0 implementation against Guardian's governing contract.

The reviewer is not being asked whether the code "looks good."

The reviewer must determine whether the implementation actually proves **G0 — Public Contracts** without weakening the contract or leaking into later gates.

---

# Read first

1. `AGENTS.md`
2. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
3. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_IMPLEMENTATION_HANDOFF.md`
4. `docs/guardian/20_Control_Plane/D-Bus_API_Contract.md`
5. `docs/guardian/20_Control_Plane/Source_Contract_Drift.md`
6. `docs/guardian/10_Platform/D-Bus.md`
7. `docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md`
8. Primary agent's completion report and diff

---

# Audit questions

## Contract

- Is the exported D-Bus object really introspected from a live test service?
- Does every public interface carry an explicit major version?
- Is the namespace legitimate, or did the implementer invent reverse-DNS ownership?
- Does the interface contain any generic command/shell/argv execution path?
- Are unknown methods handled without crashing the service?
- Are public error categories stable and typed?
- Does provider provenance preserve unknown fields honestly?
- Does drift detection distinguish match/drift/missing/invalid or equivalent states?

## TDD quality

- Do tests enforce behavior, or merely restate production constants?
- Was a hand-written expected introspection file compared to itself?
- Can the "no generic command" test catch future additions?
- Can the drift test actually fail when fixture content changes?
- Are any required tests skipped/ignored?
- Were assertions weakened relative to the TDD contract?

## Scope

- Was G1 authorization logic started prematurely?
- Were future provider/client crates added without current-gate need?
- Are there fake placeholder implementations reporting success?
- Did the primary agent add unnecessary dependencies?

## Safety

- Is there any root/sudo/client-side privileged shortcut?
- Is raw provider output exposed as the stable public error API?
- Does unknown/invalid state fail honestly rather than map to healthy/success?

## Repository quality

- Is the workspace minimal but extensible?
- Are shared contract types in appropriate shared crates?
- Is documentation linked to the wiki/TDD sources?
- Are unrelated user files untouched?

---

# Required reviewer output

## Verdict

One of:

```text
PASS
PASS WITH NON-BLOCKING FINDINGS
FAIL — CONTRACT VIOLATION
FAIL — TEST INSUFFICIENT
FAIL — SCOPE LEAK
```

## Blocking findings

For each:
- file/path;
- contract/test ID;
- problem;
- why it matters;
- exact required correction.

## Non-blocking findings

Same structure, explicitly marked non-blocking.

## Test-quality audit

Table:

| Contract test | Strong enough? | Review note |
|---|---|---|

Cover:
- P0-DBUS-001..005
- P0-REG-003..004

## Scope audit

Explicitly state whether G1+ work leaked into G0.

## Namespace audit

State whether the chosen permanent namespace has legitimate ownership/provenance.

## Recommended next action

One of:
- repair findings and re-review;
- accept G0 and prepare G1 handoff;
- resolve owner namespace decision before G0 can pass.

---

# Rule

Do not approve G0 because "all tests pass" if the tests fail to enforce the actual governing contract.
