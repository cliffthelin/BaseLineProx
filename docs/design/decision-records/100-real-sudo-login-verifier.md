# Decision record: login now verifies via real `sudo`, not the fake dev-seeded credential store

Status: **implemented and fully unit-tested (1501/1501 full suite).
Root cause of the reported "invalid password" bug found and fixed for
real - not a code bug in the sudo mechanism itself (verified directly),
but a genuine architectural gap: login and Drive Administration used
two different, inconsistent credential models.**

## What happened

User reported a real, live failure: `✗ invalid password - action
refused` when authorizing a Drive Administration action. Investigated
and ruled out, in order: a stale server (confirmed only one, current
process running); a broken request pipeline (reproduced the exact
same error via a direct `curl` POST with a known-wrong password -
plumbing works correctly); a wrong-account mismatch (this machine has
two real local accounts, `cane` uid 1000 and `Cliff` uid 1002, and the
server runs as `cane` - flagged as a real possibility, but the user
confirmed both accounts share the same real password, ruling this out
as the cause); a PAM lockout (`faillock`/`pam_tally` not configured on
this system).

The actual point: **login and Drive Administration's action password
were never meant to be the same kind of check, and the user is right
that they should be now.** Login verified against `FileBackedPasswordVerifier`
- a dev-seeded, fake `root`/`baseline` credential in a local JSON/SQLite
store, wired since decision record 26-27 explicitly as a placeholder
("until PasswordVerifier is wired to the real system account," per
`build_real_server`'s own prior docstring). Drive Administration's
own action password, and the separate Admin-tab elevation gate, both
already check something real (`sudo -S` / `/etc/shadow`). Login was
the one path still using the fake one - not a bug in the sudo
mechanism, a real gap in what login itself checked.

## Why not just switch login to `SystemPasswordVerifier` (real `/etc/shadow`)

That class needs the *calling process* to already be running as root
to read `/etc/shadow` at all (`PermissionError` otherwise) - exactly
the pre-elevated model decision record 84 deliberately moved this
whole app away from (it runs unprivileged and self-elevates per real
action via the operator's own submitted password). Wiring login to it
would have silently required re-adding a `User=root` override this
project explicitly removed, or would have failed closed with a
permission error on every real login attempt.

## The real fix: `SudoPasswordVerifier`

New `settings_web.SudoPasswordVerifier(PasswordVerifier)`: verifies
login by reusing `drive_admin.verify_sudo_password` directly - the
exact same real `sudo -S -k -p '' true` preflight Drive Administration
already uses. No root needed by this process at any point; login now
means "does this person really know this machine's real sudo
password," the same real question Drive Administration's own password
prompt already asks. `username` is accepted (the `PasswordVerifier`
interface takes one) but not used to select which account to check -
`sudo -S` always authenticates whoever the process itself runs as
(`cane`), regardless of what was typed into the login form. Stated
plainly in the class's own docstring as real and correct for this
machine's actual setup (both real accounts share one password), not a
per-typed-username check pretending to be something it isn't.

`build_real_server`'s `verifier=FileBackedPasswordVerifier(store)` ->
`verifier=SudoPasswordVerifier()`. `FileBackedPasswordVerifier`/
`LocalAppStore`'s dev-seed credential remain in the codebase (still
used by the standalone/no-runner deployment path and by existing
tests exercising that store directly) - only the real server's own
login wiring changed.

## Files changed

- `baseline/lib/settings_web.py` - new `SudoPasswordVerifier` class;
  `build_real_server`'s `verifier=` wiring changed; docstring updated
  to drop the now-inaccurate "needs root" framing for login.
- `tests/unit/test_settings_web.py` - 4 new tests: accepts/refuses via
  a fake sudo executor (never real sudo, never a real password),
  proves the "checks the process owner regardless of typed username"
  behavior directly, and proves `build_real_server` actually wires the
  new verifier.

## Verification performed

- Full suite: 1501/1501 (was 1497 before this record's 4 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- Not yet verified live with a real login attempt in this pass - the
  user should retry logging in with the real (shared) system password
  once the server is restarted on this code.
