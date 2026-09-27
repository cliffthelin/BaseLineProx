# Guardian Wave 1 Independent Review Handoff
## First Production Mutation Capability — Planning Review

This handoff governs the review of the **planning** artifact
(`GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md`), not an implementation —
there is no Wave 1 code yet. This is analogous to the pattern G9 itself
used before implementation began (a planning review, independent of
whoever writes the eventual implementation handoff, before any code is
written).

**Revision note**: this planning pair has been independently reviewed
five times.

- **Round 1** found two real defects: an internally ambiguous "Phase 2"
  numbering (§50's own text called Wave 1 both "Phase 2" and, separately,
  still called the original read-only work "Phase 2"), and an
  authorization-owner conclusion that was empirically wrong (verified
  live against real systemd/polkit: a root-relayed `RestartUnit` call is
  authorized unconditionally, performing no real per-user check at all).
  Repaired by adding §50's disambiguation rule / `W1-` prefix, and by
  requiring `guardian-helper` to perform its own **new, Guardian-owned**
  `CheckAuthorization` before calling `RestartUnit`.
- **Round 2** re-verified both round-1 fixes independently (including its
  own live VM re-test of the root-relay asymmetry) and found them sound,
  but surfaced two new, unrelated defects in its own mandated sanity
  pass: a mislabeled `SafeToResume` classification for an in-flight
  `RestartUnit` crash, and no normative ID covering the compensating
  rollback itself failing.
- **Round 3**, focused specifically on the authorization architecture,
  found round 1's fix itself defective: requiring a **new,
  Guardian-owned** `PolkitAction` for a capability G2 already classified
  as provider-owned silently converts that classification rather than
  preserving it. The repair corrected this to have `guardian-helper`
  mediate systemd's own real, already-shipped
  `org.freedesktop.systemd1.manage-units` action, stating
  `authorization.rs` would remain unmodified. Round 3 also flagged an
  unresolved unit-name/capability escape-vector question, which the
  repair closed by redesigning the method around a Guardian-defined
  `capability_id` rather than a caller-supplied unit name.
- **Round 4**, checking whether round 3's repair was actually
  *implementable*, found it was not as worded: `PolkitAction`
  (`crates/guardian-core/src/authorization.rs`) is a closed enum with no
  generic, string-carrying variant, so "check `manage-units`" and
  "`authorization.rs` stays unmodified" were mutually contradictory.
  §7/§10 below are corrected accordingly — Wave 1 now scopes a small,
  disclosed production addition to `authorization.rs`: a separate,
  equally closed `ProviderPolkitAction` enum (one variant,
  `SystemdManageUnits`) and a new, equally typed
  `authorize_provider_action` entry point, distinct from
  `authorize(PolkitAction)`. This is **not** a reversion to round 1's
  Guardian-owned-action defect (`PolkitAction` itself still gets no new
  variant) and **not** a generic raw-action-id interface (explicitly
  rejected — see §7 below). Round 4 also found no project precedent for
  a letter-suffixed normative ID (`W1-VM-002b` in the prior revision);
  the `W1-VM-*` IDs are renumbered sequentially in this pass.
- **Round 5**, checking whether round 4's design actually reproduces
  systemd's real authorization *decision* rather than merely its action
  id, found it did not: empirically snooping the real `CheckAuthorization`
  D-Bus call in a disposable VM (`busctl monitor --system`) while running
  `systemctl restart cups.service` showed systemd's own request carries
  non-empty `details` — `unit`, `verb`, `polkit.message`,
  `polkit.gettext_domain` — that a real admin polkit rule may branch on
  (e.g. `action.lookup("unit")`), while `PolkitAuthorizer::authorize()`
  hardcodes an empty details map and round 4's `ProviderPolkitAction` had
  no field to carry them. §7/§10/§12 below are corrected again:
  `ProviderPolkitAction` (a bare action-id enum) is replaced by
  `ProviderAuthorizationRequest`, a closed **request** type whose
  `action_id()` and `details()` are both derived internally from an
  already-resolved `RestartCapability` — never from caller input, and
  carrying all four evidenced fields, not a subset. Two new normative
  IDs, `W1-AUTH-007` and `W1-VM-007`, freeze this fidelity requirement
  and its VM proof.

