#!/usr/bin/env python3
"""First-boot network-repair flow: automatic discovery -> exact-diff
proposal on tty1 -> indefinite local confirmation -> bounded repair
(replace or additive, per repair.py/repair_additive.py) -> independent
target-bound verification -> package installation gated on success.

Deliberately narrow: this is NOT a general multi-action first-boot state
machine (firewall/handoff/tether policy remain out of scope - see
docs/design/milestone-1-plan.md §3a/§9 and
experiments/m0-inv6/firstboot_statemachine.py for that broader shape,
which is a separate, not-yet-authorized piece of work). This module
covers exactly one action: detecting and, after genuine local
authorization, repairing broken destination networking - the actual gap
identified in decision records 10/11.

Reuses, verbatim in spirit, the CONFIRM-gate discipline already built and
(after a real defect was found and fixed) re-proven in Investigation 6:
no timeout, no default acceptance, EOF on stdin is never treated as
confirmation. `operator_present=True` is only ever set after a REAL
CONFIRM has been read from tty1 - matching repair.py's own documented
contract for that parameter.
"""
from __future__ import annotations

import json
import sys
import time

import ifnet_config
import network
import repair
import repair_additive
import topology


def facts_verification(facts: list) -> dict:
    """{"address": bool, "gateway": bool} derived directly from
    check_lifeline()'s own facts. Reused both to compute discover()'s
    lifeline_ok below and, when the lifeline was already healthy at
    confirmation time, as firstboot_statemachine.py's genuine (never
    fabricated) verification evidence before it records a
    "network_repaired" state - see that module's record_transition
    invariant."""
    fact_map = {f["fact"]: f for f in facts}
    gw_ok = fact_map.get("gateway_reachable", {}).get("ok", True)
    addr_ok = fact_map.get("address_assigned", {}).get("ok", True)
    return {"address": bool(addr_ok), "gateway": bool(gw_ok)}


def discover(runner, check_lifeline_fn=None) -> dict:
    """Read-only. No prompt, no side effects. Always safe to call
    unattended - matches the PRD's "discovery has no side effects and
    requires no confirmation" requirement, restated here for this
    specific action."""
    check_lifeline_fn = check_lifeline_fn or network.check_lifeline
    facts = check_lifeline_fn()
    v = facts_verification(facts)
    return {"facts": facts, "lifeline_ok": bool(v["address"] and v["gateway"])}


def observed_dev(runner, facts) -> str | None:
    """The device name network.py's lifeline check attributed the
    failure to. network.py's own default-route lookup is IPv4-only
    (`ip -4 route show default`) and returns no device at all when only
    an IPv6 default route exists - exactly Fixture A's shape (decision
    record 10). Falls back to a protocol-agnostic route lookup so the
    repair proposal still knows which interface to target even when the
    only default route present is IPv6."""
    fact_map = {f["fact"]: f for f in facts}
    detail = fact_map.get("address_assigned", {}).get("detail", "")
    if ":" in detail and not detail.startswith("no address"):
        candidate = detail.split(":", 1)[0].strip()
        if candidate:
            return candidate

    for argv in (["ip", "route", "show", "default"], ["ip", "-6", "route", "show", "default"]):
        res = runner.run(argv, timeout=5)
        for line in res.stdout.splitlines():
            parts = line.split()
            if "dev" in parts:
                return parts[parts.index("dev") + 1]
    return None


def diagnose(runner, discovery: dict) -> dict:
    """Given discover()'s output, derive the repair proposal (or an
    explicit reason none could be derived - ambiguous topology, no
    candidate at all, unsupported environment). Read-only: builds the
    proposal but does not execute anything."""
    if discovery["lifeline_ok"]:
        return {"needs_repair": False, "mode": None, "target": None, "diff": None, "reason": ""}

    dev = observed_dev(runner, discovery["facts"])
    if dev is None:
        return {"needs_repair": True, "mode": None, "target": None, "diff": None,
                "reason": "lifeline is broken but no default-route device (IPv4 or IPv6) could be identified"}

    mode, derivation = repair_additive.plan_and_derive(runner, dev)
    if not derivation.ok:
        return {"needs_repair": True, "mode": None, "target": None, "diff": None,
                "reason": f"{derivation.reason or 'no repair candidate found'}",
                "candidates": [c.name for c in derivation.candidates]}

    target = derivation.target
    cfg = repair.read_interfaces_config(runner)
    if mode == "replace":
        before = target.stanza.lines
        diff = {"action": "replace", "file": target.stanza.source_path,
                "before": list(before), "after": [f"iface {target.name} inet dhcp"]}
    else:
        diff = {"action": "add", "file": target.stanza.source_path,
                "before": list(target.stanza.lines), "after": list(target.stanza.lines) +
                [f"iface {target.name} inet dhcp"],
                "note": f"the existing {target.stanza.family} {target.stanza.method} stanza is preserved "
                        "unchanged - this adds a new, separate stanza alongside it"}

    return {"needs_repair": True, "mode": mode, "target": target.name,
            "target_kind": target.kind, "physical_devices": target.physical_devices, "diff": diff, "reason": ""}


