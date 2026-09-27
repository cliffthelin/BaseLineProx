# Guardian Phase 0 Implementation Handoff
## Bootstrap + G0 Public Contracts Only

**Audience:** Primary coding agent (recommended: Codex running locally on Ubuntu 26.04.1)  
**Scope:** Repository bootstrap plus **G0 — Public Contracts**  
**Stop condition:** G0 evidence/report complete. Do **not** begin G1.  
**Governing contract:** `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`

---

# 1. Mission

Establish the first governed Guardian Rust workspace and implement the **public contract foundation** required by G0.

This assignment does **not** implement Guardian system-management behavior.

The desired result is a repository in which:

- the Rust workspace is clean and testable;
- Guardian's D-Bus public-contract shape can be introspected in an isolated test environment;
- interface versioning is explicit;
- typed public error mapping exists;
- provider provenance has a real schema;
- external provider contract drift can be detected from fixtures;
- the public API provably contains no generic privileged command execution method;
- G0 tests are green;
- ADR-001 records the D-Bus namespace/versioning decision or clearly records the one remaining owner decision if a permanent reverse-domain namespace cannot legitimately be selected by the coding agent.

Then stop.

---

# 2. Read before changing code

Read in this order:

1. `AGENTS.md`
2. `docs/guardian/INDEX.md`
3. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`
   - §2 Governing principles
   - §4 Required repository layout
   - §6 External provider provenance
   - §7 D-Bus contract
   - §16 Error model
   - §36 Required Phase 0 tests
   - §38 G0
4. `docs/guardian/30_TDD/GUARDIAN_PHASE_0_CONTRACT_RESEARCH.md`
   - D-Bus contract
   - authoritative-source hierarchy
   - error model
   - Phase 0 G0 gate
5. `docs/guardian/20_Control_Plane/D-Bus_API_Contract.md`
6. `docs/guardian/20_Control_Plane/Source_Contract_Drift.md`
7. `docs/guardian/10_Platform/D-Bus.md`
8. `docs/guardian/10_Platform/zbus.md`
9. `docs/guardian/90_Sources/wiki/ubuntu-dbus-daemon-resolute.md`
10. `docs/guardian/90_Sources/wiki/zbus-docs.md`

Do not start provider, authorization, transaction, GUI, TUI, or recovery implementation in this batch.

---

# 3. Repository bootstrap

## 3.1 Preserve existing repository state

Before editing:

- inspect repository status;
- do not delete or rewrite unrelated user work;
- record pre-existing uncommitted changes in the completion report;
- do not initialize a new Git repository if one already exists.

## 3.2 Wiki placement

If the Guardian wiki has not already been committed into the repository, place it under:

```text
docs/guardian/
```

Preserve its internal relative links.

Required paths include:

```text
docs/guardian/INDEX.md
docs/guardian/LOOKUP_MAP.md
docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md
docs/guardian/30_TDD/GUARDIAN_PHASE_0_CONTRACT_RESEARCH.md
docs/guardian/90_Sources/SOURCE_REGISTRY.md
```

Do not duplicate the wiki in multiple repository locations.

## 3.3 Initial Rust workspace

Create only crates justified by Bootstrap/G0.

Recommended minimum:

```text
Cargo.toml
crates/
  guardian-core/
  guardian-provider-api/
  guardian-daemon/
  guardian-testkit/
tests/
  contract/
  fixtures/
dbus/
  interfaces/
docs/
  adr/
```

Do not create empty future GUI/TUI/provider crates merely to mirror the long-term tree.

A crate must either contain meaningful current-gate code or not exist yet.

## 3.4 Toolchain baseline

Use the repository/Ubuntu Rust toolchain.

Establish commands equivalent to:

```bash
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

If the repository uses a task runner, Makefile, or justfile, it may wrap these commands but must not hide failures.

---

# 4. G0 deliverables

## D0-01 — Public D-Bus namespace and versioning ADR

Create:

