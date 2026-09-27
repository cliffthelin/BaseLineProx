# Guardian Phase 0 Implementation Handoff
## G6 — Indicator Decision Only

**Status:** authoritative for this gate. Prompts for this gate should
describe only the task and the delta against this document. Do not
silently reinterpret anything below; if something here conflicts with the
governing contract, the contract wins and the conflict must be raised
explicitly, not resolved by guessing.

---

# 1. Mission

Implement exactly what TDD contract §"G6 — Indicator decision" requires:

```text
Required:
- GNOME 50 test;
- Xfce 4.20 test;
- implementation selected and documented.

Tests:
P0-IND-001..003
```

Do **not** begin G7 (production daemon), G8 (real providers beyond a
fixture-scoped indicator backend), or G9 (packaging). Do not build the
GUI/TUI/CLI shells themselves — G6 is scoped to the *indicator surface
only*, per the contract's own client-surface separation (§31: "All
clients MUST remain thin," each client type is its own later concern).

# 2. Read this before anything else: G6 is a different kind of gate

G0 through G5 were provable entirely inside a headless Rust test binary --
every normative test was a deterministic, fixture-driven assertion with
no real desktop, no real D-Bus session bus with a real indicator host, and
no real window manager. **G6 is not that kind of gate.** Its own governing
section (§30) requires:

```text
Target environments:
Ubuntu 26.04.1 GNOME 50 / Wayland
Xfce 4.20 / Status Tray

Required indicator tests:
- icon appears;
- menu opens;
- menu actions invoke the client-side handler;
- state/icon update propagates;
- no X11 dependency;
- reconnect after panel/Shell restart;
- reconnect after daemon restart;
- daemon unavailable shows degraded state;
- no duplicate icon;
- clean user logout/login lifecycle.
```

None of these are provable by a `cargo test` fixture alone -- "icon
appears" and "menu opens" are real-desktop, real-compositor observations.
This gate's evidentiary standard is therefore **G1/G2's precedent, not
G3/G4/G5's**: those two gates established the pattern this project already
uses when a contract requirement is genuinely a real-host claim rather
than a pure-Rust-logic claim --

```text
docs/evidence/g1/g1-layer2-vm-setup.sh, G1_LAYER2_EVIDENCE.md
docs/evidence/g2/g2-vm-setup.sh, MODEL_A_EVIDENCE.md, MODEL_B_EVIDENCE.md
```

-- a real VM setup script, a real transcript/evidence log of what was
observed, and a milestone record that cites that evidence directly rather
than only citing `cargo test` output. **G6 must follow this same
pattern**, not attempt to fake real-desktop behavior with an in-process
Rust mock and call the contract satisfied. Where a sub-requirement
genuinely can be unit-tested in isolation (e.g. the *decision logic* that
picks an implementation, or a parser/state-machine component internal to
whichever candidate is chosen), do that in `cargo test` per this
project's normal discipline -- but the required indicator test list above
is a real-environment claim and must be evidenced as one.

# 3. Read before changing code

