"""Redirects Baseline's own control-plane paths - credentials, state,
logs - onto the persistent USER partition instead of the
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

**Persona-aware wiring (work-queue item 25, decision record 78).**
Every function above accepts an optional `persona` keyword now:
`persona=None` (the default everywhere) reproduces the exact prior
behavior byte-for-byte - the legacy singular `USER` label
at `/mnt/USER`, matching the real, already-deployed plain
partition layout on the actual `/dev/sdb` (decision record 46) - so no
existing caller or real deployment is affected. Passing a real
`persona` string (`"admin"`, `"personal"`, ...) switches to
`drive_installer.py`'s multi-persona label scheme
(`USER_<PERSONA>`), reusing its own naming functions
directly rather than re-deriving them here. Reconciling *which* scheme
the real `/dev/sdb` should actually use long-term is a separate,
still-open architecture item (flagged directly to the user, not part
of this change) - this module simply supports both without forcing a
premature choice between them.

New in this pass: `unmount_user_volume`/`unmount_redirect`/
`unmount_all_redirects` (the reverse of the `ensure_*` half - redirects
first, since they're bind-sourced from inside the persistence mount,
then the persistence volume itself), `get_active_persona`/
`set_active_persona` (a small marker file on the shared BASELINE
volume - survives a persona switch by construction, since BASELINE is
never persona-scoped), and `switch_active_persona` - the real
mechanism item 25 asked for: "switch active persona = unmount current,
authenticate, mount+rebind the newly-authenticated one." Authentication
itself is the caller's job (e.g. `settings_web.py`'s own login check) -
this function only ever proceeds when handed a `credential_ok=True` it
did not produce itself, never inferred or defaulted.
"""
from __future__ import annotations

import posixpath
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

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def append_text(self, path, content):
            raise NotImplementedError

        def listdir(self, path):
            raise NotImplementedError

    RealRunner = Runner


USER_LABEL = "USER"
# Must match drive_installer.BASELINE_VOLUMES' own real mountpoint for
# this label exactly - a real, previously-undetected mismatch (this
# was "/mnt/user-persistence", lowercase) meant the same ext4-labeled
# filesystem could end up mounted read-write at two different paths by
# two different modules, a real corruption/lost-write risk, not a
# cosmetic one (decision record 69).
MOUNT_POINT = "/mnt/USER"
FSTAB_PATH = "/etc/fstab"

# Default persona for the switch mechanism only (get_active_persona's
# fallback when no marker file exists yet) - matches drive_installer's
# own "default creator is admin" default (decision record 76). Not
# used by any legacy call (persona=None) below.
DEFAULT_PERSONA = "admin"
ACTIVE_PERSONA_MARKER_PATH = "/mnt/BASELINE/state/active_persona"


def user_label_for(persona: str | None = None) -> str:
    if persona is None:
        return USER_LABEL
    import drive_installer as di
    return di.persona_label(persona)


def user_mountpoint_for(persona: str | None = None) -> str:
    if persona is None:
        return MOUNT_POINT
    import drive_installer as di
    return di.persona_mountpoint(persona)

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


def user_mount_fstab_line(persona: str | None = None) -> str:
    label = user_label_for(persona)
    mountpoint = user_mountpoint_for(persona)
    return f"LABEL={label} {mountpoint} ext4 defaults 0 2\n"


def bind_fstab_line(target_path: str, subdir: str, persona: str | None = None) -> str:
    mountpoint = user_mountpoint_for(persona)
    return f"{mountpoint}/{subdir} {target_path} none bind 0 0\n"


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


def is_mounted_read_write(runner: Runner, path: str) -> bool:
    """Real kernel-reported mount *mode*, not just presence - a real
    corrupted volume can mount successfully but read-only, which
    `is_mounted` alone would call "mounted" while it is not actually
    usable. Checks the real comma-separated options field
    (/proc/self/mounts' 4th column) for the kernel's own authoritative
    `rw`/`ro` token - used by recovery_mode.py's hard exit condition
    (work-queue item 26)."""
    try:
        content = runner.read_text("/proc/self/mounts")
    except Exception:
        return False
    for line in content.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == path:
            options = parts[3].split(",")
            return "rw" in options
    return False