```text
docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md
```

It must document:

- selected permanent D-Bus well-known name strategy;
- interface major-version convention;
- object-path convention;
- why the selected namespace is legitimate;
- alternatives considered;
- migration consequence of changing it later.

### Namespace ownership rule

Do **not** invent ownership of a reverse-DNS domain or GitHub organization.

If the repository/project already has a legitimate domain or repository namespace, use it.

If no legitimate permanent namespace can be established from repository facts, use a clearly development-only namespace in tests and mark the permanent-name choice as the **only blocking owner decision** for final G0 acceptance. Do not fabricate ownership simply to make the checklist green.

All other G0 mechanics should still be implemented.

## D0-02 — Public D-Bus interface skeleton

Implement a real introspectable Guardian D-Bus interface sufficient to prove:

- connection and object registration;
- selected interface major suffix;
- documented object path;
- typed method/property/error surface appropriate for G0;
- no generic privileged execution endpoint.

This does not need real system-management methods.

A harmless read-only method such as contract/version/status introspection is acceptable when it exists to prove the public interface machinery.

Do not add fake future provider/system write methods.

## D0-03 — Typed error contract

Implement the stable error categories required by the TDD contract in a shared type.

At minimum, preserve all contract categories:

```text
NotAuthorized
AuthenticationUnavailable
Unsupported
ProviderUnavailable
ProviderChanged
PreconditionFailed
Conflict
Busy
TimedOut
Cancelled
InvalidRequest
Unsafe
ApplyFailed
ObservationFailed
RollbackFailed
PersistenceFailed
Internal
```

Provide deterministic mapping between internal enum/category and public D-Bus error identity.

Do not make raw provider stderr the error API.

## D0-04 — Provider provenance schema

Implement the canonical provenance record with fields equivalent to:

```text
provider_id
package_name
package_version
interface_name
interface_version
introspection_hash
policy_hash
observed_at
```

Unknown/not-applicable values must remain explicit option/unknown states.

Do not fabricate missing metadata.

## D0-05 — Contract fixture + drift detector

Create a fixture mechanism that can compare a known external provider contract/introspection snapshot against an observed/supplied snapshot and report drift.

For G0, this can operate purely on committed fixtures.

It must not require mutation of the host's system D-Bus configuration.

The result should distinguish at least:

```text
MATCH
DRIFT
MISSING
INVALID
```

or an equally explicit typed model.

Hashing may be used, but the implementation must preserve enough information to identify which fixture/provider drifted.

## D0-06 — G0 contract-test suite

Implement/activate the required G0 tests.

Normative tests:

```text
P0-DBUS-001 — introspection exists
P0-DBUS-002 — interface major present
P0-DBUS-003 — no generic execution method
P0-DBUS-004 — typed error mapping
P0-DBUS-005 — unknown method fails normally
P0-REG-003 — contract provenance
P0-REG-004 — drift detection
```

Test names in Rust may differ, but the test report must map them back to these IDs.

---

# 5. Tests first

The intended sequence is:

1. Add the G0 contract tests/fixtures.
2. Confirm they fail for the expected missing implementation.
3. Implement the minimum production code needed to satisfy them.
4. Run focused G0 tests.
5. Run full workspace tests.
6. Run format/lint.
7. Record results.

Do not write most of the production surface first and add tests afterward.

If some bootstrap test cannot literally fail first because the repository does not yet compile, document the bootstrap transition honestly rather than manufacturing a fake failing state.

---

# 6. D-Bus test environment

G0 tests must not require changing the real system bus.

Prefer an isolated/private bus such as `dbus-run-session` or the Rust equivalent test harness where practical.

The public-interface introspection test should prove the exported contract, not merely compare a hand-authored XML file to itself.

At least one test should start/register the test daemon/interface and introspect the live exported object.

Unknown method handling must return a normal D-Bus error and must not terminate the service.

---

# 7. Source fixtures

Use the wiki's source hierarchy.

