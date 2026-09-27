# Guardian TDD-contract Phase 2 Independent Review Handoff
## Read-Only Observability & Correlation — Planning Review

Reviewer instructions for auditing
`GUARDIAN_PHASE2_IMPLEMENTATION_HANDOFF.md` and the accompanying §51
amendment to `GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`. This is a planning
review — no production code was written for this pass; verify that fact
first (§1), then verify the planning claims are evidence-grounded, not
plausible-sounding narrative.

**Repair-pass context (2026-09-05).** A prior independent review found
this planning candidate's earlier version defective in three
architectural areas — an unsound `timestamp_monotonic`-based correlation
ordering model, a self-contradictory incident-severity/wire proposal
that silently reopened G3's NB-3, and an unspecified debounce-ring
eviction policy — plus two non-blocking gaps (bare, gate-unqualified
FC-N citations; an understated provider-health scope claim). All five
were corrected in the implementation handoff and in §51. This review
handoff's checklist below has been updated in lockstep to require the
*next* reviewer to verify those five corrections are genuinely present
and haven't regressed, not merely to re-run the original checklist.

**Second repair-pass context (2026-09-05).** A second, comprehensive
combined architecture-and-scope review of that repaired candidate found
the planning almost entirely sound but returned one blocking verdict —
`FAIL — DEBOUNCE CAPACITY SEMANTICS UNSAFE` — because the first repair
pass's `CapacityRejected` observability text ("as a normal Guardian
event of its own, or at minimum a documented internal counter/log
line... an implementation pass must pick one and state which") was an
unresolved disjunction, not a decision, whose "emit it as a Guardian
event" branch was never checked for recursive overflow: an emitted
rejection-`Event` fed back into `CorrelationIngress`/the open-incident
cap could itself become correlation-ingress pressure during exactly the
many-distinct-key storm the debounce ring exists to survive. That
defect is now closed with a single, non-disjunctive mechanism (§7's
bounded/saturating counter + existing `eprintln!` log line, plus an
explicit, independently-testable non-re-entry rule, `P2-REC-005`). Five
cheap, non-blocking items from the same review were fixed alongside it:
the §4.1/§18 window-duration-vs-`ingress_sequence` wording
inconsistency; the unstated `Instant`-construction test technique (now
§6a); a flat §20 file list restructured into an internal Gate 2a/2b/2c
decomposition; an implicit generic-vs-per-source enrichment boundary
(now explicit, §13); and a missing `IncidentWire` wire-shape regression
test requirement (`P2-API-003`). §16 below is added specifically to
require the *next* reviewer verify this second round of corrections is
genuinely present and has not regressed either of the two prior rounds'
corrections in the process.

---

# 1. Baseline verification

Re-run independently, do not trust the planning pass's own report:

```
git rev-parse HEAD                 # expect 1423d9c3053394e19e461ee6adea31bea9231fa7
git tag --points-at HEAD           # expect wave1-first-production-mutation
git status --short                 # expect empty (no production changes)
git diff --stat HEAD~0             # N/A; instead diff against origin/main
```

Expected changed files (planning pass only):

```
docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md   (modified — §51 appended)
docs/guardian/30_TDD/GUARDIAN_PHASE2_IMPLEMENTATION_HANDOFF.md      (added)
docs/guardian/30_TDD/GUARDIAN_PHASE2_INDEPENDENT_REVIEW_HANDOFF.md  (added)
```

If any `crates/` file, `Cargo.toml`, `Cargo.lock`, or `docs/adr/` file
changed, that is a scope violation — the task explicitly required
stopping and reporting rather than making speculative production
changes. Verify no such file changed.

Re-run the baseline validation independently (host `guardian-gui` build
fails on `libadwaita-1` — a known, disclosed, pre-existing sandbox
condition; use a disposable Ubuntu 26.04.1 VM, cloning
`https://github.com/cliffthelin/guardian-plane.git` at the exact
published commit above if no local checkout is available in the VM):

