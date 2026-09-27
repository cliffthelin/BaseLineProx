# Guardian Phase 0 Independent Review Handoff
## G7 — Production Daemon Only

# Revision note (preserved history — read before §1)

This handoff was revised once, before any G7 code was written, alongside
the implementation handoff, following an independent planning review's
verdict:

```text
FAIL — G7 ARCHITECTURAL ROLE AMBIGUITY
```

The blocking finding was that the implementation handoff did not resolve
how the daemon's transaction-engine wiring would reach a privileged
`Apply` step without relaying the client's request through the daemon to
the helper — reproducing the exact confused-deputy shape `ADR-002`
rejected during G2. The implementation handoff's new §2 resolves this
with an explicit operation-class architecture (Class A/B/C), a direct-
call invariant stated in its own text, and a transaction stage-ownership
matrix per class. This revision adds §6a below, requiring the reviewer to
independently prove that resolution actually holds in the real running
system, not merely that the handoff now describes it correctly on paper.

# 1. Baseline verification

```bash
git status
git rev-parse HEAD
git diff --name-status <accepted-G6-tag-SHA>..HEAD
git diff --stat <accepted-G6-tag-SHA>..HEAD
```

Baseline is `phase0-g6-indicator-decision` (985a04d9a9af24cf9201d9dbeb1
ebbbea762a139). Independently re-derive this SHA from `git rev-parse
phase0-g6-indicator-decision^{commit}` rather than trusting a pasted
value. Confirm `phase0-g6-indicator-decision` and every earlier
`phase0-g*` tag are unmoved. Review every actual changed file — do not
sample.

# 2. Governing material to read

```text
AGENTS.md
docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md  (§7, §14, §23,
  §24, §25, §37, §38 G7 entry, §39, §40, §41)
docs/guardian/30_TDD/GUARDIAN_G7_IMPLEMENTATION_HANDOFF.md  (§2
  especially — the topology/operation-class resolution)
docs/adr/ADR-002-guardian-privilege-topology.md  (the accepted Model B
  decision, including the direct-call correction and the
  Snapshot/Validate/Apply/Observe ownership principle)
docs/evidence/g6/G6_MILESTONE.md  (immediately prior accepted gate)
```

# 3. Required verdict

Exactly one:

```text
PASS — G7 PRODUCTION DAEMON ACCEPTED
PASS WITH NON-BLOCKING FINDINGS
FAIL — G7 REQUIRED EVIDENCE INCOMPLETE
FAIL — G7 PRIVILEGE TOPOLOGY NOT FAITHFULLY IMPLEMENTED
FAIL — G7 SCOPE BOUNDARY VIOLATION
FAIL — G7 DIRECT-CALL INVARIANT VIOLATED
```

(The last verdict is new in this revision — use it specifically when
§6a's checks find a real or latent relay path, distinct from a general
topology-fidelity gap.)

# 4. Mechanically re-derive G7's normative scope — do not trust the candidate's own framing

Read §37 and §38's G7 entry directly. Confirm independently that G7's
normative IDs are exactly `P1-DMN-001..005` and `P1-SEC-001..004` (nine
total) and no others. If the candidate's own report cites a different
ID set, that is itself a finding.

# 5. The central audit question — is this real production wiring, or G0-G5's logic re-presented with a systemd unit wrapped around it?

