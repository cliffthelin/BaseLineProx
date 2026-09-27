# Guardian G0 Repair 2 Completion Report

Verdict: **MECHANICALLY GREEN / NAMESPACE DECISION PENDING**

## 1. Scope

This change is G0 Repair 2 only. It hardens `P0-DBUS-001` and `P0-DBUS-003` and improves attribution for `P0-DBUS-001..005` at exact predecessor `7cbb262`. It does not begin G1.

## 2. Audit findings repaired

- Blocking annotation finding: annotation name/value pairs are now retained on Guardian interfaces, methods, arguments, properties, and signals and participate in live-versus-expected equality.
- Blocking allowlist finding: P0-DBUS-003 now compares a multiplicity-preserving collection of fully qualified methods, including object path, interface, member, ordered argument contracts, directions, signatures, names, and annotations.
- Non-blocking attribution finding: the private-bus suite now catches each assertion failure, labels it with its P0 contract ID, runs all five checks, and fails once with the complete result list.

## 3. Files changed

Modified:

- `crates/guardian-daemon/tests/dbus_contract.rs`.

Added:

- `docs/evidence/g0/G0_REPAIR_2_COMPLETION_REPORT.md`.

Deleted: none.

No production interface, expected XML, namespace, provider provenance, or G1 code changed.

## 4. Annotation model

`AnnotationContract` stores the exact `name` and `value`. Every applicable contract element contains an annotation vector:

```text
InterfaceContract.annotations
MethodContract.annotations
ArgumentContract.annotations
PropertyContract.annotations
SignalContract.annotations
```

Direct `<annotation>` children are parsed from both live and expected XML. Vectors are sorted so source ordering does not create false drift, but names, values, presence, and multiplicity remain part of derived structural equality. Comments and whitespace remain non-semantic; Guardian annotations are not filtered.

The P0-DBUS-001 helper additionally compares synthetic absent/added/changed annotation cases to guard the parser itself against normalizing annotations away.

## 5. Fully qualified allowlist

The P0-DBUS-003 surface uses:

```text
QualifiedMethodContract {
    object_path,
    interface_name,
    method: MethodContract {
        name,
        ordered arguments: [
            ArgumentContract {
                name,
                signature,
                direction,
                annotations,
            }
        ],
        annotations,
    }
}
```

The live recursive tree is converted to a sorted `Vec`, not a name set, so distinct locations and duplicate names remain distinct. The independent allowlist contains exactly `ContractVersion` and `ServiceState` on the root `Guardian1` interface. Each has no inputs and one unnamed `s` output with direction `out`. No other Guardian method is permitted anywhere in the reachable tree.

## 6. G0 test mapping

| Contract test | Implementation test/check | Result |
|---|---|---|
| P0-DBUS-001 | live suite → structural tree equality plus annotation parser check | PASS |
| P0-DBUS-002 | live suite → recursive terminal-major check | PASS |
| P0-DBUS-003 | live suite → fully qualified exact method surface | PASS |
| P0-DBUS-004 | exact 17-name test plus live wire-error check | PASS |
| P0-DBUS-005 | structured unknown-method identity plus survival check | PASS |
| P0-REG-003 | provenance explicit-unknown test | PASS |
| P0-REG-004 | source/interface drift test | PASS |

## 7. Adversarial checks

All mutations were made in an isolated `/tmp` copy and caused the focused suite to fail:

1. added a Guardian interface annotation — P0-DBUS-001 failed;
2. changed that annotation's value — P0-DBUS-001 failed and exposed the changed value in the model;
3. added a child `Child1.ContractVersion` and changed expected XML to match — P0-DBUS-001 passed while P0-DBUS-003 failed on the extra qualified member;
4. added a string input to `ServiceState` and changed expected XML to match — P0-DBUS-001 passed while P0-DBUS-003 failed on the argument contract;
5. added an `as` array-of-strings input to `ServiceState` and changed expected XML to match — P0-DBUS-001 passed while P0-DBUS-003 failed;
6. changed `ContractVersion` output from `s` to `u` and changed expected XML to match — P0-DBUS-003 failed on the output contract.

Temporary mutations did not enter the candidate.

## 8. Failure attribution

The suite retains one private bus and one Rust integration test because multiple concurrent zbus/private-daemon tests exceed the constrained sandbox's thread/process allowance. Each P0-DBUS-001..005 check now executes inside an unwind boundary. Failures are collected as `P0-DBUS-NNN: <detail>`, every remaining check still runs, and the suite emits one aggregate failure afterward. Mutation output confirmed later checks execute after earlier failures.

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

No required G0 test was skipped or ignored.

## 10. Scope audit

No G1+ implementation was introduced. There is no authorization, polkit, caller identity, transaction behavior, runtime provider, client, packaging, system write, or future-feature placeholder.

## 11. Namespace

The permanent namespace remains an **OPEN OWNER DECISION**. The development-only namespace and ADR-001 remain unchanged. No ownership was invented.

## 12. Git state

This repair is intended as the focused commit `test: complete G0 D-Bus contract enforcement`. Its exact hash is recorded in the final handoff and available from `git log -1`. The working tree must be clean after commit.