def _fstab_has_line(runner: Runner, line: str) -> bool:
    try:
        content = runner.read_text(FSTAB_PATH)
    except Exception:
        return False
    return line.strip() in {existing.strip() for existing in content.splitlines()}


def discover_persistence_device(runner: Runner, persona: str | None = None) -> str | None:
    """Real discovery via blkid - does a USER-labeled
    device exist anywhere among currently attached block devices,
    even if mount-by-label just failed (e.g. not yet settled, or a
    stale mount elsewhere)? Returns the real device path, or None if
    genuinely not found anywhere. Checked before any local fallback
    creation, so a real existing volume is never duplicated - the
    exact "same label, two different real volumes" risk decision
    record 69 already found once."""
    label = user_label_for(persona)
    proc = runner.run(["blkid", "-L", label], timeout=10)
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
    # Matches drive_installer.persona_volume's own real (min_gb, max_gb)
    # range (50-200, 2026-09-29 sizing defaults) - this is the same
    # USER volume, just self-installed locally instead of
    # on an external drive, so it gets the same real bounds.
    return di.adaptive_single_size_gb(free_bytes, 200, min_gb=50)


def ensure_user_volume_mounted(runner: Runner, *, persona: str | None = None, vg_name: str = "pve") -> ApplyResult:
    """Mounts USER at MOUNT_POINT if not already active,
    and ensures a durable fstab entry exists so this survives reboot
    without depending on this function running again.

    A missing external USER is "the most important aspect
    to resolve" (direct instruction) - it is never simply refused.
    Real discovery first (blkid, not just one mount-by-label attempt):
    if a labeled device exists anywhere, mount it directly rather than
    duplicating it. Only when nothing is found anywhere does this
    self-install a real, adaptively-sized local logical volume - "the
    drives are self installing systems," a second dedicated
    persistence drive is an optional upgrade, never a hard
    requirement (decision record 75).

    `persona=None` (default) uses the legacy singular label/mountpoint
    unchanged; a real persona name switches to the
    `USER_<PERSONA>` scheme (decision record 78)."""
    label = user_label_for(persona)
    mountpoint = user_mountpoint_for(persona)
    if not is_mounted(runner, mountpoint):
        runner.makedirs(mountpoint)
        proc = runner.run(["mount", f"LABEL={label}", mountpoint], timeout=30)
        if proc.returncode != 0:
            label_mount_error = proc.stderr.strip()[:300]
            device = discover_persistence_device(runner, persona)
            if device is not None:
                direct_proc = runner.run(["mount", device, mountpoint], timeout=30)
                if direct_proc.returncode != 0:
                    return ApplyResult(
                        False, f"found {label} at {device} but direct mount failed: "
                               f"{direct_proc.stderr.strip()[:300]}")
            else:
                import drive_installer as di
                local_size_gb = _local_fallback_size_gb(runner, vg_name)
                if local_size_gb <= 0:
                    return ApplyResult(
                        False, f"no {label} device found anywhere (label mount: "
                               f"{label_mount_error}) and no real local free space to self-install one")
                lv_name = di.persona_lv_name(persona) if persona is not None else "baseline_user_local"
                local_result = di.ensure_volume(
                    runner, vg_name=vg_name, lv_name=lv_name,
                    size=f"{local_size_gb}G", label=label, mountpoint=mountpoint,
                )
                if not local_result.ok:
                    return ApplyResult(
                        False, f"no {label} device found anywhere and local self-install "
                               f"failed: {local_result.detail}")

    line = user_mount_fstab_line(persona)
    if not _fstab_has_line(runner, line):
        runner.append_text(FSTAB_PATH, line)

    return ApplyResult(True, f"{label} mounted at {mountpoint}")


