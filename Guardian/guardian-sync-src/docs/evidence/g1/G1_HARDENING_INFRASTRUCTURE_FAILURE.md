# G1 Hardening — Distinguishing Polkit Infrastructure Failure

2026-08-31, following the independent G1 audit of `070e3adc30746d296f5b0b829728b55726fc541a`,
delivered as that review's own completion report (verdict: PASS WITH
NON-BLOCKING FINDINGS). That report is historical and is not rewritten here —
this document only records the repair of the one finding it raised.

## 1. Original audit finding

The independent reviewer found that `PolkitAuthorizer::authorize`
(`crates/guardian-core/src/authorization/polkit.rs`) collapsed two different
classes of failure into the same public error:

```rust
// old
Ok((false, true, _)) | Err(_) => AuthorizationOutcome::Unavailable(
    AuthorizationUnavailableReason::NoAuthenticationAgent,
),
```

Both "polkit genuinely has no agent to answer an interactive challenge" and
"the `CheckAuthorization` D-Bus call itself failed — transport error,
service unavailable, malformed response" mapped to the same
`AuthorizationOutcome::Unavailable(NoAuthenticationAgent)`, which the
existing mapping turns into the public `AuthenticationUnavailable` error.
The same conflation applied to proxy-construction failure. A real
infrastructure outage (polkit down, D-Bus unreachable) would have presented
itself to a caller as an ordinary authentication-related outcome rather than
a provider failure.

## 2. Corrected error mapping

| Condition | Guardian error |
|---|---|
| Explicit denial | `NotAuthorized` (unchanged) |
| Authentication agent genuinely unavailable | `AuthenticationUnavailable` (unchanged) |
| Background interaction forbidden | `NotAuthorized`, reason `interaction-required-but-disallowed` (unchanged) |
| Polkit provider unavailable (proxy construction fails) | `ProviderUnavailable` (**new**) |
| D-Bus transport/`CheckAuthorization` failure | `ProviderUnavailable` (**new**) |
| Internal Guardian invariant failure | `Internal` (available; not currently produced by `PolkitAuthorizer`, whose observable failures are all provider-availability problems) |

## 3. Final authorization outcome model

The smallest semantically correct change: `Authorizer::authorize` now
returns `Result<AuthorizationOutcome, AuthorizationError>` rather than a bare
`AuthorizationOutcome`. `AuthorizationOutcome` itself (`Authorized` /
`Denied` / `Unavailable(reason)`) is unchanged — it still represents only
real authorization *decisions*. The new `AuthorizationError` enum
(`ProviderUnavailable(String)` / `Internal(String)`) represents *failing to
obtain* a decision at all, and cannot be constructed from, or confused with,
an `AuthorizationOutcome` — the type system keeps the two apart:

```rust
pub trait Authorizer {
    fn authorize(
        &self,
        request: &AuthorizationRequest,
    ) -> impl Future<Output = Result<AuthorizationOutcome, AuthorizationError>> + Send;
}
```

`PolkitAuthorizer::authorize` now uses `?` to propagate proxy-construction
and `CheckAuthorization` transport failures as `AuthorizationError::ProviderUnavailable`,
before ever reaching the outcome-classification `match`.

## 4. Tests added

`crates/guardian-core/tests/authorization_contract.rs` (10 tests total, up
from 7):

- `infrastructure_provider_unavailable_maps_to_provider_unavailable_never_authentication_unavailable`
- `infrastructure_internal_maps_to_internal`
- `real_polkit_authorizer_maps_unreachable_provider_to_provider_unavailable`
  — exercises the **real** `PolkitAuthorizer` against a **real** private
  `dbus-daemon` that has no `org.freedesktop.PolicyKit1` service registered
  at all, so `CheckAuthorization` genuinely fails at the transport level.
  This is not a hand-constructed `AuthorizationError` value; it is the
  actual production code path.

The three pre-existing error-mapping tests (denial, no-agent, interaction-disallowed)
are unchanged and still pass — the approved mappings were preserved exactly.

