"""ExecStartPre gate for baseline-settings-web.service - refuses to
launch the browser settings UI (settings_web.py, PRD SS5.16) until
baseline-firstboot.service has genuinely committed. Editing sections
like network/firewall/ssh through the settings UI before firstboot's
own statemachine has finished configuring them could race with it;
gating this the same way Track A3's kiosk GUI is gated avoids that,
rather than inventing a second notion of "done" that could drift from
the real one. Reuses firstboot_statemachine.already_completed()
unchanged, same as kiosk_gate.py.
"""
from __future__ import annotations

import sys

import firstboot_statemachine as fsm


def check(state_dir=fsm.STATE_DIR) -> int:
    return 0 if fsm.already_completed(state_dir) else 1


def main() -> int:
    rc = check()
    if rc != 0:
        print("[baseline-settings-web-gate] baseline-firstboot.service has "
              "not committed yet - refusing to start the settings web UI.",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