def unmount_user_volume(runner: Runner, *, persona: str | None = None) -> ApplyResult:
    """The reverse of `ensure_user_volume_mounted` - real `umount`,
    never assumed to succeed. A no-op success if already unmounted, so
    callers (e.g. `switch_active_persona`) can call it unconditionally."""
    mountpoint = user_mountpoint_for(persona)
    if not is_mounted(runner, mountpoint):
        return ApplyResult(True, f"{mountpoint} already not mounted")
    proc = runner.run(["umount", mountpoint], timeout=30)
    if proc.returncode != 0:
        return ApplyResult(False, f"umount {mountpoint} failed: {proc.stderr.strip()[:300]}")
    return ApplyResult(True, f"{mountpoint} unmounted")


def ensure_redirect(runner: Runner, target_path: str, subdir: str, *, persona: str | None = None) -> ApplyResult:
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
    mountpoint = user_mountpoint_for(persona)
    if not is_mounted(runner, mountpoint):
        return ApplyResult(False, f"{mountpoint} is not mounted - refusing to touch {target_path}")

    persistence_side = f"{mountpoint}/{subdir}"

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

    line = bind_fstab_line(target_path, subdir, persona)
    if not _fstab_has_line(runner, line):
        runner.append_text(FSTAB_PATH, line)

    return ApplyResult(True, f"{target_path} bind-mounted to {persistence_side}")


def unmount_redirect(runner: Runner, target_path: str) -> ApplyResult:
    """The reverse of `ensure_redirect` for one target path - real
    `umount` of the bind mount only, the persistence-side subdirectory
    and its content are never touched. A no-op success if not
    currently bound, so callers can call it unconditionally."""
    if not is_mounted(runner, target_path):
        return ApplyResult(True, f"{target_path} already not bind-mounted")
    proc = runner.run(["umount", target_path], timeout=15)
    if proc.returncode != 0:
        return ApplyResult(False, f"umount {target_path} failed: {proc.stderr.strip()[:300]}")
    return ApplyResult(True, f"{target_path} unbound")


def ensure_all_redirects(runner: Runner, *, persona: str | None = None) -> list[ApplyResult]:
    """Runs `ensure_user_volume_mounted` first - everything else
    depends on it - then `ensure_redirect` for each of REDIRECT_PATHS.
    Stops and returns early if the persistence mount itself fails."""
    results = [ensure_user_volume_mounted(runner, persona=persona)]
    if not results[0].applied:
        return results
    for target_path, subdir in REDIRECT_PATHS.items():
        results.append(ensure_redirect(runner, target_path, subdir, persona=persona))
    return results


def unmount_all_redirects(runner: Runner, *, persona: str | None = None) -> list[ApplyResult]:
    """The reverse of `ensure_all_redirects`, in the correct reverse
    order: every redirect is unbound first (each is bind-sourced from
    inside the persistence mount - unmounting the persistence volume
    first would leave them dangling, bound to nothing real), then the
    persistence volume itself."""
    results = [unmount_redirect(runner, target_path) for target_path in REDIRECT_PATHS]
    results.append(unmount_user_volume(runner, persona=persona))
    return results


def get_active_persona(runner: Runner, *, default: str = DEFAULT_PERSONA) -> str:
    """Reads the real, durable marker of which persona is currently
    the active one - lives on the shared BASELINE volume (never
    persona-scoped by construction), so it survives every switch.
    Falls back to `default` only when no marker has ever been written
    yet (a fresh install, or a caller that has never called
    `switch_active_persona`)."""
    if not runner.path_exists(ACTIVE_PERSONA_MARKER_PATH):
        return default
    content = runner.read_text(ACTIVE_PERSONA_MARKER_PATH).strip()
    return content or default


def set_active_persona(runner: Runner, persona: str) -> None:
    runner.makedirs(posixpath.dirname(ACTIVE_PERSONA_MARKER_PATH))
    runner.write_text_atomic(ACTIVE_PERSONA_MARKER_PATH, persona)


