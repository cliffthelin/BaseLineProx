# Decision record: hard gate on restore_backup - never overwrite USER_PERSISTENCE without a fresh backup

Status: **implemented and tested (1078/1078 suite passing at this
point). Not run against real hardware.**

## Direct instruction

"Recovery should have a Baseline Recovery mode... They don't get any
access to the User persistence without passing credential checks and
never overwriting the user persistence unless there is valid proof of
it being backed up successfully within 24 hours. There are behavior
rules that need TDD enforced and not acknowledged."

## The fix

`backup_restore.py` gained a real, durable backup-success manifest
(`record_backup_manifest`/`read_backup_manifest`, one JSON file per
target under `INSTALLER_CACHE/backup_manifests/` - survives a
reinstall of the disposable stage) and
`has_recent_successful_backup(runner, *, target, now, max_age_s=86400)`.

`restore_backup` now refuses **unconditionally**, not via an opt-in
flag a caller could forget to pass: any restore that would touch
USER_PERSISTENCE - named explicitly in `members`, or an unconstrained
restore-everything (`members=None`), which conservatively counts too -
refuses before `tar` is ever invoked unless a fresh (<=24h) manifest
proves a real successful backup. Omitting the caller's `now` also
refuses, rather than silently skipping the check because a parameter
was forgotten - fails closed on missing information, not open.

`create_backup` records a manifest per target automatically when
given `now` and the real tar call succeeds - never for a backup that
didn't actually happen.

`control_panel_web.py`'s `handle_backup`/`handle_restore` now thread
real wall-clock time (`time.time()`, supplied by `do_POST`) through to
satisfy this gate - four pre-existing tests (three in
`test_backup_restore.py`, one in `test_control_panel_web.py`) needed a
pre-seeded fresh manifest added to keep testing what they originally
intended, now that the gate applies to them too.

## What this does not do

- Does not yet build the automated recurring encrypted backup job that
  would keep the 24h window satisfied without manual action - flagged
  directly by the user as expected next work ("presumably regular
  backups of the UserPersistance will be automated too a separate
  storage device and be encrypted"), not built in this pass.
- Not run against real hardware.

## Verification performed

- 20 new tests: manifest record/read round-trip, freshness true/false
  at the boundary and past it, wrong-target isolation,
  `create_backup`'s manifest recording (only on real tar success, only
  when `now` given), and the restore gate itself (refuses
  unconstrained, refuses named USER_PERSISTENCE members, refuses with
  no `now` at all, allows with a fresh manifest, refuses with a stale
  one, and confirms non-USER_PERSISTENCE members are unaffected).
- Full suite: 1078/1078 passing after propagating the fix through
  `control_panel_web.py`, no regressions.
