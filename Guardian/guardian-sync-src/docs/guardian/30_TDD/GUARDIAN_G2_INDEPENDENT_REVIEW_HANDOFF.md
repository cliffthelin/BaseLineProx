# Guardian G2 Independent Review Handoff
## Read-only architecture/evidence audit after the primary coding agent completes G2 — Privilege Topology

**Recommended reviewer:** Claude Code in plan/read-only review mode, or another independent coding agent  
**Do not modify code during the first review pass.**

---

# Mission

Audit the primary agent's G2 privilege-topology decision against Guardian's
governing contract.

The reviewer is not being asked whether the ADR reads convincingly. It must
determine whether both topologies were genuinely, fairly evaluated with real
evidence, whether the selected model (if any) actually preserves G0's public
contract and G1's authorization invariants across the privilege boundary,
and whether the evidence is real rather than modeled or asserted.

G2 is the gate where "we measured it" is easy to fake and expensive to get
wrong: a privilege-topology decision made on weak evidence becomes the
foundation every later provider, transaction, and write path builds on. A
plausible-sounding ADR with mocked or absent host evidence is a failure of
this gate, not a pass with caveats.

---

# Read first

1. `AGENTS.md`
2. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` (§2, §6, §7, §8, §9, §24, §25, §36 P0-PRIV, §38 G2)
3. `docs/guardian/30_TDD/GUARDIAN_G2_IMPLEMENTATION_HANDOFF.md`
4. `docs/guardian/30_TDD/GUARDIAN_G1_IMPLEMENTATION_HANDOFF.md` §6–§8 (the authorization abstractions G2 must preserve)
5. `docs/evidence/g1/G1_MILESTONE.md` and the `phase0-g1-identity-authorization` tag (confirm G2 work descends from it and did not silently reopen G1)
6. `docs/adr/ADR-002-guardian-privilege-topology.md`
7. `docs/evidence/g2/` in full, including any raw `systemd-analyze security` output and VM transcripts
8. Primary agent's completion report and diff

---

# Audit questions

## Fair comparison

- Were both Model A and Model B actually built to the point of producing
  real measurements, or was one sketched while the other was fully
  prototyped?
- Does the ADR's "Rejected alternatives" section read as a genuine
  comparison, or as post-hoc justification for a conclusion reached first?
- Was the winner effectively preselected by which model got more
  implementation effort before the comparison was written?

## Privilege inventory

- Does the Privilege Requirement Inventory (TDD contract §26 areas, plus
  the fuller list in the implementation handoff §5) cover the required
  capability areas, or are several silently missing?
- Are unknowns marked honestly ("unknown — requires host research") rather
  than guessed?
- Does the inventory actually drive the capability-bounding decisions for
  both models, or is it decorative?
- Where a capability area is classified `Guardian polkit authorization`, was it
  checked whether the underlying provider actually performs its own
  authorization (making it `provider-owned authorization`, needing no
  Guardian privilege at all), rather than defaulting to the more privileged
  classification out of convenience?

## Capability justification

- Is every proposed Linux capability tied to a specific inventoried need,
  with a stated reason a narrower alternative doesn't suffice?
- Is `CAP_SYS_ADMIN` (or an equivalently broad capability) proposed without
  being treated as functionally equivalent to root? Any such proposal
  without exceptional, itemized justification is a blocking finding.
- Is full root proposed anywhere without first showing that no capability
  subset was sufficient?
- Do the individually-justified exceptions (capabilities, hardening
  weakenings, `ReadWritePaths=` grants), taken together, add up to
  something functionally close to unrestricted access for the selected
  model? Per-item justification satisfied while the cumulative result
  defeats minimization is itself a blocking finding, not a pass with
  caveats (implementation handoff §12, "Privilege creep is an architectural
  signal").

## Helper design (Model B, if built)

- Does the helper's D-Bus surface consist of individually typed, bounded
  methods, or does it contain anything resembling `RunCommand`/`RunShell`/
  `Execute(argv)`/a generic "apply this operation" method?
- Does the helper perform its **own** `CheckAuthorization` against real
  polkit using the real caller identity it itself resolved, or does it
  trust a UID/username/`authorized=true` claim forwarded by the
  unprivileged core?
- Is there a described or tested TOCTOU window between the core's decision
  and the helper's apply?
- Could the helper, as designed, be driven to perform an operation nobody
  explicitly authorized, by a compromised or merely buggy core?

## Authorization/error semantics across the boundary

- Does `AuthorizationOutcome` vs. `AuthorizationError`'s separation (from
  G1) survive into any Model B design, or does a "helper unavailable"
  condition get silently folded into an existing category?
- If Model B was built far enough to need helper-unavailable semantics, are
  they deterministic and typed, or ad hoc?

## systemd hardening evidence

- Is `systemd-analyze security` output present for each real systemd unit
  actually built, or merely described/estimated?
- For each hardening directive claimed compatible or incompatible, is there
  a stated reason grounded in the §5 inventory, or an unexplained assertion?
- Are exceptions distinguished as temporary vs. architectural, per the
  implementation handoff §11?
- Is there any evidence a hardening directive was disabled specifically to
  make a test pass, rather than because of a genuine, documented
  incompatibility?

## Transaction and failure-containment analysis

- Is the answer to "who owns snapshot/authorize/apply/observe/rollback"
  concrete and specific to the actual prototype built, or generic boilerplate
  that could apply to any architecture?
- Were the failure scenarios in the implementation handoff §14 actually
  reasoned through per model, or handwaved?
- Is any failure scenario claimed "tested" that could not plausibly have
  been tested on a disposable VM (e.g. an actual mid-write host reboot)? If
  so, was it honestly labeled as reasoned-about rather than executed?

## Host evidence provenance

- Are VM setup scripts and raw transcripts committed under `docs/evidence/g2/`,
  reproducible the same way `docs/evidence/g1/g1-layer2-vm-setup.sh` is?
- Does the evidence show real distinct systemd units, real capability sets
  tested (not just declared in a unit file that may never have actually
  been loaded), and real `systemd-analyze security` runs?
- Is there any place where "the daemon started successfully" is presented
  as proof a capability set is sufficient, without also proving the bounded
  test write actually succeeded under that capability set?

## G0/G1 regression protection

- Does G0's public D-Bus surface remain exactly `ContractVersion`/
  `ServiceState`?
- Do G1's `AuthorizationOutcome`/`AuthorizationError` types remain intact
  (extended for a Model B helper boundary only if genuinely needed, never
  collapsed back together)?
- Does the real caller-identity-resolution invariant from G1 (never trust a
  client-supplied UID/PID/username/role) survive across any new privilege
  boundary Model B introduces?

## Scope

- Did G3 (Capability Registry, Provider Arbitrator), G4 (transaction
  engine), or any real provider implementation leak into this batch, beyond
  the single bounded test write each model needed to be measurable?
- Was any client (GUI/TUI/CLI), packaging, or recovery-target work started?
- Is there a permanent helper API committed to production code without its
  own explicit statement that it still needs a dedicated future security
  review?

---

# Required reviewer output

## Verdict

One of:

```text
PASS
PASS WITH NON-BLOCKING FINDINGS
FAIL — CONTRACT VIOLATION
FAIL — PRIVILEGE EVIDENCE INSUFFICIENT
FAIL — SCOPE LEAK
FAIL — PRESELECTED TOPOLOGY
FAIL — GENERIC PRIVILEGED BROKER
FAIL — CONFUSED-DEPUTY BOUNDARY UNSAFE
FAIL — PRIVILEGE CREEP
```

`FAIL — PRIVILEGE EVIDENCE INSUFFICIENT` applies whenever real host/systemd
evidence was substituted with mocks, assertions, or reasoning presented as
measurement — this is the G2 analogue of G1's
`FAIL — HOST-DEPENDENT PROOF MISSING OR FAKED`, and should be used with the
same rigor.

`FAIL — PRESELECTED TOPOLOGY` applies when the comparison reads as
justification for a conclusion reached before both models were fairly
built and measured.

`FAIL — GENERIC PRIVILEGED BROKER` applies when any helper (or daemon)
method — regardless of name — accepts an argument shape that lets a caller
reach an arbitrary filesystem path, sysfs/procfs node, D-Bus destination,
provider name with an opaque payload, or action name whose implementation
isn't closed and typed. Use this specific verdict rather than folding it
into `FAIL — CONTRACT VIOLATION`, so the failure class is unambiguous.

`FAIL — CONFUSED-DEPUTY BOUNDARY UNSAFE` applies when a Model B helper
trusts a caller-identity or authorization claim forwarded by the core
instead of independently resolving and authorizing, or when a TOCTOU window
exists between the core's decision and the helper's apply that the
implementation did not close.

`FAIL — PRIVILEGE CREEP` applies when the individually-justified
capabilities/hardening-exceptions/writable-paths, taken together, amount to
something functionally close to unrestricted access for the selected
model — even if every individual item was properly documented (implementation
handoff §12, "Privilege creep is an architectural signal").

## Blocking findings

For each:
- file/path;
- contract/test ID (P0-PRIV-00N) or ADR section;
- problem;
- why it matters (privilege-escalation/confused-deputy/evidence-integrity
  risk, not just style);
- exact required correction.

## Non-blocking findings

Same structure, explicitly marked non-blocking.

## Adversarial question audit

Explicitly state whether the design (as evidenced, not as claimed) withstands
each of the following. Answer each with a specific pointer to the evidence
or code that settles it, not a general assurance:

1. Unprivileged core sends a forged UID to the helper — does the real
   caller identity still win?
2. Core claims a caller is authorized without proof — does the helper
   perform its own `CheckAuthorization` regardless?
3. Helper receives something resembling arbitrary command/argv — is this
   structurally impossible, or merely avoided by convention?
4. A new helper method is added without independent authorization — is
   there a structural guard, or only a code-review convention?
5. Helper crashes after a write completes but before acknowledging the
   core — what does the evidence say happens to transaction state?
6. Core (daemon) crashes while the helper is mid-mutation — same question.
7. A stale authorization decision is reused for a later call — is identity/
   authorization re-resolved per call (per G1's identity-lifetime rule), or
   could a helper cache a decision across calls?
8. A provider outage is misreported as a denial — does the
   `AuthorizationOutcome`/`AuthorizationError` (or equivalent) separation
   actually hold at the helper boundary, or collapse?
9. systemd restarts one component (core or helper) independently — could
   this create two writers active simultaneously for the same capability
   (violating the single-writer rule)?
10. Is any proposed capability set broader than the §5 inventory justifies
    for the actual bounded test write performed?
11. Was any systemd hardening directive disabled specifically to make a
    test pass, rather than for a genuine documented incompatibility?
12. Could a privileged process (daemon or helper) unexpectedly read outside
    its required scope (e.g. a user's home directory) given the tested
    `ProtectHome=`/`ReadWritePaths=` configuration?
13. Could the helper, as designed, be driven by any client to perform an
    operation equivalent to a general-purpose root command broker — even
    indirectly, through some combination of its typed methods, or through a
    method whose name avoids `RunCommand`/`RunShell`/`Execute` but whose
    argument shape is functionally equivalent — e.g. `WriteFile(path, bytes)`,
    `SetSysfs(path, value)`, `CallDbus(service, path, method, args)`,
    `ExecuteProvider(name, opaque_payload)`, `Invoke(action_name, arbitrary_json)`?
    A name-only blacklist check is insufficient here — evaluate whether the
    method's *argument shape* lets a caller reach anywhere in the
    filesystem/device tree/D-Bus namespace it wants merely by varying an
    argument.
14. Is any capability area classified `provider-owned authorization`
    (needing no Guardian privilege at all) actually double-checked against
    the provider's real D-Bus interface, or is it asserted without
    verifying the provider genuinely performs its own authorization? The
    reverse error also counts: is an area that's genuinely provider-owned
    incorrectly classified as needing Guardian-held privilege, inflating
    the measured privilege requirement for one or both models?
15. If a core-to-helper (or equivalent split) request is retried after a
    timeout — because the core never received the helper's acknowledgment —
    could the helper apply the same mutation twice? Is this risk assessed
    even though full idempotency-key handling belongs to G4?
16. After a restart of either component, could both processes end up
    believing they hold write authority for the same capability
    simultaneously — distinct from whether a restart merely spawns a
    second writer process? Does write-authority state get re-derived on
    restart, or does it persist unsafely across one?

## Test-quality audit

Table:

| Contract test | Strong enough? | Real host evidence? | Review note |
|---|---|---|---|

Cover P0-PRIV-001..003.

## Scope audit

Explicitly state whether G3/G4/provider/client/packaging work leaked into
G2.

## Recommended next action

One of:
- repair findings and re-review;
- accept G2 and prepare G3 handoff;
- gather the specific missing host evidence before G2 can pass;
- resolve the specific contract ambiguity found before G2 can proceed.

---

# Rule

Do not approve G2 because the ADR is well-written and internally consistent
if the evidence behind it is thin, modeled, or asserted rather than
genuinely measured on real systemd/polkit/capabilities in the disposable
VM. A confident-sounding privilege-topology decision built on weak evidence
is more dangerous than an honestly reported `G2 BLOCKED` — every later gate
inherits this one's mistakes.
