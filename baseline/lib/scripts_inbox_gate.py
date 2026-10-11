"""ExecStartPre gate for baseline-scripts-inbox.service - refuses to
start the scripts inbox CRUD server until USER is actually
mounted, so a script pushed before that lands on the real persistent
volume rather than silently writing through to the disposable
substrate. Reuses persist_bind_mounts.is_mounted unchanged, the exact
same real-kernel-state check ensure_redirect already relies on for the
same reason (decision record 62's own established concern, applied
here to a different consumer of the same mountpoint).
"""
from __future__ import annotations

import sys

import persist_bind_mounts as pbm

from repair import RealRunner


def check(runner, *, independent_marker_path="/etc/baseline/independent-drive.json",
          policy_path=None, active_persona_marker_path=pbm.ACTIVE_PERSONA_MARKER_PATH,
          mount_table_path="/proc/self/mounts") -> int:
    try:
        mountpoint = pbm.active_user_mountpoint(
            runner, independent_marker_path=independent_marker_path,
            policy_path=policy_path,
            active_persona_marker_path=active_persona_marker_path,
        )
        return 0 if pbm.is_mounted(runner, mountpoint, mount_table_path=mount_table_path) else 1
    except (OSError, RuntimeError, ValueError):
        return 1


def main(runner=None) -> int:
    if runner is None:
        runner = RealRunner()
    try:
        mountpoint = pbm.active_user_mountpoint(runner)
        mounted = pbm.is_mounted(runner, mountpoint)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[baseline-scripts-inbox-gate] cannot verify active persistence mount: {exc}",
              file=sys.stderr)
        return 1
    rc = 0 if mounted else 1
    if rc != 0:
        print(f"[baseline-scripts-inbox-gate] {mountpoint} is not mounted - "
              "refusing to start the scripts inbox server.", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
