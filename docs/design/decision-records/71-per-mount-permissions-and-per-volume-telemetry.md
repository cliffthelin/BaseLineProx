# Decision record: per-mount permission restrictions and per-volume telemetry

Status: **implemented and tested (1027/1027 suite passing). Mount/
remount semantics verified via real `df`/argv-shape smoke tests, not a
real loop-mounted ext4 filesystem (no root available in this
environment - not run against real hardware).**

## Direct instruction

Confirmed real follow-up work from decision record 68's architecture
discussion: "per-mount permission restrictions (e.g. noexec on
SESSION_TEMP) and per-volume telemetry."

## Per-mount permission restrictions

New `drive_installer.MOUNT_OPTIONS`: `nosuid,nodev` on every one of
the four volumes (none should ever host a setuid binary or a device
node), additionally `noexec` on `SESSION_TEMP` (pure ephemeral session
data, never anything meant to run) and `INSTALLER_CACHE` (holds
ISOs/driver packages, consumed by name via `dpkg`/`mount`/`xorriso`,
never executed directly). Deliberately **not** on `USER_PERSISTENCE` -
it holds the scripts inbox (decision record 70), and an operator may
reasonably `chmod +x` and run a pushed script directly from there; not
on `BASELINE` - app/VM/LXC state may legitimately need to execute
things it stores.

`mount_argv`/`ensure_volume` now apply these options on every mount,
new or pre-existing. The pre-existing case matters as much as the new
one: `ensure_mounted_with_options` first attempts a plain mount with
the real options (works if not yet mounted), and if that fails because
the volume is already mounted, issues a real `mount -o remount,<opts>`
to actually apply the restriction to a volume mounted before this fix
existed - not just recording the intent for next boot. A real fstab
entry (`ensure_fstab_entry`, idempotent, mirrors
`persist_bind_mounts.py`'s own `_fstab_has_line` pattern) is also
written so the same options survive a reboot without depending on this
code running again.

## Per-volume telemetry

New `drive_installer.collect_volume_usage` - real `df -B1
--output=size,used,avail,pcent` per `BASELINE_VOLUMES` mountpoint, not
a second lvs-based estimate that could drift from what is actually
mounted. A volume that isn't mounted (`df` fails) is skipped, not an
error - the same tolerance `diagnostics.py`'s own collectors already
hold themselves to for missing hardware.

Wired into `sensors_collect.py`'s existing 30s collection cycle/store
(source `"volume"`, keys `<LABEL>/percent_used` and `<LABEL>/used_bytes`)
rather than building a separate periodic-collection mechanism -
reuses the same timer, the same sqlite store, the same 24h retention,
with zero new moving parts.

## Verification performed

- `drive_installer.py`: 10 new RED-then-GREEN tests for
  `mount_argv`/`remount_argv`/`fstab_line`/`ensure_fstab_entry`/
  `ensure_mounted_with_options`, including a test proving a
  pre-existing mount gets a real remount call to apply options, and a
  test proving fstab entries are never duplicated. 7 more for
  `collect_volume_usage`/`parse_df_output`/`df_argv`.
- Real `df -B1 --output=size,used,avail,pcent` run against this actual
  dev machine's `/home` - output format matches
  `parse_df_output`'s assumption exactly, confirmed directly rather
  than assumed from documentation.
- Real end-to-end: `collect_volume_usage` against `repair.RealRunner`
  on this dev machine correctly returns `[]` (none of
  `BASELINE_VOLUMES`' mountpoints exist here) with no crash; a full
  real `collect_once()` cycle against a real sqlite `:memory:` db and
  `RealRunner` recorded 42 real samples with no error.
- `sensors_collect.py`: 2 new tests confirming real volume samples
  land under source `"volume"` with the right keys/values, and that
  the pre-existing no-hardware test's sample count (`0`) is unaffected
  since the fake's default unmatched-command response
  (`returncode=0`, empty stdout) already makes `parse_df_output`
  return `None` for every volume.
- Not run against a real loop-mounted ext4 filesystem - no root
  available in this environment to verify `mount -o noexec` actually
  blocks execution live; the argv shapes and idempotent
  mount-then-remount logic are fully verified, and `-o noexec`/
  `nosuid`/`nodev` are standard, long-documented Linux mount option
  semantics, not something this module invents.
- `tools/check_provision_deploys_all_imports.py` - zero gaps
  (`sensors_collect.py`'s new `drive_installer` import is already
  staged).
- Full suite: 1027/1027 passing, no regressions.
