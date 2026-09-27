# W1-AUTH-002 — repair-pass evidence closure

**Status before this repair pass**: implemented (`AuthorizationOutcome::
Unavailable(AuthorizationUnavailableReason::NoAuthenticationAgent)` maps to
`GuardianDbusError`'s `AuthenticationUnavailable` category via
`into_provider_dbus_error`), with the pure mapping already unit-tested
(`wave1_authorization_contract.rs::no_authentication_agent_maps_to_authentication_unavailable_via_provider_request_mapping`),
but "not separately VM-reproduced (requires a real interactive-required-
but-no-agent condition, not exercised this pass)".

## What was missing

The pure `AuthorizationOutcome -> GuardianDbusError` mapping was already
proven. What was missing was evidence that the real, unmodified
`PolkitAuthorizer::check_authorization_raw`
(`crates/guardian-core/src/authorization/polkit.rs`) genuinely produces
`AuthorizationUnavailableReason::NoAuthenticationAgent` against a real
polkit authority for a real "interactive requested, no agent could
complete it" condition — as opposed to only being reachable via a
hand-constructed `AuthorizationOutcome` in a test double.

Per `check_authorization_raw`'s own documented mapping,
`NoAuthenticationAgent` requires: `interactive == true` (so
`ALLOW_USER_INTERACTION` is set) **and** polkit's `CheckAuthorization`
still returns `is_challenge == true` (no agent actually resolved it).

## Real VM evidence (`guardian-g9`)

A fresh, ordinary system user (`wave1noagent`, no login session, no
desktop, no registered polkit authentication agent) was created — deliberately
**not** covered by any explicit `YES`/`NO` branch in the evidence-only
`60-wave1-evidence.rules` fixture, so the request falls through to
polkit's real, built-in default policy for
`org.freedesktop.systemd1.manage-units` (which requires interactive
admin authentication), with `interactive=true` on the mediated call:

```
$ sudo useradd -m -s /bin/bash wave1noagent

$ sudo -u wave1noagent gdbus call --system \
    --dest io.github.cliffthelin.GuardianHelper1 \
    --object-path /io/github/cliffthelin/GuardianHelper1 \
    --method io.github.cliffthelin.GuardianHelper1.RestartCapability \
    "cups-restart" true
Error: GDBus.Error:io.github.cliffthelin.Guardian1.Error.AuthenticationUnavailable: no authentication mechanism available for org.freedesktop.systemd1.manage-units
```

This is the real, unmodified `guardian-helper` production binary, the real
`PolkitAuthorizer`, and the real system polkit authority (no test double
anywhere in this path) producing exactly the typed error
`into_provider_dbus_error`'s `NoAuthenticationAgent` arm constructs:
`GuardianErrorCategory::AuthenticationUnavailable.with_message(format!(
"no authentication mechanism available for {}", request.action_id()))`.

The test user was removed after capture (`userdel -r wave1noagent`).

## Disposition

W1-AUTH-002 is now closed with real VM evidence, in addition to the
pre-existing pure-mapping unit test. No code change was required — this
was purely an evidence gap, not a defect.
