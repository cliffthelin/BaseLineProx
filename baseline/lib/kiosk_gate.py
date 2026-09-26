"""ExecStartPre gate for baseline-kiosk.service (Track A3) - refuses to
launch the kiosk GUI until baseline-firstboot.service has genuinely
committed, so the kiosk never appears in front of an unconfigured
machine. Reuses `firstboot_statemachine.already_completed()`'s
existence-based, fail-closed discipline unchanged rather than
re-implementing a second notion of "done" that could drift from the
real one.
"""
from __future__ import annotations

import sys

import firstboot_statemachine as fsm


def check(state_dir=fsm.STATE_DIR) -> int:
    return 0 if fsm.already_completed(state_dir) else 1


def main() -> int:
    rc = check()
    if rc != 0:
        print("[baseline-kiosk-gate] baseline-firstboot.service has not "
              "committed yet - refusing to start the kiosk.", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
