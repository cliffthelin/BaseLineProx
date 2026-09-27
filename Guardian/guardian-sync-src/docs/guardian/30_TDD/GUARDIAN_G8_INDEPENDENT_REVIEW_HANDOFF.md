# Guardian Phase 1 Independent Review Handoff
## G8 — Initial Providers Only

# 1. Baseline verification

```bash
git status
git rev-parse HEAD
git diff --name-status phase0-g7-production-daemon..HEAD
git diff --stat phase0-g7-production-daemon..HEAD
```

Baseline is `phase0-g7-production-daemon`
(`9984e0ac348cf48c87c06f1259167603779a676e`). Independently re-derive
this SHA from `git rev-parse phase0-g7-production-daemon^{commit}` rather
than trusting a pasted value. Confirm it and every earlier `phase0-g*` tag
are unmoved. Review every actual changed file — do not sample.

# 2. Governing material

```text
AGENTS.md
docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md  (§26, §27, §28,
  §29, §35, §37 P1-SYS/PSI/LGI/UDS/UPW/ACC, §38 G8 entry, §40, §41)
docs/guardian/30_TDD/GUARDIAN_G8_IMPLEMENTATION_HANDOFF.md
docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md
docs/evidence/g7/G7_MILESTONE.md  (immediately prior accepted gate;
  particularly its SafeToResume/idempotency forward constraint)
```

# 3. Required verdict

```text
PASS — G8 INITIAL PROVIDERS ACCEPTED
PASS WITH NON-BLOCKING FINDINGS
FAIL — G8 REQUIRED EVIDENCE INCOMPLETE
FAIL — G8 WRITE SCOPE VIOLATION
FAIL — G8 PRIVILEGE/AUTHORIZATION MISCLASSIFIED
FAIL — G8 PUBLIC API SCOPE VIOLATION
```

`FAIL — G8 WRITE SCOPE VIOLATION` exists specifically for the risk this
gate's own planning identified as central: the governing contract
requires **read-only** providers, with `PowerOff()`/`SetSession()`
explicitly deferred (§26/§27/§28). If the candidate implements either
real write, or wires any capability into a genuine `Apply`/mutation path,
that is not "extra thoroughness" — it is out of scope and must fail on
this basis regardless of code quality.

# 4. Mechanically re-derive G8's normative scope — do not trust the candidate's own framing

Read §26, §27, §28, §37's six `P1-*` groups, and §38's G8 entry directly.
Independently confirm:

- Exactly nineteen normative IDs: `P1-SYS-001..003`, `P1-PSI-001..005`,
  `P1-LGI-001..002`, `P1-UDS-001..004`, `P1-UPW-001..002`,
  `P1-ACC-001..003`.
- **Every one of the nineteen is a read/parse/enumerate/detect/reject-
  before-write claim** — none asserts a successful mutation, a rollback,
  or a crash-during-Apply scenario. If the candidate's own completion
  report frames any ID as proving a write succeeded, that framing itself
  is a finding, independent of whether the underlying code is otherwise
  sound.
