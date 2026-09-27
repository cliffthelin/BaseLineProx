# G1 Layer 1 — Private-Bus Evidence

Run on the primary development workstation. No system bus, no real polkit,
no root — every connection is a real `dbus-daemon --session` private bus
launched by `guardian_testkit::PrivateSessionBus`, per existing G0
convention.

## What is real vs. mocked here

Real: every D-Bus connection's unique bus name, assigned by the private
`dbus-daemon` itself — never fabricated. Mocked: the *authorization
decision* only (`MockAuthorizer` in
`crates/guardian-daemon/tests/g1_authorization_contract.rs`), because no
real polkit authority exists on a private bus. See
`docs/evidence/g1/G1_LAYER2_EVIDENCE.md` for the real-polkit half.

## Results

```text
crates/guardian-core/tests/authorization_contract.rs   7 passed, 0 failed
crates/guardian-daemon/tests/g1_authorization_contract.rs   6 passed, 0 failed
```

| Test | Proves |
|---|---|
| `p0_auth_001_authorization_request_has_no_field_a_client_claim_could_occupy` | Structural: `AuthorizationRequest` has no field a client claim could occupy |
| `p0_auth_001_caller_identity_cannot_be_spoofed` | Two real, distinct connections; grant follows real identity in both directions regardless of claimed uid/username/is_admin |
| `p0_auth_002_denied_action_never_reaches_the_mutation_step` | Denial proven via the exact ordering trace (`received → identity_resolved → validated → authorized_checked`, no `mutation_applied`), not only end-state comparison |
| `p0_auth_003_background_request_fails_closed_without_prompting` | Non-interactive request for an action requiring interaction is denied, zero mutation |
| `p0_auth_004_explicit_interactive_request_may_proceed_once_granted` | The identical request marked interactive succeeds once granted |
| `granting_low_risk_does_not_authorize_high_risk` | Granularity: one action's grant does not leak to another |
| `caller_identity_is_re_resolved_fresh_never_cached_across_connections` | Identity-lifetime rule (G1 handoff §8): two sequential real connections resolve to two different identities; nothing is cached |
| `error_mapping_*` (3 tests) | G1 handoff §6 mapping: denial → `NotAuthorized`; unavailable-no-agent → `AuthenticationUnavailable`; interaction-disallowed → `NotAuthorized` (not a new error) |
| `all_four_g1_test_actions_have_the_exact_polkit_action_ids_from_the_tdd_contract` | Action ids match TDD contract §9 exactly |

Full baseline (`cargo fmt --check`, `cargo clippy --workspace --all-targets
--all-features -- -D warnings`, `cargo test --workspace`) is reported in the
completion report; all green, 17 tests total across the whole workspace.
