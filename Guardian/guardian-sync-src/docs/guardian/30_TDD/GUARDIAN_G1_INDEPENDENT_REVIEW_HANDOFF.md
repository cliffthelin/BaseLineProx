# Guardian G1 Independent Review Handoff
## Read-only contract audit after the primary coding agent completes G1 — Identity & Authorization

**Recommended reviewer:** Claude Code in plan/read-only review mode, or another independent coding agent  
**Do not modify code during the first review pass.**

---

# Mission

Audit the primary agent's G1 implementation against Guardian's governing contract.

The reviewer is not being asked whether the code "looks good."

The reviewer must determine whether the implementation actually proves that
Guardian identifies and authorizes callers safely — using the real system-bus
caller identity, never client-supplied claims — without weakening the contract
or leaking into G2+ work.

G1 is higher-stakes to review than G0: it is the last gate before privileged
write paths can plausibly be attached to anything. A test-quality gap here is
a real authorization bypass waiting to happen, not a cosmetic contract slip.

---

# Read first

1. `AGENTS.md`
2. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` (§2, §8, §9, §36 P0-AUTH, §38 G1)
3. `docs/guardian/30_TDD/GUARDIAN_G1_IMPLEMENTATION_HANDOFF.md`
4. `docs/guardian/20_Control_Plane/Privilege_and_Authorization.md`
5. `docs/guardian/10_Platform/Polkit.md`
6. `docs/evidence/g0/G0_MILESTONE.md` and the `phase0-g0-public-contracts` tag (confirm G1 work descends from it and did not silently reopen G0)
7. Primary agent's completion report and diff

---

# Audit questions

## Identity and spoof resistance

- Is the authorization subject actually derived from the real D-Bus system-bus unique connection name, or from something the client can influence?
- Does any code path read a client-supplied UID, PID, username, role, or `is_admin`-equivalent field and let it affect the authorization outcome, even as a fallback or default?
- Is there a real test (not just a unit test against a mock) that sends a forged identity field over an actual connection and proves it has zero effect?
- Per G1 handoff §8: is caller identity re-resolved from the current message/connection on every call, with no cross-call caching of a unique-name → identity mapping? Does a disconnect/reconnect or bus-name owner change genuinely invalidate any prior resolved identity, rather than being untested?

## Denial behavior and error mapping

- When a decision is denied, is the test-provider's state verified unchanged (not merely "the call returned an error")?
- Could a partial side effect occur before the denial is evaluated? (Validate-then-authorize ordering matters — GP-05/GP-06, and is now a hard invariant in G1 handoff §7: resolve caller → validate → authorize → only then mutate.) Does at least one test exercise this exact ordering directly, not just compare before/after state that a buggy mutate-then-rollback implementation could also pass?
- Does the implementation follow the G1 handoff §6 error mapping exactly: explicit denial → `NotAuthorized`; authentication mechanism unavailable → `AuthenticationUnavailable`; background/non-interactive request blocked from prompting → `NotAuthorized` (with internal reason metadata, not a new public error); spoofed-but-ignored identity data → no error by itself; provider/system failure → the corresponding existing category, never disguised as an authorization outcome?
- Was any new public D-Bus error category introduced for G1? If so, does the completion report show the existing 17 categories were genuinely insufficient, per handoff §6's instruction to report the gap rather than add one unilaterally?

## Interactive vs. non-interactive

- Is there a genuine structural barrier preventing a background/automatic code path from requesting interactive authentication, or merely a convention/comment?
- Does the explicit user-initiated path exist and is it distinguishable in code from the background path, not just by an ignored parameter?

## Host-dependent proof (the part most likely to be faked)

- Is P0-AUTH-001 proven with a real second bus connection with a genuinely different unique name, or does the test smuggle the "different identity" through the same connection?
- Is P0-AUTH-004/005 proven against real polkit / a real text agent on Ubuntu 26.04.1, or is a graphical/text prompt merely asserted to have been "requested" without ever completing?
- Is the VM evidence (§5.2 of the G1 handoff) actually present — logs, transcripts, or a described real run — or is it asserted without evidence?
- If any Layer 2 (VM) test was not actually run, does the completion report say so honestly, or does it claim G1 complete anyway?

## polkit action taxonomy

- Do the test actions match the granularity required by TDD contract §9 (`guardian.test.read` / `.low-risk-write` / `.moderate-write` / `.high-risk-write`), or was a single catch-all action used, which would fail to prove granular authorization actually works?
- Does granting a low-risk action leave high-risk actions denied?

## SSH policy

- Is the SSH authorization behavior documented as a deliberate decision (with rationale), or is it whatever happened to occur because a graphical agent was absent?

## Scope

- Was any G2 privilege-topology decision (Model A vs. Model B) made or assumed here, beyond the minimum needed to host G1's test actions?
- Was any real provider, transaction, GUI/TUI/CLI/indicator, or packaging code introduced?
- Did the G0 two-method public surface or 17-error taxonomy change without a governing reason?
- Are there fake placeholder implementations reporting success (e.g., an authorization check that always returns "authorized" in a mode meant to look real)?

## Repository quality

- Is identity/authorization logic in an appropriate shared location (`guardian-core` or equivalent), not duplicated per-crate?
- Are unrelated files (G0 evidence, ADR-001, prior handoffs) left untouched except where a genuine G1-driven correction is needed?

---

# Required reviewer output

## Verdict

One of:

```text
PASS
PASS WITH NON-BLOCKING FINDINGS
FAIL — CONTRACT VIOLATION
FAIL — TEST INSUFFICIENT
FAIL — HOST-DEPENDENT PROOF MISSING OR FAKED
FAIL — SCOPE LEAK
```

`FAIL — HOST-DEPENDENT PROOF MISSING OR FAKED` is its own category, separate from
generic test insufficiency, because G1's real-world proof is the entire point of
the gate — a private-bus mock cannot stand in for it.

## Blocking findings

For each:
- file/path;
- contract/test ID (P0-AUTH-00N);
- problem;
- why it matters (spoofing/bypass risk, not just style);
- exact required correction.

## Non-blocking findings

Same structure, explicitly marked non-blocking.

## Test-quality audit

Table:

| Contract test | Strong enough? | Proven on real host? | Review note |
|---|---|---|---|

Cover P0-AUTH-001..005.

## Scope audit

Explicitly state whether G2+ privilege-topology or any provider/transaction/client
work leaked into G1.

## Recommended next action

One of:
- repair findings and re-review;
- accept G1 and prepare G2 handoff;
- rerun specific P0-AUTH tests in the disposable VM before G1 can pass.

---

# Rule

Do not approve G1 because "all tests pass" if the host-dependent tests were mocked
instead of genuinely run against real polkit and a real system-bus caller identity.
A green private-bus suite proves the logic is internally consistent; it does not
prove the authorization boundary actually holds on the real system.
