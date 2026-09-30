# Decision record: real, safe "live install screen" viewer - replacing a manual raw-socket command that killed a real install

Status: **implemented and fully unit-tested (1539/1539 full suite).
Not yet live-verified against a real, actively-running install (none
was running at the time this was built) - the operator's next real
`build_self_installer` attempt is the actual proof.**

## What this resolves

Direct instruction, 2026-09-29: "keep things improving," following a
real mistake earlier the same session - a manual `nc`-piped
`screendump <path>\nquit\n` sent to a real install's QEMU monitor
socket, intending `quit` to close the shell pipe, actually terminated
the entire VM (QEMU's monitor treats `quit` as a real command, not a
connection-closing convenience). The install had to be restarted from
scratch. The user's own point stands: checking install progress should
be a real, safe application feature, not something requiring hand-
typed raw socket commands that carry exactly this kind of risk.

## What was built

1. `drive_setup_install.send_monitor_command_via_socket(monitor_socket,
   command, timeout=5.0)` - the same real, safe HMP-over-unix-socket
   pattern `_RealInstallProcess.send_monitor_command` already used
   (connect, drain the banner, send the one real command, close), now
   reachable as a standalone function using only the monitor socket's
   real path on disk - needed because a real install's own Python
   process handle doesn't survive past the single web request that
   launched it, but the socket file itself persists on disk for as
   long as QEMU is alive. Its own contract is the actual fix: it sends
   *exactly* the command it's given and nothing else - there is no
   code path in this function that can send `quit`.
2. `ppm_to_png(ppm_bytes)` - a minimal, stdlib-only (`zlib`/`struct`)
   P6-PPM-to-PNG encoder. No new system dependency: neither
   ImageMagick's `convert` nor `ffmpeg` is provisioned anywhere in
   this project (checked directly - `boot/provision.sh` has neither),
   and Pillow isn't a stdlib module either. Browsers don't render PPM
   natively, so a real, dependency-free converter was the honest
   choice over introducing a new provisioned package just for this.
3. `capture_live_screendump_png(monitor_socket, ...)` - composes the
   two: requests one real screendump, reads the real file QEMU wrote,
   converts it, cleans up the temp file. Genuinely raises (never a
   fake blank image) if no real install is actually running there.
4. New `GET /drive-admin/screendump?workspace=<path>` route
   (`baseline_web.py`) returning real `image/png` bytes, or a clean
   404/502 JSON error when no install is running or the capture fails
   - never a fake success.
5. A real "Live install screen" section on the Drive Administration
   page: an `<img>` plus a manual **Refresh** button - deliberately
   not auto-polling, so this feature itself can never hammer a real
   QEMU process the way an aggressive interval-based capture might.

## Files changed

- `baseline/lib/drive_setup_install.py` - the three new functions
  above.
- `baseline/lib/baseline_web.py` - `_binary_response` helper, the new
  `/drive-admin/screendump` route, the page's new "Live install
  screen" section (HTML/CSS/JS), `Path` promoted to a real module-
  level import (was only ever imported locally inside
  `build_real_server` before).
- Tests: `test_drive_setup_install.py` (4 new - proves the socket
  function sends exactly the given command and never `quit`, using a
  real Unix socket test server; `ppm_to_png` round-trips real pixel
  data through an independent PNG chunk reader, and refuses non-P6
  input; `capture_live_screendump_png` reads the real written file and
  cleans up after itself), `test_baseline_web.py` (2 new - the route
  returns a clean 404 with no install running, and returns a real PNG
  when a real Unix socket test server stands in for QEMU's own
  monitor, again proving `quit` is never sent).

## Verification performed

- Full suite: 1539/1539 (was 1533 before this record's 6 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Not yet live-verified against a real, actively-running install** -
  no install was running at the time this was built (the earlier one
  had just been killed by the mistake this feature fixes). The
  operator's next real `build_self_installer` attempt, followed by
  clicking Refresh on the new Live install screen section, is the
  actual real-world proof this works end-to-end.