All of round 2's, round 3's, round 4's, and round 5's findings are
addressed in the current planning pair. **Do not assume any of these
repairs are correct merely because they respond to a prior review's
findings — verify each one independently, from scratch, exactly as if
you had found the original defects yourself.**

# 1. Baseline verification

Confirm independently: `HEAD`/`origin/main` match
`c02b43ebae0801d3dff6571757fb919569a33578`, tag
`phase0-g9-clients-packaging` points there, and no Wave-1-named tag
exists yet. Confirm the working tree contains only the planning
artifacts this handoff governs (the two Wave 1 handoff docs and the §50
contract amendment) — no production Rust file should differ from the
tagged G9 commit.

# 2. Governing material

- `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §46–§50 —
  §50 is the new amendment authorizing this work at all; read it in
  full and confirm it genuinely preserves §47's original text rather
  than silently rewriting it (AGENTS.md's "supersede, don't hide" rule).
- `docs/adr/ADR-002-guardian-privilege-topology.md` — the trusted-caller
  finding this handoff's §7 discusses and distinguishes from the actual
  `RestartUnit` case.
- `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md` — the sole
  source for every capability-family classification in §1/§3 of the
  implementation handoff.
- `crates/guardian-core/src/transaction/recovery.rs`,
  `crates/guardian-core/src/arbitration.rs`,
  `crates/guardian-core/src/error.rs` — the unmodified machinery the
  implementation handoff claims to reuse without extension.
- `crates/guardian-core/src/authorization.rs` and `crates/guardian-core/
  src/authorization/polkit.rs` — **not** claimed unmodified in this
  revision; read these directly to verify the planned
  `ProviderAuthorizationRequest` addition (§7 below) is real, small, and
  closed, that its `details()` return shape can actually carry
  `unit`/`verb`/`polkit.message`/`polkit.gettext_domain`, and that
  `PolkitAction` itself genuinely gains no new variant. Also read
  `PolkitAuthorizer::authorize()`'s current hardcoded empty `details`
  map directly — this is the concrete evidence for round 5's finding.
- `docs/evidence/g9/G9_MILESTONE.md` — the accepted G9 baseline this
  work builds on.

Treat the implementation handoff's own claims as navigation only.

# 3. Required verdict

```text
PASS — WAVE 1 PLANNING ACCEPTED, READY FOR IMPLEMENTATION HANDOFF LOCK
PASS WITH NON-BLOCKING FINDINGS
FAIL — WAVE 1 SCOPE AUTHORITY INSUFFICIENT
FAIL — WAVE 1 CANDIDATE SELECTION UNSOUND
FAIL — WAVE 1 SINGLE-WRITER MODEL INSUFFICIENT
FAIL — WAVE 1 AUTHORIZATION OWNERSHIP UNRESOLVED
FAIL — WAVE 1 RECOVERY/IDEMPOTENCY INSUFFICIENT
FAIL — WAVE 1 METHOD-SHAPE/ALLOWLIST BOUNDARY INSUFFICIENT
FAIL — WAVE 1 GOVERNANCE/NUMBERING AMBIGUOUS
FAIL — WAVE 1 NORMATIVE IDS INCONSISTENT
FAIL — PROVIDER AUTHORIZATION API STILL NOT IMPLEMENTABLE
FAIL — PROVIDER POLICY SEMANTICS NOT PRESERVED
FAIL — PROVIDER AUTHORIZATION CONTEXT/DETAILS UNRESOLVED
```

(The last three verdicts were added after round 5's finding: checking
the correct action id is necessary but not sufficient — a mediated
check with the wrong/empty *details* can still diverge from what the
provider's real policy would decide. Use `PROVIDER AUTHORIZATION
CONTEXT/DETAILS UNRESOLVED` for exactly this shape of defect — the
action id is right, the type-level architecture is otherwise sound, but
the details a real admin policy could depend on are missing, wrong, or
only partially reproduced. Use `PROVIDER POLICY SEMANTICS NOT PRESERVED`
for a broader failure of the mediation itself (e.g. contract wording
that overclaims what systemd would see, or a design that would let a
Guardian-owned grant substitute for the provider's own policy). Use
`PROVIDER AUTHORIZATION API STILL NOT IMPLEMENTABLE` if, as in round 4,
the design cannot actually be built against the real, current
authorization machinery as worded.

The prior revision of this handoff's own §4 and §13 already referenced
`FAIL — WAVE 1 GOVERNANCE/NUMBERING AMBIGUOUS` without it appearing in
this list — an inconsistency fixed here by adding it, along with a
distinct `NORMATIVE IDS INCONSISTENT` verdict for ID-integrity findings
that aren't themselves a numbering-ambiguity issue, e.g. a duplicate,
gap, or nonstandard ID form.)

("Authorization ownership unresolved" covers every possible failure
mode found across all four review rounds: no independent Guardian-side
check at all — round 1's original defect; a check that exists but is
not genuinely provider-mediated, i.e. it substitutes a Guardian-owned
policy for the provider's own — round 3's defect; and a design that is
correct in intent but not actually expressible through the real,
existing typed authorization API as worded — round 4's defect,
including a design that reopens a generic raw-action-id interface as an
overcorrection. All four shapes are the same verdict; §7 below requires
you to state explicitly which, if any, is present.)

# 4. §50 amendment audit — check this before anything else

Independently confirm §50 does not silently rewrite §47's original text
(diff-check both sections exist, §47's "Phase 2... expands read-only
observability and correlation" line is unchanged, byte-for-byte).

**Numbering coherence — the specific defect the prior review found.**
Confirm §50's revised text genuinely resolves the ambiguity rather than
merely asserting it's resolved. Specifically verify: (a) §50 never uses
the bare word "Phase 2" without a qualifier (`TDD-contract Phase 2` or
`master-spec Phase 2`) anywhere in its own text — grep for every
occurrence of "Phase 2" in §50 and check each one; (b) every new
normative ID in the implementation handoff uses the `W1-` prefix, with
zero `P2-*` (or any other `P<phase>-`) IDs remaining anywhere; (c) §50
explicitly states Wave 1 is not TDD-contract Phase 2 and does not rename,
renumber, or relocate it. If any bare, unqualified "Phase 2" remains in
§50, or any ID still uses a `P<phase>-` prefix, the numbering defect is
not actually fixed and the verdict must be `FAIL — WAVE 1 GOVERNANCE/
NUMBERING AMBIGUOUS` regardless of how the surrounding prose reads.

Confirm §50's acceptance bar is genuinely restrictive — capable of
rejecting a candidate — not written permissively enough to rubber-stamp
whatever was already selected. Confirm §50 does not implicitly authorize
I/O Guardian, TDD-contract Phase 2 correlation, or any other master-spec-
later-phase work beyond the one selected candidate.

# 5. Mechanical scope re-derivation audit

Independently re-derive the capability-family table (implementation
handoff §1) directly from `docs/evidence/g2/
PRIVILEGE_REQUIREMENT_INVENTORY.md`'s 24 rows — do not trust the
handoff's own transcription. Confirm every "unknown — requires host
research" row is correctly excluded from candidacy (8 rows: BPF/eBPF,
thermald-write, NVML, fwupd, journald-rotation, apt/package state,
generic hardware control, usbguard). Confirm UDisks `PowerOff()` is
excluded for the stated scope reason (I/O Guardian module ownership),
not merely ranked lower — re-read the G2 inventory's own "I/O Guardian
storage power-off... deferred as a real feature until the I/O Guardian
module phase" line directly.

# 6. Candidate ranking audit

Independently score the four in-scope candidates (systemd restart, PPD
`HoldProfile`, NetworkManager config write, AccountsService
`SetSession`) against §50's own acceptance-bar criteria, not against the
implementation handoff's own ranking table. Confirm the selected
candidate (systemd unit restart) is the one a fair, independent scoring
actually produces — not merely that the handoff's table says so. Pay
particular attention to whether PPD's lack of any G8 read provider and
lack of provider-owned authorization is weighted correctly (it should
disqualify PPD from being a strong *first* candidate even though it
remains structurally eligible).

# 7. Authorization-owner finding audit — the most important single claim in the handoff

The implementation handoff's §7 (in this revision) claims that
`guardian-helper` must call a new, typed `authorize_provider_request`
entry point — carrying a new, closed `ProviderAuthorizationRequest` enum
(`crates/guardian-core/src/authorization.rs`, one variant for Wave 1:
`SystemdRestart { capability }`) — against the real caller identity it
resolves directly from its own D-Bus connection, **before** calling
`RestartUnit`, with both the action id (`org.freedesktop.systemd1.manage-
units`) and the request's complete authorization details derived
internally from the already-resolved capability, never from caller
input. This is the fourth correction to this claim: round 1 found that
skipping any independent Guardian-side check entirely was wrong
(empirically, in a real VM — a root-relayed call is authorized
unconditionally); round 1's own fix (requiring a **new, Guardian-owned**
`PolkitAction`) was found wrong by round 3, on the grounds that it
silently converts a provider-owned capability into a Guardian-owned one;
round 3's own fix (mediate the provider's real action id,
`authorization.rs` unmodified) was found **unimplementable** by round 4,
since `PolkitAction` cannot express an arbitrary action id; round 4's own
fix (a bare `ProviderPolkitAction` action-id enum) was found
**detail-incomplete** by round 5, since checking the right action id with
empty details still diverges from what systemd's real request would be.

**Do not accept any of these corrections on the strength of a prior
review's finding alone — re-verify all four, independently, yourself:**

- **Model, explicitly.** State which of these three the handoff actually
  implements, and confirm it is Model B:
  - Model A (wrong): `guardian-helper` checks a **Guardian-specific**
    polkit action, then calls systemd as root. Guardian becomes the
    authorization authority.
  - Model B (correct, required here): `guardian-helper` checks
    **systemd's own real action** (`org.freedesktop.systemd1.manage-
    units`) for the resolved caller, then calls systemd as root only if
    that succeeds. The provider's own policy remains authoritative;
    Guardian only mediates the query because the real caller cannot
    query it directly (ADR-002's trusted-caller restriction).
  - Model C: caller goes directly to the provider, no Guardian mediation
    at all — not applicable here given `guardian-helper`'s intended
    trust topology, but confirm the handoff does not accidentally drift
    toward it either (e.g. by skipping Guardian's own check and trusting
    systemd's internal one, which would reintroduce round 1's defect).
- **Confirm no new `PolkitAction` variant and no new `.policy` file are
  proposed for this capability anywhere in the handoff** (§10, §14, and
  the normative IDs in §12) — their presence would mean Model A survived
  despite the prose claiming otherwise.
- **Confirm the design is actually implementable against the real code
  as worded — this is round 4's specific check.** Read
  `crates/guardian-core/src/authorization.rs` directly: confirm
  `PolkitAction` is unchanged (still exactly the 5 pre-existing
  variants, no `SystemdManageUnits` or equivalent added to it), and
  confirm the handoff plans a **separate**, disjoint
  `ProviderAuthorizationRequest` enum with its own `action_id()`
  returning exactly `"org.freedesktop.systemd1.manage-units"` for its
  one variant, plus a new, equally typed entry point (e.g.
  `authorize_provider_request`) that takes
  `ProviderAuthorizationRequest`, never a raw `&str`/`String` action id.
  Confirm the handoff does **not** claim `authorization.rs` remains
  fully unmodified (that claim is itself now a defect, per round 4) —
  it should instead explicitly disclose this addition as scoped
  production work (§10, and the "Public API minimality" section's
  opening). If the handoff instead proposes a generic
  `authorize_provider(action_id: &str, ...)`-shaped interface, or any
  other way for a caller-supplied or dynamically-constructed string to
  reach a `CheckAuthorization` call, that is itself a blocking finding —
  it re-opens exactly the unbounded authorization surface Guardian's
  typed-`PolkitAction` design has avoided since G1, and must be treated
  as harshly as Model A.
- **Confirm the request reproduces the provider's real authorization
  details — this is round 5's specific check, and the newest, most
  load-bearing item in this list.** Independently re-establish (VM
  D-Bus snoop via `busctl monitor --system`, or equivalent authoritative
  evidence — do not merely trust the handoff's citation) exactly what
  `details` systemd's own `manage-units` request carries for a real
  `RestartUnit`/`systemctl restart` on the selected unit. Confirm the
  handoff's `ProviderAuthorizationRequest::details()` (or equivalent)
  returns exactly those fields — for Wave 1's `cups-restart` candidate,
  `unit`, `verb`, `polkit.message`, `polkit.gettext_domain` — derived
  solely from the already-resolved `RestartCapability`, with no
  parameter through which a caller or any other external input could
  add, remove, or alter a detail key or value. Confirm
  `PolkitAuthorizer::authorize()`'s existing hardcoded-empty-details
  behavior is **not** silently reused for the provider path (read the
  actual entry point's implementation plan, not just its type
  signature) — if the plan reuses the exact same empty-details code path
  for `authorize_provider_request`, that is a live regression to round
  4's defect regardless of what the type is named. If the handoff omits
  any of the four evidenced fields, includes fewer than what a real
  direct call would send, or leaves the exact detail values unspecified
  (e.g. "systemd metadata" without giving the literal values), the
  verdict must be `FAIL — PROVIDER AUTHORIZATION CONTEXT/DETAILS
  UNRESOLVED`.
- Independently confirm the real action id: read
  `/usr/share/polkit-1/actions/org.freedesktop.systemd1.policy` (or
  equivalent) in a disposable VM yourself, or via `busctl`/`pkaction`,
  rather than trusting the handoff's citation of it.
- Confirm §10's proposed method (`GuardianHelper1.RestartCapability`) is
  documented as performing `CheckAuthorization` against that real action
  id *before* `Apply`/`RestartUnit`, not after, and not merely alongside
  it as an optional step — check §6's transaction-lifecycle table's
  `Authorize` row specifically.
- Confirm the handoff requires `guardian-helper` to resolve the caller's
  identity from **its own** incoming D-Bus connection (matching
  `GuardedWrite`'s real, accepted `resolve_caller_identity` precedent in
  `crates/guardian-helper/src/main.rs` — read that function's actual
  call site yourself) — and that no step anywhere has `guardian-daemon`
  resolving identity and passing it to `guardian-helper` as a data value
  (a relayed/trusted-claim pattern AGENTS.md's Privilege rules already
  forbid).
- If you have VM access, independently verify: (a) an unprivileged,
  non-admin user's direct `RestartUnit` call is denied against their own
  identity, but a root-issued call is not (round 1's finding); (b) a
  user with a real, OS-level `manage-units` grant that has *nothing to
  do with Guardian* is authorized through `guardian-helper`'s mediated
  check without any Guardian-specific grant existing — this test is the
  one that actually distinguishes Model B from Model A, since Model A
  could also pass test (a) while still being architecturally wrong; and
  (c) `W1-VM-007`'s detail-sensitive scenario — install a real, evidence-
  only polkit rule keyed on `action.lookup("unit")`/`action.lookup
  ("verb")`, and confirm `guardian-helper`'s mediated check produces the
  *same* decision a direct systemd call would under that rule, for both
  a matching and a mismatched unit/verb — this is the test that
  distinguishes round 5's fix from round 4's, since round 4's design
  could pass tests (a) and (b) while still failing (c).
- Confirm the handoff cites and reconciles the G7 precedent
  (`AttemptProviderDelegatedWrite`, rejected as "an unjustified permanent
  production API addition") and correctly declines to treat
  `GuardedWrite`'s own action as a template for this candidate (that
  action is legitimately Guardian-owned for a capability with no other
  provider — mirroring it here would reintroduce Model A).

If Model A is present in any form (a new Guardian action exists, is
checked, or is required anywhere in the handoff for this capability), or
if no independent Guardian-side check exists at all, or if the design is
not actually implementable against the real, current `authorization.rs`
as worded, or if it is implementable only by reintroducing a generic
raw-action-id or raw-details interface, the authorization design is
still unresolved and the verdict must be `FAIL — WAVE 1 AUTHORIZATION
OWNERSHIP UNRESOLVED`. Separately — and this is not the same failure
mode — if the model and API shape are otherwise sound but the mediated
request's `details` omit, alter, or only partially reproduce what
systemd's real request would carry, the verdict must instead be
`FAIL — PROVIDER AUTHORIZATION CONTEXT/DETAILS UNRESOLVED`, regardless
of how confidently the handoff's prose asserts the fix. State explicitly
in your report which model you found, whether the planned
`authorization.rs` addition is real, small, closed, and honestly
disclosed, and whether its details reproduce the real, evidenced
provider request exactly.

# 8. Transaction lifecycle audit

Verify every step in the implementation handoff's §6 table maps onto an
**unmodified** G4 concept — no new transaction state, no new
`ApplyOutcome`/`ObservationOutcome` variant, no new `RecoveryClassification`
variant. Confirm the `RollbackKind::BestEffort` classification for a
restart's "compensating action" is honest (a second restart is not a
true inverse of the first) rather than inflated to `Native`. Confirm
`Validate` and `Authorize` are both attributed to `guardian-helper`
itself in this revision (not `guardian-daemon`, and not split between
the two) — the note under §6's table explaining why `guardian-daemon`'s
own read is not trusted as an input to either step should be present and
should make sense on its own terms, not merely assert the conclusion.

# 9. SafeToResume and rollback-failure audit

Independently re-derive the crash-point → `RecoveryClassification` table
(implementation handoff §8) by tracing `crates/guardian-core/src/
transaction/recovery.rs::classify()`'s actual match arms — including
`classify_applying()`'s distinct arms for `ApplyOutcome::
PartialOrUncertainMutation` (in-flight, uncertain) versus
`ConfirmedSuccess`/`ResponseLostOrUnknown` (believed complete) — against
each described crash point. Do not trust the handoff's table. A prior
review found an earlier version conflated these two, assigning the more
optimistic `MustObserve` to the genuinely in-flight case where the real
classifier produces `StateAmbiguous`; confirm this revision's table
keeps them distinct and correctly classified. Confirm no crash point is
assigned a more optimistic classification than the existing, unmodified
classifier would actually produce for the corresponding
`TransactionState`/`ApplyOutcome`/`ObservationOutcome` combination.
Confirm this section is genuinely unaffected by the authorization-owner
correction (it should be — the crash points are all downstream of
Authorize, not inside it) rather than silently drifting.

**Rollback-failure coverage** — a second, previously-missing area:
confirm a normative ID exists covering the `BestEffort` compensating
restart itself failing, and that it requires: the failure is surfaced
honestly (the real, existing `TransactionState::RollbackFailed` and
`GuardianErrorCategory::RollbackFailed`, not a fabricated success); no
infinite retry loop; a later recovery pass over a `RollbackFailed`
transaction reaches `RequiresHumanRecovery` via `classify()`'s own
fallback arm (read that arm directly — it is the same `_ =>` branch that
already exists, unmodified). Confirm the handoff points to
`GuardedWrite`'s own real, accepted
`rollback_failure_during_recovery_is_surfaced_not_silently_successful`
fixture (`crates/guardian-helper/src/main.rs`) as the rigor bar, and
does not invent new G4 behavior to cover this case. If no such ID
exists, or if it invents new recovery machinery instead of reusing
`RollbackFailed`, that is a blocking finding under `FAIL — WAVE 1
RECOVERY/IDEMPOTENCY INSUFFICIENT`.

# 10. Single-writer audit

Confirm the existing `arbitration.rs::Ownership::ProviderOwnedWriter`
variant genuinely fits this capability without modification — verify by
reading the type definition directly, not by trusting the handoff's
assertion. Confirm the handoff correctly identifies that job-merging/
concurrent-writer behavior (§9, `W1-TXN-003`) is **unverified, real VM
evidence required** — not assumed safe. If the handoff asserts this as
settled rather than flagging it as unverified, that is a finding.

# 11. Public API minimality and method-shape/allowlist-escape audit

Confirm the handoff's disclosed production scope is exactly: no new
`PolkitAction` variant, no new `.policy` file, one new closed
`ProviderAuthorizationRequest` enum (one variant, `SystemdRestart`,
carrying a `RestartCapability` and internally deriving both `action_id()`
and a complete `details()`) plus its typed `authorize_provider_request`
entry point in `authorization.rs`, and one new typed method
(`GuardianHelper1.RestartCapability`) plus its fixed capability table in
`guardian-helper`. If the handoff proposes a new `PolkitAction`/`.policy`
action anywhere, Model A survived and this is itself sufficient for
`FAIL — WAVE 1 AUTHORIZATION OWNERSHIP UNRESOLVED` (cross-reference §7).
If the handoff still claims `authorization.rs` remains entirely
unmodified, that claim is itself now a defect (round 4's finding) —
flag it. If the handoff's `details()` (or equivalent) omits any of the
real, evidenced fields (`unit`, `verb`, `polkit.message`,
`polkit.gettext_domain`) or leaves them unspecified, that is round 5's
defect — cross-reference §7 and use `FAIL — PROVIDER AUTHORIZATION
CONTEXT/DETAILS UNRESOLVED`. If the handoff proposes *more* than this
disclosed scope (e.g. a generic action-id or details interface,
additional `ProviderAuthorizationRequest` variants beyond
`SystemdRestart`, or additional `RestartCapability` table rows without
their own gate), investigate why — it may indicate scope creep or a
regression toward an earlier defect.

**Method shape.** Confirm the method's only caller-supplied selector is
a Guardian-defined `capability_id` — never a unit name, an operation
name, or any other string a caller could use to name an arbitrary
systemd unit. Confirm the resolution from `capability_id` to (exact
canonical unit, exact single permitted operation, exact provider action
to check) happens entirely inside `guardian-helper`, against a
compiled/configured table, with no caller-suppliable component
contributing to the unit name at any point — no aliasing, no templated-
unit substitution, no path-like unit names, no normalization step
applied to caller input (there should be no caller-supplied unit-name
input to normalize in the first place). Confirm the method cannot drift
toward a generic `RestartUnit(String)`/`ManageSystemd(unit, action)`/
`CallProvider(...)` shape — there should be no parameter through which a
caller names an arbitrary target or operation. If the method accepts a
unit name, an operation string, or any other unconstrained target
selector from the caller, that is a blocking finding under `FAIL — WAVE
1 METHOD-SHAPE/ALLOWLIST BOUNDARY INSUFFICIENT`.

Confirm no client-facing (CLI/TUI/GUI/indicator) capability is proposed
as part of Wave 1's own acceptance — if one is silently smuggled in
anywhere in the handoff, that is a blocking finding (AGENTS.md's
forbidden-shortcuts discipline applies identically here). Confirm the
handoff explicitly names the intended caller of `RestartCapability` for
Wave 1's own acceptance (an evidence/test harness, mirroring
`GuardedWrite`'s own real precedent) rather than leaving "who invokes
this" undefined.

**Capability-table governance.** Confirm the handoff states explicitly
that adding another `RestartCapability` row is a capability expansion
requiring its own governed gate/review — not something implementation
may do merely by configuration. Confirm exactly one row (`cups-restart`
→ `cups.service` → `Restart`) is defined for Wave 1's own acceptance,
and that CUPS is explicitly described as a replaceable evidence target,
not a permanent fixture of the capability model.

# 12. Authorization-semantics audit

Confirm the implementation handoff's mapping table (§11) genuinely
requires zero new `GuardianErrorCategory` variants — read `crates/
guardian-core/src/error.rs`'s existing 17-category enum directly and
confirm `PreconditionFailed`/`Conflict`/`Unsupported` are real, already-
accepted categories, not renamed/repurposed in a way that would
constitute a hidden taxonomy change. Confirm the table's own
`RollbackFailed` category (§9's rollback-failure ID) is likewise reused,
not invented. Confirm the `Authorized`/`Denied` rows correctly describe
`guardian-helper`'s call to `authorize_provider_request` (§7 above) —
against systemd's real `manage-units` action **and its complete real
details** — as the actual decision point, and correctly describe it as
*mediating* the provider's policy rather than *replacing* it with a
Guardian one, or approximating it with a partial detail set.

# 13. Normative-ID audit

Confirm the new IDs (§12 in this revision) use the `W1-` prefix
exclusively — per §50's corrected disambiguation rule, **not** `P2-*` or
any other `P<phase>-` prefix. If even one ID still uses `P2-*`, that is
itself sufficient for `FAIL — WAVE 1 GOVERNANCE/NUMBERING AMBIGUOUS`
regardless of §4's own finding, since it would mean the numbering fix
was not actually carried through consistently. Confirm the ID list's
"minimum required test areas" (per the original planning prompt) are all
actually covered: valid mutation success, invalid-target rejection before
authorization, unauthorized denial, interaction-required behavior,
provider unavailable, competing-writer/conflict, crash before Apply,
crash during/after Apply (with the in-flight/`StateAmbiguous` case
distinct from the response-lost/`MustObserve` case — §9 above),
observation success, observation ambiguous, rollback success, **rollback
failure** (§9 above — this was previously missing; confirm it now
exists and is adequate, not merely present), restart recovery,
idempotency/replay, no generic broker path, no privilege-boundary
bypass; a source-level ID confirming `ProviderAuthorizationRequest` is
disjoint from `PolkitAction` and that the provider-mediation entry point
takes only the typed enum, never a raw string (round 4's
implementability finding, now `W1-AUTH-006`); and — new in this round —
a source-level ID (`W1-AUTH-007`) confirming the request's `action_id()`
and `details()` are both derived solely from the resolved capability,
with the exact literal detail values matching real evidence, plus a real
VM ID (`W1-VM-007`) proving decision-equivalence with a native systemd
request under a detail-sensitive admin rule (round 5's finding). Flag
any gap. Confirm at least one ID specifically proves the mediated check
is genuinely provider-policy-governed — i.e. a caller denied under, or
authorized under, the real `manage-units` policy without any
Guardian-specific grant existing (not merely that *some* denial/allow
happens) — not merely a direct-to-systemd test that would not have
caught the original relay defect, not merely a test that would pass
equally under Model A, and not merely a test that would pass even with
empty/partial details (round 5's specific gap — `W1-VM-007` must be the
one that actually distinguishes detail-complete from detail-empty
mediation).

**ID renumbering check (round 4).** Confirm the implementation handoff's
`W1-VM-*` IDs are sequential (`W1-VM-001` through `W1-VM-007`, or
whatever the current final count is) with **no letter-suffixed ID**
anywhere (a prior revision had `W1-VM-002b`; round 4 found no precedent
for this form anywhere in the project's accepted G0–G9 normative-ID
history and required renumbering). If any letter-suffixed ID survives,
or if the renumbering introduced a duplicate or a gap, the verdict must
be `FAIL — WAVE 1 NORMATIVE IDS INCONSISTENT`. Independently enumerate
every final `W1-*` ID yourself (do not just copy the handoff's own
enumeration) and confirm it matches. Expected totals as of this
revision: `W1-MUT: 4, W1-AUTH: 7, W1-TXN: 3, W1-REC: 9, W1-VM: 7`, total
**30** — `W1-AUTH-007` and `W1-VM-007` are new, appended sequentially at
the end of their respective ranges (never inserted mid-range), per
round 5's repair.

# 14. Evidence-ladder audit

Confirm Layer 4 (real VM) is where genuine acceptance is earned, and
that no Layer 5 (physical hardware) requirement was silently introduced.
Confirm the Layer 2 plan (a private-D-Bus mock systemd1 service) is
concrete enough to actually build, not merely gestured at. Confirm
Layer 4 no longer proposes authoring a Guardian-specific `.policy`
fixture for this capability's authorization *action* (that would
indicate Model A survived) — it should instead rely on systemd's own
already-shipped `.policy` action plus real OS-level polkit configuration
for the VM's test users. Confirm the separate, evidence-only,
detail-sensitive polkit `.rules` fixture required for `W1-VM-007` is
explicitly described as never packaged/shipped in production (§14 of
the implementation handoff) — it exists solely to prove
decision-equivalence under a detail-sensitive rule, not as a
Guardian-authored production policy.

# 15. Scope-discipline audit

Confirm the implementation handoff's §14/§15 exclusions are complete and
match §50's own scope exclusions exactly — no silent expansion into I/O
Guardian, TDD-contract Phase 2 correlation, a new Provider Arbitrator
variant, a new error category, or a client-facing write surface.

# 16. Required report

1. §50 amendment soundness;
2. mechanical scope re-derivation cross-check;
3. candidate ranking cross-check;
4. authorization-owner finding audit (§7 above — the load-bearing claim;
   state explicitly which model — A, B, or C — you found);
5. provider-authorization-detail fidelity result (§7 above — the exact
   native systemd request vs. the mediated request's `action_id()`/
   `details()`, field by field);
6. transaction lifecycle audit;
7. SafeToResume and rollback-failure audit;
8. single-writer audit;
9. public API minimality and method-shape/allowlist-escape audit;
10. authorization-semantics audit;
11. normative-ID completeness audit (exact enumeration, expected 30);
12. evidence-ladder audit;
13. scope-discipline audit;
14. blocking findings;
15. non-blocking findings;
16. exact next action.

"Exact next action" must be one of:
- `Lock the Wave 1 implementation handoff and authorize implementation to begin.`
- `Repair the Wave 1 planning and request another focused review.`

Then STOP. Do not modify the candidate. Do not commit. Do not push. Do
not begin any Wave 1 implementation.
