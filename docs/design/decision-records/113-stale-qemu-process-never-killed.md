# Decision record: a previous run's own QEMU process was never killed before launching a new one

Status: **real bug found live, via direct process/IO-counter inspection
of an install that appeared to be running but was not. Fixed, covered
by two new regression tests.**

## What happened

After decision record 112's `disk_serial` fix, a new real install
(job `eda4c594ed5140358adb8dac5120ed76`) was launched and its own
progress log reported "Real QEMU install running, answer server
listening on 10.0.2.100:8443." Attempting to verify progress via the
new safe `/drive-admin/screendump` endpoint failed with a real,
deterministic `[Errno 111] Connection refused` against the QEMU
monitor socket - reproduced identically via `nc`, a fresh direct
Python socket connection (bypassing the web app entirely), and a
5-attempt retry loop over 5 seconds. `ss -lxp` and `lsof` both showed
the socket file genuinely `LISTEN`-owned by a live process
(`qemu-system-x86_64`, pid 68235), and `/proc/net/unix` showed a
normal `SS_UNCONNECTED` (idle-listener) state - ruling out the usual
explanations (dead process, wrong namespace, wrong permissions,
AppArmor - though the AppArmor check itself was inconclusive here,
`sudo -n journalctl -k` returned empty even for unrelated lines,
suggesting that specific command isn't usable non-interactively in
this session rather than proving no denial occurred).

## Root cause

Comparing `ps -o lstart` for the running QEMU process against the
`mtime` of the very files it was supposedly still booting from
(`baseline-self-installer.iso`, `answer-embedded.iso`,
`answer-server-cert.pem`) showed the process started at 08:20:01,
five minutes *before* those files existed (08:25). That is only
possible if this QEMU process was a **leftover from an earlier
attempt** at the same workspace path, never killed, still holding
`/dev/sdd` and the workspace's `monitor.sock` open, while a *later*
job (`eda4c594...`) rebuilt fresh ISOs and restarted the answer server
around it without ever checking whether a previous process was still
alive.

Confirmed further: `/dev/sdd`'s real partition table was completely
unchanged from its pre-install state (`pve-root`/`pve-swap`/
`vm-202`/`vm-203` all still present), and the stale process's own
`/proc/<pid>/io` `wchar` counter grew by only 24 bytes across an 8
second sample - not remotely consistent with an installer actively
partitioning/formatting a 512GB target. The stale process was not
progressing; it was simply never terminated.

No `pkill`/`terminate`/process-cleanup of any kind exists anywhere in
`self_installer.py`, `drive_setup_install.py`, or `drive_admin.py`'s
`build_self_installer` action - every previous fix in this area added
new capability but none ever addressed a prior run's process still
being alive when a new one starts.

## Fix

- **New `InstallRunner.kill_process_using_path(path) -> bool`**
  (`drive_setup_install.py`), real implementation via
  `pgrep -f <path>` (QEMU's own `-monitor unix:<path>,server,nowait`
  argument makes the path a unique, distinguishing match) +
  `os.killpg(os.getpgid(pid), SIGKILL)` per match.
- **`build_and_write_self_installer`** (`self_installer.py`) now
  checks `install_runner.path_exists(workspace / "monitor.sock")`
  immediately before building the QEMU invocation; if a stale monitor
  socket file is already present, it calls
  `install_runner.kill_process_using_path(...)` first and reports the
  cleanup via `progress(...)` before launching the new process.

## Why no existing test caught this

No existing test in `test_self_installer.py` ever exercised the
QEMU-launch success path all the way through `install_runner.popen` -
every prior test either refused at an earlier stage or stopped itself
via a monkeypatched exception immediately after invocation
construction, before a stale-process scenario could even be
represented. `FakeInstallRunner.popen` itself unconditionally raised
`NotImplementedError`, so no test could have reached this path without
first extending the fake.

## Files changed

- `baseline/lib/drive_setup_install.py` - `InstallRunner.kill_process_using_path`
  (abstract) + `RealInstallRunner.kill_process_using_path` (real
  `pgrep`/`killpg` implementation).
- `baseline/lib/self_installer.py` - stale-process check + kill before
  launching QEMU.
- `tests/unit/test_drive_setup_install.py` - `FakeInstallRunner` gained
  `existing_paths`, `killed_paths`, `kill_process_using_path`, and a
  real (non-raising) `popen` path via `scripted_popen_process`.
- `tests/unit/test_self_installer.py` - two new regression tests: a
  stale monitor-socket file triggers the kill before launch, and a
  fresh workspace with no stale file never calls it.

## Verification performed

- Full suite: 1547/1547 (was 1545 before this record's 2 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Found via real, direct evidence** - process start-time vs. file
  mtime comparison, `/proc/<pid>/io` counter growth over a real
  measured interval, and `lsblk`'s real, unchanged partition table on
  `/dev/sdd` - not from inspection or a pre-existing test.
- The actual stale process (pid 68235) was killed for real after this
  fix was written, and a fresh install re-triggered through the
  now-corrected code path (see `docs/changelog/proxmox/003.md` for the
  matching changelog entry and its own follow-up verification).
