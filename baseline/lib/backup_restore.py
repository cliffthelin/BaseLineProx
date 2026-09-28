"""Real backup/restore for the persistence volumes and/or the exported
config - tar-based, deliberately: `tar` is POSIX-standard, present on
every real Linux distribution (a bare Debian/Proxmox install included)
with zero extra package installs, and readable by virtually anything -
the real meaning of "battle tested... regardless of what OS."

Direct instruction: "if the targeted drive is detected to have a
Baseline build even with install option is should request to make a
backup of the being replaced persistence partitions / containers and
wired in to successful be able to do so." `backup_required()` is the
real gate this wires to: True whenever
`drive_installer.detect_existing_baseline_install()` found ANY of the
three volumes already present - a partial existing install still has
real data worth protecting, not just a fully-provisioned one.

Selective by design, matching "Backup can be selected to backup only
selected partition / containers or all and can be selected to only
back config": `targets` names exactly which real mountpoints (or
container paths) to include - `all_persistence_targets()` is the "all"
convenience, a caller-built subset is the "only selected" case, and
`config_only=True` switches to backing up only the real config file(s)
this project writes, ignoring any `targets` passed alongside it.
"Restore options should align in the same way": `restore_backup()`
takes the same selective-`members` shape tar itself supports.

**Restore never decrypts anything, structurally, not just by
convention** - this module has no dependency on and no awareness of
`config_crypto.py` at all (proven directly by
`test_restore_never_invokes_any_decryption_mechanism`). A config file
that was encrypted before backup comes back out of the archive exactly
as encrypted as it went in; decrypting it is always a separate,
explicit, password-gated step. Backup/restore can never be used to
bypass an encryption or password someone set up.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError

        def read_text(self, path):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def makedirs(self, path):
            raise NotImplementedError


DEFAULT_CONFIG_PATHS = ("/etc/baseline/install-config.json", "/etc/smartd.conf")

# Real, durable proof a backup succeeded - lives on INSTALLER_CACHE so
# it survives a reinstall of the disposable stage, matching this
# project's own persistence philosophy (decision record 68).
DEFAULT_MANIFESTS_DIR = "/mnt/INSTALLER_CACHE/backup_manifests"
DEFAULT_MAX_BACKUP_AGE_S = 24 * 60 * 60
USER_PERSISTENCE_TARGET = "/mnt/USER_PERSISTENCE"


@dataclass
class CommandResult:
    ok: bool
    detail: str


def backup_required(install_detection: dict) -> bool:
    return bool(install_detection.get("found_volumes"))


def all_persistence_targets() -> list:
    import drive_installer
    return [mountpoint for _, _, _, mountpoint in drive_installer.BASELINE_VOLUMES]


def create_backup_argv(dest_path: str, targets: list) -> list:
    return ["tar", "-czf", dest_path] + list(targets)


def create_backup(runner: Runner, *, dest_path: str, targets: list = None, config_only: bool = False,
                   now: float = None, manifests_dir: str = DEFAULT_MANIFESTS_DIR) -> CommandResult:
    """`config_only` ignores any `targets` passed alongside it and
    backs up only the real config file(s) this project writes - never
    persistence data. Refuses (no real tar call made) if neither a
    real target list nor config_only was given.

    When `now` is given and the real tar call succeeds, records a real
    backup-success manifest for every target - the durable proof
    `has_recent_successful_backup`/`restore_backup`'s own hard gate
    checks. Omitting `now` records nothing (unchanged, pre-existing
    behavior for a caller that doesn't care about freshness proof)."""
    if config_only:
        targets = list(DEFAULT_CONFIG_PATHS)
    if not targets:
        return CommandResult(False, "no targets given to back up")
    proc = runner.run(create_backup_argv(dest_path, targets), timeout=600)
    if proc.returncode != 0:
        return CommandResult(False, f"tar failed: {proc.stderr.strip()}")
    if now is not None:
        for target in targets:
            record_backup_manifest(runner, target=target, ts=now, manifests_dir=manifests_dir)
    return CommandResult(True, f"backed up {len(targets)} target(s) to {dest_path}")


def manifest_path_for(target: str, manifests_dir: str = DEFAULT_MANIFESTS_DIR) -> str:
    safe_name = target.strip("/").replace("/", "_") or "root"
    return f"{manifests_dir}/{safe_name}.json"


def record_backup_manifest(runner: Runner, *, target: str, ts: float,
                            manifests_dir: str = DEFAULT_MANIFESTS_DIR) -> None:
    """Real, durable proof a backup of `target` succeeded at `ts`.
    Called only after the real tar call already reported success -
    never records a manifest for a backup that didn't actually
    happen."""
    runner.makedirs(manifests_dir)
    path = manifest_path_for(target, manifests_dir)
    runner.write_text_atomic(path, json.dumps({"target": target, "ts": ts}))


def read_backup_manifest(runner: Runner, *, target: str, manifests_dir: str = DEFAULT_MANIFESTS_DIR):
    path = manifest_path_for(target, manifests_dir)
    if not runner.path_exists(path):
        return None
    try:
        return json.loads(runner.read_text(path))
    except ValueError:
        return None


def has_recent_successful_backup(runner: Runner, *, target: str, now: float,
                                  max_age_s: float = DEFAULT_MAX_BACKUP_AGE_S,
                                  manifests_dir: str = DEFAULT_MANIFESTS_DIR) -> bool:
    manifest = read_backup_manifest(runner, target=target, manifests_dir=manifests_dir)
    if manifest is None or manifest.get("target") != target:
        return False
    ts = manifest.get("ts")
    if not isinstance(ts, (int, float)):
        return False
    return 0 <= (now - ts) <= max_age_s


def list_backup_contents_argv(archive_path: str) -> list:
    return ["tar", "-tzf", archive_path]


def list_backup_contents(runner: Runner, archive_path: str) -> list:
    """Real listing, for a selective-restore preview - an unreadable
    archive reads back as an empty list, never raises."""
    proc = runner.run(list_backup_contents_argv(archive_path), timeout=60)
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line]