def format_proposal_for_tty1(diagnosis: dict) -> str:
    """Exact-diff display, per instruction: the operator sees precisely
    what would change, not a summary."""
    lines = ["=" * 60, "Detected topology and proposed network repair:", ""]
    lines.append(f"Mode: {diagnosis['mode']}")
    lines.append(f"Target interface: {diagnosis['target']} ({diagnosis.get('target_kind', '?')})")
    lines.append(f"Physical device(s): {', '.join(diagnosis.get('physical_devices', []))}")
    lines.append("")
    lines.append(f"File: {diagnosis['diff']['file']}")
    lines.append("--- before ---")
    lines.extend(diagnosis["diff"]["before"])
    lines.append("--- after ---")
    lines.extend(diagnosis["diff"]["after"])
    if diagnosis["diff"].get("note"):
        lines.append("")
        lines.append(diagnosis["diff"]["note"])
    lines.append("")
    lines.append("Type CONFIRM and press Enter to proceed. No timeout. No default.")
    lines.append("=" * 60)
    return "\n".join(lines)


def wait_for_confirmation(stdin=None) -> bool:
    """Blocks indefinitely on real tty1 input. No timeout, no default
    acceptance, no injected/simulated response of any kind - identical
    discipline to Investigation 6's corrected state machine (the
    original auto-confirm defect that investigation found and fixed is
    exactly the failure mode this function exists to prevent). EOF on
    stdin (e.g. the tty closed) is never treated as confirmation; the
    function keeps waiting rather than proceeding.

    `stdin` is injectable for tests (an iterable of lines); production
    callers pass nothing and get real sys.stdin.
    """
    source = stdin if stdin is not None else iter(sys.stdin.readline, None)
    for line in source:
        if line is None:
            time.sleep(1)
            continue
        if line.strip() == "CONFIRM":
            return True
        if line == "":
            time.sleep(1)
    return False


def run_first_boot_network_repair(runner, requested_by: str = "first-boot-state-machine",
                                   stdin=None, print_fn=print, check_lifeline_fn=None) -> dict:
    """The full flow. Returns a result dict with enough detail for the
    caller (the broader first-boot state machine, once it exists - see
    module docstring) to decide whether package installation may
    proceed. `package_install_allowed` is only ever True after a real
    CONFIRM was read AND independent target-bound verification (address,
    route, gateway, DNS, HTTPS) succeeded - never on confirmation alone.
    """
    discovery = discover(runner, check_lifeline_fn)
    if discovery["lifeline_ok"]:
        return {"action": "none", "reason": "lifeline already healthy", "package_install_allowed": True}

    diagnosis = diagnose(runner, discovery)
    if not diagnosis["needs_repair"] or diagnosis["mode"] is None:
        # Broken lifeline but nothing this action can safely propose
        # (ambiguous topology, no candidate, or no identifiable device) -
        # refuse and stay at tty1; package installation stays locked.
        print_fn(f"[network-repair] lifeline broken, no safe automatic repair could be derived: "
                  f"{diagnosis['reason']}")
        print_fn("[network-repair] remaining at tty1 - no automatic retry, no package installation.")
        return {"action": "refused", "reason": diagnosis["reason"], "package_install_allowed": False}

    print_fn(format_proposal_for_tty1(diagnosis))
    confirmed = wait_for_confirmation(stdin)
    if not confirmed:
        print_fn("[network-repair] not confirmed - no change made.")
        return {"action": "declined", "package_install_allowed": False}

    if diagnosis["mode"] == "replace":
        result = repair.reset_interface_to_dhcp(runner, diagnosis["target"], requested_by,
                                                  operator_present=True, check_lifeline_fn=check_lifeline_fn)
    else:
        result = repair_additive.add_dhcp_to_bridge(runner, diagnosis["target"], requested_by,
                                                      operator_present=True, check_lifeline_fn=check_lifeline_fn)

    print_fn(f"[network-repair] result: {result.outcome} - {result.detail}")
    return {"action": diagnosis["mode"], "target": diagnosis["target"], "result": result,
            "package_install_allowed": bool(result.ok)}


if __name__ == "__main__":
    sys.exit(0 if run_first_boot_network_repair(repair.RealRunner())["package_install_allowed"] else 1)
