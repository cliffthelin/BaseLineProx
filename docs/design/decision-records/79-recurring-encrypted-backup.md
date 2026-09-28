# Decision record: automated recurring encrypted backup job

Status: **implemented and tested (1176/1176 suite passing, up from
1158 after decision record 78). Not run against real hardware. Does
NOT yet target a genuinely separate physical device - see below.**

## What this closes

Work-queue item 27: "Automated recurring encrypted backup job
(separate device target, matching `sensors_collect.timer`'s pattern) -
keeps decision record 74's 24h freshness gate satisfied without manual
action." Its stated blocker was "needs a decision on which device
counts as 'the separate one' once multiple personas/volumes exist."

## The real, honest gap this only partially closes

No third physical device exists in this dev session - only `/dev/sdd`
(Proxmox/BASELINE) and `/dev/sdb`
(USER_PERSISTENCE/INSTALLER_CACHE/SESSION_TEMP) are real and attached
(decision record 46). The new job's default target
(`/mnt/INSTALLER_CACHE/encrypted_backups`) is **not** physically
separate from USER_PERSISTENCE - both currently live on the same
drive. This does not satisfy "separate device" in the strong sense
item 27 meant, and this record says so plainly rather than claiming
otherwise.

What genuinely is real and done: the target directory is a live
setting, not a hardcoded path, so attaching a real separate device
later is a one-line configuration change, not new code - the
automation, encryption, and freshness-manifest wiring underneath it is
the real, tested part of this pass, matching this project's own
"pragmatic, stated-as-such choice, not a final production answer"
precedent (the plan's own A2 phase made the identical kind of call for
the real `sdb` storage backend).

## What was built

**`baseline/lib/backup_recurring.py`** (new) - orchestrates
`backup_restore.create_backup` and `config_crypto.encrypt_file`
directly, never reimplementing either. `run_encrypted_backup` backs up
one persona's real USER_PERSISTENCE mountpoint (or the legacy singular
one, `persona=None`), encrypts the resulting archive, and deletes the
plaintext copy immediately - proven directly in tests (a real
`remove()` call, not just an absent write). `is_due` reuses
`backup_restore.has_recent_successful_backup` directly as the
"did this already run recently enough" signal instead of inventing a
second, separate last-run tracker - one real record of truth, shared
with `restore_backup`'s own freshness gate. `run_if_due` is the real
entry point: skips all real work (never even touches the password
file) when the last successful backup is still within the configured
interval (`DEFAULT_INTERVAL_HOURS = 12` - half of
`backup_restore.DEFAULT_MAX_BACKUP_AGE_S`'s 24h window, so a single
missed run still leaves the freshness gate satisfied). `main` attempts
one persona at a time and reports each outcome, matching
`persist_bind_mounts.main`'s own pattern.

**A related, real gap found and fixed while building this**:
`backup_restore.restore_backup`'s own freshness gate always checked
the legacy singular `USER_PERSISTENCE_TARGET` manifest, regardless of
which persona's data the restore actually concerns - a real blind spot
now that personas are real (decision record 76) and persona-scoped
manifests exist (this job records one per persona's own mountpoint).
Added an optional `persistence_targets` parameter (defaults to
`[USER_PERSISTENCE_TARGET]` - byte-identical to the pre-existing
behavior for every caller that doesn't pass it) so a caller restoring
a real persona's archive can point the freshness check at that
persona's own manifest instead of one it was never recorded under.

**New systemd units**: `baseline-backup-recurring.service` (oneshot,
`Requires=`/`After=baseline-persist-bind-mounts.service` - backing up
an unmounted persistence volume would be silently backing up nothing,
or writing straight through to the disposable substrate) and
`baseline-backup-recurring.timer` (hourly check via `OnUnitActiveSec=1h`
- deliberately more frequent than the 12h actual-backup interval,
since `is_due` makes checking cheap and this decouples "how often we
check" from "how often it should actually run," matching decision
record 72's own established cadence philosophy). New bin script
`baseline/bin/baseline-backup-recurring` - refuses outright (exit 1,
no silent skip) if `BASELINE_BACKUP_PASSWORD_FILE` isn't configured,
attempts one real backup per `drive_installer.DEFAULT_PERSONAS`.
Staged in `provision.sh` (lib, bin+chmod, both units, both verification
lists, and enabled at the end alongside the other seven units - now
eight).

## What this does not do

Does not target a genuinely separate physical device - the real,
still-open gap, explicitly not hidden. Does not decide encryption-key
management/rotation - `BASELINE_BACKUP_PASSWORD_FILE` must already
exist as a private file before this unit can do anything, matching
`config_crypto.py`'s own "password never touches an argv or a log
line" discipline; how that file itself gets provisioned is a separate,
future concern. Does not run against real hardware.

## Verification performed

- `backup_recurring.py`: 15 tests (filename generation for both
  personas and the legacy default; `is_due` true/false at the interval
  boundary and per-persona isolation; a real backup+encrypt+delete
  round trip with the plaintext deletion proven directly via a
  Runner-level spy, not inferred; a real tar failure never reaching
  encryption; a real encryption failure reported correctly;
  `run_if_due`'s skip-vs-run branches; `main`'s per-persona attempt
  loop and its exit-code aggregation).
- `backup_restore.py`: 3 new tests for the `persistence_targets`
  parameter (a persona-scoped manifest satisfies it, an unrelated
  manifest doesn't, and omitting it reproduces the pre-existing
  legacy-target behavior byte-for-byte) - all 32 pre-existing tests
  pass unchanged.
- `tools/check_provision_deploys_all_imports.py`: zero gaps.
- `bash -n boot/provision.sh`: valid syntax.
- Full suite: 1176/1176 passing, no regressions.