- `AGENTS.md`
- `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §30 (Desktop
  indicator decision gate -- the authoritative requirement list, quoted
  above), §31 (GUI/TUI/CLI/indicator thinness rule), §36 (P0-IND-001..003
  definitions), §39 (implementation order -- note the tension described
  in §7 below), §45 (Phase 0 exit criteria: "indicator implementation is
  selected").
- `docs/guardian/10_Platform/StatusNotifierItem.md`,
  `docs/guardian/20_Control_Plane/Client_Surfaces.md` -- existing pointer
  pages.
- `docs/guardian/90_Sources/wiki/ksni-docs.md`,
  `docs/guardian/90_Sources/wiki/ayatana-glib-resolute.md` -- external
  source snapshots for the two named Rust/GLib candidate libraries;
  recheck their canonical URLs before relying on any version/API claim.
- `docs/evidence/g1/`, `docs/evidence/g2/` -- the established real-host
  evidence pattern this gate must follow (§2 above).
- `docs/evidence/g5/G5_MILESTONE.md` -- the accepted G5 state; nothing in
  it directly gates G6 (diagnostic safety and the indicator surface are
  unrelated concerns), but its "module presence != executed safety
  contract" lesson (FC-2) applies here too: a chosen indicator
  implementation must actually be exercised against the real target
  environments, not merely selected on paper.
- `docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md`,
  `docs/adr/ADR-002-guardian-privilege-topology.md` -- the ADR format
  this project already uses for exactly this kind of "compare N real
  candidates, document the decision" gate. The contract's own exit
  criteria (§45 area) references an "ADR-006 Desktop indicator
  implementation" that does not yet exist in `docs/adr/` -- **this gate
  must create it**, following ADR-001/ADR-002's structure.

# 4. Normative G6 contract IDs

```text
P0-IND-001 — GNOME compatibility: chosen indicator works on Ubuntu GNOME 50/Wayland.
P0-IND-002 — Xfce compatibility: chosen indicator works on Xfce 4.20 Status Tray.
P0-IND-003 — reconnect: indicator reconnects after daemon or host restart.
```

Each of these three needs real-environment evidence per §2 -- not a
simulated/mocked D-Bus session standing in for a real desktop shell.

# 5. Required candidate comparison (§30)

Compare at least these three candidates, for real, against both target
environments:

1. legacy GTK3 Ayatana AppIndicator;
2. GLib-only Ayatana AppIndicator 2.x;
3. direct Rust SNI + canonical DBusMenu (e.g. `ksni`).

**"The winning implementation is the simplest candidate that passes all
required targets. The test result, not library recency, selects the
implementation."** (§30, verbatim) -- do not pre-select `ksni` merely
because it is the pure-Rust option this project otherwise prefers; run
the actual comparison and let the real GNOME 50/Xfce 4.20 test results
decide. If a candidate fails a required test (icon appears, menu opens,
reconnect, etc.) on either target environment, it is disqualified
regardless of how idiomatic or modern it is.

# 6. Decision-logic scope (what CAN be unit-tested)

Once real-environment testing has determined which candidates pass which
required tests, the *selection* itself -- given a real results matrix, is
there exactly one candidate that passes every required test on every
target environment, and if more than one does, does "simplest" have a
documented, defensible tiebreak -- is a legitimate thing to model as real
Rust logic with real unit tests, if you choose to build a decision-record
type rather than only a prose ADR. This is optional, not required by the
contract; do not build elaborate scaffolding here merely to have
"something in `cargo test`" for a gate that is fundamentally an
environment-comparison decision. If you do build it, keep it to: a real
results-matrix type (candidate × target-environment × pass/fail per
required test), a real "does exactly one candidate satisfy all required
tests everywhere" query, and tests proving that query's logic against a
few different fixture matrices (including an ambiguous/tied case and a
zero-winners case) -- not a reimplementation of the indicator itself.

# 7. Implementation-order tension (read before scheduling work)

The contract's gate list (§38-region) places G6 (indicator decision)
immediately after G5 and before G7 (production daemon)/G8 (providers)/G9
(clients). Its separate §39 "Implementation order" list places "Indicator
compatibility spike and selected implementation" at item 18 -- after the
daemon skeleton (13), initial providers (14), CLI (15), TUI shell (16),
and GUI shell (17). **This is a real tension in the governing contract
text, not a misreading -- but it resolves cleanly. Treat the gate list as
authoritative for this project's actual sequencing; §39 is a notional
build-order checklist, not a binding per-gate dependency graph.**

Resolution basis, independently verifiable from this project's own git
history rather than asserted:

- §45 (Phase 0 exit criteria) and §3 (Phase boundaries) both distinguish
  "indicator implementation **selected**" (Phase 0/G6, this gate) from
  the real `guardian-indicator` build (Phase 1/G9, tested by `P1-IND-*`,
  not `P0-IND-*`) -- the contract's own vocabulary already separates
  "decide" from "build," independent of §39.
- §39's own item ordering is demonstrably not a binding G-by-G sequence
  this project has ever honored, and correctly so: §39 places "privilege
  topology prototypes and decision" at item 12 -- *after* "transaction
  engine" (item 8), "diagnostic budget" (item 9), and "recorder" (item
  10). This project's actual, accepted gate history shows the opposite:
  `phase0-g2-privilege-topology` was tagged and accepted on 2026-08-31 at
  16:24, well *before* `phase0-g4-transaction-engine` (20:44) and
  `phase0-g5-diagnostic-safety` (21:46) the same day -- i.e., G0 through
  G5 were completed strictly in gate-number order, directly contradicting
  §39's own item ordering for privilege topology. Since §39 already
  diverges from this project's real, correct practice at G2, its later
  placement of the indicator spike (item 18) cannot be read as a hard
  dependency without the same contradiction recurring here.
- §38's "no gate advances until all required tests for that gate pass,"
  combined with the gate list placing G6 before G7, means G7's daemon
  skeleton (§39 item 13) cannot literally precede G6's completion --
  reinforcing that §39's item 18 placement cannot be a hard prerequisite
  without contradicting §38 itself.

**Conclusion: resolution A.** G6 is an early decision/spike gate; the
*chosen* candidate's full production wiring happens later (G9), mirroring
G2's own precedent exactly (real prototypes, a real decision, ADR-002,
production wiring deferred to G7). This is the default reading for this
gate. Still record the decision explicitly in the completion report
(mirroring the G5 handoff's §5 requirement) rather than silently assuming
it -- if you find contract text this handoff missed that changes this
conclusion, cite it and stop rather than overriding this resolution
silently.

# 8. Explicit non-goals (do not implement here)

- No real production daemon (`guardian-daemon` skeleton, systemd unit,
  real D-Bus service registration) unless needed as minimal evidence
  infrastructure for P0-IND-003's "reconnect after daemon restart" claim
  -- and even then, keep it to the minimal skeleton needed to prove that
  one claim, not a real G7 daemon. **If such a stub is built, it MUST be
  explicitly marked non-production** (e.g. a clearly-named scratch crate
  or module such as `guardian-indicator-evidence-stub`, or a prominent
  doc comment stating it is disposable G6 evidence infrastructure, not a
  starting point for G7) and must not be silently adopted, extended, or
  reused as the real G7 daemon skeleton when that gate begins -- G7 must
  design its own daemon skeleton from its own governing handoff, not
  inherit one built to satisfy a single G6 evidence requirement.
- No GUI/TUI/CLI shell implementation.
- No real provider (systemd/PSI/logind/UDisks/UPower/AccountsService --
  all G8).
- No packaging (G9).
- No changes to `guardian-core`'s G0-G5 modules unless a genuine,
  narrowly-scoped need appears (unlikely -- the indicator surface is a
  new, separate client-facing concern).

# 9. Fail-closed / degraded-state checklist

- "daemon unavailable shows degraded state" (§30's own required test)
  must be a real, distinct, observable state -- never silently rendered
  as "icon just doesn't appear" with no indication anything is wrong.
- "no duplicate icon" must hold across a real reconnect sequence, not
  merely on first launch.
- A candidate that cannot be evidenced as passing a required test on a
  target environment is disqualified for that environment -- it must not
  be selected "provisionally" pending later verification.

# 10. TDD sequence

1. Set up the real GNOME 50/Wayland and Xfce 4.20 test environments
   (disposable VMs, matching G1/G2's `*-vm-setup.sh` precedent) before
   writing any indicator code. Never use a primary/production desktop for
   this testing.
2. Run each of the three required candidates against the real required
   test list (§30) on both environments; record real evidence (transcript,
   screenshots/recording references, or equivalent) per candidate per
   environment, matching `docs/evidence/g1/G1_LAYER2_EVIDENCE.md`'s
   format. **Any screenshot or recording MUST carry stated provenance**
   directly in its filename or an adjacent caption/log line: which
   candidate build, which environment (GNOME 50 or Xfce 4.20), and when
   it was captured -- an unlabeled image is not admissible evidence, no
   matter how real the underlying test was, since it cannot be
   independently attributed to a specific candidate/environment/run.
   **After each candidate/environment run, perform and record an explicit
   teardown step**: remove any autostart entry the candidate installed,
   revert any shell-extension or panel-plugin change made to test it, and
   confirm (e.g. via a final screenshot or log line) the VM/session is
   back to its pre-test baseline before the next candidate is tested or
   the VM is discarded -- no uncontrolled autostart entry or permanent
   shell-extension change may be left behind, even on a disposable VM
   that will itself be discarded, since an intermediate snapshot or clone
   of that VM could otherwise carry the leftover state forward.
3. Only after real results exist: write the ADR (`ADR-006`) documenting
   the decision per §30's own selection rule.
4. If you choose to build the optional decision-logic type from §6, do
   that with normal `cargo test` TDD discipline, using the real matrix
   you just gathered as one of its test fixtures.
5. Write the G6 milestone evidence record once real P0-IND-001..003
   results exist for the selected implementation.

# 11. Adversarial self-check before reporting done

1. simulated-desktop leakage -- was any required test (icon appears, menu
   opens, reconnect) claimed as passing based on an in-process mock
   D-Bus session rather than a real GNOME 50/Xfce 4.20 environment?
2. premature selection -- was a candidate selected before all three were
   actually run against both real environments?
3. recency bias -- did "simplest passing candidate" get silently
   overridden by "the one that felt more modern/idiomatic"?
4. degraded-state silence -- does "daemon unavailable" ever look
   indistinguishable from "everything is fine, no icon needed right now"?
5. reconnect gap -- is P0-IND-003 evidenced for both "daemon restarted"
   and "desktop panel/Shell restarted" (§30 lists both as separate
   required tests), or only one of the two?
6. scope leak -- did G7/G8/G9 material (real daemon, real providers,
   packaging) get implemented under cover of "needed for the indicator
   spike"?
7. ADR gap -- does `docs/adr/ADR-006-*.md` exist and actually cite the
   real evidence gathered, or is it a restatement of this handoff's
   candidate list without real results behind it?

# 12. Completion states

Report exactly one, honestly:

```text
G6 CANDIDATE — INDICATOR DECISION READY FOR INDEPENDENT AUDIT
G6 PARTIAL — REAL-ENVIRONMENT EVIDENCE INCOMPLETE
G6 BLOCKED — GOVERNING CONTRACT INSUFFICIENT
G6 BLOCKED — NO CANDIDATE PASSES ALL REQUIRED TARGETS
```

Do not report `CANDIDATE` on the strength of unit tests alone if any of
the real-environment required tests (§30) lack real evidence.

# 13. Completion report

Include, at minimum: which of the three required candidates were
actually run against which real environments, with evidence references
(not just a claim); the exact §30 required-test results per candidate per
environment; the final selection and the §30 tiebreak rule applied if
more than one candidate passed everywhere; the §7 implementation-order
tension and how it was resolved for this work; whether the optional §6
decision-logic type was built and its test results if so; `ADR-006`'s
location and content; full `cargo fmt --check` / `cargo clippy
--workspace --all-targets --all-features -- -D warnings` / `cargo test
--workspace` output for whatever Rust code this gate did add; and an
explicit statement of what was deferred to G7/G8/G9 and why.

Then stop. Do not begin G7. Do not tag G6 -- independent review happens
first, exactly as it did for G0 through G5.