def switch_active_persona(runner: Runner, *, to_persona: str, credential_ok: bool,
                           vg_name: str = "pve") -> ApplyResult:
    """The real active-persona switch mechanism work-queue item 25
    asked for: "switch active persona = unmount current, authenticate,
    mount+rebind the newly-authenticated one."

    Authentication is deliberately the caller's own job (e.g.
    `settings_web.py`'s real login check against a persona's stored
    credential) - this function only ever proceeds when handed a
    `credential_ok=True` it did not produce itself. This mirrors
    `recovery_tiers.py`'s own discipline of never inferring a
    credential axis - a caller that skips the real check and passes
    `True` anyway owns that mistake; this function cannot detect it,
    only refuse to default to it.

    Switching to the persona that is already active is a safe,
    idempotent no-op (re-ensures the mount/redirects are actually up,
    matching every other `ensure_*` function's own idempotence) rather
    than an unnecessary unmount/remount cycle."""
    if not credential_ok:
        return ApplyResult(False, f"refusing to switch to persona {to_persona!r}: no proven persistence credential")

    from_persona = get_active_persona(runner)
    if from_persona == to_persona:
        results = ensure_all_redirects(runner, persona=to_persona)
        set_active_persona(runner, to_persona)
        failed = [r for r in results if not r.applied]
        if failed:
            return ApplyResult(False, f"persona {to_persona!r} already active but re-ensure failed: {failed[0].detail}")
        return ApplyResult(True, f"persona {to_persona!r} already active")

    unmount_results = unmount_all_redirects(runner, persona=from_persona)
    failed = [r for r in unmount_results if not r.applied]
    if failed:
        return ApplyResult(False, f"failed to cleanly unmount persona {from_persona!r}: {failed[0].detail}")

    mount_results = ensure_all_redirects(runner, persona=to_persona)
    failed = [r for r in mount_results if not r.applied]
    if failed:
        return ApplyResult(False, f"failed to mount persona {to_persona!r}: {failed[0].detail}")

    set_active_persona(runner, to_persona)
    return ApplyResult(True, f"switched active persona from {from_persona!r} to {to_persona!r}")


def main(runner: Runner = None, print_fn=print, now: float = None) -> int:
    """Real entry point, matching this project's own boot-invoked
    scripts (e.g. repair_additive_persist.main()): print each result,
    exit 0 only if every one of them actually applied.

    Work-queue item 26's real automatic recovery-mode entry point: when
    this cascade genuinely fails (never on a mere slow start - only
    the real, exhausted-fallback failure `ensure_all_redirects` itself
    already reports), records a durable recovery-mode entry via
    `recovery_mode.record_entry` before returning - the fact of
    needing recovery is captured the moment it actually happens, not
    left for some later poller to notice."""
    if runner is None:
        runner = RealRunner()
    if now is None:
        import time
        now = time.time()
    results = ensure_all_redirects(runner)
    for result in results:
        print_fn(f"[{'ok' if result.applied else 'FAILED'}] {result.detail}")
    ok = all(r.applied for r in results)
    if not ok:
        import recovery_mode
        recovery_mode.record_entry(runner, now=now, reason="cascade_failed")

    # Decision record 88, direct instruction: health validations "at
    # boot" - purely observational. A dependency check failing here
    # (even a LOUD one) never changes this function's own return code:
    # gating boot itself on a health check would trade a real, working
    # mount cascade for a new way to fail to boot, which is a worse
    # outcome than a degraded-but-running machine that a later
    # troubleshooting pass can actually see the failure on.
    try:
        import dependencies as dep
        for r in dep.run_checks(phase=dep.BOOT):
            print_fn(f"[dep-{'ok' if r.ok else 'FAIL'}] {r.id}: {r.detail}")
    except Exception as exc:  # noqa: BLE001 - health reporting must never block or crash boot
        print_fn(f"[dep-FAIL] dependency checks themselves could not run: {exc!r}")

    return 0 if ok else 1
