"""ExecStartPre gate for baseline-kiosk.service (Track A3) - refuses to
launch the kiosk GUI until firstboot has committed and the storage policy
verifies mounted role identities, including retained administrative AppData.
Reuses the firstboot completion check and the real storage verifier; never
fall back to a browser profile on the disposable root filesystem.
"""
from __future__ import annotations

import sys

import firstboot_statemachine as fsm
import storage_policy
from repair import RealRunner


def check(state_dir=fsm.STATE_DIR, *, storage_check=None) -> int:
    if not fsm.already_completed(state_dir):
        return 1
    try:
        report=(storage_check or (lambda:storage_policy.verify_runtime(RealRunner())))()
        return 0 if (isinstance(report,dict) and report.get('state')=='storage_verified'
                     and 'APPDATA_ADMIN' in report.get('roles',[])) else 1
    except Exception:
        return 1


def main() -> int:
    rc = check()
    if rc != 0:
        print("[baseline-kiosk-gate] baseline-firstboot.service has not "
              "committed or retained AppData storage is not verified - refusing to start the kiosk.", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