`crates/guardian-core/Cargo.toml` gained two dev-dependencies to support the
real-path test: `async-io` (to drive the async `authorize()` future from a
plain `#[test]` fn without pulling in `zbus::blocking`'s hidden `block_on`)
and `guardian-testkit` (for `PrivateSessionBus`).

## 5. Adversarial mutation checks (temporary, not committed)

Five mutations, each in a disposable scratch copy, each reverted:

1. Transport failure (`Err`) mapped back to `AuthenticationUnavailable` →
   caught by `real_polkit_authorizer_maps_unreachable_provider_to_provider_unavailable`.
2. Explicit denial mapped to `ProviderUnavailable` → caught by
   `error_mapping_explicit_denial_maps_to_not_authorized`.
3. No-authentication-agent mapped to `ProviderUnavailable` → caught by
   `error_mapping_no_authentication_agent_maps_to_authentication_unavailable`.
4. Background interaction-required mapped to `AuthenticationUnavailable` →
   caught by `error_mapping_interaction_disallowed_maps_to_not_authorized_not_a_new_error`.
5. Every outcome collapsed into `Internal` → caught 4 of 9 tests
   simultaneously, including the real-path test.

All five failed exactly as expected; none were left in the tracked repository.

## 6. Validation (primary workstation)

```text
cargo fmt --check                                                    PASS (no diff)
cargo clippy --workspace --all-targets --all-features -D warnings    PASS (no warnings)
cargo test --workspace                                                20 passed, 0 failed, 0 ignored
cargo test -p guardian-daemon --test dbus_contract --nocapture       1 passed, 0 failed
```

(guardian-core's pure suite went from 7 to 10 tests; everything else
unchanged in count.)

## 7. Layer 2 impact and re-verification

The `Authorizer` trait signature changed, so `tests/vm/g1-layer2/src/server.rs`
required updating (the same one-line pattern as the daemon test file: match
on the `Result`, map `Err` via `AuthorizationError::into_dbus_error`, then
proceed with the existing `AuthorizationOutcome` handling). It was rebuilt
and **re-executed** in a fresh disposable Ubuntu 26.04.1 VM
(`guardian-g1-hardening`, destroyed after use) using the unmodified
`docs/evidence/g1/g1-layer2-vm-setup.sh`:

- Wire-level compatibility confirmed unchanged: `guardiang01` granted
  `low-risk-write` → `OK`; `guardiang02` (ungranted) → `NotAuthorized`;
  `guardiang01` on `high-risk-write` (never granted) → `NotAuthorized`.
  Identical to the pre-hardening evidence.
- **New, real confirmation of the fix itself:** `sudo systemctl mask polkit`
  (stop alone was insufficient — polkit is D-Bus-activatable and
  auto-restarted on the next call; masking blocks activation too) made the
  real `CheckAuthorization` D-Bus call genuinely fail. The client received
  `ERROR io.github.cliffthelin.Guardian1.Error.ProviderUnavailable`
  (previously this would have been `AuthenticationUnavailable`). Server log:

  ```text
  [g1-layer2-server] real polkit result: Err(ProviderUnavailable("CheckAuthorization failed: org.freedesktop.systemd1.UnitMasked: Unit polkit.service is masked."))
  ```

- polkit was unmasked and restarted; a subsequent identical call returned
  `OK` again, confirming full recovery.

The full interactive `pkttyagent` text-authentication dance (P0-AUTH-004/005's
strongest evidence) was **not** re-executed — this change does not touch
that code path (the `Ok((false, true, _))` branches, which govern the
interactive-challenge outcomes, are untouched), and the prior pass's
evidence for it remains applicable as-is.

**Result:** `Layer 2 partially re-executed: wire-compatibility sweep
(P0-AUTH-001/002) plus a new, real `ProviderUnavailable` proof against a
genuinely masked polkit service; the interactive pkttyagent chain was not
repeated.`
