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
container paths) to include - `all_volume_targets()` is the "all"
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
import os
import re
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
USER_TARGET = "/mnt/USER"


@dataclass
class CommandResult:
    ok: bool
    detail: str


def backup_required(install_detection: dict) -> bool:
    return bool(install_detection.get("found_volumes"))


def all_volume_targets() -> list:
    import drive_installer
    return [mountpoint for _, _, _, _, mountpoint in drive_installer.BASELINE_VOLUMES]


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


def _restore_touches_user_volume(members: list = None) -> bool:
    """`None` (restore everything in the archive) conservatively
    counts as touching USER too - fails safe, not open by
    default."""
    if members is None:
        return True
    return any(m.startswith("USER") for m in members)


def restore_backup(runner: Runner, *, archive_path: str, dest_root: str = "/", members: list = None,
                    now: float = None, max_age_s: float = DEFAULT_MAX_BACKUP_AGE_S,
                    manifests_dir: str = DEFAULT_MANIFESTS_DIR,
                    volume_targets: list = None) -> CommandResult:
    """Extracts exactly what's asked for, verbatim - `members` (from
    list_backup_contents()) restores only those entries, matching
    create_backup()'s own selective shape; omitted, everything in the
    archive is restored. Ensures `dest_root` exists first - a real
    finding from an end-to-end smoke test: `tar -C dest` requires the
    directory to already exist and simply fails if it doesn't.

    Hard gate, not a caller-opt-in flag, per direct instruction:
    "never overwriting the user persistence unless there is valid
    proof of it being backed up successfully within 24 hours." Any
    restore that would touch USER (named in `members`, or
    an unconstrained restore-everything) refuses outright - tar is
    never even invoked - unless a real, recorded manifest proves a
    successful backup of USER within `max_age_s`. Omitting
    `now` also refuses, rather than silently skipping the check
    because a caller forgot a parameter.

    `volume_targets` (decision record 79): which manifest
    target(s) count as proof, checked as "any one is fresh enough."
    Defaults to `[USER_TARGET]` - the legacy singular
    target, byte-identical to this function's pre-existing behavior -
    so every existing caller is unaffected. A caller restoring a real
    persona's own archive passes that persona's own mountpoint(s)
    instead (e.g. via `persist_bind_mounts.user_mountpoint_for`),
    since a persona-scoped backup's manifest is never recorded under
    the legacy singular path."""
    if _restore_touches_user_volume(members):
        if now is None:
            return CommandResult(
                False, "refusing to restore into/over USER: `now` was not given, "
                       "so backup freshness cannot be verified")
        targets_to_check = volume_targets or [USER_TARGET]
        if not any(has_recent_successful_backup(runner, target=t, now=now,
                                                 max_age_s=max_age_s, manifests_dir=manifests_dir)
                   for t in targets_to_check):
            return CommandResult(
                False, f"refusing to restore into/over USER: no proof of a successful "
                       f"backup of {targets_to_check} within {max_age_s:g}s - back it up first")

    runner.run(["mkdir", "-p", dest_root], timeout=10)
    proc = runner.run(restore_backup_argv(archive_path, dest_root, members=members), timeout=600)
    if proc.returncode != 0:
        return CommandResult(False, f"tar extract failed: {proc.stderr.strip()}")
    return CommandResult(True, f"restored {archive_path} into {dest_root}")


# ---------------------------------------------------------------------------
# Request-boundary checks for the backup / restore / encrypt routes. A request used to name any destination
# and any source paths, and tar / gpg ran as root: a logged-in session could overwrite /etc/passwd with an
# archive or archive /root/.ssh somewhere readable. Now: a backup is written only as a NEW file in a known
# backup folder, reads only Baseline's own volumes and config, and a restore goes only to /mnt or a Baseline
# volume. Each check raises ValueError; callers turn that into a refusal before anything runs.
# ---------------------------------------------------------------------------

BACKUP_DIRS = ("/mnt/INSTALLER_CACHE/backups", "/mnt/INSTALLER_CACHE/encrypted_backups")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _clean_abs(path, what: str) -> str:
    if (not isinstance(path, str) or not path or "\x00" in path or "\n" in path or "\r" in path
            or not os.path.isabs(path) or os.path.normpath(path) != path):
        raise ValueError(f"{what} must be a clean absolute path")
    return path


def _in_backup_dir(path: str, what: str) -> None:
    parent, name = os.path.split(path)
    if parent not in BACKUP_DIRS or not _NAME_RE.match(name):
        raise ValueError(f"{what} must be a plain file name directly inside one of: {', '.join(BACKUP_DIRS)}")


def check_new_backup_file(runner, path, *, suffix: str, what: str = "destination") -> str:
    """A file Baseline may create: inside a backup folder, right extension, and it must not already exist."""
    path = _clean_abs(path, what)
    _in_backup_dir(path, what)
    name = os.path.basename(path)
    if not name.endswith(suffix) or name == suffix:
        raise ValueError(f"{what} must end in {suffix}")
    if runner.path_exists(path):
        raise ValueError(f"{path} already exists; a backup never overwrites an existing file")
    return path


def check_existing_backup_file(runner, path, *, what: str = "archive") -> str:
    path = _clean_abs(path, what)
    _in_backup_dir(path, what)
    if not runner.path_exists(path):
        raise ValueError(f"{path} was not found")
    return path


def _baseline_roots() -> list:
    import drive_installer
    return [mp for *_rest, mp in drive_installer.BASELINE_VOLUMES] + list(DEFAULT_CONFIG_PATHS) + ["/etc/baseline"]


def check_backup_sources(targets) -> list:
    if not isinstance(targets, list) or not targets or not all(isinstance(x, str) for x in targets):
        raise ValueError("targets must be a non-empty list of paths")
    roots = _baseline_roots()
    for target in targets:
        _clean_abs(target, "a backup source")
        if not any(target == root or target.startswith(root + "/") for root in roots):
            raise ValueError(f"{target} is not one of Baseline's own volumes or configuration")
    return list(targets)


def check_restore_root(path) -> str:
    import drive_installer
    path = _clean_abs(path, "restore destination")
    if path != "/mnt" and path not in [mp for *_rest, mp in drive_installer.BASELINE_VOLUMES]:
        raise ValueError("a restore can only go to /mnt or one of Baseline's own volumes")
    return path


def check_restore_members(members) -> list:
    if members in (None, []):
        return []
    if not isinstance(members, list) or not all(isinstance(m, str) and m for m in members):
        raise ValueError("members must be a list of archive entry names")
    for m in members:
        if m.startswith("/") or os.path.normpath(m) != m or ".." in m.split("/") or "\n" in m or m.startswith("-"):
            raise ValueError(f"unsafe archive entry name {m!r}")
    return list(members)
