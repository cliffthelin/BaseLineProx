# Decision record: the real Control Panel web application replaces the paste-JSON bridge

Status: **implemented, unit-tested (11 new tests, 933/933 suite
passing), and proven live against real tar/lvs on this machine - not
just fakes.** The HTTP server was actually started on this host and
driven with real `curl` requests: `/api/detect` returned this
machine's real, live LV state (including a real permission-denied
note, handled gracefully, not a crash); `/api/backup`, `/api/backup/list`,
and `/api/restore` ran a genuine tar create/list/extract round-trip and
the restored file's content matched byte-for-byte. Not yet run against
the real target Proxmox hardware, and not yet wired into every tab of
the configurator artifact - stated honestly below, not left implicit.

## What was asked

Direct, emphatic correction, after several turns of building a static
HTML artifact with "paste the real command's output here" bridges for
drive detection, differences, and backup/restore: *"This is not what I
asked for and it doesnt even work... THIS IS A WEB APPLICATION THAT
INSTALLS SUBSTRATE CONTROL PLANES AND VM AND IS A MASTER CONFIG LIST
THAT ALSO DRIVES STANDARD MANAGMENT BEHAVIORS. IT IS NOT A FORM. I
NEVER WILL PASTE RESULTS INTO IT OR GENERATE JSONS TO USE SOMEWHERE
ELSE."*

## Why the artifact could never satisfy this

A claude.ai published Artifact is a static page in a browser sandbox
with no server, no socket access, and no channel to a filesystem or
another host - it structurally cannot run `tar`, `lvs`, or `openssl`,
or reach a real Proxmox box. Every "paste the real output here" step
in the earlier configurator work was the honest consequence of that
constraint, not a design preference - but honest-about-a-limitation is
not the same as solving the actual problem, and the correction is
right: a tool whose entire job is to review and drive real install/
update/backup behavior has to actually be reachable from the real
target, running real code, or it never does what it's for.

## What was built instead

A real, live web application - `baseline/lib/control_panel_web.py` -
reusing this project's own already-proven pattern for exactly this
shape of surface: `settings_web.py` (PRD SS5.16), which already
establishes `http.server.HTTPServer`/`BaseHTTPRequestHandler` with
Runner-style dependency injection and pure `handle_*` route functions
returning a `RouteResult`, so every route's real decision logic is
unit-testable with a `FakeRunner` while the actual HTTP wiring stays a
thin pass-through.

Every route calls straight into the real backend modules already
built and tested this session - no intermediate JSON file, no copy-
paste step, anywhere:

- `GET /api/detect` -> `drive_installer.detect_existing_baseline_install()`
- `GET /api/differences` -> `config_diff.compute_full_diff()` (reads
  the real exported config off disk itself, at `--config-path`; hands
  off honestly if none has been exported yet - never fabricates a diff)
- `POST /api/backup` / `GET /api/backup/list` / `POST /api/restore` ->
  `backup_restore.create_backup()` / `list_backup_contents()` /
  `restore_backup()`
- `POST /api/update` -> `update_pipeline.apply_selective_update()`
  (reads the real config the same way `/api/differences` does)
- `POST /api/validate-drive` -> `physical_device_safety.validate_target_device()`
- `POST /api/backup/encrypt` / `POST /api/backup/decrypt` ->
  `config_crypto.encrypt_file()` / `decrypt_file()`, with the password
  written to a private, immediately-removed 0600 temp file for the
  real `openssl` call - never a bare argv, matching this project's own
  established credential-handling discipline
  (`baseline-drive-inventory`'s docstring).

`GET /` serves a real, minimal HTML/JS page that calls these routes
with `fetch()` and renders the live JSON response - no textarea
anywhere invites pasting a result in or copying a generated request
out. `baseline/bin/baseline-control-panel` is the real entry point.

## Verification performed

- RED confirmed first for every `handle_*` function.
- 11 new unit tests against `FakeRunner`/a hand-built `physical_device_safety.Runner`
  fake - one genuine test bug found and fixed along the way (the fake's
  `udevadm` response didn't vary by `--name=`, so the target and boot
  device appeared identical; fixed to return different real-shaped
  serials per device, the same class of self-caught fake-quality issue
  this project has hit before).
- **Live proof, not just fakes**: started the real server on this
  machine (`RealRunner`, real `physical_device_safety.Runner`) and hit
  it with real `curl`:
  - `GET /api/detect` returned this machine's actual `lvs` state
    (no Baseline volumes found here, correctly, plus a real
    permission-denied note for the non-root run, handled without
    crashing).
  - `POST /api/backup` really created a tar archive on disk;
    `GET /api/backup/list` really listed its real contents;
    `POST /api/restore` really extracted it, and the restored file's
    content matched the original byte-for-byte.
  - The test server and its temp files were fully cleaned up
    afterward - nothing left running, no artifact left on disk.
- Full suite: 933/933 passing (922 before this change - +11 new), no
  regressions.

## What this deliberately does not yet do

- Only the routes above are wired for real. The rest of the earlier
  configurator's many review tabs (Proxmox tools, drivers, VMs,
  credentials, etc.) are not yet exposed through this server - that is
  real, separate follow-up work, one section at a time, not silently
  promised here.
- Not run against the real target Proxmox hardware - only against this
  dev machine's own real `lvs`/`tar`, which correctly has no Baseline
  volumes and is not the actual install target.
- Authentication/session handling (real for `settings_web.py`'s login
  flow) is not yet present on this server - it currently assumes a
  trusted LAN-local operator, matching `settings_web.py`'s own stated
  scope ("a persistent, LAN-scoped web surface"), but this has not
  been explicitly re-examined for the control panel's own routes yet.
