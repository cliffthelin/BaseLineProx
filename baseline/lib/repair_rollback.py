#!/usr/bin/env python3
"""Standalone rollback executor for the host-network repair action.

Deliberately independent of the main Baseline process: this is what the
transient systemd rollback timer actually calls
(`/opt/baseline/bin/baseline-repair-rollback same-boot <attempt-id>`), so it
has to work correctly even if Baseline's TUI, its repair worker, or the
whole `baseline` process is dead or was never running this boot. It imports
`repair.py` and `network.py` only - neither pulls in Textual/Rich, so this
stays a small, fast, dependency-light script.

Two entry points:

- `same_boot_rollback(attempt_id)` - what the transient timer calls. Covers
  the required cases explicitly named in review: Baseline crashing, the
  repair worker hanging, or the TUI being killed after a repair was
  applied.

- `boot_time_recovery()` - the logic for the *permanent, dormant* recovery
  service Cliff's plan calls for, which would additionally cover a reboot
  during the rollback window. Implemented here as pure, tested logic
  (reads the pending manifest, restores if one exists, records the
  interrupted attempt, clears pending state, always exits 0 so it can
  never itself block boot) - but **the systemd unit that would run this at
  boot is not installed by this change.** Cliff's own review made
  installing it conditional on proving where in the real Proxmox/Debian
  boot sequence it's safe to run (after the filesystem holding the backup
  is available, before `networking.service`/the ifupdown2 startup path
  consumes the candidate config). This session has no real Proxmox/Debian
  host or package archive reachable to verify that ordering against (see
  the implementation reply this shipped with), so per Cliff's explicit
  instruction - "if that ordering cannot be proven safely, refuse to
  implement reboot recovery speculatively" - no `.service`/`.timer` unit
  file is created or wired into `boot/provision.sh` for this function.
  `boot_time_recovery()` is ready to be called by such a unit once the
  ordering is confirmed against a real host (the disposable-VM integration
  test Cliff already required is the natural place to confirm it).
  Until then, reboot-during-the-120s-window is the one named failure mode
  this slice does not yet cover; every other required case (crash, hang,
  kill) is covered by the transient timer today.
"""
import sys

import repair
import network


def same_boot_rollback(attempt_id: str, runner: repair.Runner = None) -> int:
    runner = runner or repair.RealRunner()
    restored, detail = repair.restore_backup(runner, attempt_id)
    repair.log_event(runner, attempt_id, "rolled_back", "pass" if restored else "fail", detail,
                      config_restoration_confirmed=restored)
    if not restored:
        repair.log_event(runner, attempt_id, "rollback_failed", "fail", detail)
        # Escalate loudly rather than staying quiet, per plan - a failed
        # restore is the one outcome that must surface directly.
        return 2

    reload_res = runner.run(["ifreload", "-a"], timeout=30)
    if reload_res.returncode != 0:
        repair.log_event(runner, attempt_id, "rollback_failed", "fail",
                          f"restore wrote back cleanly but ifreload -a failed: {reload_res.stderr.strip()}")
        return 2

    manifest = repair.read_pending_manifest(runner)
    target = manifest.get("target_interface") if manifest else None
    connectivity_restored = None
    if target:
        verification = repair.verify_target(runner, target, stabilize=False)
        connectivity_restored = verification.ok
        # Per plan: the original config may itself have been unreachable -
        # rollback success is judged on config-restoration, not this.
        repair.log_event(runner, attempt_id, "rollback_confirmed", "info",
                          f"config restored; connectivity_restored={connectivity_restored}",
                          config_restoration_confirmed=True,
                          connectivity_restored=connectivity_restored)
    else:
        repair.log_event(runner, attempt_id, "rollback_confirmed", "info", "config restored",
                          config_restoration_confirmed=True)

    repair.clear_pending_manifest(runner)
    repair.close_attempt(runner, attempt_id, "rolled_back")
    return 0


def boot_time_recovery(runner: repair.Runner = None) -> int:
    """See module docstring: implemented, not yet wired to an installed
    systemd unit. Idempotent and always returns 0 - a boot-time recovery
    path must never itself become a reason boot doesn't proceed."""
    runner = runner or repair.RealRunner()
    manifest = repair.read_pending_manifest(runner)
    if manifest is None:
        return 0  # nothing pending - the common case on every normal boot
    attempt_id = manifest["attempt_id"]
    repair.log_event(runner, attempt_id, "boot_recovery_triggered", "info",
                      "pending manifest found at boot - a repair attempt was interrupted before completing")
    rc = same_boot_rollback(attempt_id, runner=runner)
    if rc != 0:
        repair.log_event(runner, attempt_id, "boot_recovery_failed", "fail",
                          "boot-time restore did not complete cleanly - manual review needed")
    return 0


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: baseline-repair-rollback {same-boot <attempt-id> | boot-recovery}", file=sys.stderr)
        return 64
    if argv[0] == "same-boot" and len(argv) == 2:
        return same_boot_rollback(argv[1])
    if argv[0] == "boot-recovery":
        return boot_time_recovery()
    print(f"unrecognized invocation: {argv!r}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main())
