# Guardian Phase 0 — G1 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Validated commit and tag

```text
Validated commit:  761bd4ae869c3e5d2168b8f9da47fbe797e89c62
G1 tag:            phase0-g1-identity-authorization (annotated, points to 761bd4a)
```

`761bd4a` is the exact commit both the full independent G1 audit and the
subsequent focused hardening re-review evaluated. No administrative commit
sits between the reviewed state and the tag — this record itself is the
first commit after it, and it does not move the tag.

## Independent review verdicts

- Full independent G1 audit: **PASS WITH NON-BLOCKING FINDINGS**. The sole
  code-level finding (polkit infrastructure/transport failures collapsed
  into `AuthenticationUnavailable`) was repaired in `761bd4a` itself.
- Focused hardening re-review (scoped to that one repair): **PASS**.

Full detail: `docs/evidence/g1/G1_LAYER1_EVIDENCE.md`,
`docs/evidence/g1/G1_LAYER2_EVIDENCE.md`,
`docs/evidence/g1/G1_HARDENING_INFRASTRUCTURE_FAILURE.md`.

## Normative test status

```text
P0-AUTH-001 — caller identity cannot be spoofed         PASS (Layer 1 + Layer 2, real system bus, real distinct OS UIDs)
P0-AUTH-002 — denied action does not apply               PASS (Layer 1 ordering-trace proof + Layer 2 real polkit denial)
P0-AUTH-003 — background action cannot prompt            PASS (Layer 1 + Layer 2 real non-interactive fail-closed)
P0-AUTH-004 — explicit user action may prompt             PASS (Layer 1 + Layer 2 real interactive flag reaching real polkit, real agent completion)
P0-AUTH-005 — VT/text authorization                       PASS (Layer 2: real pkttyagent, real challenge, real credential, real authorization)
```

## Layer 1 status

Private-bus proof, primary workstation, no root: real distinct D-Bus
connection identities, mocked authorization decision (no real polkit exists
on a private bus). 10 tests in `crates/guardian-core/tests/authorization_contract.rs`
+ 6 in `crates/guardian-daemon/tests/g1_authorization_contract.rs`, all
green.

## Layer 2 (real-host) status

Disposable Ubuntu 26.04.1 LTS VMs (multipass), each destroyed after evidence
capture. Real system D-Bus, real polkit 127, real distinct local OS users,
real `pkttyagent` text authentication, and — from the hardening pass — a
real masked-polkit-service failure genuinely producing `ProviderUnavailable`.
See `docs/evidence/g1/g1-layer2-vm-setup.sh` for the reproducible setup and
`docs/evidence/g1/g1_layer2_server_transcript.log` for raw transcripts.

## Test counts at the milestone

```text
cargo fmt --check                                                    PASS (no diff)
cargo clippy --workspace --all-targets --all-features -D warnings    PASS (no warnings)
cargo test --workspace                                                20 passed, 0 failed, 0 ignored
cargo test -p guardian-daemon --test dbus_contract --nocapture       1 passed, 0 failed
```

## G2 status at the milestone

No G2 code exists. The daemon/process model is exactly the one established
in G0, reused as-is by G1's test harnesses. No privilege-topology decision,
privileged-helper architecture, or provider implementation has been made.
G2 planning artifacts (`GUARDIAN_G2_IMPLEMENTATION_HANDOFF.md`,
`GUARDIAN_G2_INDEPENDENT_REVIEW_HANDOFF.md`) were prepared alongside this
milestone record but describe work that has not started.
