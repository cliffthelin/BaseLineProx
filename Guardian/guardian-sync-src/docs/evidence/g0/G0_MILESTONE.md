# Guardian Phase 0 — G0 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Description:           A local-first system control and recovery plane for Ubuntu Linux.
```

## Permanent D-Bus namespace

```text
Well-known bus name:  io.github.cliffthelin.Guardian1
Guardian interface:   io.github.cliffthelin.Guardian1
Root object path:     /io/github/cliffthelin/Guardian1
Error namespace:      io.github.cliffthelin.Guardian1.Error.*
```

Ownership basis: the repository owner's explicit attestation that they control
`github.com/cliffthelin`. Not machine-verified at the time of this record — see
`docs/adr/ADR-001-guardian-dbus-namespace-and-versioning.md` for the pre-publication
check this implies.

## Validated commit and tag

```text
Validated commit:  15cdb787f99b4374f08a4c6bd3fe570f07f74960
G0 tag:            phase0-g0-public-contracts (annotated, points to 15cdb78)
```

`15cdb78` adds only the independent audit report on top of `2103f94` (the namespace
finalization commit, current-main lineage). It is the tag target rather than `2103f94`
because it is the first commit that carries the final independent audit evidence
alongside the permanent-namespace implementation.

### Tag re-anchoring note

When this repository was first pushed to GitHub, `git pull --rebase origin main`
replayed the entire local history onto GitHub's auto-created `README.md` commit,
producing new commit objects for everything with the same content and messages but
different hashes. The `phase0-g0-public-contracts` tag had already been pushed
against the pre-rebase commit (`e54f475909fa7957c424560c77fd21c8b80bb36a`), which
left the tag with no common ancestor with `main`.

The tag was subsequently re-anchored to `15cdb78`, the content-identical
current-main-lineage equivalent (verified: the only diff between `e54f475` and
`15cdb78` is the pre-existing `README.md`; `HEAD` descends from `15cdb78`). The
original pre-rebase lineage remains fully resolvable under the archival tag
`g0-pre-rebase-lineage`, which points at the original `e54f475`. Historical G0
evidence reports written against the pre-rebase hashes (`1ab7a47`, `6117715`,
`7cbb262`, `3de9f1e`, `d85e374`, `e54f475`) are unchanged and remain accurate
statements of what happened at the time; those hashes resolve via
`g0-pre-rebase-lineage` rather than via `main`.

## Final audit verdict

**PASS — G0 PERMANENT-NAMESPACE FINALIZATION VALIDATED**, per
`docs/evidence/g0/G0_INDEPENDENT_AUDIT_REPORT.md`. Namespace consistently applied
across all active code, zero development-namespace references outside historical
evidence, all required tests and quality gates green, historical evidence integrity
preserved, G0 gate compliance confirmed against TDD contract §38.

## Test counts at the milestone

```text
cargo fmt --check                                                    PASS (no diff)
cargo clippy --workspace --all-targets --all-features -D warnings    PASS (no warnings)
cargo test --workspace                                                4 passed, 0 failed, 0 ignored
```

Test IDs: `P0-DBUS-001..005`, `P0-REG-003..004` — all pass.

## G1 status at the milestone

No G1 code exists at this milestone. The public D-Bus surface remains exactly
`ContractVersion` and `ServiceState`; no caller-identity, authorization, polkit,
provider, transaction, client, or packaging code has been implemented. G1 planning
artifacts (`GUARDIAN_G1_IMPLEMENTATION_HANDOFF.md`,
`GUARDIAN_G1_INDEPENDENT_REVIEW_HANDOFF.md`) were prepared alongside this milestone
record but describe work that has not started.
