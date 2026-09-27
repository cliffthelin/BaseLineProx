# Guardian G0 Permanent-Namespace Finalization Report

Verdict: **G0 PERMANENT-NAMESPACE CANDIDATE — READY FOR INDEPENDENT AUDIT**

## 1. Governing scope

Assigned work was the G0 permanent-namespace finalization only, against frozen mechanical candidate `3de9f1e`. Governing sections were TDD contract §7.1 (naming decision gate), §7.2–7.3 (object hierarchy and versioning), §36 (`P0-DBUS-001..005`, `P0-REG-003..004`), and §38 (G0), plus ADR-001.

No G1 work was started. No authorization, polkit, caller identity, provider, transaction, client, or packaging code was added.

## 2. Independent mechanical audit of 3de9f1e

Verdict: **MECHANICAL PASS**, reached independently rather than by accepting the prior reviewer's conclusion.

The suite was not merely run; it was mutation-tested. Nine deliberate defects were introduced into throwaway copies of `3de9f1e`, and every one was caught by the contract test that should own it:

| Mutation | Killed by |
|---|---|
| Third method added to the live interface | P0-DBUS-001, P0-DBUS-003 |
| Error taxonomy name drift (`.Unsafe` → `.Unsafely`) | P0-DBUS-004 (`error_contract`) |
| Interface major dropped (`Guardian1` → `Guardian`) | P0-DBUS-002 |
| Annotation present in committed XML but not live | P0-DBUS-001 |
| Expected XML signature drift (`s` → `u`) | P0-DBUS-001 |
| Provenance `unknown` fabricated into a value | P0-REG-003 |
| Provenance key silently dropped | P0-REG-003 |
| Drift comparator hardcoded to `Match` | P0-REG-004 |
| zbus member-rename no-op (control) | correctly not flagged |

The tests are load-bearing, not decorative. Live introspection is recursive from the Guardian root, annotations participate in equality, the method allowlist is fully qualified and multiplicity-preserving, and one typed error is proven over a real private-bus wire.

### Scoping limitation recorded, not repaired

P0-DBUS-003 walks the object tree starting at the Guardian root path. A Guardian-owned method exported at a *sibling* path is therefore outside its audit — demonstrated by the suite's own test-only `ErrorProbe1`, which lives at a sibling path and does not disturb the allowlist. This satisfies the contract as written (§36 P0-DBUS-003 requires that introspection contain no generic execution method) and the implementation exceeds that text. It is noted here because once the daemon owns a well-known bus name and exports objects outside the Guardian root, the audit should widen accordingly. No change was made under this commit's scope.

## 3. Ownership resolution

The repository supplied no ownership evidence: no remote, no `gh` installation or configuration, no SSH keys, and `git config user.name`/`user.email` of `Codex`/`codex@local` — a local agent identity, not an owner. Every other repository on the workstation with a remote is a third-party upstream clone.

The namespace was therefore *not* inferred. The owner was asked directly and selected `github.com/cliffthelin`. The ownership basis is that explicit attestation; it is not machine-verified, and ADR-001 records that limitation and the pre-publication check it implies.

## 4. Permanent D-Bus identity

```text
Well-known bus name:  io.github.cliffthelin.Guardian1
Guardian interface:   io.github.cliffthelin.Guardian1
Root object path:     /io/github/cliffthelin/Guardian1
Error namespace:      io.github.cliffthelin.Guardian1.Error.*
```

`cliffthelin` is a valid D-Bus name element (`[A-Za-z_][A-Za-z0-9_]*`, no hyphen, no leading digit) and needs no mangling. The namespace does not depend on the local username, hostname, project display name, or repository description.

Public identity: **Guardian Plane**, slug `guardian-plane`, described as a local-first system control and recovery plane for Ubuntu Linux. Ubuntu is the target platform, not part of the owned brand.

## 5. Namespace migration

Current governing contract migrated:

- `crates/guardian-core/src/error.rs` — prefix and all 17 error identities;
- `crates/guardian-core/tests/error_contract.rs` — the independent 17-name expectation table;
- `crates/guardian-daemon/src/lib.rs` — interface name and root object path;
- `crates/guardian-daemon/tests/dbus_contract.rs` — expected-XML include, Guardian interface prefix, test-only error-probe interface and path, annotation-parser fixtures;
- `dbus/interfaces/io.github.cliffthelin.Guardian1.xml` — renamed from the development filename, contents updated;
- `docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md` — permanent decision, ownership basis, alternatives, consequences;
- `docs/evidence/g0/live-introspection.xml` — recaptured live from a private bus under the permanent namespace.

Historical evidence intentionally retained unchanged:

- `docs/evidence/g0/G0_COMPLETION_REPORT.md`;
- `docs/evidence/g0/G0_REPAIR_COMPLETION_REPORT.md`;
- `docs/evidence/g0/G0_REPAIR_2_COMPLETION_REPORT.md`;
- `docs/evidence/g0/live-introspection.development-namespace-3de9f1e.xml` (added — the byte-preserved development-namespace capture).

Those reports correctly state the namespace in force when they were written. Rewriting them would falsify the record. ADR-001 preserves the development decision in a dedicated section rather than deleting it.

Also intentionally untouched: `GUARDIAN_PHASE_0_1_TDD_CONTRACT.md`, `GUARDIAN_PHASE_0_CONTRACT_RESEARCH.md`, and the handoffs. Their `<namespace>` placeholders are deliberate contract text, and the handoffs are historical instructions.

## 6. Validation

```text
cargo fmt --check                                             PASS (no diff)
cargo clippy --workspace --all-targets --all-features -D warnings   PASS (no warnings)
cargo test --workspace                                        4 passed, 0 failed, 0 ignored
cargo test -p guardian-daemon --test dbus_contract --nocapture      1 passed, 0 failed, 0 ignored
```

No required test was skipped, ignored, weakened, or deleted. The public method surface remains exactly `ContractVersion` and `ServiceState`. The error taxonomy remains exactly 17 categories.

Namespace-sensitive mutation checks were repeated after the migration in isolated build directories: an extra live method still fails P0-DBUS-001/003, a single error name reverted to the old namespace still fails P0-DBUS-004, dropping the interface major still fails P0-DBUS-002, and expected-XML signature drift still fails P0-DBUS-001.

## 7. Independence

This finalization was implemented and validated by the same agent, so this green result is **not** the independent G0 audit. A separate read-only agent must audit this exact commit before the repository receives a G0 tag or proceeds toward G1.
