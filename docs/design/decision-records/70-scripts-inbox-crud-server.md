# Decision record: the scripts inbox - login-gated file CRUD for pushing scripts to run later

Status: **implemented and tested (1007/1007 suite passing). Login/CRUD
flow verified for real against a genuine running HTTP server on a real
socket; not run against real hardware.**

## Direct instruction

"network sharing and phone responses or scripts pushed to a folder
Proxmox or Baseline can run" - asked what the actual phone-side
mechanism was; the answer was direct: "You need to help come up with
it right now it's just files with server and folder access to CRUD."

## What was built

**`baseline/lib/scripts_inbox.py`** - real, Runner-injectable file CRUD
(`list_scripts`/`read_script`/`write_script`/`delete_script`) scoped to
one folder (default `/mnt/USER_PERSISTENCE/scripts_inbox` - persists
across a reinstall, unlike the disposable substrate). Every name is
validated as a single, flat, safe filename before it ever reaches a
real path join (regex + `posixpath.basename` equality) - path
traversal refused by construction, matching `gui_brokers.file_picker`'s
own established discipline for this exact threat, not pattern-matching
the string alone. This module never executes anything - running a
script from the inbox is always a deliberate, manual operator action
at a real terminal, matching PRD SS2/SS6's "explicit human decision
for anything consequential" principle.

**`baseline/lib/scripts_inbox_web.py`** - the real HTTP CRUD server.
**Login-gated**, unlike `control_panel_web.py` (decision record 65),
which has no authentication at all and stays operator-invoked-only for
exactly that reason. This server is meant to be reached over the
network - that is the whole point, a phone pushing a script - so it
must never repeat that gap. Reuses `settings_web.py`'s own proven auth
machinery directly rather than duplicating it:
`PasswordVerifier`/`SessionStore`/`handle_login`/
`FileBackedPasswordVerifier`/`JsonFileStore`, with its own separate
credential store from settings-web's own (a different data file, now
also placed on USER_PERSISTENCE so the login itself survives a
reinstall) - a compromised scripts-inbox login can't also reach
settings, and vice versa. Every route is a pure `handle_*` function
returning a `RouteResult`, matching every other web module in this
project.

**`baseline/lib/scripts_inbox_gate.py`** - the `ExecStartPre` gate:
refuses to start until USER_PERSISTENCE is actually mounted, reusing
`persist_bind_mounts.is_mounted` unchanged - the exact real-kernel-state
check `ensure_redirect` already relies on for the same reason. Without
this, a script pushed before the mount is ready could silently create
`/mnt/USER_PERSISTENCE/scripts_inbox` on the disposable substrate
instead of the real persistent volume - the same write-through class
`persist_bind_mounts.py`'s own module docstring already names.

## A real bug found by live smoke testing, not caught by fakes

The fallback `Runner` interface in `scripts_inbox.py` was first written
with a `write_text` method - but a real end-to-end test against a
genuine running server (real socket, real login, real write/read/
delete round trip) crashed with `AttributeError: 'RealRunner' object
has no attribute 'write_text'`. `repair.RealRunner`'s real method is
`write_text_atomic` (temp file + fsync + `os.replace` - strictly safer
for a script file that might be read mid-write). The hand-written test
fakes in both test files had matched this same wrong assumption, so
unit tests alone would never have caught it - exactly why this
project's live-smoke-test discipline exists. Fixed in the module and
both fakes; re-ran the full real end-to-end test afterward and
confirmed login, write, list, read (byte-identical), a rejected path-
traversal attempt (`400`), a rejected unauthenticated request (`401`),
delete, and the real file's absence from real disk afterward.

## A real cross-module mismatch found while wiring this in

Tracing where to default the inbox directory surfaced a separate real
bug: `persist_bind_mounts.py`'s `MOUNT_POINT` (`/mnt/user-persistence`,
lowercase) didn't match `drive_installer.py`'s own real mountpoint for
the same labeled volume (`/mnt/USER_PERSISTENCE`, uppercase) - fixed
separately as decision record 69, before this module's own default was
chosen, so it would not inherit either side's inconsistency.

## What this does not do

- No systemd unit gates the reverse direction (i.e., nothing stops the
  server if USER_PERSISTENCE is later unmounted mid-run) - only the
  start-time gate exists.
- Not run against real hardware - the login/CRUD flow is verified end
  to end against a real local HTTP server and real disk I/O on this
  dev machine, not against a real Baseline install.
- Does not add rate limiting or account lockout to the reused login
  flow - inherits exactly settings_web.py's own current posture,
  unchanged.

## Verification performed

- RED-then-GREEN for `scripts_inbox.py` (20 tests), `scripts_inbox_web.py`
  (12 tests), `scripts_inbox_gate.py` (4 tests).
- A real end-to-end smoke test: a genuine `http.server.HTTPServer` on a
  real socket, a real login against the seeded root/baseline account,
  a real write/list/read/delete round trip against real disk, a real
  path-traversal attempt correctly refused (400), a real unauthenticated
  request correctly refused (401), and confirmation the deleted file
  is genuinely gone from real disk afterward.
- `bash -n boot/provision.sh` - clean.
- `systemd-analyze verify boot/baseline-scripts-inbox.service` -
  structurally clean (only the expected "binary not found on this dev
  machine" note).
- `tools/check_provision_deploys_all_imports.py` - zero gaps.
- Full suite: 1007/1007 passing, no regressions.
