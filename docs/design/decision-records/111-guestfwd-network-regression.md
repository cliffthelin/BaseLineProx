# Decision record: `restrict=on` blocks guest→host answer-server traffic entirely - decision record 03's own already-proven `guestfwd` fix had silently regressed

Status: **real, structural bug found live during a real install
attempt, root-caused by rediscovering this project's own earlier
decision record (03), fixed by restoring the already-proven
mechanism, and covered by new regression tests. Real, self-triggered
retry with this fix applied was launched after writing this record.**

## What happened

A real, self-triggered `build_self_installer` run (with decision
records 106-110's fixes already applied) finally reached the real
Proxmox installer environment - DHCP succeeded, the installer
correctly attempted to POST its answer-file request - and failed with
a real `io: Connection refused` reaching `https://10.0.2.2:8443/...`.

## Diagnosis

Rather than guess, built a fully isolated, disposable reproduction
with the exact same `-nic user,restrict=on` networking config as
production: a plain HTTP test server on an arbitrary host port,
completely unrelated to the answer server, probed directly from
inside a booted guest via bash's own `/dev/tcp` pseudo-device (sent as
real keystrokes over the safe monitor-socket mechanism, decision
record 108 - `curl`/`wget` aren't installed in this minimal installer
environment). Result: `bash: connect: Connection refused` - a real,
conclusive, general proof that `restrict=on` blocks *all* guest→host
TCP connectivity, not just this one service, not a fluke.

This is not a new discovery - **decision record 03 documented this
exact finding years ago**, with the exact fix already proven working:
`-netdev user,id=net0,restrict=on,guestfwd=tcp:10.0.2.100:8443-tcp:127.0.0.1:<port>`
+ `-device virtio-net-pci,netdev=net0,mac=...` (the long form - `guestfwd`
isn't expressible via the `-nic` shorthand at all). Record 03's own
words: "DHCP/DNS/router-advertisement traffic works because SLIRP
implements those protocols internally, not because they're proxied to
a real host socket" - and: "worth carrying into Milestone 1's real
design as the default networking approach for any answer-server-
dependent QEMU session, physical-drive milestone included."

The actual, real `drive_setup_install.py`/`self_installer.py` code
never carried this forward - it used the plain `-nic user,restrict=on`
shorthand, with `DEFAULT_SERVER_HOST = "10.0.2.2"` (SLIRP's own
gateway, not the distinct `10.0.2.100` guestfwd address record 03
established), and its own docstring's claim ("matching decision record
03's accepted design exactly") was simply false - a genuine
documentation/implementation drift that nothing had caught until a
real install attempt reached far enough to expose it.

## Fix

Restored decision record 03's own proven design:

- New `drive_setup_install._network_argv` builds the long-form
  `-netdev`/`-device virtio-net-pci` invocation with a real `guestfwd`
  rule when `guestfwd_host`/`guestfwd_port` are given, falling back to
  the plain `-nic` shorthand otherwise (backward compatible for any
  caller that doesn't need it).
- `build_sparse_install_invocation` gained `guestfwd_host`/
  `guestfwd_port` parameters, threaded through to `_network_argv`.
- `self_installer.DEFAULT_SERVER_HOST` corrected from `"10.0.2.2"` to
  `"10.0.2.100"` - the distinct guestfwd-forwarded address, not the
  real SLIRP gateway.
- `self_installer.build_and_write_self_installer`'s own call to
  `build_sparse_install_invocation` now passes
  `guestfwd_host=server_host, guestfwd_port=server_port` - the same
  values already baked into the answer file's own URL, now actually
  reaching the QEMU invocation too.

## Files changed

- `baseline/lib/drive_setup_install.py` - `_network_argv` (new),
  `build_sparse_install_invocation` (new params + call site).
- `baseline/lib/self_installer.py` - `DEFAULT_SERVER_HOST` corrected;
  its own call site passes the new params.
- Tests: `test_drive_setup_install.py` (2 new - guestfwd argv shape
  when given, plain `-nic` fallback when not), `test_self_installer.py`
  (1 new - `DEFAULT_SERVER_HOST` corrected; 1 new - proves
  `build_and_write_self_installer` actually forwards `server_host`/
  `server_port` as `guestfwd_host`/`guestfwd_port` to the real
  invocation builder, isolated via monkeypatching the two intermediate
  stages rather than fully re-deriving their own already-tested
  internal behavior).

## Verification performed

- Full suite: 1544/1544 (was 1541 before this record's 3 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Real, isolated, disposable reproduction of the actual failure**:
  an independent test HTTP server, unrelated to the answer server,
  confirmed unreachable from a booted guest under the exact production
  networking config, via a real `/dev/tcp` probe sent as real
  keystrokes - not assumed from documentation or memory of QEMU's own
  docs. All disposable test images/processes cleaned up after.
- A real, self-triggered `build_self_installer` retry with this fix
  applied was launched after writing this record - the operator should
  confirm the real answer-file POST now succeeds (reaching a 2xx/4xx
  HTTP response instead of `Connection refused`) via the Live install
  screen viewer.
