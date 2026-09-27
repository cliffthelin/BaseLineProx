"""Redirects Baseline's own control-plane paths - credentials, state,
logs - onto the persistent USER_PERSISTENCE partition instead of the
disposable substrate, per direct instruction ("All user data including
credentials and config and logs should go to the User Persistence
partition"). Every existing Baseline module keeps using the same
absolute paths (/etc/baseline, /var/lib/baseline, /var/log/baseline)
unchanged - the redirection happens at the mount layer via bind
mounts, not by editing every module's hardcoded path.

Idempotent and safe to run on every boot / every provision.sh
invocation: never overwrites existing persisted content, migrates
pre-existing substrate content into the persistence partition exactly
once (only on first run, when the persistence side is still empty),
and never duplicates an /etc/fstab entry. `ensure_redirect` itself
refuses to touch its target path at all if the persistence partition
isn't mounted first - not just `ensure_all_redirects`'s own sequencing
- a redirect onto an unmounted mountpoint would silently write straight
through to the disposable substrate instead, exactly the bug this
module exists to prevent; the guarantee holds by construction, on
whichever function a future caller actually calls.

Not yet run against real hardware - see decision record 62.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from repair import RealRunner, Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError

        def makedirs(self, path):
            raise NotImplementedError

        def read_text(self, path):
            raise NotImplementedError

        def append_text(self, path, content):
            raise NotImplementedError

        def listdir(self, path):
            raise NotImplementedError

    RealRunner = Runner


PERSISTENCE_LABEL = "USER_PERSISTENCE"
# Must match drive_installer.BASELINE_VOLUMES' own real mountpoint for
# this label exactly - a real, previously-undetected mismatch (this
# was "/mnt/user-persistence", lowercase) meant the same ext4-labeled
# filesystem could end up mounted read-write at two different paths by
# two different modules, a real corruption/lost-write risk, not a
# cosmetic one (decision record 69).
MOUNT_POINT = "/mnt/USER_PERSISTENCE"
FSTAB_PATH = "/etc/fstab"

# absolute path -> subdirectory name on the persistence partition
REDIRECT_PATHS = {
    "/etc/baseline": "etc-baseline",
    "/var/lib/baseline": "var-lib-baseline",
    "/var/log/baseline": "var-log-baseline",
}


@dataclass
class ApplyResult:
    applied: bool
    detail: str


def persistence_mount_fstab_line() -> str:
    return f"LABEL={PERSISTENCE_LABEL} {MOUNT_POINT} ext4 defaults 0 2\n"


def bind_fstab_line(target_path: str, subdir: str) -> str:
    return f"{MOUNT_POINT}/{subdir} {target_path} none bind 0 0\n"


def is_mounted(runner: Runner, path: str) -> bool:
    """Real kernel-reported state via /proc/self/mounts - never
    inferred from fstab content alone (fstab can list a mount that
    hasn't actually been applied yet, e.g. right after this module
    itself appends an entry but before the next boot)."""
    try:
        content = runner.read_text("/proc/self/mounts")
    except Exception:
        return False
    for line in content.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == path:
            return True
    return False


def _fstab_has_line(runner: Runner, line: str) -> bool:
    try:
        content = runner.read_text(FSTAB_PATH)
    except Exception:
        return False
    return line.strip() in {existing.strip() for existing in content.splitlines()}


def discover_persistence_device(runner: Runner) -> str | None:
    """Real discovery via blkid - does a USER_PERSISTENCE-labeled
    device exist anywhere among currently attached block devices,
    even if mount-by-label just failed (e.g. not yet settled, or a
    stale mount elsewhere)? Returns the real device path, or None if
    genuinely not found anywhere. Checked before any local fallback
    creation, so a real existing volume is never duplicated - the
    exact "same label, two different real volumes" risk decision
    record 69 already found once."""
    proc = runner.run(["blkid", "-L", PERSISTENCE_LABEL], timeout=10)
    if proc.returncode != 0:
        return None
    device = proc.stdout.strip()
    return device or None


def _local_fallback_size_gb(runner: Runner, vg_name: str) -> int:
    import drive_installer as di
    free_proc = runner.run(di.vg_free_bytes_argv(vg_name), timeout=15)
    if free_proc.returncode != 0:
        return 0
    free_bytes = di.parse_vg_free_bytes(free_proc.stdout)
    if free_bytes is None:
        return 0
    return di.adaptive_single_size_gb(free_bytes, 300)


def ensure_persistence_mounted(runner: Runner, *, vg_name: str = "pve") -> ApplyResult:
    """Mounts USER_PERSISTENCE at MOUNT_POINT if not already active,
    and ensures a durable fstab entry exists so this survives reboot
    without depending on this function running again.

    A missing external USER_PERSISTENCE is "the most important aspect
    to resolve" (direct instruction) - it is never simply refused.
    Real discovery first (blkid, not just one mount-by-label attempt):
    if a labeled device exists anywhere, mount it directly rather than
    duplicating it. Only when nothing is found anywhere does this
    self-install a real, adaptively-sized local logical volume - "the
    drives are self installing systems," a second dedicated
    persistence drive is an optional upgrade, never a hard
    requirement (decision record 75)."""
    if not is_mounted(runner, MOUNT_POINT):
        runner.makedirs(MOUNT_POINT)
        proc = runner.run(["mount", f"LABEL={PERSISTENCE_LABEL}", MOUNT_POINT], timeout=30)
        if proc.returncode != 0:
            label_mount_error = proc.stderr.strip()[:300]
            device = discover_persistence_device(runner)
            if device is not None:
                direct_proc = runner.run(["mount", device, MOUNT_POINT], timeout=30)
                if direct_proc.returncode != 0:
                    return ApplyResult(
                        False, f"found {PERSISTENCE_LABEL} at {device} but direct mount failed: "
                               f"{direct_proc.stderr.strip()[:300]}")
            else:
                import drive_installer as di
                local_size_gb = _local_fallback_size_gb(runner, vg_name)
                if local_size_gb <= 0:
                    return ApplyResult(
                        False, f"no {PERSISTENCE_LABEL} device found anywhere (label mount: "
                               f"{label_mount_error}) and no real local free space to self-install one")
                local_result = di.ensure_volume(
                    runner, vg_name=vg_name, lv_name="baseline_user_persistence_local",
                    size=f"{local_size_gb}G", label=PERSISTENCE_LABEL, mountpoint=MOUNT_POINT,
                )
                if not local_result.ok:
                    return ApplyResult(
                        False, f"no {PERSISTENCE_LABEL} device found anywhere and local self-install "
                               f"failed: {local_result.detail}")

    line = persistence_mount_fstab_line()
    if not _fstab_has_line(runner, line):
        runner.append_text(FSTAB_PATH, line)

    return ApplyResult(True, f"{PERSISTENCE_LABEL} mounted at {MOUNT_POINT}")


def ensure_redirect(runner: Runner, target_path: str, subdir: str) -> ApplyResult:
    """Idempotent bind-mount setup for one redirected path.

    First run (the persistence-side subdirectory doesn't exist yet):
    creates it, and if `target_path` already has real content (a
    pre-existing substrate install), migrates that content into the
    persistence subdirectory before bind-mounting - never silently
    discarded, matching this project's "never destroy data the
    operator didn't explicitly ask to lose" instinct.

    Every subsequent run: only ensures the bind mount is active and
    the fstab entry durable - never re-migrates, never duplicates.

    Refuses outright if MOUNT_POINT isn't actually mounted, regardless
    of caller - `ensure_all_redirects` already sequences this
    correctly, but the guarantee has to hold inside this function
    itself too, or a future direct call could silently create the
    persistence-side directory on the disposable substrate (since
    nothing is really mounted at MOUNT_POINT) and bind onto that -
    exactly the write-through-to-the-substrate bug this module exists
    to prevent."""
    if not is_mounted(runner, MOUNT_POINT):
        return ApplyResult(False, f"{MOUNT_POINT} is not mounted - refusing to touch {target_path}")

    persistence_side = f"{MOUNT_POINT}/{subdir}"

    if not runner.path_exists(persistence_side):
        runner.makedirs(persistence_side)
        if runner.path_exists(target_path):
            for entry in runner.listdir(target_path):
                runner.run(["mv", str(entry), persistence_side + "/"], timeout=30)

    if not runner.path_exists(target_path):
        runner.makedirs(target_path)

    if not is_mounted(runner, target_path):
        proc = runner.run(["mount", "--bind", persistence_side, target_path], timeout=15)
        if proc.returncode != 0:
            return ApplyResult(False, f"bind mount {target_path} failed: {proc.stderr.strip()[:300]}")

    line = bind_fstab_line(target_path, subdir)
    if not _fstab_has_line(runner, line):
        runner.append_text(FSTAB_PATH, line)

    return ApplyResult(True, f"{target_path} bind-mounted to {persistence_side}")


def ensure_all_redirects(runner: Runner) -> list[ApplyResult]:
    """Runs `ensure_persistence_mounted` first - everything else
    depends on it - then `ensure_redirect` for each of REDIRECT_PATHS.
    Stops and returns early if the persistence mount itself fails."""
    results = [ensure_persistence_mounted(runner)]
    if not results[0].applied:
        return results
    for target_path, subdir in REDIRECT_PATHS.items():
        results.append(ensure_redirect(runner, target_path, subdir))
    return results


def main(runner: Runner = None, print_fn=print) -> int:
    """Real entry point, matching this project's own boot-invoked
    scripts (e.g. repair_additive_persist.main()): print each result,
    exit 0 only if every one of them actually applied."""
    if runner is None:
        runner = RealRunner()
    results = ensure_all_redirects(runner)
    for result in results:
        print_fn(f"[{'ok' if result.applied else 'FAILED'}] {result.detail}")
    return 0 if all(r.applied for r in results) else 1
