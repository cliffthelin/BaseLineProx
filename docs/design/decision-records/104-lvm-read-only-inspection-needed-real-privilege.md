# Decision record: real LVM read-only inspection (`pvs`/`vgs`/`lvs`) was silently failing for a plain user - masked by always-empty real state

Status: **real, confirmed bug found live, fixed, and covered by
updated tests across 5 files. Live-verified: `/dev/sdd`'s `vg_name`
now correctly resolves to `pve` (was `null`).**

## What happened

User: "There are no BASELINE identified Drives nor the grouping that
puts them on the top." Investigated directly rather than assuming the
earlier feature (decision record 99's Baseline-drive detection) was
simply reporting an accurate "nothing exists yet" - confirmed via a
real, direct `sudo -n pvs`/`sudo -n vgs`/`sudo -n lvs` against this
machine's actual `pve` VG that `/dev/sdd3` genuinely has a real,
populated volume group. The web page, however, reported `vg_name:
null` for `/dev/sdd` - a real discrepancy between what the system
actually has and what the page showed.

## Root cause

`pvs`/`vgs`/`lvs` fail for a plain, non-root user on this real
machine: `pvs` as `cane` returns `WARNING: Running as a non-root
user... /run/lock/lvm/P_global:aux: open failed: Permission denied`,
exit code 5 - confirmed directly. `drive_admin.find_vg_for_device`
and `drive_installer.list_logical_volumes_argv`/
`list_logical_volume_sizes_argv`/`vg_free_bytes_argv` all called these
commands bare, with no privilege wrapping of their own, relying
entirely on whatever `Runner` the caller happened to pass in. The
page-rendering path (`GET /drive-admin`) uses a plain, unprivileged
runner (`deps["runner"]`, a real but non-elevated `RealRunner`) - so
every one of these calls has been silently failing there since this
project began querying real LVM state, `returncode != 0` treated
identically to "genuinely found nothing." This went undetected because
the real answer (no Baseline volumes exist anywhere yet) happened to
look the same either way - until now, when `/dev/sdd`'s real `pve` VG
should have shown up as a real VG name even with zero Baseline volumes
on it, and didn't.

## Fix

This machine's own real sudoers file has `pvs`/`vgs`/`lvs`/`vgchange`
specifically, individually passwordless (`(root) NOPASSWD: /usr/sbin/
vgs, /usr/sbin/lvs, /usr/sbin/vgchange, /usr/sbin/pvs, ...` - confirmed
live via `sudo -n -l`) - a deliberate, narrow, read-only allowance.
All four read-only argv builders now prefix their command with `sudo
-n`: `-n` makes the call fail cleanly (never hang waiting for a
password) on any machine where this specific passwordless allowance
isn't configured, rather than making anything worse than today's
already-broken silent failure.

Destructive LVM commands (`lvcreate`/`vgcreate`/`pvcreate`/`wipefs`/
etc.) are deliberately **not** given this treatment - those correctly
continue to rely on the caller's own already-privileged runner
(`PkexecRunner`, decision record 103) during a real action; this
project does not add a blanket passwordless allowance for anything
that writes.

## Files changed

- `baseline/lib/drive_installer.py` - `list_logical_volumes_argv`,
  `vg_free_bytes_argv`, `list_logical_volume_sizes_argv` all prefixed
  with `sudo -n`.
- `baseline/lib/drive_admin.py` - `find_vg_for_device`'s own `pvs`
  call prefixed with `sudo -n`.
- Tests updated across 5 files (`test_drive_installer.py`,
  `test_drive_admin.py`, `test_control_panel_web.py`,
  `test_drive_installer_telemetry.py`, `test_persist_bind_mounts.py`):
  `FakeRunner` matcher lambdas changed from exact-prefix equality
  (`a[:1] == ["lvs"]`) to substring matching (`"lvs" in a`), since the
  real argv shape changed; direct argv-equality tests
  (`test_list_logical_volumes_argv`/`test_vg_free_bytes_argv`) updated
  to expect the new `sudo -n` prefix explicitly.

## Verification performed

- Full suite: 1522/1522 (unchanged count - no new tests added, existing
  ones updated to match the real new argv shape).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Live verification, not just unit tests**: confirmed directly via
  terminal that `pvs` fails for plain `cane` (exit 5, permission
  denied) and that `sudo -n pvs`/`sudo -n lvs pve` succeed and report
  real data. Restarted the server on the fixed code and confirmed via
  live DOM inspection that `/dev/sdd`'s `vg_name` now correctly
  resolves to `"pve"` (was `null`). The Volumes table's "not created
  yet" for all 6 Baseline volumes is now a genuinely truthful,
  successful read - directly cross-checked against this same session's
  own `sudo -n lvs pve` output (only `root`/`swap`/`data`/`vm-202-*`/
  `vm-203-*` exist, zero `baseline_*` volumes) - not a masked failure.
- `is_baseline_drive` correctly remains `False` for `/dev/sdd` - this
  is accurate, not a remaining bug: the drive genuinely has no
  Baseline volumes on it yet (that still depends on the wipe/rebuild
  or freeing real space, per the earlier real-space-shortfall finding).
