# Guardian Phase 0 Implementation Handoff
## G1 — Identity & Authorization Only

**Audience:** Primary coding agent  
**Scope:** **G1 — Identity & Authorization** only  
**Stop condition:** G1 evidence/report complete. Do **not** begin G2, privilege topology, provider work, transactions, clients, or packaging.  
**Governing contract:** `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`  
**Prerequisite:** G0 tagged at `phase0-g0-public-contracts` (commit `15cdb787f99b4374f08a4c6bd3fe570f07f74960`). Confirm this tag exists and `HEAD` descends from it before starting.

---

# 1. Mission

Prove that Guardian identifies and authorizes callers correctly, before any privileged write path exists to protect.

G1 does not implement a privileged write operation. It implements the identity and
authorization *plumbing* — caller identity resolution, polkit subject construction,
the interactive/non-interactive distinction, and denial behavior — against a small
number of test-only actions, so the mechanism can be proven safe before it is
attached to anything that matters.

The desired result is a repository in which:

- Guardian resolves the authorization subject from the real D-Bus system-bus caller identity, never from client-supplied fields;
- a client cannot influence its own authorization by sending a UID, PID, username, or `is_admin` flag as method data;
- a denied polkit decision provably leaves test-provider state untouched;
- a non-interactive (background) request cannot trigger an interactive authentication prompt;
- an explicit user-initiated request can enter the interactive authentication flow;
- text authentication from a VT/recovery context is proven, not assumed;
- SSH authorization behavior is an intentional policy decision, not an accident of a missing graphical agent;
- `P0-AUTH-001..005` are green;
- no generic privileged command-execution surface has been introduced.

Then stop.

---

# 2. Read before changing code

Read in this order:

1. `AGENTS.md`
2. `docs/guardian/INDEX.md`
3. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
   - §2 Governing principles (GP-02, GP-03, GP-06, GP-10 especially)
   - §8 Caller identity and authorization
   - §9 polkit action taxonomy
   - §36 P0-AUTH-001..005
   - §38 G1
4. `docs/guardian/20_Control_Plane/Privilege_and_Authorization.md`
5. `docs/guardian/10_Platform/Polkit.md`
6. `docs/guardian/90_Sources/wiki/ubuntu-polkit-resolute.md`
7. `docs/guardian/90_Sources/wiki/ubuntu-pkttyagent.md`
8. `docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md` (for the namespace G1 code must build under)
9. `docs/evidence/g0/G0_MILESTONE.md`

Do not start provider, transaction, GUI, TUI, indicator, or recovery implementation in this batch. Do not start G2 privilege-topology prototyping (Model A/B comparison) — that is a separate gate with its own tests.

---

# 3. Scope boundary

## In scope

- A caller-identity resolution component that reads the actual system-bus unique name of the calling connection (not method arguments).
- A minimal polkit subject model built from that resolved identity.
- Test-only polkit actions equivalent to `guardian.test.read`, `guardian.test.low-risk-write`, `guardian.test.moderate-write`, `guardian.test.high-risk-write` (TDD contract §9), used only to exercise the authorization mechanism.
- The interactive-vs-noninteractive distinction: a flag or call-context that governs whether `AllowUserInteraction`-equivalent behavior may be requested, and proof that background/automatic code paths cannot set it.
- Denial-path proof: a denied decision must leave whatever minimal test-provider state exists completely unchanged.
- Text-agent (`pkttyagent`-equivalent) authentication proof from a VT/non-graphical context.
- An explicit, documented SSH authorization policy decision (allow, deny, or context-dependent) — not silence.

## Out of scope for this batch

- Any real privileged system-management action (storage, sessions, services, resources, USB, logs).
- Provider Arbitrator, Capability Registry, transaction engine, event/incident model.
- G2 privilege-topology prototypes (Model A / Model B). G1 must reuse the existing
  `guardian-daemon` process and current G0 execution model for the bounded G1
  authorization test surface. G1 must not choose, compare, prototype, or implement
  the eventual privilege-topology split — that decision belongs exclusively to G2.
  If minor test-only process setup is genuinely necessary, it must not become a
  production privilege-topology decision.
- GUI/TUI/CLI/indicator clients.
- Packaging, systemd unit hardening review (that is G2 §24).
- Changing the 17-error taxonomy or the two-method `Guardian1` public surface established in G0. If G1 needs new D-Bus surface (e.g., to expose the test actions), it must be additive within `Guardian1` or a clearly separate, clearly test-scoped interface — do not renumber or break the G0 contract.

