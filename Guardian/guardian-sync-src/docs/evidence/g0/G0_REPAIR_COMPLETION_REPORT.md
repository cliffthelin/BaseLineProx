# Guardian G0 Contract-Test Hardening Repair Report

Verdict: **MECHANICALLY GREEN / NAMESPACE DECISION PENDING**

## 1. Scope

This repair is limited to G0 contract-test hardening for `P0-DBUS-001..005`. It repairs the independent audit findings against frozen candidate `6117715` without beginning G1.

## 2. Audit findings repaired

- Blocking finding 1: live zbus introspection and committed expected XML are now parsed into the same structural contract model and compared completely for every Guardian-owned object/interface.
- Blocking finding 2: live introspection now recursively follows child nodes from the Guardian root, and the full reachable Guardian method surface must equal the two-method G0 allowlist.
- Blocking finding 3: all 17 categories now map to native zbus `DBusError` variants; an independent exact-name table and a private-bus wire test enforce the public identities.
- Non-blocking P0-DBUS-005 finding: the test now matches `zbus::Error::MethodError` and asserts the exact structured `org.freedesktop.DBus.Error.UnknownMethod` name before proving continued service responsiveness.

## 3. Files changed

Modified:

- `Cargo.toml` and `Cargo.lock`;
- `crates/guardian-core/Cargo.toml`;
- `crates/guardian-core/src/error.rs`;
- `crates/guardian-core/tests/error_contract.rs`;
- `crates/guardian-daemon/Cargo.toml`;
- `crates/guardian-daemon/tests/dbus_contract.rs`.

Added:

- `docs/evidence/g0/G0_REPAIR_COMPLETION_REPORT.md`.

Deleted: none.

`roxmltree` is a small, established XML parser used only by the daemon contract tests. A structural XML parser is necessary because substring matching cannot validate D-Bus members, signatures, directions, property access, signals, or recursive nodes. zbus is now a `guardian-core` dependency because the shared public error contract uses zbus's supported native `DBusError` mechanism.

## 4. G0 test mapping

| Contract test | Implementation test | Result |
|---|---|---|
| P0-DBUS-001 | `p0_dbus_001_through_005_live_private_bus_contract_suite` → `assert_p0_dbus_001_live_export_matches_complete_expected_contract` | PASS |
| P0-DBUS-002 | same suite → `assert_p0_dbus_002_every_guardian_interface_has_terminal_major_one` | PASS |
| P0-DBUS-003 | same suite → `assert_p0_dbus_003_entire_live_tree_has_exact_g0_method_allowlist` | PASS |
| P0-DBUS-004 | `p0_dbus_004_every_error_has_the_exact_native_dbus_identity`; private-bus suite → `assert_p0_dbus_004_representative_typed_error_crosses_private_bus` | PASS |
| P0-DBUS-005 | private-bus suite → `assert_p0_dbus_005_unknown_method_is_structured_and_service_survives` | PASS |
| P0-REG-003 | `p0_reg_003_provider_contract_provenance_preserves_unknowns` | PASS |
| P0-REG-004 | `p0_reg_004_source_interface_drift_is_meaningfully_detected` | PASS |

## 5. Structural contract enforcement

The integration suite starts a private `dbus-daemon`, connects through zbus, and registers the real `GuardianContract` at the documented object path. It calls `org.freedesktop.DBus.Introspectable.Introspect` on that live object. Both the live XML and `dbus/interfaces/org.guardianproject.Development.Guardian1.xml` are parsed into ordered structures containing:

- object paths and Guardian interface names;
- method names and ordered arguments;
- each argument's name, D-Bus signature, and input/output direction;
- property names, signatures, and access modes;
- signal names and argument contracts.

Only non-Guardian standard infrastructure interfaces are filtered out. Guardian-owned differences are retained. The complete live tree must equal the independently committed expected tree, and the expected root path must equal the documented `OBJECT_PATH`.

## 6. Recursive surface audit