```
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Expected: 347 passed, 0 failed, 3 ignored, clippy clean, fmt clean —
identical to the published baseline, because this pass made zero
production changes. A different count means either the reviewer's
checkout is wrong or the planning pass silently touched production code
— treat either as a blocking finding.

---

# 2. Governing material to read before judging anything else

- `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §47
  (original Phase 2 authorization), §50 (Wave 1, and its
  disambiguation rule — read this even though Wave 1 is closed, because
  §51 depends on it), §51 (this pass's new amendment).
- `docs/guardian/30_TDD/TDD_Gate_Index.md` — confirm G0–G9/Wave 1 status
  lines match what §51 claims.
- `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md` — the exact
  table §11 of the implementation handoff claims to reuse unmodified.
- `docs/evidence/g4/G4_MILESTONE.md` (FC-1..FC-4) and
  `docs/evidence/g5/G5_MILESTONE.md` (FC-1, FC-2) — confirm the
  implementation handoff's §8/§12 persistence/deferral tables cite the
  correct **gate** for each FC-N (G4's FC-3 is not the same list as G5's
  FC-1/FC-2 — verify every citation is gate-qualified, not bare).
- `docs/evidence/g3/G3_MILESTONE.md` — confirm NB-3's disposition text
  (`Risk`: `DEFERRED`, owner "whichever gate first needs to reconstruct
  a `Risk` value from a serialized representation") and confirm the
  implementation handoff/§51 leave it explicitly open, not closed.
- `crates/guardian-core/src/{event,incident,recorder,budget,psi}.rs`,
  `crates/guardian-core/src/providers/psi.rs` (`event_from_crossing`,
  `ThresholdMonitor::sequence`),
  `crates/guardian-daemon/src/dbus_surface.rs` (`IncidentWire`),
  `crates/guardian-daemon/src/bin/guardian-daemon.rs` (`now_secs`,
  `monitoring_tick`, `capability_registry_tick`),
  `crates/guardian-client/src/lib.rs` (`IncidentWire`,
  `From<IncidentWire>`).

---

# 3. Required verdict

One of:

```
TDD-CONTRACT PHASE 2 PLANNING ACCEPTED
TDD-CONTRACT PHASE 2 PLANNING REJECTED — <reason>
TDD-CONTRACT PHASE 2 PLANNING CONDITIONALLY ACCEPTED — <conditions>
```

Do not accept merely because the handoff is long, well-organized, and
cites real file paths — that is necessary, not sufficient. Verify each
cited fact against the actual file.

---

# 4. §51 amendment audit — check this before anything else

- Does §51 preserve §47 and §50 unchanged, adding new text only, per
  AGENTS.md's "supersede, don't hide" rule? Diff-check the file: §47's
  and §50's own text must be byte-identical to the pre-§51 version.
- Does §51 correctly conclude "§47 alone is sufficient authorization" —
  i.e., is there in fact no conflict between §47 and any other governing
  document for *this specific planning scope*? Verify by independently
  re-reading §47 and confirming its "read-only observability and
  correlation" framing is not contradicted elsewhere. (Contrast with
  Wave 1, where §47's framing genuinely did not cover a production
  mutation — confirm the reviewer agrees that gap does not recur here;
  a planning pass deriving Phase 2's scope is squarely inside "read-only
  observability and correlation," unlike Wave 1's write path.)
- Does §51 avoid re-using the unqualified word "Phase 2" anywhere,
  per §50's binding disambiguation rule? Grep the new section for a bare
  "Phase 2" not preceded by "TDD-contract" or "master-spec."
- Does §51's `P2-*` family list match the implementation handoff §19
  exactly (same family names)? A mismatch means one document drifted
  from the other during writing.
- Is §51 dated and does it include Consequences/Revision
  history/Rollback-migration sections in the same shape §50 uses? A
  missing section is a documentation-discipline defect, not merely
  cosmetic — this project's own AGENTS.md ADR requirements (context,
  decision, alternatives, evidence, consequences, rollback) apply.

---

# 5. Mechanical-derivation audit (task item 1)

- Re-derive the §1 table in the implementation handoff independently.
  For at least three rows (suggest: "Incident envelope," "Correlation
  engine," "`Transactions1` D-Bus surface"), grep the actual source
  yourself and confirm the "Existing foundation"/"Missing work" columns
  are accurate, not aspirational.
- Specifically verify the claim "no production code anywhere constructs
  a real `Incident`" — run:
  `grep -rn "Incident {" --include=*.rs crates/*/src` (excluding
  `crates/*/tests`) and confirm it returns nothing, or if it returns
  something, treat the handoff's central premise as wrong and reject.
- Verify the claim that `Incidents1.list_incidents()` and
  `Transactions1.list_transactions()` are hard-coded empty by reading
  `crates/guardian-daemon/src/dbus_surface.rs` directly — do not accept
  the handoff's paraphrase.

---

# 6. Read-only boundary audit (task item 2)

- Confirm the implementation handoff's §2 and §20 introduce no new
  privileged method, no new `guardian-helper` capability, and do not
  quietly reclassify Wave 1's `cups-restart` scope. Cross-check §20's
  "Unmodified, explicitly" list against every file it names — none
  should appear in any "Modified"/"New" bucket elsewhere in the same
  document.
- Confirm §12's transaction-observability deferral is a genuine deferral
  (no code path added) and not a disguised partial implementation (e.g.
  a "just reading one field" carve-out) — the handoff's own text
  forbids exactly that pattern (G9 handoff §6.1's forbidden paths), so
  verify §12 does not silently reintroduce one.

---

# 7. Correlation model audit (task items 4, 6, 13, 14) — the most
important single section

- For each of §4.1/§4.2/§4.3 in the implementation handoff, verify the
  seven required elements are present and internally consistent: source
  event(s), correlation key(s), temporal window, deterministic vs.
  heuristic, confidence, creation/update rule, terminal/closure rule,
  provenance. A missing element for any rule is a rejection-level
  finding, not a nit.
- **Ingress-ordering regression check (repair-pass requirement).** Verify
  every temporal-window/ordering statement in §4.1/§4.2/§4.3 and §6 is
  phrased in terms of the `CorrelationIngress` ingress clock/sequence
  (§6), and **never** in terms of a producer's own `timestamp_monotonic`
  or `sort_by_monotonic_order`. Specifically confirm: (a)
  `crates/guardian-daemon/src/bin/guardian-daemon.rs`'s `monitoring_tick`
  still sets `timestamp_monotonic` from `now_secs()` (wall-clock) and
  `crates/guardian-core/src/providers/psi.rs`'s `event_from_crossing`
  still sets it from `ThresholdMonitor::sequence` — i.e. confirm neither
  producer was silently modified to "fix" the field, since that would
  itself be an undisclosed production change; (b) the handoff's own text
  states each event's raw `timestamp_monotonic` is retained as
  **provenance only** and never consulted for a grouping/windowing
  decision anywhere in §4/§6/§7/§18; (c) `P2-EVT-001`/`P2-EVT-003` in
  §19 actually encode this as testable properties (a test with two fake
  producers emitting wildly different/backwards raw timestamps must
  still group by ingress order); (d) the restart-epoch statement
  (`P2-EVT-004`, §9) is present and states the ingress clock/sequence
  reset with no cross-restart persistence. **Required verdict addition:**
  if any correlation rule anywhere still compares raw
  `timestamp_monotonic` values across producers for a grouping/windowing
  decision, that is a reintroduction of the original blocking defect and
  requires `TDD-CONTRACT PHASE 2 PLANNING REJECTED`, not a conditional
  note.
- Verify §4.3's confidence cap (`Hypothesis`) and terminology
  requirement ("correlated with," never "caused by") are not just
  stated but are testable — confirm P2-COR-005 in §19 actually encodes
  this as a checkable property, not prose alone.
- Verify §14's claim that `Health`'s real variants are
  `Healthy/Warning/Error/Stale/Unknown` (not the task prompt's
  illustrative `Healthy→Degraded`) by reading
  `crates/guardian-provider-api/src/capability.rs` directly. If the
  handoff is wrong about the real enum, its §4.2 correlation rule is
  built on a false premise and must be corrected before acceptance.
- **Provider-health scope-honesty regression check (repair-pass
  requirement).** Verify §1, §3, §4.2, and §13 all state plainly that no
  `Event` of any kind is produced for provider-health today — confirm by
  reading `crates/guardian-daemon/src/bin/guardian-daemon.rs`'s
  `capability_registry_tick` directly and confirming it returns
  `Vec<CapabilityRecord>` only. Any section that reverts to describing
  this as merely needing "detection logic" (implying an event stream
  already exists) is a regression of the corrected finding and must be
  flagged.
- Verify no opaque AI/LLM scoring was introduced anywhere in §4 — every
  rule must be a plain, auditable function of typed inputs.

---

# 8. Events-vs-incidents and severity/wire audit (task items 5, 15) — corrected, repair pass

- Verify §5's "reopening" decision (new `IncidentId` with text
  backreference, no `Reopened` status) is explicitly flagged as a
  design decision, not smuggled in as if it were obviously the only
  option — the task required exactly this kind of decision be called
  out, and it is scored on whether it was surfaced honestly.
- **Severity-deferral regression check (repair-pass requirement,
  replaces the original severity-field check).** Verify §15 states
  severity is **deferred in full** for this phase — no `severity` field
  is added to `Incident`. Independently check
  `crates/guardian-core/src/incident.rs` to confirm `Incident` still has
  no `severity` field and `Incident::link_event(&mut self, event_id:
  EventId)`'s signature is still exactly `EventId`-only (not `Event`,
  not `Risk`) — i.e. confirm the type was genuinely **not** modified,
  not merely that the handoff claims it wasn't.
- Verify `crates/guardian-daemon/src/dbus_surface.rs`'s `IncidentWire`
  and `crates/guardian-client/src/lib.rs`'s matching `IncidentWire`/
  `From<IncidentWire>` are still the identical positional 7-tuple shape
  as the published baseline (`1423d9c3053394e19e461ee6adea31bea9231fa7`)
  — diff both files against that commit directly rather than trusting
  the handoff's "stays frozen" claim.
- Verify G3's NB-3 note (`docs/evidence/g3/G3_MILESTONE.md`) is
  explicitly and honestly left **open** by §15/§51 — the text must state
  plainly that this phase does not trigger NB-3 (because severity is
  deferred) and must not claim NB-3 is closed, resolved, or
  inapplicable-forever. A future re-review must reject any version that
  silently drops this open-item statement.
- **Required verdict addition:** if a future re-review finds `severity`
  added to `Incident`, `link_event`'s signature changed, `IncidentWire`'s
  shape changed, or NB-3 silently closed/ignored, that is a regression
  of a resolved blocking defect and requires
  `TDD-CONTRACT PHASE 2 PLANNING REJECTED`.

---

# 9. Determinism and bounds audit (task items 6, 7) — corrected, repair pass

- **Corrected determinism check.** Verify §6's determinism claim rests
  entirely on the `CorrelationIngress` ingress clock/sequence total
  order (§6), **never** on raw `timestamp_monotonic`/
  `sort_by_monotonic_order` and never on `timestamp_wall`. A correlation
  design that compares any producer's own `timestamp_monotonic` or
  wall-clock time anywhere for grouping decisions must be rejected — see
  §7 above for the required verdict on this specific regression.
- Verify §6 states the restart-epoch semantics explicitly (ingress
  clock/sequence reset to a fresh epoch on daemon restart, no
  persistence, no cross-restart ordering guarantee) and that this is
  consistent with §9's incident-loss statement — the two must not
  contradict each other.
- **Verify all three bounded state classes, not two (repair-pass
  correction to this checklist item).** §7 must specify three
  independent bounded structures with three independently-stated
  eviction/rejection policies, not two: (1) the open-incident cap
  (force-close-oldest — verify this is stated), (2) the closed-incident
  ring (FIFO-drop-oldest, mirroring `BoundedRecorder` — verify this is
  stated), and (3) the debounce/dwell bookkeeping ring for
  provider-health flapping (§4.2) — verify this ring's policy is
  **reject-not-evict** (a typed `CapacityRejected` outcome for the new
  candidate, existing candidates never evicted), **not** FIFO eviction.
  A version of §7 that describes the debounce ring with FIFO/oldest-
  eviction, or that does not specify its policy at all, is a regression
  of the resolved blocking defect on this point and requires
  `TDD-CONTRACT PHASE 2 PLANNING REJECTED`.
- **Corrected (second repair pass) — `CapacityRejected` observability
  must be the single, non-disjunctive mechanism, not "pick one."**
  Verify §7, §18, and `P2-REC-003`'s own normative text in the
  implementation handoff all state, identically, that a
  `CapacityRejected` outcome (a) increments a daemon-owned, bounded/
  saturating rejection counter (`saturating_add`, never itself
  unbounded), (b) writes one plain operational log line via
  `guardian-daemon`'s existing `eprintln!("[guardian-daemon] ...")`
  convention — confirm by reading
  `crates/guardian-daemon/src/bin/guardian-daemon.rs` directly that this
  is in fact the project's only existing logging mechanism (no
  `tracing`/`log` crate anywhere in the workspace's `Cargo.toml` files) —
  and (c) **by rule DOES NOT construct or feed another `Event` into
  `CorrelationIngress` or any other correlation input path.** A version
  that still reads as a menu ("a Guardian event, or at minimum a
  counter/log line — implementation states which") is a regression of
  this repair and requires `TDD-CONTRACT PHASE 2 PLANNING REJECTED`, not
  a conditional note.
- **Recursive-overflow non-re-entry check (second repair pass,
  required).** Verify `P2-REC-005` (§19) exists, is independently
  testable, and states exactly the property that forecloses the
  recursive-overflow risk: under a sustained storm of many distinct new
  debounce-candidate keys past capacity, the number of
  `CorrelationIngress`-admitted events is provably bounded by the real
  event producers alone, never inflated by the count of
  `CapacityRejected` outcomes themselves. Confirm no correlation-input
  code path anywhere in §4/§6/§7/§20 constructs an `Event` from a
  `CapacityRejected` outcome. If any code path or test plan implies a
  rejection can re-enter `CorrelationIngress`, that is the exact
  blocking defect this repair pass exists to close and requires
  `TDD-CONTRACT PHASE 2 PLANNING REJECTED`.
- Verify §18's adversarial matrix has a corresponding row (the "many new
  debounce keys" storm scenario) that is not silently merged with the
  open-incident-cap storm scenario (they have different,
  non-interchangeable mitigations — verify the handoff does not conflate
  them), and that this row now cites the saturating-counter-plus-log-line
  mechanism and `P2-REC-005`'s non-re-entry guarantee, not the retired
  disjunction.
- Verify §7's claim that correlation "never calls `budget::evaluate`...
  on its own grouping path" is consistent with §16's deferral — the two
  sections must not contradict each other.

---

# 10. Persistence and restart-semantics audit (task items 8, 9)

- **Gate-qualified FC-N citation check (repair-pass requirement).**
  Verify every FC-N citation throughout the implementation handoff and
  §51 names its actual gate — "G5's FC-1," "G5's FC-2," "G4's FC-3" —
  never a bare "FC-1"/"FC-2"/"FC-3" that could be misread as one
  continuous series. Cross-check each against the real text: G4's own
  FC-1 ("`DiagnosticCost` unconsumed"), FC-2 ("no budget-denied typed
  outcome"), FC-3 ("Flight Recorder unrelated to G4's persistence
  module"), FC-4 ("PSI has no G3/G4 representation") in
  `docs/evidence/g4/G4_MILESTONE.md`; G5's own FC-1 ("recorder byte
  boundedness") and FC-2 ("`RecorderPolicy` runtime wiring") in
  `docs/evidence/g5/G5_MILESTONE.md` — note G5 has only two FC items,
  not three; there is no "G5's FC-3." Verify §8's persistence table
  cites G5's FC-1/FC-2 and §12's transaction-observability deferral
  cites G4's FC-3, not the other way around or unqualified. The
  implementation handoff must not claim any of these are closed by this
  phase; confirm it explicitly states they remain open (it does, in
  §8's summary line and §21).
- Verify §9's restart/reboot loss-semantics statement is unambiguous and
  matches §8's "nothing persisted" conclusion — an implementation
  handoff that says "nothing is persisted" but then implies incidents
  "mostly" survive restart would be self-contradictory; confirm no such
  contradiction exists.
- Verify the `/var/lib/guardian/{daemon,helper}` ownership split
  description matches `docs/adr/ADR-008-guardian-package-filesystem-
  layout.md` exactly (owners, directory names) — do not accept a
  paraphrase that drops the ownership distinction.

---

# 11. Public API and privilege audit (task items 10, 11, 12)

- Verify §10's claim that `IncidentWire`/`guardian_client::Incident`
  already exist and are reused, not reinvented, by reading
  `crates/guardian-client/src/lib.rs` directly.
- Verify §11 reuses G2's table without promoting any `unknown` row —
  diff the implementation handoff's privilege claims against
  `docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`'s actual rows
  for PSI, systemd (read), UDisks2 (read), UPower, AccountsService
  (read), journald (read). Any row where the handoff's classification
  disagrees with G2's is a blocking finding requiring the
  `PRIVILEGE BOUNDARY UNRESOLVED` verdict, not a silent correction.
- Verify §11's cross-source privacy finding (§4.3 correlation
  potentially over-implying a relationship) is a genuine, specific
  concern with a genuine, specific mitigation (`confidence` cap) — not
  a vague "this could be sensitive" hand-wave with no concrete
  resolution.

---

# 12. Testing ladder and adversarial matrix audit (task items 17, 18)

- Verify every row in the implementation handoff's §18 adversarial
  matrix maps to at least one named normative ID in §19, or is
  explicitly marked N/A with a stated reason (persistence corruption,
  budget exhaustion) — an adversarial scenario with no corresponding ID
  and no N/A justification is an incomplete plan.
- Verify the Layer 1–5 assignments in §17 are consistent with where the
  underlying mechanism actually lives (e.g. PSI is `/proc`-backed, so a
  claim that PSI correlation needs Layer 3 umockdev would be wrong —
  confirm the handoff correctly places it outside Layer 3).
- Confirm §18's adversarial matrix includes the two rows added by this
  repair pass — the ingress-order-vs-raw-timestamp scenario
  (`P2-EVT-003`) and the many-new-debounce-keys `CapacityRejected`
  scenario (`P2-REC-003`/`P2-REC-004`, distinct from the existing
  many-existing-keys open-incident-cap row) — and that the removed
  "wire-visible severity" test row is genuinely absent, not merely
  unasserted.

---

# 13. Normative-ID audit (task item 19) — revised, repair pass

- Confirm no ID in §19 uses a letter suffix (the `002b` defect Wave 1's
  own revision history records and fixed) — every ID must be a plain
  sequential number within its family.
- Confirm every ID is independently testable as stated — pick three at
  random (suggest P2-COR-006, P2-INC-002, P2-VM-002) and verify a
  competent implementer could write a single, unambiguous test from the
  ID's text alone, without needing to re-read surrounding prose to
  disambiguate.
- Confirm the family list (`P2-EVT-*`, `P2-COR-*`, `P2-INC-*`,
  `P2-REC-*`, `P2-API-*`, `P2-VM-*`) matches between §51 of the contract
  and §19 of the implementation handoff exactly.
- **Retired/new-ID audit (repair-pass requirement).** Confirm
  `P2-INC-001` is explicitly marked **retired** (not silently deleted,
  not renumbered into a different requirement) with a stated reason
  (severity deferred, §15) and no replacement ID minted in its place —
  a version that quietly reuses the number `P2-INC-001` for an unrelated
  requirement is a documentation-discipline defect. Confirm
  `P2-EVT-003`, `P2-EVT-004`, `P2-REC-003`, `P2-REC-004` are present,
  each independently testable, and each traces to one of the three
  binding architectural decisions (ingress ordering, restart-epoch
  reset, debounce-rejection observability, existing-candidate survival
  respectively). Confirm `P2-REC-001`'s text was actually reworded to
  reject-not-evict, not left as the original FIFO-eviction wording with
  new IDs merely appended alongside it (that would leave the original,
  unsafe policy still normatively stated).
- Confirm the total literal `P2-*` ID list is stated in full in this
  review's final report (§16) — not merely a count — since the count
  itself changed from the original draft and a bare count would hide
  exactly the kind of silent renumbering this section exists to catch.
- **Second-repair-pass ID audit (new).** Confirm `P2-REC-003` was
  **reworded** (not merely re-typeset) to state the single,
  non-disjunctive mechanism (bounded/saturating counter + existing
  `eprintln!` log line) — a version still containing "implementation
  states which" language is a regression. Confirm `P2-REC-005` is
  **new**, independently testable, and traces to the debounce-rejection
  non-re-entry-into-`CorrelationIngress` decision. Confirm `P2-API-003`
  is **new**, independently testable, and traces to the `IncidentWire`
  wire-shape regression-lock decision. Confirm none of
  `P2-REC-003`/`P2-REC-005`/`P2-API-003` reuses a number already retired
  or assigned to a different requirement, and that no other ID's text
  changed incidentally in the process of adding these three.

---

# 14. Second-repair-pass audit (five non-blocking items)

- **Window-definition reconciliation.** Verify §4.1 now states the PSI
  correlation window is a **duration** measured against
  `CorrelationIngress`'s `ingress_clock` (`Instant`-based), and that
  `ingress_sequence` is stated to serve only as a tie-breaker for events
  sharing an identical `Instant`, never as the window measurement
  itself. Verify §18's "correlation-window boundary" row matches this
  wording — a version where that row still describes window-boundary
  tests as manipulating "explicit ingress-sequence values" (conflating
  the tie-breaker with the duration measurement) is a regression of this
  item.
- **`Instant`-construction technique.** Verify a §6a (or equivalently
  located) section exists stating the concrete technique: one real
  `base = Instant::now()` at test setup, then `base +
  Duration::from_millis(N)` for forward placement or
  `base.checked_sub(Duration::from_millis(N))` for backwards/reordering
  cases. Confirm this note is referenced from wherever Layer-1 test
  construction is described (§6/§17/§18) rather than left an isolated,
  unreferenced aside.
- **Internal gate decomposition.** Verify §20 contains an explicit
  Gate 2a/2b/2c breakdown (or equivalent), and that each gate states its
  purpose, dependencies on prior gates, the normative IDs it owns, its
  implementation scope, which test layers apply, what VM evidence (if
  any) it needs, and its own exit criteria. Verify the gate breakdown
  does not change the underlying `P2-*` scope or ID list — it must be a
  sequencing addition only; if it silently drops or adds a requirement
  under cover of "restructuring," treat that as a scope-discipline
  finding (§15 below), not an acceptable structural change.
- **Generic-vs-enrichment categorization.** Verify §3's systemd/logind/
  UDisks2/UPower/AccountsService rows (or wherever the categorization
  ends up) explicitly mark the generic, uniform Availability/Health-
  transition signal as **REQUIRED FOUNDATION** and each source's richer,
  source-specific semantics (named per source: UDisks2 device identity/
  appearance-disappearance, logind session/inhibitor detail, UPower
  battery/AC detail, AccountsService session specifics) as **OPTIONAL
  FUTURE ENRICHMENT, not part of this Phase 2 gate sequence** — a
  blanket "no gap beyond general correlation wiring" cell surviving
  anywhere for these rows is a regression of this item.
- **`IncidentWire` regression-test requirement.** Verify `P2-API-003`
  (§19) exists and requires a test locking `IncidentWire`'s exact current
  7-field positional-tuple-of-`String`s shape, and that the handoff
  states plainly this is a regression guard for Phase 2, not a new
  capability. Independently confirm the shape claim itself by reading
  `crates/guardian-daemon/src/dbus_surface.rs:233` and
  `crates/guardian-client/src/lib.rs:195` directly.

---

# 15. Scope-discipline audit (task items 21, 23)

- Confirm the implementation handoff does not pull in any Wave 1
  hardening-backlog item (`JobRemoved` prefilter, rollback race
  fixture, listener-thread instrumentation) — grep for these terms in
  the new document; their absence (except as an explicit "not pulled
  in" statement, if present) is correct.
- Confirm the changed-file list this planning pass reports (§1 of this
  review handoff) is exhaustive — run `git status --short` and
  `git diff --stat` against `origin/main` yourself rather than trusting
  the planning pass's own enumeration.
- Confirm no `Cargo.toml`/`Cargo.lock`/`crates/` file changed. If one
  did, the planning pass violated the task's explicit "STOP and report"
  instruction for any production change and must be rejected regardless
  of the planning content's quality.

---

# 16. Required report

State the verdict from §3, then for each of the sixteen audit sections
above: pass/fail/conditional, with the specific evidence checked (file
path + what was confirmed or contradicted), not a restatement of the
implementation handoff's own claims. Flag any place where this review
handoff itself found the implementation handoff's citation did not match
the actual source file — that is the most valuable single class of
finding an independent review can produce here, per this project's own
established standard (G4's "module presence != executed contract"
lesson exists precisely because an earlier review accepted a claim
without checking the source).

**First repair-pass regression verdicts (required, in addition to the
above).** State an explicit pass/fail for each of the five corrections
the first repair pass made, since a regression on any of these is scored
as a rejection per the required-verdict additions in §7/§8/§9 above, not
merely a nit:

1. Correlation-ingress ordering model genuinely used for all
   grouping/windowing decisions; raw producer `timestamp_monotonic`
   values are provenance-only and never compared across producers.
2. `IncidentWire`/`Incident::link_event`'s signatures are genuinely
   unchanged (diffed against the published baseline, not merely
   claimed); no `severity` field exists on `Incident`; G3's NB-3 is
   explicitly and honestly left open.
3. The debounce/dwell bookkeeping ring's reject-not-evict
   `CapacityRejected` policy is specified and its rejection is
   observable; existing tracked candidates cannot be evicted by
   new-key pressure.
4. Every FC-N citation is gate-qualified (G4's vs. G5's) and accurate
   against the real milestone text.
5. Provider-health event production is honestly described as
   nonexistent today (not merely needing "detection logic").

**Second repair-pass regression verdicts (required, in addition to the
above — new).** State an explicit pass/fail for each of the following,
since a regression on the first is scored as a rejection per §9's
required-verdict addition above, not merely a nit:

1. The `CapacityRejected` observability mechanism is the single,
   non-disjunctive rule (bounded/saturating counter + existing
   `eprintln!("[guardian-daemon] ...")` log line, both always, never a
   choice) — not the retired "pick one" disjunction — **and** a
   `CapacityRejected` outcome is confirmed, by rule and by an
   independently-testable ID (`P2-REC-005`), to never construct or feed
   an `Event` into `CorrelationIngress` or any other correlation input
   path.
2. §4.1's window definition is reconciled with §18's adversarial-matrix
   wording: the window is a duration measured via `ingress_clock`, and
   `ingress_sequence` is stated as a tie-breaker only.
3. The `Instant`-construction test technique (`base = Instant::now()` +
   `Duration::from_millis(N)` / `checked_sub`) is stated explicitly
   somewhere a Layer-1 test-writer would find it.
4. §20 contains an internal Gate 2a/2b/2c decomposition with purpose,
   dependencies, owned normative IDs, implementation scope, test layers,
   VM evidence, and exit criteria stated for each gate, without having
   silently changed the underlying scope or ID list.
5. Generic capability-health-transition correlation is marked REQUIRED
   FOUNDATION and each of UDisks2/logind/UPower/AccountsService's
   richer, source-specific semantics is marked OPTIONAL FUTURE
   ENRICHMENT, not part of this gate sequence, named per source.
6. `P2-API-003` requires an `IncidentWire` wire-shape regression test,
   correctly described as a regression guard, not a new capability.

Also enumerate the full, literal `P2-*` ID list as it stands after both
repair passes (not a count) — including the retired `P2-INC-001` and
every new ID from both repair passes (`P2-EVT-003`, `P2-EVT-004`,
`P2-REC-003` (reworded, not merely re-typeset), `P2-REC-004`,
`P2-REC-005`, `P2-API-003`) — confirming none was silently renumbered or
reused for a different requirement.
