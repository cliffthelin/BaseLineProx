# Decision record: a previous run's own answer server was never stopped before a new one tried to bind the same port

Status: **real bug found live, in the same debugging chain as decision
record 113 (stale QEMU process) - the same missing-cleanup pattern,
for a different real resource. Fixed, covered by two new regression
tests.**

## What happened

After decision record 114's second correction (the `virtio-scsi-pci`
+ `scsi-hd` serial fix), a real install finally got *past* the
"filter did not match any device" bug entirely for the first time in
this debugging chain - but failed with a new error instead:
`INFO: Fetching answer file via HTTP failed: timeout: global` /
`ERROR: Aborting: Could not find any answer file!`. A same-workspace
retry, triggered immediately after to check whether this was a flake,
instead failed outright before QEMU even had a chance to boot:
`"outcome": "error", "detail": "OSError: [Errno 98] Address already
in use"`.

## Root cause

`build_and_write_self_installer` constructs a fresh
`dsan.EphemeralAnswerServer(bind_host="0.0.0.0", bind_port=server_port,
...)` and calls `.start()` on every run - but nothing anywhere ever
called `.stop()` on the *previous* run's own server first. Each
server binds a real `http.server.HTTPServer` socket in its own
constructor and spawns a background thread serving it forever
(`serve_forever`); since `build_and_write_self_installer` returns
without keeping any reference to `server`, the object becomes
unreachable from Python's own code but the background thread still
holds a live reference to `self`, so the socket is never actually
closed - the previous server keeps running, forever, inside
`baseline-web`'s own long-lived process.

This explains both real symptoms directly:

- The **timeout**: an earlier, even-older run's own answer server was
  still alive, and Python's `socketserver.TCPServer` sets
  `allow_reuse_address = True` by default - which permits a *second*
  bind to briefly succeed even while a port is still actively listened
  on in some kernel/timing circumstances, but does not mean the new
  guest's request reliably reaches the *new* server. The guest's fresh
  answer.toml embeds a brand-new session token; if its HTTPS request
  got routed to the old, stale server instead (whose `session` object
  has a different token), the mismatch caused a hang rather than a
  clean response.
- The **`Address already in use` crash**: on the very next retry, the
  bind of a *third* server onto the same still-occupied port failed
  outright rather than silently racing - the previous server(s) were
  still genuinely listening.

## Fix

- New module-level `self_installer._active_answer_server` (mirroring
  `baseline_web.py`'s own `_JOBS` registry precedent for real,
  process-wide state) tracks the single currently-active
  `EphemeralAnswerServer` instance.
- Before constructing a new server, `build_and_write_self_installer`
  now checks `_active_answer_server`; if one exists, calls `.stop()`
  on it and reports the cleanup via `progress(...)` before proceeding,
  the same real-cleanup pattern decision record 113 established for
  the QEMU process.

## Why no existing test caught this

No existing test ever exercised the answer-server construction/start
success path more than once in the same test - every test either
refused earlier or stopped itself at the first `dsan.SessionState`/
`dsan.EphemeralAnswerServer` construction via a monkeypatched
exception. A repeated real call, the only way to observe stale-server
reuse, had never been represented.

## Files changed

- `baseline/lib/self_installer.py` - `_active_answer_server` module
  state; stop-then-replace logic before constructing a new server.
- `tests/unit/test_self_installer.py` - `_reset_active_answer_server`
  autouse fixture (module-level state must not leak across tests in
  the same pytest process); 2 new regression tests: a second real run
  stops the first server before starting its own, and the very first
  run never attempts to stop anything.

## Verification performed

- Full suite: 1552/1552 (was 1550 before this record's 2 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Found via two real, distinct live failures** in direct succession
  (a real answer-fetch timeout, then a real `OSError: Address already
  in use` on the very next retry) - not from inspection. `ss -tlnp`
  was used directly against the real host to confirm the actual
  listening-socket state at each step rather than assumed.
- A real, self-triggered retry with this fix applied was launched
  after writing this record.
