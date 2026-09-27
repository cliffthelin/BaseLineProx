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

from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


DEFAULT_CONFIG_PATHS = ("/etc/baseline/install-config.json", "/etc/smartd.conf")


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


def create_backup(runner: Runner, *, dest_path: str, targets: list = None, config_only: bool = False) -> CommandResult:
    """`config_only` ignores any `targets` passed alongside it and
    backs up only the real config file(s) this project writes - never
    persistence data. Refuses (no real tar call made) if neither a
    real target list nor config_only was given."""
    if config_only:
        targets = list(DEFAULT_CONFIG_PATHS)
    if not targets:
        return CommandResult(False, "no targets given to back up")
    proc = runner.run(create_backup_argv(dest_path, targets), timeout=600)
    if proc.returncode != 0:
        return CommandResult(False, f"tar failed: {proc.stderr.strip()}")
    return CommandResult(True, f"backed up {len(targets)} target(s) to {dest_path}")


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


def restore_backup(runner: Runner, *, archive_path: str, dest_root: str = "/", members: list = None) -> CommandResult:
    """Extracts exactly what's asked for, verbatim - `members` (from
    list_backup_contents()) restores only those entries, matching
    create_backup()'s own selective shape; omitted, everything in the
    archive is restored. Ensures `dest_root` exists first - a real
    finding from an end-to-end smoke test: `tar -C dest` requires the
    directory to already exist and simply fails if it doesn't."""
    runner.run(["mkdir", "-p", dest_root], timeout=10)
    proc = runner.run(restore_backup_argv(archive_path, dest_root, members=members), timeout=600)
    if proc.returncode != 0:
        return CommandResult(False, f"tar extract failed: {proc.stderr.strip()}")
    return CommandResult(True, f"restored {archive_path} into {dest_root}")
