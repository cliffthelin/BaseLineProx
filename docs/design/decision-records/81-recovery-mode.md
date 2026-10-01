# Decision record: Recovery Mode itself - real entry, userless discovery, hard exit condition

> **Note, 2026-09-30 (docs-vs-code audit, v0.2 row 30):** There is no `recovery_web.py`. The logic is `recovery_mode.py` and `recovery_tiers.py`, and the page is in `settings_web.py` / `baseline_web.py`. Since 2026-09-30 recovery also needs a login plus this machine's root password or passphrase (v0.2 row 45), so any statement below that recovery discovery needs no credential is superseded. The record below is left as written.

Status: **implemented and tested (1223/1223 suite passing, up from
1194 after decision record 80). Not run against real hardware.**

## What this closes

Work-queue item 26: "Recovery mode itself: real entry (after
discovery+repair cascade fails, or on-demand), userless discovery UI,
hard exit condition (can't leave without a persona volume confirmed
read-write), SESSION_TEMP-scoped working state, credential tiers via
`recovery_tiers.py`/`admin_elevation.py` only - not blocked on the
now-withdrawn item 24." Its stated blocker (item 25's active-persona
concept, and the UI surface decision) is resolved by decision records
78 (persona-aware wiring) and 80 (the Admin tab established
`settings_web.py` as the real web surface for exactly this kind of
page).

Explicitly, deliberately: nothing in this pass touches or depends on
the withdrawn USB challenge-response mechanism (decision record 77) -
every credential tier used here is `recovery_tiers.py`'s pure
two-axis model, unchanged.

## What was built

**`baseline/lib/recovery_mode.py`** (new):

- `should_enter(cascade_applied: bool) -> bool` - the real automatic
  entry predicate, true exactly when the discovery+repair cascade
  genuinely failed.
- `discover(runner, *, personas) -> DiscoveryReport` - **guest-tier,
  no credential of any kind** - reports which personas have a real,
  currently-mounted volume, which don't, and which persona is active.
  Matches `recovery_tiers.GUEST_ACTIONS`'s `view_recovery_screen`
  being always present, never conditionally withheld.
- `can_exit(runner, *, personas) -> (bool, str)` / `attempt_exit(...)` -
  the hard exit condition, per direct instruction: "Without it being
  in read and write mode the machine should not be able to leave
  recovery mode." Checks the kernel's own reported mount *options*
  (new `persist_bind_mounts.is_mounted_read_write`), not just "is it
  mounted at all" - a real corrupted volume can mount successfully but
  read-only, which must not satisfy this condition.
  `attempt_exit` is the *only* code path that ever clears the active
  flag, and it refuses outright (never writes) unless `can_exit` is
  real-true at the moment of the call - the guarantee holds by
  construction, not by every future caller remembering to check first.
- `record_entry`/`read_state`/`is_active` - real JSON state at
  `/mnt/SESSION_TEMP/recovery_mode/state.json`. SESSION_TEMP
  specifically, per direct instruction: "The Temp volume can hold
  session only user non persistent data and that is a fit for
  recovery" - never a persona's own persistence, which may be exactly
  what is broken.

**`persist_bind_mounts.py`**: new `is_mounted_read_write` (real
`/proc/self/mounts` options-field check for the kernel's own `rw`
token). `main()` now calls `recovery_mode.record_entry(reason=
"cascade_failed")` directly the moment its own cascade genuinely
fails - the real automatic entry trigger, captured when the condition
that requires it actually happens, not left for a separate poller.

**`settings_web.py`**: `handle_recovery_view`/`handle_recovery_exit` -
deliberately no `sessions`/`token` parameter anywhere in this pair,
guest-tier by construction (not merely "session optional" - there is
no session concept involved at all). New routes `GET /recovery` (the
userless discovery view) and `POST /recovery/exit`. New
`render_recovery_page` - no login form anywhere on the page, proven
directly in a test (`"password" not in body.lower()`).

**New CLI `baseline/bin/baseline-recovery-mode`** - the real
"on-demand" half of entry (`--enter`), plus `--status` and `--exit`
for direct operator use outside the web surface. Staged in
`provision.sh` alongside `recovery_mode.py` itself.

## Why guest-tier discovery lives on settings_web.py rather than a separate server

Considered a standalone `recovery_web.py` server, reasoning that
settings_web.py's own account store (bind-mounted onto whichever
persona is active) could be unusable if persistence itself is broken -
exactly the scenario recovery mode exists for. On inspection this
concern doesn't hold: `JsonFileStore` degrades to seeding a fresh store
at whatever path it's given rather than crashing if the bind-mounted
directory is missing or empty, and the new recovery routes take no
dependency on `JsonFileStore`/sessions at all. Reusing the existing,
already-proven `http.server` surface avoids running a second HTTP
server for no real architectural gain, matching this project's
"reuse established patterns" convention.

## What this does not do

Does not build a real systemd-level escalation chain that automatically
switches the machine's own display/service state into "recovery mode"
the moment `record_entry` fires - `persist_bind_mounts.main`'s own
service still just exits 1 as before (now with the added, durable side
effect of a real state record); wiring that record into an actual
visible mode switch (kiosk redirect, tty takeover, etc.) is a real,
separate integration step, not built here. Does not run against real
hardware.

## Verification performed

- `persist_bind_mounts.py`: 6 new tests (`is_mounted_read_write`'s
  true/false/absent/unreadable cases; `main`'s real recovery-entry
  recording on cascade failure and its absence on success) - all 53
  pre-existing tests pass unchanged.
- `recovery_mode.py`: 15 tests (`should_enter`; `discover`'s found/
  missing/active-persona reporting including the "nothing found"
  case; `can_exit`'s true/false-on-read-only/false-on-absent cases;
  `record_entry`/`read_state`/`is_active`; `attempt_exit`'s refusal
  without a real read-write persona, success once one exists, and the
  never-entered-yet case).
- `settings_web.py`: 8 new tests (`handle_recovery_view`/
  `handle_recovery_exit`'s hand-off/success/refusal paths;
  `render_recovery_page`'s real discovery rendering and its
  no-login-form guarantee) - all 48 pre-existing tests pass unchanged.
- `tools/check_provision_deploys_all_imports.py`: caught
  `recovery_mode.py` genuinely missing from `provision.sh` the moment
  it became reachable; fixed, now zero gaps.
- `bash -n boot/provision.sh`: valid syntax.
- Full suite: 1223/1223 passing, no regressions.