A later-gate feature that looks easy is still out of scope (AGENTS.md, "Gate discipline").

---

# 4. Normative tests

From TDD contract §36:

### P0-AUTH-001 — caller identity cannot be spoofed
**Given** a client sends a method call with a UID/PID/role field in its arguments that differs from its real bus identity  
**When** Guardian resolves the authorization subject  
**Then** the resolved subject is derived only from the real system-bus caller identity; the supplied fields have no effect.

### P0-AUTH-002 — denied action does not apply
**Given** a polkit decision denies a test action  
**When** the client retries or the daemon handles the denial  
**Then** the test-provider's observable state is byte-for-byte unchanged from before the call.

### P0-AUTH-003 — background action cannot prompt
**Given** a request made in a non-interactive/background context  
**When** authorization is evaluated  
**Then** no interactive authentication prompt is triggered; the call fails closed instead.

### P0-AUTH-004 — explicit GUI-style action may prompt
**Given** a request explicitly marked as user-initiated  
**When** authorization requires interaction  
**Then** the request may enter the interactive authentication flow.

### P0-AUTH-005 — VT text auth
**Given** a VT/recovery-style non-graphical session  
**When** a test action requires authorization  
**Then** a text authorization agent can complete the authorization, proven on the real Ubuntu 26.04.1 target, not mocked.

All five must pass before G1 is reported complete. None may be skipped, weakened, or marked ignored (AGENTS.md, "TDD rule").

---

# 5. Test-layer split — this is the primary implementation discipline for G1

G1 is the first gate where Guardian's behavior genuinely depends on the host: real
system-bus caller identity and real polkit decisions cannot be produced by a private
`dbus-daemon --session` the way G0's contract tests were. Split the work accordingly.

## 5.1 Pure / private-bus tests (run anywhere, including this workstation)

Suitable for, and REQUIRED to cover:

- caller-identity extraction logic (parsing/resolving a unique bus name from a connection, independent of whether that connection is on the real system bus);
- spoof resistance — constructing a method call with attacker-supplied identity fields and proving the resolver ignores them;
- the interactive/noninteractive flag's plumbing — proving a background code path structurally cannot set the interactive flag, via a private bus and a mocked/fake polkit decision function;
- mocked authorization decisions (allow/deny) and proving a denial leaves a test double's state untouched;
- unit tests for the polkit subject-model construction (the data shape, not a live polkit call).

These belong in `guardian-core` and/or `guardian-daemon` test suites and must not require the real system bus, real polkit, or root.

## 5.2 Disposable Ubuntu 26.04.1 VM tests (required, not optional, for G1 completion)

Required for anything that cannot be honestly proven without the real stack:

- **P0-AUTH-001** in its strongest form: a real system-bus client with a real distinct unique name, proving Guardian's resolved subject matches that real identity and ignores forged argument fields.
- **P0-AUTH-002**: a real polkit action definition, a real denial (e.g. via a restrictive polkit rule or an explicit test user with no grant), and inspection of real test-provider state before/after.
- **P0-AUTH-003 / P0-AUTH-004**: real graphical vs. non-interactive `AllowUserInteraction` behavior — this cannot be faked on a headless dev box.
- **P0-AUTH-005**: `pkttyagent` (or the equivalent supported text agent) actually completing authentication from a real VT.
- SSH policy: an actual SSH session attempting the test action, to prove the documented policy (§8.5) is what actually happens, not merely what is intended.

Do not attempt to simulate a real polkit authorization decision or a real graphical
prompt with a mock and call that sufficient for G1 completion — AGENTS.md prohibits
placeholder results that masquerade as working functionality, and a mocked "prove"
of a host-dependent behavior is exactly that. Layer 1 (§5.1) proves the logic;
Layer 2 (§5.2) proves the host integration. G1 needs both.

If VM access is not available when this handoff is picked up, implement and fully
green the Layer 1 (private-bus) tests, then stop and report exactly which P0-AUTH
tests remain unproven and why — do not report G1 complete on Layer 1 alone.

---

# 6. Authorization-outcome error mapping

G1 must not invent public error semantics. Every authorization outcome maps to one
of the 17 existing `GuardianDbusError` categories (`crates/guardian-core/src/error.rs`).
Do not add a new public error category unless this mapping proves the existing
taxonomy genuinely cannot express a required outcome — if that happens, stop and
report the gap rather than adding one unilaterally.

**Authorization explicitly denied**
Examples: polkit returns a definitive denial; the caller is authenticated/known but
lacks permission for the requested action.
Return: `NotAuthorized`.

