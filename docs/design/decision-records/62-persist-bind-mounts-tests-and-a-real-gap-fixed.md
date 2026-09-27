# Decision record: persist_bind_mounts.py - tests written, one real gap found and fixed

Status: **implemented and unit-tested (20 tests, 953/953 suite
passing).** Not run against real hardware.

## What was asked

Direct instruction: *"All user data including credentials and config
and logs should go to the User Persistence partition."* Followed by an
explicit sequencing choice for a change destined for real hardware:
build and test the module properly first (Option 1), rather than
setting it up by hand during the drive build and formalizing it after.
The implementation (`persist_bind_mounts.py`) already existed from
that planning pass; this record covers writing its tests and fixing
what they found - *"tests before implementation counts as done."*

## What was verified already correct

19 of 20 tests passed against the implementation exactly as written,
with no changes: the fstab line builders, `is_mounted()`'s real
`/proc/self/mounts` parsing (never inferred from fstab content alone,
which can list a mount not yet actually applied), `ensure_persistence_mounted()`'s
idempotent mount-and-fstab-entry behavior and real failure reporting,
and `ensure_redirect()`'s core migrate-once/bind/no-duplicate-fstab-entry
behavior.

## The one real gap found and fixed

The module's own docstring claimed: a redirect onto an unmounted
`MOUNT_POINT` "would silently write straight through to the disposable
substrate instead, exactly the bug this module exists to prevent" -
but that guarantee was only actually true through `ensure_all_redirects()`'s
own call sequencing (it calls `ensure_persistence_mounted()` first and
stops if that fails). `ensure_redirect()` itself had no such guard -
called directly, with the persistence partition not actually mounted,
it would have created the persistence-side subdirectory *on the
disposable substrate itself* (since nothing was really mounted at
`MOUNT_POINT`) and bind-mounted onto that - the exact silent
write-through bug the module claims to prevent, just reachable by a
different call path than the one first tested.

`test_ensure_redirect_refuses_when_persistence_partition_is_not_mounted`
proved this directly (asserted `applied is False` and that nothing was
created/mounted); the fix adds the same `is_mounted(runner, MOUNT_POINT)`
check directly inside `ensure_redirect()`, so the guarantee holds by
construction on whichever function a future caller actually calls -
the same "defense by construction, not just by convention" pattern
this project already uses elsewhere (e.g. `wipe_signatures()` only
ever accepting a validated dict, never a bare path).

## A test-realism limitation, handled honestly rather than worked around

One test originally tried to assert the full first-boot chain in one
shot: persistence not yet mounted -> real mount command runs ->
kernel reports it mounted -> all three redirects succeed. A
`FakeRunner`'s `/proc/self/mounts` content is static; it doesn't
update itself just because a fake `mount` command "succeeded," the
way a real kernel immediately would. Asserting the full chain against
that fake would have required either extending `FakeRunner`'s shared,
widely-used API with a side-effect hook (risking every other test file
that constructs one), or quietly asserting something the fake can't
actually prove. Split into two honest, separately-real tests instead:
one proving the real `mount` command is actually issued when not yet
mounted, and one proving all three redirects actually succeed once
persistence is mounted (the real steady-state case - true on every
boot after the first) - together covering the same ground without
either compromise.

## Verification performed

- 20 unit tests against `FakeRunner` - fstab line builders,
  `is_mounted()`, `ensure_persistence_mounted()`, `ensure_redirect()`
  (including the newly-fixed guard), and `ensure_all_redirects()`'s
  sequencing and early-stop-on-failure behavior.
- Full suite: 953/953 passing (933 before this change), no
  regressions.
- Not run against real hardware, and not yet wired into
  `provision.sh` or `firstboot_statemachine.py` - the module exists
  and is now genuinely tested, but nothing calls it yet. That wiring,
  and the real-hardware drive-build step this was written ahead of,
  are real, separate next steps.