- §26's own section title ("Initial **read-only** providers") and its
  explicit deferral language for `PowerOff()` ("production `PowerOff()`
  deferred until I/O Guardian phase") and session write ("the actual
  session write remains deferred from Phase 1") are the primary basis for
  confirming this — quote them directly in your report rather than
  paraphrasing.

# 5. Write-scope audit — the primary audit question

For every provider adapter in the diff, independently trace:

```text
- Does it ever call a mutating D-Bus method (StartUnit/StopUnit,
  PowerOff, SetSession, AddInhibitor, or any other write-shaped method)
  on any of the five D-Bus-backed providers?
- Does it ever instantiate guardian-core's TransactionRecord or call any
  guardian-core::transaction::engine function?
- Does it ever construct a call against GuardianHelper1?
- Does UDisks's PowerOff validation/rejection logic (§27) stop at
  *rejection* (CanPowerOff==false, stale identity, removal-during-window,
  etc. — all negative/precondition tests) without ever reaching a real
  PowerOff() call in any code path, including "success" paths?
- Does AccountsService's session validation logic (§28) stop at
  *validation* without ever reaching a real SetSession()/SetXSession()
  call?
```

Search broadly — not just literal method-name grep, but any D-Bus proxy
construction against `org.freedesktop.systemd1`/`org.freedesktop.UDisks2`/
`org.freedesktop.Accounts`/`org.freedesktop.login1` that could reach a
write-shaped member, including through a generic `call()`/`call_method()`
helper that takes a member name as a runtime string (which would itself
also be a §40 forbidden-shortcut finding — a generic D-Bus invoker).

# 6. Provider-interface validation

For each of the six providers, independently verify against the
implementation handoff's §6 contract table:

```text
- Interface layer used matches the accepted hierarchy (native D-Bus for
  five; kernel interface /proc/pressure/* for PSI) — flag any
  unjustified fallback to CLI parsing.
- CapabilityRecord population uses genuinely observed values, not
  hardcoded ones — spot-check by forcing a provider-absent case (Layer 2
  mock or Layer 4 VM) and confirming `Health`/`Availability` reflect it,
  not a default.
- authorization_ownership is Knowledge::Unknown where not actually
  evidenced this gate (systemd/PSI/logind/UPower reads, and
  AccountsService's read path) rather than a fabricated Known value.
- UDisks's authorization_ownership for the *unimplemented* PowerOff
  capability, if a CapabilityRecord for it exists at all this gate,
  correctly reuses G2's already-evidenced ProviderOwnedAuthorization
  classification (verify against
  docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md directly) rather
  than re-deriving or guessing it.
```

# 7. Privilege/authorization validation

- Confirm every G8 CapabilityRecord's `privilege_requirement` is
  `NoDirectPrivilege`, evidenced (not merely asserted) by the read path
  requiring no elevated caller privilege on a correctly-policed bus.
- Confirm none of G2's eight `Unknown` privilege areas (BPF/eBPF,
  thermald write, NVML, fwupd, journald rotation, apt/package, generic
  hardware control, usbguard) is touched by any G8 provider — independent
  grep/source review, not trust in the handoff's own claim.
- Confirm no capability anywhere in this diff reaches execution with
  `PrivilegeRequirement::Unknown` — re-verify G3's NB-1/G4's already-closed
  fail-closed guarantee is not somehow bypassed by a new provider
  construction path (it shouldn't be touchable at all, since no G8
  provider performs a write, but confirm this structurally rather than
  assuming).

# 8. Transaction trace — expect "none exists," verify it

