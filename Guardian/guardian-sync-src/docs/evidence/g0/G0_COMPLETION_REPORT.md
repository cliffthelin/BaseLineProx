# Guardian Bootstrap + G0 Completion Report

Verdict: **MECHANICALLY GREEN / NAMESPACE DECISION PENDING**

## 1. Governing scope

The assignment was repository Bootstrap plus G0 — Public Contracts only. Governing sections were TDD contract §§2, 4, 6, 7, 16, 36 (`P0-DBUS-001..005`, `P0-REG-003..004`), and 38 (G0), together with the Bootstrap + G0 implementation handoff.

## 2. Pre-existing repository state

The supplied directory contained `AGENTS.md`, both handoffs, and the wiki at `Guardian_Wiki/`. It was not a Git repository and contained no Rust workspace or code. Therefore there were no pre-existing tracked/uncommitted changes. The byte-identical wiki was placed at `docs/guardian/` as required; the original duplicate was moved to `/tmp/Guardian_Wiki.pre-bootstrap-copy` and remains recoverable until temporary storage is cleared.

Baseline environment:

```text
Ubuntu 26.04 LTS (VERSION_ID=26.04)
rustc 1.98.0 (88d9e12ae 2026-08-18)
cargo 1.98.0 (797e8a9bc 2026-08-05)
```

The original Snap shim could not launch and no rustup default was configured. The standard stable toolchain with rustfmt and Clippy was installed through the existing rustup installation; no host system packages or D-Bus configuration were changed.

## 3. Architecture decisions

ADR-001 records that repository facts establish no legitimate permanent reverse-DNS ownership. G0 therefore uses `org.guardianproject.Development.Guardian1` and `/org/guardianproject/Development/Guardian1` only as conspicuous development names. Interface major 1 is explicit; incompatible contract or authorization changes require a new major.

The exported G0 service is real, introspectable, read-only, and limited to `ContractVersion` and `ServiceState`. Tests launch a new private `dbus-daemon`, register the actual zbus object, introspect it live, make an unknown call, then prove the service remains responsive. Provider drift uses SHA-256 of supplied bytes and reports typed `Match`, `Drift`, `Missing`, or `Invalid` results with provider identity and both available hashes.

## 4. Files changed

Added:

- workspace manifests: `.gitignore`, `Cargo.toml`, `Cargo.lock`;
- `crates/guardian-core/` error contract and test;
- `crates/guardian-provider-api/` provenance/drift contracts and tests;
- `crates/guardian-daemon/` live D-Bus interface and contract tests;
- `crates/guardian-testkit/` isolated private-bus harness;
- `dbus/interfaces/org.guardianproject.Development.Guardian1.xml`;
- `tests/fixtures/providers/freedesktop-dbus/` introspection and provenance fixtures;
- `docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md`;
- `docs/evidence/g0/live-introspection.xml` and this report;
- the supplied wiki under `docs/guardian/`;
- supplied governance and handoff documents as initial repository content.

Modified: none of the supplied document contents.

Deleted: none. The pre-repository wiki directory was relocated after a byte-for-byte comparison to prevent duplicate wiki trees.

## 5. G0 test mapping

| Contract test | Implementation test | Result |
|---|---|---|
| P0-DBUS-001 | `p0_dbus_001_live_export_has_introspection` | PASS |
| P0-DBUS-002 | `p0_dbus_002_every_guardian_interface_has_major_version` | PASS |
| P0-DBUS-003 | `p0_dbus_003_live_export_has_no_generic_execution_endpoint` | PASS |
| P0-DBUS-004 | `p0_dbus_004_every_error_has_a_unique_stable_dbus_identity` | PASS |
| P0-DBUS-005 | `p0_dbus_005_unknown_method_returns_error_and_service_survives` | PASS |
| P0-REG-003 | `p0_reg_003_provider_contract_provenance_preserves_unknowns` | PASS |
| P0-REG-004 | `p0_reg_004_source_interface_drift_is_meaningfully_detected` | PASS |

## 6. Validation commands

Final validation:

```text
cargo fmt --check
PASS

cargo clippy --workspace --all-targets --all-features -- -D warnings
PASS (0 warnings)

cargo test --workspace
PASS: 7 passed, 0 failed, 0 ignored; 8 zero-test unit/doc harnesses also passed

cargo test -p guardian-daemon --test dbus_contract -- --nocapture
PASS: 4 passed, 0 failed, 0 ignored; emitted the live introspection XML
```

The first bootstrap compile failed as expected because the test contract referenced missing/incorrect implementation details; production code and tests were corrected. The first parallel live-bus run exposed constrained-environment thread exhaustion after two tests. The harness now serializes independent private-bus cases; the final focused and workspace runs pass normally without forcing Cargo's global test thread count.

## 7. Contract evidence

- Live exported introspection capture: `docs/evidence/g0/live-introspection.xml`.
- Expected public interface: `dbus/interfaces/org.guardianproject.Development.Guardian1.xml`.
- Namespace/versioning decision: `docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md`.
- Provider fixture and provenance: `tests/fixtures/providers/freedesktop-dbus/`.
- The committed provenance includes provider/source identity, Ubuntu package origin/version, source URL/date, interface identity, SHA-256, and explicit `unknown` states.
- Drift evidence mutates the supplied interface member from `ListNames` to `ListPeers` and proves a changed hash/provider-specific `Drift`; it separately proves `Match`, `Missing`, and invalid-baseline behavior.

## 8. Deferred work

G1 and every later gate remain unimplemented. There is no caller identity, polkit, authorization, provider discovery/runtime registry, provider arbitrator, transaction engine, production daemon binary/service, system provider, GUI/TUI/CLI, packaging, system write, or future-feature placeholder.

## 9. Open issues / contract ambiguity

The only blocking owner decision is the legitimate permanent D-Bus namespace. No domain or organization ownership was inferred or invented. ADR-001 documents the atomic migration required after the owner supplies that decision. Accordingly, the result is not reported as G0 PASS.

No provider contract drift was found while using the committed G0 fixture. The fixture is deliberately compact and source-attributed; it does not claim to be a complete installed-provider introspection dump.

## 10. Git state

The repository is on branch `main`. The governance/wiki baseline is commit `1ab7a47` (`docs: establish Guardian governance and wiki baseline`). This report and the implementation belong to the following G0 implementation commit (`HEAD`). Git uses the repository-local automated identity `Codex <codex@local>`. `target/` is ignored, and the candidate was required to have a clean working tree before independent review.