G7 depends entirely on already-tested logic from G1-G5 (transaction
engine, persistence, budget, PSI, recorder, arbitration, identity,
authorization — see the implementation handoff §3 for exact file
locations). The real risk this audit exists to catch: a candidate that
builds systemd units and D-Bus registrations, but never actually routes
real requests through the real engine/persistence code paths — i.e., a
thin shell that *looks* like a production daemon/helper pair in its unit
files but doesn't actually exercise the logic G0-G5 spent five gates
proving. For every one of the nine normative IDs, trace the actual code
path: does the evidence prove the real logic ran in the *correct
process* (per the implementation handoff's §2 class matrix), or only
that a process started and a D-Bus name was claimed?

# 6. Privilege topology fidelity audit (ADR-002)

- Does a real `guardian-helper` binary exist, running as root, with
  narrow, individually-authorized, typed write methods — not a generic
  command broker?
- Does `guardian-daemon` genuinely run unprivileged? Verify via the same
  kind of `/proc/<pid>/status` capability inspection G2's own evidence
  used (`ADR-002` §"systemd hardening"), not by trusting the unit file's
  `User=` directive alone — confirm the *running* process's actual
  capability set.
- Does `guardian-helper` independently verify caller identity/
  authorization, or does it trust a claim forwarded by `guardian-core`?
  ADR-002 states this must never happen — verify it directly against
  the real running services (e.g., attempt a call to `guardian-helper`
  that bypasses `guardian-daemon` entirely and confirm it is still
  correctly authorized or correctly rejected).
- Check the naming-collision resolution from the implementation
  handoff's §2.1/§4 was actually followed: `guardian-core` remains
  library-only in the built binaries (no process named "core" exists),
  `guardian-daemon` is the unprivileged process, `guardian-helper` is
  the privileged process, matching exactly.
- Check the D-Bus name assignment from §2.2 was followed: `guardian-
  daemon` owns `io.github.cliffthelin.Guardian1`; `guardian-helper` owns
  `io.github.cliffthelin.GuardianHelper1`; neither claims the other's
  name.

# 6a. Direct-call invariant audit (new in this revision — the primary blocking risk from the prior FAIL)

This section exists specifically because the prior review found the
implementation handoff did not resolve how the daemon's transaction
wiring reaches a privileged `Apply` without relaying through it. Do not
accept the implementation handoff's §2 as sufficient on its own — prove
the *built system* actually matches it. At minimum, perform and report
each of the following as a real test against the running services, not a
code-read inference:

```text
1. Daemon relay test (the primary risk): attempt to trigger the Class A
   test write via guardian-daemon (e.g., call any method guardian-daemon
   exposes that might internally construct a call to
   GuardianHelper1's mutation method). Confirm no such code path exists
   — grep guardian-daemon's source for any client construction against
   GuardianHelper1, AND confirm behaviorally that no daemon-exposed
   method results in a mutation being applied via guardian-helper.

2. Caller-identity-through-relay test — MUST FAIL as an architecture, and
   the review must confirm it fails: if a relay path is somehow found,
   verify guardian-helper resolves the caller as guardian-daemon's own
   identity, not the original client's — i.e., prove the confused-deputy
   shape is real and observable if the relay exists at all, as the
   sharpest possible demonstration that the direct-call invariant is
   load-bearing, not decorative. (If no relay path exists, as required,
   this test has nothing to exercise — state that explicitly rather than
   fabricating a relay to test against.)

3. Forwarded-UID trust test: call guardian-helper with any available
   mechanism that could carry a caller-supplied uid/identity claim
   (argument, header-like field) and confirm guardian-helper ignores it
   in favor of its own D-Bus connection credentials.

4. Forwarded-authorization trust test: confirm guardian-helper performs
   its own real CheckAuthorization call for every Class A mutation
   attempt, never accepting a pre-computed "already authorized" claim
   from any other process.

5. Daemon-writes-helper-state test: confirm guardian-daemon's process has
   no write access to guardian-helper's state directory (§2.6) —
   filesystem permission check plus confirm no code path attempts it.

6. Helper-accepts-daemon-authorship test: if guardian-helper ever reads
   anything guardian-daemon produced (per §2.6's optional read-sharing
   accessor, if built), confirm it is never treated as authorization or
   identity evidence — only as non-authoritative coordination context, if
   used at all.

7. Class B routed through helper test: confirm the Class B evidence path
   (guardian-daemon → provider stand-in) never calls guardian-helper.
   Provider-owned authorization must not touch the helper merely because
   it exists (§2.8).

8. Dual-writer test: confirm guardian-daemon's and guardian-helper's
   transaction-record directories are disjoint (§2.6) and that no single
   transaction record is ever written by both processes.

9. Generic-helper-method audit: enumerate every method GuardianHelper1
   exposes; confirm each is narrowly typed for one specific operation —
   none accepts an opaque payload, argv, arbitrary path, or action-name
   string that could serve more than the one evidenced Class A operation.

10. Guardian1/GuardianHelper1 growth audit: enumerate every method/
    property/signal on both interfaces; confirm each maps to a specific
    one of the nine normative IDs. Any surface that doesn't map to a
    required test is itself a finding (§2.8's guardrail).

11. Helper-unavailable fail-closed check: with `guardian-helper`
    unavailable (stopped, crashed, or otherwise unreachable), attempt a
    Class A Guardian-owned privileged mutation through every reachable
    production client path. Verify: no daemon/provider fallback path
    performs the mutation; no prior authorization result is reused; no
    operation is silently reclassified as provider-owned (Class B) to
    route around the unavailable helper; and the public result
    represents the operation as unavailable/failed, never as successful.
    Zero privileged mutation may occur. This is distinct from checks 1-2
    above (which test whether a relay path exists at all) — this checks
    the failure behavior specifically when the one legitimate path
    (direct client → helper) is down, since G7 is precisely the gate
    where `guardian-helper` becomes real and this failure mode first
    becomes possible to get wrong.
```

Report each of the eleven checks individually with PASS/FAIL and the
concrete evidence (introspection output, source excerpt, or behavioral
transcript) backing each result — a summary claim without per-check
evidence does not satisfy this section.

# 7. Real-environment evidence audit (G1/G2/G6 evidentiary standard applies)

For each of the nine normative IDs, verify:

```text
- real disposable VM, not the primary workstation;
- real systemd (systemctl start/stop/restart, real kill -9), not
  simulated or scripted-around;
- real D-Bus calls against the real system bus, not a private test bus
  standing in for "real";
- real systemd-analyze security output as a genuine artifact for EACH
  unit separately, not a summary claiming a score for "the daemon" as if
  it were one unit;
- provenance on every screenshot/transcript (candidate/build identity,
  environment, timestamp/run identity), same standard as G6's evidence.
```

Specifically interrogate:

- **P1-DMN-002/005 (restart / crash recovery)**: per the implementation
  handoff's §2.5/§5, these must be evidenced against **`guardian-helper`**
  for the Class A claim (a real in-flight privileged transaction at the
  moment of restart/kill) and **separately** against `guardian-daemon`
  for the Class B/C claim. Evidence gathered against only one process and
  generalized to both is a finding. An idle-process restart proves much
  less than the required claim either way.
- **P1-DMN-004 (clean stop)**: does the evidence show the persistence
  store's actual state (not just "the process exited 0") before and
  after stop, for the correct owning process per §2.5?
- **P1-SEC-004 (privilege denial)**: is the "unauthorized client" a
  genuinely different, unprivileged identity, or the same privileged
  test harness merely omitting a flag? Does the denied call go directly
  to `guardian-helper`, per the direct-call invariant, rather than being
  routed through `guardian-daemon`?

# 8. Fail-closed / forbidden-shortcuts audit (§40)

Confirm none of §40's list was violated: no `sudo` from any client, no
GUI-as-root (not applicable yet — no GUI exists), no generic root
command broker anywhere in `guardian-helper`, no shell-out where a
stable D-Bus provider API was already selected, no direct `/etc` writes
from an unprivileged client.

# 9. Forward-constraint audit (G4/G5 carried into G7)

Verify the implementation handoff's §7 claims are actually true, not
just asserted:

- Is `RecorderPolicy`/`recorder_policy_for()` (G5) genuinely called by
  `guardian-daemon`'s real recorder instance and its result actually
  acted upon — or merely constructed and left unused (repeating the
  exact class of gap G4's own independent audit caught and required
  fixed)? Confirm this lives in `guardian-daemon`, not `guardian-helper`
  (§2.4's class placement).
- If G5's FC-1 (byte-boundedness) or G4's FC-3 (recorder/persistence
  relationship) became relevant during this gate's wiring work, was
  either explicitly addressed and documented, or explicitly and
  honestly deferred with a stated reason — not silently ignored?

# 10. Scope-leak audit (G8/G9)

Confirm no real provider (systemd unit inspection beyond what's needed
to prove the daemon's own liveness, PSI, logind, UDisks, UPower,
AccountsService), no CLI/TUI/GUI, no production indicator, and no
packaging work was implemented under cover of "needed to evidence the
daemon." `ksni` (G6's selection) should not appear wired into a real
indicator client anywhere in this diff — that is G9. Confirm Class B's
evidence used a minimal bounded stand-in, not a real provider (§6
implementation-handoff out-of-scope list).

Confirm `tests/vm/g6-daemon-evidence-stub` was not copied, extended, or
otherwise used as either binary's skeleton (implementation handoff §2.8).

# 11. Regression audit

Verify unmoved: all `phase0-g0..g6` tags. Verify unchanged: G0-G5's
`guardian-core` library logic (any diff there must be a narrowly-scoped,
explicitly-documented integration bugfix per the implementation
handoff's §6 "out of scope" note — not a redesign). Confirm the public
D-Bus contract (`io.github.cliffthelin.Guardian1` namespace, ADR-001)
was extended additively if at all, never broken, and confirm
`io.github.cliffthelin.GuardianHelper1` is a genuinely new, separate
name, not a subpath or alias of `Guardian1`.

# 12. Validation

```bash
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Baseline before G7: 189 passed, 0 failed. Report the exact new total —
G7 is expected to add real integration tests, so an increase is
expected and should be explained, not merely reported as a number.

# 13. Required report

```text
1. Baseline/candidate SHAs, tag state
2. Full changed-file reconciliation (every file, not sampled)
3. P1-DMN-001..005 matrix: what was actually proven, with artifact
   references, and which process (guardian-daemon or guardian-helper)
   each piece of evidence targets
4. P1-SEC-001..004 matrix: same
5. Privilege topology fidelity findings (§6)
6. Direct-call invariant findings — all eleven §6a checks, individually,
   with PASS/FAIL and concrete evidence per check
7. Real-vs-simulated evidence findings (§7)
8. Forbidden-shortcuts findings (§8)
9. Forward-constraint findings (§9)
10. Scope-leak findings (§10)
11. Regression findings (§11)
12. Validation results
13. Blocking findings (or "None")
14. Non-blocking findings
15. Verdict
16. Recommended next action
```

Then STOP. Do not push. Do not tag. Do not begin G8/G9 work.
