# G1 Layer 2 — Real-Host Evidence

Disposable Ubuntu 26.04.1 VM, provisioned via `multipass launch 26.04` and
destroyed after this evidence was captured. Setup script:
`docs/evidence/g1/g1-layer2-vm-setup.sh`. Full server-side log:
`docs/evidence/g1/g1_layer2_server_transcript.log`.

## 1. Host versions (matches the researched Resolute baseline)

```text
PRETTY_NAME="Ubuntu 26.04 LTS"
VERSION="26.04 LTS (Resolute Raccoon)"
dbus-daemon                1.16.2-2ubuntu4
polkitd                    127-2ubuntu1
libpolkit-agent-1-0        127-2ubuntu1
libpolkit-gobject-1-0      127-2ubuntu1
rustc                      1.93.1
cargo                      1.93.1
```

## 2. What ran

`tests/vm/g1-layer2/` is a standalone Cargo package (not a workspace member,
so it never touches the primary workstation's `cargo build/test/clippy
--workspace`) with two binaries:

- `g1-layer2-server` — registers `AuthProbe1` on the **real system D-Bus**,
  backed by the **real** `guardian_core::authorization::polkit::PolkitAuthorizer`
  (production code, not a mock — the same type shipped in `guardian-core`).
- `g1-layer2-client` — a thin CLI that calls one `AuthProbe1` method and
  prints the real resolved unique bus name, real OS uid, and the outcome.

Two real local users were created: `guardiang01` (uid 1001, granted
`guardian.test.read` and `guardian.test.low-risk-write` by a real
`/etc/polkit-1/rules.d` rule matched on `subject.user`) and `guardiang02`
(uid 1002, granted nothing — denied purely by polkit's implicit defaults).

## 3. P0-AUTH-001 — caller identity cannot be spoofed (real system bus)

| Caller | Real UID | Claimed identity in method args | Action | Real polkit outcome |
|---|---|---|---|---|
| guardiang01 | 1001 | uid=1000, user="nobody", is_admin=false | low-risk-write | **Authorized** |
| guardiang02 | 1002 | uid=0, user="root", is_admin=true | low-risk-write | **Denied** |

`guardiang01` succeeded despite claiming to be an unprivileged stranger;
`guardiang02` was denied despite claiming to be root with `is_admin=true`.
The real system-bus unique name and real OS uid (read from
`GetConnectionUnixUser`) are the only things that ever reached
`guardian_core::identity::CallerIdentity` — proven directly in the server log
(`unique_name=:1.34 uid=Some(1001)`, `unique_name=:1.35 uid=Some(1002)`).
**Strong form proven on the real system bus, not the private test bus.**

## 4. P0-AUTH-002 — denied action does not apply (real polkit)

`guardiang01` (granted `low-risk-write` only) attempting `high-risk-write`
was denied by real polkit (never granted by any rule, falls to the action's
implicit `no` default). The G1 handoff §7 ordering invariant (already proven
structurally at Layer 1) applies identically here since it is the same
production `attempt()` code path — a real denial from `PolkitAuthorizer`
still short-circuits before any mutation. **Real-host denial proven.**

Granting `low-risk-write` did not implicitly grant `high-risk-write` for the
same real user (TDD contract §9, last line) — confirmed by the same test.

## 5. P0-AUTH-003 — background (non-interactive) request fails closed (real polkit)

`guardiang01`, non-interactively (`interactive=false`), attempting
`moderate-write` (which requires `auth_self` — interactive authentication)
was denied by real polkit with no prompt of any kind. **Real-host proof
obtained: a non-interactive request for an action that requires interaction
gets a flat, immediate denial from the real polkit authority — it never
even attempts to reach an authentication agent.**

## 6. SSH policy

`guardiang01` connecting over a real SSH session (password auth, creating a
genuine `systemd-logind` session — confirmed via `loginctl`) and attempting
the identical granted `low-risk-write` call got the identical `Authorized`
result as a local (non-SSH) call. **Guardian's G1 authorization boundary
does not special-case SSH at all — behavior is identical because the
authorization decision is derived purely from the D-Bus system-bus identity
and real polkit policy, which do not distinguish transport.** This is the
intentional SSH policy for G1: *supported, and behaviorally identical to any
other local caller*, not a special code path.

## 7. P0-AUTH-004 / P0-AUTH-005 — interactive completion: NOT obtained (first attempt, 2026-08-30)

Preserved as historical record of the first attempt. **Superseded by §9–§11
below**, which identify the root cause and obtain full completion in a later
pass the same day. This section is not rewritten to imply the first attempt
succeeded — it did not; the diagnosis below explains why, precisely.

This is reported honestly rather than fabricated or downgraded.

**What was attempted:** `pkttyagent --process <client-pid>` was registered
(as `guardiang01`, inside a real SSH session with a real logind session and
a real allocated pty) before the client made an `interactive=true` request
for `moderate-write` (which requires `auth_self`). Client-process liveness
during registration was explicitly verified via `ps -p <pid>` before
registering the agent.

**What happened:** the real `CheckAuthorization` call still returned a flat
denial (`is_authorized=false`, `is_challenge=false`) — polkit never routed
the request to the registered agent, and no password prompt ever appeared.
Two distinct failure modes were observed across attempts, both narrowed down
by direct experimentation:

- When `pkttyagent` was launched without a real controlling terminal of its
  own (e.g. via a non-pty `ssh host command` invocation), it failed outright
  with `Error opening current controlling terminal for the process
  ('/dev/tty')`.
- With a real pty (`ssh -t`, or an `expect`-driven interactive session) and
  a verified-alive target PID, `pkttyagent` registered without error, but
  the subsequent `CheckAuthorization` call still came back as a flat denial
  with no challenge and no prompt — i.e., polkit did not consider the
  registered agent applicable to resolve this specific `system-bus-name`
  subject in this VM's minimal session configuration, for a reason not
  conclusively identified within the time budget available for this pass
  (candidates include how `system-bus-name` subjects are correlated to a
  registered `--process` agent versus a full desktop session/seat, which
  this disposable VM does not have).

**Consequence:** the D-Bus, real-caller-identity, and real-polkit-decision
halves of P0-AUTH-004/005 are proven (the interactive flag is correctly
threaded through to a real `CheckAuthorization` call with `AllowUserInteraction`
set, per the server log and `PolkitAuthorizer` source). The specific
requirement that a real authentication agent complete an interactive
challenge — the strongest-form host evidence the G1 handoff §5.2 and this
review's own audit checklist require for these two tests — was **not**
obtained. This is reported as unexecuted, not downgraded to a pass.

## 8. Result of the first attempt (2026-08-30)

```text
P0-AUTH-001: PASS (real system bus, real distinct OS users)
P0-AUTH-002: PASS (real polkit denial + granularity)
P0-AUTH-003: PASS (real polkit non-interactive fail-closed)
P0-AUTH-004: INCOMPLETE (interactive flag reaches real polkit; agent completion not obtained)
P0-AUTH-005: INCOMPLETE (pkttyagent registered but did not receive the challenge; no completion evidence)
SSH policy:  PASS (real SSH session, identical behavior confirmed intentional)
```

---

## 9. Root cause (completion pass, 2026-08-30, same day)

A fresh disposable VM was used for this pass (`guardian-g1-vm3`, destroyed
after evidence capture, same versions as §1).

**The root cause was a test-policy misconfiguration, not a defect in
Guardian, `PolkitAuthorizer`, or `pkttyagent`.**

`guardian.test.moderate-write`'s original policy set only
`allow_active=auth_self`, leaving `allow_any=no` (a hard, unchallengeable
deny) at its default. Polkit does not classify a remote/SSH session as
"active" (it has no seat — confirmed via `loginctl session-status`, which
shows no `Seat:` line for an SSH session), and, as discovered empirically
below, does not classify it as "inactive" either — it falls under
`allow_any`. Since `allow_any` was `no`, **every** interactive attempt over
SSH was silently and correctly denied by real polkit before any agent could
ever be consulted — no amount of `pkttyagent` registration-mode
experimentation could have fixed this, because there was never a challenge
being generated in the first place.

This was isolated with a bisection, not guessed:

1. `pkaction -v` confirmed the action genuinely had `implicit active: auth_self`
   (not a hard `no`) — action-definition problem (hypothesis A) ruled out on
   its face.
2. `pkcheck --enable-internal-agent --allow-user-interaction --process $$`
   over a real SSH session with a real logind session (confirmed via
   `loginctl session-status`) still returned a flat `Not authorized.` with
   **no prompt at all**, even using polkit's own built-in agent — ruling out
   external-agent registration mechanics (hypothesis B) as the cause of
   *this* failure.
3. Setting `allow_inactive=yes` (unconditional allow) and retesting still
   produced `Not authorized.` — this eliminated the "SSH is classified
   inactive" hypothesis; the subject was not falling into either the active
   or inactive bucket.
4. Setting `allow_any=yes` (unconditional allow) as the final sanity check
   **succeeded** (clean exit 0, no `Not authorized.` line) — proving the
   subject was being classified under `allow_any`, which had never been set
   to anything but its "no" default for this action.
5. Setting `allow_any=auth_self` (alongside the existing `allow_active` and
   `allow_inactive` settings) produced a **real password prompt** on the
   first subsequent attempt, using `pkcheck --enable-internal-agent`.

Fix applied: `guardian.test.moderate-write`'s three implicit-authorization
fields (`allow_any`, `allow_inactive`, `allow_active`) are now all
`auth_self`, matching the actual real-world session types (including
non-seated SSH/VT/recovery sessions) this test exists to exercise. This is
recorded in the corrected `docs/evidence/g1/g1-layer2-vm-setup.sh`.

No Guardian code was implicated at any point in this diagnosis — the same
`guardian_core::authorization::polkit::PolkitAuthorizer` code from the first
attempt, unchanged, is what succeeds below.

## 10. Reference-agent proof (`pkcheck --enable-internal-agent`)

With the corrected policy, over the same real SSH/logind session as
`guardiang01`:

```text
==== AUTHENTICATING FOR guardian.test.moderate-write ====
Guardian G1 test moderate-risk write
Authenticating as: guardiang01
Password: [supplied — not recorded]

==== AUTHENTICATION COMPLETE ====
RESULT_EXIT:0
```

This established, before touching Guardian at all, that the VM/policy/session
combination genuinely supports interactive authentication end to end — the
diagnostic reference required by the review handoff before debugging
Guardian's own integration.

## 11. Real end-to-end proof: Guardian client + real `pkttyagent`

**Test A — `pkttyagent --process <client-pid>` (succeeded):**

```text
registration mode:        --process <pid>, --notify-fd 1
subject (Guardian side):  system-bus-name, unique_name=:1.90
unique system bus name:   :1.90 (identical at every step: client's own
                           report, pkttyagent's target resolution, and the
                           server's resolved caller)
registration confirmation: pkttyagent produced no registration error;
                           immediately followed by a real password prompt
session:                   real SSH/logind session, guardiang01 (uid 1001),
                           no seat (remote), Type=tty, Service=sshd
```

Transcript (credential redacted):

```text
==== AUTHENTICATING FOR guardian.test.moderate-write ====
Guardian G1 test moderate-risk write
Authenticating as: guardiang01
Password: [supplied — not recorded]

==== AUTHENTICATION COMPLETE ====
--- guardian client output ---
client real unique_name: :1.90
client real uid (from /proc/self/status): Uid: 1001 1001 1001 1001
client pid: 7831
OK
```

Guardian server log for the same exchange:

```text
[g1-layer2-server] resolved caller: unique_name=:1.90 uid=Some(1001)
[g1-layer2-server] real polkit outcome: Authorized
```

This is full completion: real system D-Bus → real caller identity resolved
by Guardian's own `resolve_caller_identity` → real `PolkitAuthorizer` call
with `AllowUserInteraction` set → real `pkttyagent` prompt → real credential
supplied by the real test user → real `CheckAuthorization` returning
authorized → Guardian's `attempt()` handler proceeding past the
authorization gate and completing the bounded test action → the client
observing `OK`.

**Test B — `pkttyagent --system-bus-name <unique-name>` (informative
failure, not a gap):**

```text
Error registering authentication agent: GDBus.Error:org.freedesktop.PolicyKit1.Error.Failed:
Only unix-process and unix-session subjects can be used for authentication agents.
```

This is polkit's own documented API constraint, not a defect: `pkttyagent`'s
agent-*registration* call only accepts `unix-process`/`unix-session` scopes.
Guardian's `PolkitAuthorizer` correctly uses a `system-bus-name`
*authorization subject* in `CheckAuthorization` — a different, valid polkit
concept — and polkit internally resolves that subject to the underlying
process for matching against a registered `--process` agent, which is
exactly what Test A proved works. With no agent registered at all (Test B's
registration failed outright), Guardian's client correctly received
`AuthenticationUnavailable`:

```text
[g1-layer2-server] resolved caller: unique_name=:1.95 uid=Some(1001)
[g1-layer2-server] real polkit outcome: Unavailable(NoAuthenticationAgent)
```

This is a useful secondary confirmation that the `NoAuthenticationAgent`
mapping path is real and correctly reachable, not merely theoretical.

## 12. P0-AUTH-003 regression check (post-fix)

Re-ran the identical non-interactive request against the *same*, now
`auth_self`-everywhere policy, with no `pkttyagent` registered:

```text
$ g1-layer2-client moderate false 1000 nobody false
client real unique_name: :1.99
client real uid: 1001
ERROR io.github.cliffthelin.Guardian1.Error.NotAuthorized
exit:1
```

Server log:

```text
[g1-layer2-server] resolved caller: unique_name=:1.99 uid=Some(1001)
[g1-layer2-server] real polkit outcome: Unavailable(InteractionRequiredButDisallowed)
```

No prompt of any kind was attempted (no `pkttyagent` was even running for
this call). The public error remains `NotAuthorized`, exactly as the G1
handoff §6 mapping requires — real polkit itself reports `is_challenge=true`
here (this specific request), which `PolkitAuthorizer` correctly maps to
`InteractionRequiredButDisallowed`. Making the interactive path work did
**not** weaken the background/no-prompt guarantee.

## 13. Final sweep (P0-AUTH-001/002, re-confirmed under the final VM state)

```text
guardiang01 (granted) low-risk-write   → Authorized
guardiang02 (not granted) low-risk-write → Denied
guardiang01 high-risk-write (never granted) → Denied
```

Unchanged from §3–§4; re-run for completeness alongside the 004/005
completion pass, per governing instruction to re-verify the whole suite, not
only the previously-incomplete tests.

## 14. Final result

```text
P0-AUTH-001: PASS (real system bus, real distinct OS users)
P0-AUTH-002: PASS (real polkit denial + granularity)
P0-AUTH-003: PASS (real polkit non-interactive fail-closed; re-confirmed post-fix)
P0-AUTH-004: PASS (interactive flag reaches real polkit; real agent completes the challenge)
P0-AUTH-005: PASS (real pkttyagent registers, receives the challenge, real credential answers it, real authorization returned)
SSH policy:  PASS (real SSH session, identical behavior confirmed intentional)
```