**Authentication mechanism unavailable**
Examples: interactive authentication is legitimately allowed for this request, but
no usable authentication mechanism/agent is available; polkit cannot provide the
required authentication path.
Return: `AuthenticationUnavailable`.

**Background/non-interactive request cannot prompt**
A background/non-interactive request that would require interactive authentication
must never open graphical authentication, never open text authentication, and fail
closed instead.
Return: `NotAuthorized`, with structured internal/reason metadata distinguishing
`interaction-required-but-disallowed` (or an equivalent internal reason) from an
ordinary denial. The *public* error stays `NotAuthorized` for this condition during
G1 — do not add a new public D-Bus error solely to distinguish it; the reason
explains why.

**Invalid/spoofed identity data supplied by client**
Client-supplied UID/PID/username/role fields never establish identity. If such data
is merely present and ignored because identity is derived from the real D-Bus
caller, authorization proceeds normally using the true caller — this is not an
error condition by itself. If the request format itself violates a typed method
contract (malformed/wrong-typed arguments), use the existing request-validation
behavior for that (e.g. `InvalidRequest`) rather than treating the spoofed identity
data as if it were authoritative or as a special error case.

**Provider/system failure**
Do not misreport provider, transport, or internal failures as authorization
denials. Use the existing corresponding typed error category (e.g.
`ProviderUnavailable`, `Internal`) so a real failure is never disguised as a
security decision, and a security decision is never disguised as a transient fault.

---

# 7. Authorization-before-mutation ordering (hard invariant)

G1's test actions must follow this order, with no exceptions:

```text
receive request
→ resolve actual D-Bus caller
→ validate request/preconditions needed for authorization
→ perform authorization decision
→ only if authorized may the bounded test mutation/action execute
```

A denied or unavailable authorization result must produce **zero provider mutation**
and **zero system mutation** — not a mutation followed by a rollback, and not a
side effect (including logging a state change, not just an audit-trail entry)
that occurs before the authorization decision is reached. `P0-AUTH-002` must prove
this ordering directly, not merely prove that the end state matches the start
state by coincidence of a mock's implementation. Do not rely solely on the
independent-review handoff to catch a mutation-before-authorization bug — this
ordering is a requirement of the implementation itself, not just a review
checklist item.

---

# 8. Caller-identity lifetime and staleness

- Authorization identity is resolved from the caller associated with the *current*
  D-Bus message/connection, at the time of that call — never cached from an earlier
  call and reused.
- Guardian must not cache a D-Bus unique-name → identity relationship beyond the
  lifetime/context in which it is valid.
- A disconnect/reconnect, or a bus name owner change, invalidates any stale
  caller-identity state; a subsequent call must re-resolve identity from the bus,
  not from memory.
- Client-supplied identity data never repairs or replaces stale bus identity — if
  the resolved caller identity is stale or unavailable, the request fails closed
  (see §6), it does not fall back to anything the client supplied.

This is a G1 identity-correctness rule, not a G2 privilege-topology decision — it
does not require deciding how the daemon process itself is structured.

---

# 9. Privilege rules that apply directly to this batch

From AGENTS.md, restated because G1 is where they first bite:

- Never trust a client-supplied UID, PID, username, role, or `is_admin` flag as authorization evidence — this is the literal subject of P0-AUTH-001.
- Do not bypass polkit/provider arbitration for a system write. G1 has no real writes yet, but the test actions must still go through the same authorization path a real write would use, so the mechanism is actually being proven.
- Do not silently fall back to a more privileged path because a preferred provider or auth mechanism failed. If the text agent or graphical agent is unavailable, the action fails closed with a typed error, not a silent bypass.
- All privileged public operations must be typed and bounded — no generic `RunCommand`/`RunShell`/argv-passthrough, including for test actions.

---

# 10. Completion report

Follow the AGENTS.md "Completion report" structure (governing scope; files changed;
tests; evidence; contract compliance; git state), plus:

- explicit P0-AUTH-001..005 pass/fail/not-yet-proven table;
- which tests ran on this workstation (Layer 1) vs. in the disposable VM (Layer 2);
- if any Layer 2 test could not be run, say so plainly rather than reporting G1 complete;
- confirmation that the §6 error mapping, §7 ordering invariant, and §8 identity-lifetime rule were followed, with the specific test(s) that prove each.

Do not tag a G1 milestone yourself. Stop and hand off for independent review per
`docs/guardian/30_TDD/GUARDIAN_G1_INDEPENDENT_REVIEW_HANDOFF.md`.
