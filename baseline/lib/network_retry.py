"""Unattended retry of exactly the network change the person confirmed at first boot.

When first boot could not get internet (no cable, no DHCP yet), it rolls the change back, installs from the drive's own
repository and commits. This retries, on a timer, ONLY that same change: the one the person authorized with CONFIRM.

  - nothing happens before first boot has committed, and never again once a retry (or first boot) has verified;
  - a link must be up; otherwise it waits and touches nothing;
  - the change is applied only if a fresh diagnosis proposes exactly what was confirmed (mode, target, diff); any
    other proposal is recorded and left for a new CONFIRM;
  - the repair is the existing, transactional one (independent rollback timer armed first, target-bound verification),
    called with operator_present=False, so it also refuses while anyone is connected through the affected device;
  - every attempt is recorded in network-retry.json (the first-boot journal is never written).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import firstboot_statemachine as fsm

RETRY_FILE = "network-retry.json"
ATTEMPTS_KEPT = 50


def authorized_change(journal: dict) -> dict | None:
    """The change the person confirmed, if first boot ended without a verified network; otherwise None."""
    states = [entry.get("state") for entry in journal.get("history", [])]
    if "confirmed" not in states or "network_repaired" in states:
        return None
    proposed = [e for e in journal["history"] if e.get("state") == "proposed"]
    diagnosis = proposed[-1].get("diagnosis", {}) if proposed else {}
    if not diagnosis.get("needs_repair") or diagnosis.get("mode") not in ("replace", "additive") \
            or not diagnosis.get("target"):
        return None
    return {"mode": diagnosis["mode"], "target": diagnosis["target"], "diff": diagnosis.get("diff")}


_BRIDGE_PORTS = re.compile(r"^([ \t]*bridge[-_]ports[ \t]+)[^#\r\n]+", re.MULTILINE)


def _without_bridge_port_names(after):
    """The proposed file with the NIC names on `bridge-ports` lines blanked. bridge_port.py (ADR 0001) legitimately points a bridge at the
    NIC the drive finds on a new machine; that must not make the confirmed change look like a different one. Nothing else is ignored."""
    if isinstance(after, str):
        return _BRIDGE_PORTS.sub(r"\1<nic>", after)
    if isinstance(after, (list, tuple)):                      # the diagnosis carries the proposed file as a list of lines
        return [_without_bridge_port_names(line) for line in after]
    return after


def same_change(authorized: dict, diagnosis: dict) -> bool:
    return bool(diagnosis.get("needs_repair")
                and diagnosis.get("mode") == authorized["mode"]
                and diagnosis.get("target") == authorized["target"]
                and _without_bridge_port_names((diagnosis.get("diff") or {}).get("after"))
                == _without_bridge_port_names((authorized["diff"] or {}).get("after")))


# After these the timer has nothing left to do and is disabled; every other action is tried again at the next tick.
FINISHED = frozenset({"already_verified", "verified_without_change", "applied_ok", "nothing_to_retry"})


def _load(state_dir: Path) -> dict:
    try:
        record = json.loads((state_dir / RETRY_FILE).read_text())
        if isinstance(record, dict):
            return record
    except (OSError, ValueError):
        pass
    return {"verified": None, "attempt_count": 0, "attempts": []}


def _save(state_dir: Path, record: dict, action: str, detail: str) -> None:
    record["attempt_count"] = record.get("attempt_count", 0) + 1
    record["attempts"] = (record.get("attempts", []) + [
        {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": action, "detail": detail}])[-ATTEMPTS_KEPT:]
    fsm._durable_write(state_dir / RETRY_FILE, json.dumps(record, indent=1) + "\n")


def attempt(state_dir: Path, *, discover_fn, diagnose_fn, link_up_fn, repair_fn) -> dict:
    """One bounded attempt. The four functions are the system's probes and the repair itself (see `main`)."""
    state_dir = Path(state_dir)
    record = _load(state_dir)
    if record.get("verified"):
        return {"action": "already_verified"}
    if fsm.already_completed(state_dir) is None:
        return {"action": "awaiting_first_boot"}
    authorized = authorized_change(fsm.load_journal(state_dir))
    if authorized is None:
        return {"action": "nothing_to_retry"}

    def finish(action, detail, verified=None):
        if verified:
            record["verified"] = verified
        _save(state_dir, record, action, detail)
        return {"action": action, "detail": detail}

    discovery = discover_fn()
    if discovery["lifeline_ok"]:
        return finish("verified_without_change", "the connection verified without any change from this retry",
                      {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "how": "already_healthy", "verification": {}})
    if not link_up_fn():
        return finish("waiting_for_link", "no physical link is up; nothing was changed")
    diagnosis = diagnose_fn(discovery)
    if not same_change(authorized, diagnosis):
        return finish("proposal_changed", "the proposed change is no longer the confirmed one; a new CONFIRM is needed")
    result = repair_fn(authorized["mode"], authorized["target"])
    if result.ok:
        return finish("applied_ok", result.detail, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                     "how": "confirmed change re-applied",
                                                     "verification": dict(result.verification)})
    return finish("applied_failed", result.detail or str(result.refusal_code))


def carrier_up(path: Path) -> bool:
    """True only when the kernel says the link is up. Reading `carrier` of an interface that is administratively down raises EINVAL
    (seen on PC601's laptop, 2026-10-12: the retry service crashed with a traceback every five minutes)."""
    try:
        return path.read_text().strip() == "1"
    except OSError:
        return False


def main() -> int:
    import firstboot_network_repair as fbnr
    import network
    import repair
    import repair_additive

    runner = repair.RealRunner()

    def link_up() -> bool:
        return any(carrier_up(Path(f"/sys/class/net/{nic}/carrier")) for nic in network._physical_nics())

    def repair_it(mode: str, target: str):
        function = repair.reset_interface_to_dhcp if mode == "replace" else repair_additive.add_dhcp_to_bridge
        return function(runner, target, "network-retry", operator_present=False,
                        check_lifeline_fn=network.check_lifeline)

    result = attempt(fsm.STATE_DIR, discover_fn=lambda: fbnr.discover(runner, network.check_lifeline),
                     diagnose_fn=lambda discovery: fbnr.diagnose(runner, discovery),
                     link_up_fn=link_up, repair_fn=repair_it)
    print("[baseline-network-retry] " + json.dumps(result))
    if result["action"] in FINISHED:
        subprocess.run(["systemctl", "disable", "--now", "baseline-network-retry.timer"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