For external D-Bus fixture provenance, retain:

- provider/source identifier;
- source URL or local package origin;
- retrieval/capture date;
- content hash;
- interface/bus name where applicable.

Do not copy arbitrary large external documentation into source code.

Use fixture files plus provenance metadata.

---

# 8. Explicitly out of scope

Do not implement:

- polkit authorization logic beyond types/interfaces strictly necessary to compile G0;
- caller identity;
- G1 tests;
- privilege-topology prototypes;
- Capability Registry runtime discovery;
- Provider Arbitrator behavior;
- transaction engine;
- PSI provider;
- UDisks provider;
- AccountsService provider;
- systemd provider;
- GUI;
- TUI;
- CLI product commands;
- desktop indicator;
- packaging;
- system writes;
- USBGuard integration;
- session switching;
- recovery actions;
- thermal controls;
- log remediation.

Do not "get ahead" by adding stubs for these that appear functional.

---

# 9. Required evidence

Before reporting completion, provide:

## Repository baseline

```text
git status
rustc --version
cargo --version
```

and Ubuntu release information if available.

## Test evidence

Run and report:

```bash
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Plus any private D-Bus integration command required for the live introspection test.

Report exact pass/fail/ignored counts where the tooling exposes them.

## Contract evidence

Include:

- exported D-Bus introspection output or committed fixture produced from it;
- ADR-001;
- provider-provenance fixture;
- drift test fixtures/result.

---

# 10. G0 pass criteria

G0 can be marked PASS only when:

### P0-DBUS
- P0-DBUS-001 passes.
- P0-DBUS-002 passes.
- P0-DBUS-003 passes.
- P0-DBUS-004 passes.
- P0-DBUS-005 passes.

### P0-REG
- P0-REG-003 passes.
- P0-REG-004 passes.

### Quality
- `cargo fmt --check` passes.
- clippy passes with warnings denied.
- full workspace tests pass.
- no required G0 test is ignored/skipped.
- no generic privileged command interface exists.
- no G1+ feature has been implemented to claim progress.

### Namespace
- permanent namespace is legitimately selected and ADR-001 accepted;

**or**, if repository facts do not provide a legitimate ownership namespace:

- all G0 mechanics/tests are green under a development namespace;
- ADR-001 clearly identifies the permanent namespace as a blocking owner decision;
- report G0 as **MECHANICALLY GREEN / NAMESPACE DECISION PENDING**, not PASS.

---

# 11. Required completion report

Return exactly these sections:

## 1. Governing scope

State that the assignment was Bootstrap + G0 only.

## 2. Pre-existing repository state

List unrelated changes discovered before work.

## 3. Architecture decisions

Summarize ADR-001 and any non-architectural implementation choices.

## 4. Files changed

Separate:
- added;
- modified;
- deleted.

## 5. G0 test mapping

Use a table:

| Contract test | Implementation test | Result |
|---|---|---|
| P0-DBUS-001 | ... | PASS/FAIL |
| ... | ... | ... |

## 6. Validation commands

Show commands and results/counts.

## 7. Contract evidence

List introspection/provenance/drift artifacts.

## 8. Deferred work

Explicitly confirm G1 and later work were not implemented.

## 9. Open issues / contract ambiguity

List all.

## 10. Git state

Show final `git status` and commit hash if a commit was requested/permitted.

---

# 12. Stop rule

After completing the report:

**STOP.**

Do not begin G1 authorization/caller-identity implementation.

The G0 result is intended for independent review before the repository advances to G1.

---

# 13. Independent review handoff

The next reviewer should audit:

1. the diff;
2. ADR-001;
3. live/introspection fixture;
4. G0 test mapping;
5. whether tests meaningfully enforce the TDD contract;
6. whether any G1+ behavior leaked in;
7. whether the D-Bus namespace is legitimate;
8. whether the public interface accidentally creates a generic privilege path.

Only after reviewer findings are repaired and G0 remains green should G1 begin.