def restore_backup_argv(archive_path: str, dest_root: str, *, members: list = None) -> list:
    argv = ["tar", "-xzf", archive_path, "-C", dest_root]
    if members:
        argv += list(members)
    return argv


def _restore_touches_user_persistence(members: list = None) -> bool:
    """`None` (restore everything in the archive) conservatively
    counts as touching USER_PERSISTENCE too - fails safe, not open by
    default."""
    if members is None:
        return True
    return any(m.startswith("USER_PERSISTENCE") for m in members)


def restore_backup(runner: Runner, *, archive_path: str, dest_root: str = "/", members: list = None,
                    now: float = None, max_age_s: float = DEFAULT_MAX_BACKUP_AGE_S,
                    manifests_dir: str = DEFAULT_MANIFESTS_DIR,
                    persistence_targets: list = None) -> CommandResult:
    """Extracts exactly what's asked for, verbatim - `members` (from
    list_backup_contents()) restores only those entries, matching
    create_backup()'s own selective shape; omitted, everything in the
    archive is restored. Ensures `dest_root` exists first - a real
    finding from an end-to-end smoke test: `tar -C dest` requires the
    directory to already exist and simply fails if it doesn't.

    Hard gate, not a caller-opt-in flag, per direct instruction:
    "never overwriting the user persistence unless there is valid
    proof of it being backed up successfully within 24 hours." Any
    restore that would touch USER_PERSISTENCE (named in `members`, or
    an unconstrained restore-everything) refuses outright - tar is
    never even invoked - unless a real, recorded manifest proves a
    successful backup of USER_PERSISTENCE within `max_age_s`. Omitting
    `now` also refuses, rather than silently skipping the check
    because a caller forgot a parameter.

    `persistence_targets` (decision record 79): which manifest
    target(s) count as proof, checked as "any one is fresh enough."
    Defaults to `[USER_PERSISTENCE_TARGET]` - the legacy singular
    target, byte-identical to this function's pre-existing behavior -
    so every existing caller is unaffected. A caller restoring a real
    persona's own archive passes that persona's own mountpoint(s)
    instead (e.g. via `persist_bind_mounts.persistence_mountpoint_for`),
    since a persona-scoped backup's manifest is never recorded under
    the legacy singular path."""
    if _restore_touches_user_persistence(members):
        if now is None:
            return CommandResult(
                False, "refusing to restore into/over USER_PERSISTENCE: `now` was not given, "
                       "so backup freshness cannot be verified")
        targets_to_check = persistence_targets or [USER_PERSISTENCE_TARGET]
        if not any(has_recent_successful_backup(runner, target=t, now=now,
                                                 max_age_s=max_age_s, manifests_dir=manifests_dir)
                   for t in targets_to_check):
            return CommandResult(
                False, f"refusing to restore into/over USER_PERSISTENCE: no proof of a successful "
                       f"backup of {targets_to_check} within {max_age_s:g}s - back it up first")

    runner.run(["mkdir", "-p", dest_root], timeout=10)
    proc = runner.run(restore_backup_argv(archive_path, dest_root, members=members), timeout=600)
    if proc.returncode != 0:
        return CommandResult(False, f"tar extract failed: {proc.stderr.strip()}")
    return CommandResult(True, f"restored {archive_path} into {dest_root}")
