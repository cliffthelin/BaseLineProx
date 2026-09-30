# Decision record: real live-progress console for long-running Drive Administration actions

Status: **implemented and fully unit-tested (1510/1510 full suite).
Verified live in the browser (see below). Not yet re-verified against
a real, full `build_self_installer` run with the operator's own real
password.**

## What this resolves

Direct instruction, 2026-09-29: "add a console log of what is running
and doing to show at the bottom of the modal," following the user's
"its not working" report on `build_self_installer`. Real cause:
`build_self_installer`'s pipeline (device validation, cert generation,
assistant-binary acquisition, answer-file build, ISO prep, ISO
remaster, QEMU launch) ran entirely synchronously inside one HTTP
request - genuinely minutes of real work with zero feedback until it
finished. The browser looked frozen because, from its perspective, it
was: one `fetch()` that wouldn't resolve for a long time.

## Real fix, not a fake progress bar

1. `self_installer.build_and_write_self_installer` gained an optional
   `on_progress: str -> None` callback, called once per real stage
   with a short, honest description of what's actually happening right
   now (validating the device, locating/using the cached ISO,
   acquiring the assistant binary, building the answer file, preparing
   the ISO, baking the self-contained ISO, launching QEMU) - never a
   simulated percentage or a fake step count.
2. `drive_admin.build_self_installer`/`perform_action` thread this
   same callback through by name - every other action's own lambda
   simply doesn't forward it, so passing one is harmless for them
   (verified directly: `test_perform_action_does_not_choke_on_on_progress_for_an_action_that_ignores_it`).
3. `baseline_web.py`'s `/drive-admin/action` POST now starts the real
   action in a background thread and returns immediately with a real
   `job_id` - never blocks the request. A new in-memory job registry
   (`_JOBS`, one dict per job: `lines`/`done`/`outcome`/`detail`)
   records progress as `on_progress` actually reports it. A new
   `/drive-admin/job-log?job_id=...` GET route reports the job's
   current real state.
4. The modal gained a `<pre id="driveAdminModalConsole">` that appears
   on confirm and is filled by real polling (`pollJobLog`, ~700ms
   interval) - appends only genuinely new lines, auto-scrolls, and on
   `done` proceeds to the same redirect-with-notice-banner flow that
   already existed, now carrying the real final outcome/detail.

## Not addressed / real limitations disclosed

- The in-memory job registry is not pruned and does not survive a
  server restart - acceptable for a single-operator admin tool, not a
  general-purpose job queue.
- A crash inside the background thread is caught and reported as a
  real `outcome: "error"` (never silently hangs the poll loop
  forever), but no attempt is made to retry or resume a failed job.

## Files changed

- `baseline/lib/self_installer.py` - `on_progress` parameter + 7 real
  stage-progress calls through `build_and_write_self_installer`.
- `baseline/lib/drive_admin.py` - `build_self_installer` accepts and
  forwards `on_progress`; `perform_action` threads it into any
  action's params by name.
- `baseline/lib/baseline_web.py` - `_JOBS`/`_run_action_job`; POST
  `/drive-admin/action` now starts a background job and returns a
  `job_id`; new GET `/drive-admin/job-log`; modal gained the console
  element, its CSS, and the polling JS (`pollJobLog`).
- Tests: `test_self_installer.py` (2 new - real stage lines captured,
  no-op default doesn't raise), `test_drive_admin.py` (1 new -
  `on_progress` doesn't break an action that ignores it),
  `test_baseline_web.py` (3 new - job starts immediately, job-log
  reports real completion, unknown job_id returns 404).

## Verification performed

- Full suite: 1510/1510 (was 1504 before this record's 6 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- Live browser verification: triggering an action shows the console
  area, real polling requests hit `/drive-admin/job-log`, and the job
  reaches `done` with a real outcome/detail, confirmed via direct DOM
  inspection.
- **Not yet re-verified against a real, full `build_self_installer`
  run** - the user should retry with their own real password; the
  cached Proxmox source ISO is now staged at
  `/mnt/INSTALLER_CACHE/isos/proxmox-ve-source.iso` (copied from an
  earlier session's own verified download, same SHA-256), so that
  particular earlier refusal should not recur.
