# Guardian Phase 0 Independent Review Handoff
## G6 — Indicator Decision Only

This document is authoritative for the independent review of a G6
implementation candidate. Use it in place of restating the architecture
in a review prompt.

# 1. Baseline verification

- Confirm the exact baseline commit (should be `phase0-g5-diagnostic-safety`,
  `5bcf21bdb2fc07f0ccbef6051b9162e92c96f890`, or a later commit the task
  explicitly names) and the candidate commit.
- Confirm every earlier gate tag (`phase0-g0-public-contracts` through
  `phase0-g5-diagnostic-safety`) is an ancestor of the candidate and
  unmoved.
- Confirm no `phase0-g6-*` tag exists yet.

# 2. Governing material to read

- `AGENTS.md`
- `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §30, §31,
  §36 (P0-IND-001..003), §39, §45
- `docs/guardian/30_TDD/GUARDIAN_G6_IMPLEMENTATION_HANDOFF.md` (this
  gate's authoritative implementation handoff)
- `docs/evidence/g5/G5_MILESTONE.md` (FC-1/FC-2 -- unrelated to indicator
  scope directly, but its "module presence != executed safety contract"
  lesson is the direct analogue of this gate's central risk: "candidate
  selected on paper != candidate proven against real environments")
- `docs/evidence/g1/G1_LAYER2_EVIDENCE.md`, `docs/evidence/g2/MODEL_A_EVIDENCE.md`,
  `docs/evidence/g2/MODEL_B_EVIDENCE.md` -- the evidentiary bar this
  gate's real-environment claims must meet, by precedent.

# 3. Required verdict

```text
PASS
PASS WITH NON-BLOCKING FINDINGS
FAIL — SIMULATED EVIDENCE SUBSTITUTED FOR REAL ENVIRONMENT
FAIL — PREMATURE OR UNJUSTIFIED CANDIDATE SELECTION
FAIL — <other short, specific label>
```

# 4. THE central audit question (highest priority, read first)

**G6 is unlike every prior gate audited so far.** G0-G5's independent
audits could verify a claim by running `cargo test` and by executing real
adversarial mutations against tracked Rust source. G6's normative
requirements (§30: icon appears, menu opens, reconnect after panel/Shell
restart, reconnect after daemon restart, no duplicate icon, clean
logout/login, daemon-unavailable degraded state, no X11 dependency) are
**real-desktop-environment claims**, not pure-Rust-logic claims. The
single most important thing this review must determine is:

**Is every one of P0-IND-001/002/003 backed by genuine evidence of the
candidate actually running against a real GNOME 50/Wayland session and a
real Xfce 4.20 session -- or does the completion report substitute an
in-process mock, a unit test of the indicator library's internal state
machine, or prose assertion for that evidence?**

A `cargo test` pass proves nothing here by itself unless the test is
explicitly show to be *decision-logic* over an already-gathered real
results matrix (see implementation handoff §6) -- verify that any test
suite the candidate ships is not quietly standing in for the real-
environment claim it cannot actually prove.

# 5. Normative contract audit

Independently re-derive from the contract text itself:

```text
P0-IND-001 — GNOME compatibility
P0-IND-002 — Xfce compatibility
P0-IND-003 — reconnect
```

For each: what exact evidence would constitute proof (per §30's required-
test list), what evidence the candidate actually provides, and whether
that evidence is real-environment or simulated. A candidate claiming
`CANDIDATE` status with only simulated evidence is an automatic `FAIL --
SIMULATED EVIDENCE SUBSTITUTED FOR REAL ENVIRONMENT`, regardless of how
much Rust code exists.

# 6. Candidate comparison audit

- Confirm all three required candidates (legacy GTK3 Ayatana
  AppIndicator, GLib-only Ayatana AppIndicator 2.x, direct Rust SNI/
  `ksni`) were actually evaluated, not just the eventual winner. A
  completion report that only discusses the selected candidate, with no
  record of why the other two were rejected (which specific required
  test failed, on which environment), is incomplete -- `FAIL —
  PREMATURE OR UNJUSTIFIED CANDIDATE SELECTION`.
- Confirm the selection rule was actually applied as written: "the
  simplest candidate that passes all required targets... the test
  result, not library recency, selects the implementation." If multiple
  candidates passed everywhere, confirm the tiebreak used is genuinely
  "simplest" (by some stated, defensible measure) and not an unstated
  preference.
- If a candidate was disqualified, confirm the disqualifying evidence is
  real (a specific required test failed on a specific real environment),
  not assumed/inferred from documentation about the library.

# 7. Real-environment evidence audit

- For each environment (GNOME 50/Wayland, Xfce 4.20), confirm a real
  evidence artifact exists (VM setup script + transcript/log, matching
  `docs/evidence/g1/g1-layer2-vm-setup.sh` + `G1_LAYER2_EVIDENCE.md`'s
  format, or an equivalent real-artifact standard) -- not merely a
  completion-report assertion that testing "was done."
- Confirm the required-test list (§30) was evidenced item-by-item: icon
  appears, menu opens, menu actions invoke the client-side handler,
  state/icon update propagates, no X11 dependency, reconnect after
  panel/Shell restart, reconnect after daemon restart, daemon unavailable
  shows degraded state, no duplicate icon, clean logout/login lifecycle
  -- ten distinct claims, not one aggregate "it worked" claim.
- Reconnect specifically (P0-IND-003) has two distinct required sub-
  claims per §30 ("reconnect after panel/Shell restart" AND "reconnect
  after daemon restart") -- confirm both are separately evidenced, not
  only one.
- **Provenance:** every screenshot/recording cited as evidence must be
  directly attributable, via its filename or an adjacent caption/log
  line, to a specific candidate build, a specific environment (GNOME 50
  or Xfce 4.20), and a specific capture time. An unlabeled image proves
  nothing about which candidate or environment it came from -- treat any
  such unlabeled evidence as equivalent to no evidence for that specific
  claim, even if the image itself looks real.
- **Teardown:** confirm each candidate/environment run's evidence
  includes an explicit teardown record (autostart entries removed, any
  shell-extension/panel-plugin change reverted, session/VM confirmed back
  to baseline) before the next candidate was tested or the VM was
  discarded. Absence of any teardown record is a finding -- flag it even
  if nothing appears to have gone wrong, since the requirement is about
  discipline that prevents leftover state from silently propagating
  through a cloned/snapshotted VM image, not about a specific observed
  failure.

# 8. Decision-logic audit (only if the candidate built the optional §6 type)

If the candidate built a results-matrix/selection-query Rust type: verify
its tests use the *real* gathered matrix (or a fixture matrix that
matches the real results, if the real matrix is recorded elsewhere) as at
least one test case, plus an ambiguous-tie case and a zero-winners case.
Confirm this type does not itself become the "evidence" for P0-IND-001/
002/003 -- it can only ever prove "given this matrix, the selection logic
picks correctly," never "the candidate actually passed on a real
desktop."

# 9. ADR-006 audit

Confirm `docs/adr/ADR-006-*.md` (or equivalently named) exists, follows
the structure of `ADR-001`/`ADR-002`, and cites the real evidence
gathered in this gate rather than merely restating the implementation
handoff's candidate list. An ADR that could have been written before any
real testing happened (i.e., contains no environment-specific findings)
is a finding.

# 10. Implementation-order tension audit

The implementation handoff's §7 resolves the gate-list-vs-§39 tension in
favor of resolution A (G6 is an early decision/spike gate; §39 is a
notional, non-binding build-order checklist), citing this project's own
git history (`phase0-g2-privilege-topology` accepted before
`phase0-g4-transaction-engine`/`phase0-g5-diagnostic-safety`, directly
contradicting §39's own item ordering) as decisive evidence. Confirm the
candidate recorded this resolution explicitly in its completion report
rather than silently assuming it, and confirm nothing in the candidate's
actual work implies a different, unstated resolution was used instead
(e.g. building far more daemon/provider infrastructure than resolution A
would justify, which would suggest the candidate was actually operating
under an unstated resolution B or C).

If the candidate built minimal daemon-skeleton infrastructure to evidence
P0-IND-003's "reconnect after daemon restart" claim, confirm: (a) it is
genuinely minimal (not a G7 production daemon built under cover of this
gate); (b) it is **explicitly marked non-production/disposable** (a
clearly-scratch-named crate/module, or a prominent doc comment stating it
is G6 evidence infrastructure only) per the implementation handoff's §8
requirement; and (c) the completion report does not suggest or imply this
stub should be reused as G7's actual daemon skeleton -- G7 must design
its own from its own governing handoff. A stub that exists but isn't
clearly marked disposable is a finding, even if it's otherwise minimal.

# 11. Scope-leak audit (G7/G8/G9)

- No real production daemon beyond whatever minimal skeleton was
  explicitly justified per §10.
- No GUI/TUI/CLI shell implementation.
- No real provider (systemd/PSI/logind/UDisks/UPower/AccountsService).
- No packaging.
- No unrelated `guardian-core` G0-G5 module changes.

# 12. Regression audit

- `git diff --stat <G5-tag>..<candidate>` for anything outside a new
  indicator-scoped path or `docs/adr/ADR-006-*.md` needs individual
  justification.
- Re-run the full pre-G6 test suite (189 tests as of the G5 milestone)
  and confirm zero regressions.

# 13. Validation

```text
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Report actual results, independently summed. Note: this gate may add
little or no new Rust code if it stays scoped to real-environment
comparison plus an ADR -- a small/zero test-count delta is not itself a
finding, given §2's framing of this gate's actual nature.

# 14. Required report

Include, at minimum: full changed-file reconciliation (independently
enumerated, not sampled); explicit answer to §4's central audit question
for each of P0-IND-001/002/003; the candidate-comparison audit (§6)
results for all three required candidates, not just the winner; the
real-environment evidence audit (§7) results, item-by-item against §30's
ten required tests; the decision-logic audit (§8) if applicable; the
ADR-006 audit (§9); the implementation-order tension audit (§10); scope-
leak confirmation (§11); regression confirmation (§12); exact validation
output (§13); blocking findings (file/evidence-gap, contract/test,
problem, why it matters, required correction -- "None" if none); non-
blocking findings (same format, or "None"); and exactly one recommended
next action from:

```text
Tag G6 and prepare G7 gate.
Repair G6 and re-review.
Gather missing real-environment evidence before re-review.
Reconsider G6 candidate selection.
```

Then stop. Do not tag G6. Do not begin G7. Do not push unless the task
explicitly instructs it.
