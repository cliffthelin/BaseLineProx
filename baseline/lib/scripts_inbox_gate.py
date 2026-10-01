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

try:
    from repair import RealRunner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    RealRunner = None


def check(runner) -> int:
    return 0 if pbm.is_mounted(runner, pbm.MOUNT_POINT) else 1


def main(runner=None) -> int:
    if runner is None:
        runner = RealRunner()
    rc = check(runner)
    if rc != 0:
        print(f"[baseline-scripts-inbox-gate] {pbm.MOUNT_POINT} is not mounted - "
              "refusing to start the scripts inbox server.", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