Starting at `/org/guardianproject/Development/Guardian1`, the live walker parses direct child `<node>` entries, resolves each child path, introspects it, and repeats while rejecting cycles. It gathers every interface under the Guardian development prefix on every reachable object.

The union of public Guardian method names across that tree must equal exactly:

```text
ContractVersion
ServiceState
```

Thus any additional method—including a generic broker on a new child interface—requires an explicit contract/test change and otherwise fails G0.

## 7. Typed D-Bus error proof

`GuardianDbusError` derives zbus's native `DBusError`. An independently written test table enforces these exact public names:

```text
org.guardianproject.Development.Guardian1.Error.NotAuthorized
org.guardianproject.Development.Guardian1.Error.AuthenticationUnavailable
org.guardianproject.Development.Guardian1.Error.Unsupported
org.guardianproject.Development.Guardian1.Error.ProviderUnavailable
org.guardianproject.Development.Guardian1.Error.ProviderChanged
org.guardianproject.Development.Guardian1.Error.PreconditionFailed
org.guardianproject.Development.Guardian1.Error.Conflict
org.guardianproject.Development.Guardian1.Error.Busy
org.guardianproject.Development.Guardian1.Error.TimedOut
org.guardianproject.Development.Guardian1.Error.Cancelled
org.guardianproject.Development.Guardian1.Error.InvalidRequest
org.guardianproject.Development.Guardian1.Error.Unsafe
org.guardianproject.Development.Guardian1.Error.ApplyFailed
org.guardianproject.Development.Guardian1.Error.ObservationFailed
org.guardianproject.Development.Guardian1.Error.RollbackFailed
org.guardianproject.Development.Guardian1.Error.PersistenceFailed
org.guardianproject.Development.Guardian1.Error.Internal
```

The integration test registers a separate test-only `ErrorProbe1` interface outside the production Guardian tree. Its harmless `RepresentativeFailure` returns `ProviderChanged`; the client asserts the structured wire error name. This does not expand the committed production interface.

## 8. Mutation/adversarial checks

An isolated `/tmp` copy was deliberately mutated and restored between cases. The focused suite failed for all required adversarial changes:

1. adding `UnexpectedPublicMethod` to the live Guardian interface;
2. changing `ContractVersion` output from D-Bus `s` to `u`;
3. renaming `ServiceState` to `ServiceMode`;
4. registering a reachable child `CommandBroker1.Execute` interface;
5. changing both live and expected interface names to an unversioned terminal `Guardian` name;
6. changing the native `ProviderChanged` error variant/name to `ProviderChangedWire`;
7. returning a structured `ProviderChanged` error whose human message was `UnknownMethod` where P0-DBUS-005 requires the standard structured unknown-method identity.

No mutation was made in the candidate working tree.

## 9. Validation

```text
cargo fmt --check
PASS

cargo clippy --workspace --all-targets --all-features -- -D warnings
PASS (0 warnings)

cargo test --workspace
PASS: 4 passed, 0 failed, 0 ignored; 8 zero-test unit/doc harnesses also passed

cargo test -p guardian-daemon --test dbus_contract -- --nocapture
PASS: 1 integration suite passed, 0 failed, 0 ignored
```

The single private-bus integration test intentionally executes five separately named contract assertion functions sequentially. This avoids private-bus/zbus thread exhaustion in the constrained development sandbox without requiring nonstandard Cargo test-thread flags.

## 10. Scope audit

No G1+ work was added. There is no authorization, polkit, caller identity, transaction behavior, runtime provider, client, packaging, system write, or future-feature placeholder. The only additional D-Bus interface is test-only and exists solely inside the integration-test binary.

## 11. Namespace

The permanent namespace remains an **OPEN OWNER DECISION**. The implementation continues to use the clearly development-only namespace documented by ADR-001. No domain or organization ownership was inferred or invented.

## 12. Git state

The repair is intended as one focused commit named `test: harden G0 public contract enforcement` after final validation and staged-diff inspection. The exact commit hash is recorded in the final handoff and is available from `git log -1`. The working tree must be clean after that commit.