For every provider, confirm **no** `TransactionRecord`/`engine::snapshot`/
`engine::apply`/etc. is instantiated anywhere in the G8 diff. If the
candidate did wire any provider into the transaction engine (even for
read-only purposes, "just to prove the pattern"), that is itself a
finding — Class C reads do not need transactional wrapping (per the G7
handoff's own established classification), and adding it either signals
scope confusion or a premature attempt to pre-build write infrastructure
for `PowerOff`/`SetSession`, which is explicitly deferred.

# 9. Single-writer adversarial tests

Given §8's expected finding is "no real write path exists," the
adversarial tests this section would normally require (competing writer
detection, ambiguous-ownership fail-closed behavior) have **no real
subject in G8's actual scope**. Confirm the implementation handoff
correctly says so (§8 of the implementation handoff) rather than
fabricating single-writer tests against a nonexistent write path merely
to appear thorough. If the candidate *did* build such tests, verify they
test something real (e.g., the arbitrator's already-accepted G3/G4
behavior applied to a genuinely new candidate-provider scenario) and are
not decorative.

# 10. Idempotency/recovery audit

Same expectation as §9: G7's `SafeToResume` forward constraint is not
yet triggered by anything in G8's real scope. Confirm the candidate does
not claim any G8 capability is `SafeToResume`-eligible (none should exist
to classify). If UDisks/AccountsService validation logic includes any
language suggesting the *future* write will automatically inherit
`SafeToResume`, that contradicts G7's binding forward constraint and is a
blocking finding regardless of how well-reasoned the surrounding logic
is.

# 11. Real-VM evidence audit

For each of the nineteen normative IDs, verify real (not only mocked)
evidence exists per the implementation handoff's §17 plan — a disposable
Ubuntu 26.04.1 VM, not the primary workstation. Specifically interrogate:

```text
- P1-PSI-004 ("without busy polling"): does the evidence show a genuine
  poll/epoll-based or notification-driven trigger, or a disguised
  busy-loop with a sleep that merely looks event-driven? Ask for the
  actual implementation technique, not just a passing test.
- P1-UDS-003/004: is umockdev genuinely used for re-enumeration/removal,
  or was a real (harder to reproduce, higher-risk) physical device used
  on the primary workstation? Either real umockdev or a real disposable
  VM's own virtual disk re-enumeration is acceptable; the primary
  workstation is not.
- P1-LGI-001/002, P1-UPW-001/002, P1-ACC-001..003: real provider
  presence/absence proven against the real VM's actual system state, not
  only a private/mock bus standing in for "real."
```

# 12. Public API-growth audit

Confirm `io.github.cliffthelin.Guardian1`'s introspected shape is
byte-identical to G7's accepted frozen surface (`ContractVersion`,
`ServiceState` only) — real, fresh `gdbus introspect --recurse` against
a real running `guardian-daemon`, not a code read alone. Any new method,
property, or signal on `Guardian1` is a blocking finding unless the
implementation handoff's §12 "no expansion required" conclusion is
independently re-derived as wrong by the reviewer (in which case, say so
explicitly and explain which normative ID actually requires it).

# 13. Forward-constraint audit

- G5 FC-2: confirm still open, no new spill/retention sink introduced.
- G4 FC-3: confirm recorder/persistence independence unchanged (trivially
  true if §8's expected "no transaction engine touched" finding holds).
- G2's eight `Unknown` areas: confirm the implementation handoff's
  disposition (all deferred, none required) is independently correct,
  not merely restated.

# 14. Regression audit

Verify unmoved: all `phase0-g0..g7` tags. Verify unchanged:
`guardian-helper`'s Class A write path, `guardian-daemon`'s
`GuardianContract` (G0's frozen shape), the Class B disposable-prototype
disposition, systemd units/D-Bus policy/polkit rules from G7. Confirm the
G8 diff is additive only within `guardian-core`'s provider-adapter
modules and `guardian-daemon`'s Capability Registry population — no
edits to G0-G7's already-accepted logic beyond a narrowly-scoped,
explicitly-disclosed integration fix if one was genuinely needed.

# 15. Validation

```bash
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Baseline before G8: 212 passed, 0 failed. Report the exact new total —
G8 is expected to add real Layer 1 (and likely Layer 2/3 harness-adjacent)
tests, so an increase is expected and should be explained per-provider,
not merely reported as a number.

# 16. Required report

```text
1. Baseline/candidate SHAs, tag state
2. Full changed-file reconciliation (every file, not sampled)
3. Independent normative-ID re-derivation (confirm all nineteen, confirm
   all are read/observe/reject-before-write in nature)
4. Write-scope audit findings (§5) — the primary verdict-determining
   section
5. Provider-interface validation findings (§6)
6. Privilege/authorization validation findings (§7)
7. Transaction-trace findings (§8) — expect and confirm "none"
8. Single-writer adversarial-test findings (§9) — expect and confirm "not
   yet triggered, correctly not fabricated"
9. Idempotency/recovery audit findings (§10) — expect and confirm
   "SafeToResume not claimed for anything"
10. Real-VM evidence findings (§11), per provider
11. Public API-growth audit (§12)
12. Forward-constraint findings (§13)
13. Regression findings (§14)
14. Validation results
15. Blocking findings (or "None")
16. Non-blocking findings
17. Verdict
18. Recommended next action
```

Then STOP. Do not push. Do not tag. Do not begin G9 work.
