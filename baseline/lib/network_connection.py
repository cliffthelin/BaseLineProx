"""One network connection's settings: its name, whether it is switched on, and whether it is the primary or the fallback path.

The TUI's connection dialog and the console's connection page both call this, so the two cannot differ: the same changes are made in the same order with the same messages. The modules that touch
the system (`network`, `netpref`) are passed in, so the logic is checked without touching a system.
"""
from __future__ import annotations

LIFELINE_STAGE_LABELS = [
    ("nic_detected", "NIC detected"), ("driver_bound", "Driver bound"), ("carrier_present", "Carrier present"), ("address_assigned", "Address assigned"),
    ("gateway_reachable", "Gateway reachable"), ("dns_functioning", "DNS functioning"), ("internet_reachable", "Internet reachable"),
    ("llm_provider_reachable", "LLM provider reachable"),
]
ROLES = (None, "primary", "fallback")


def lifeline_text(facts, is_active_device: bool) -> str:
    if not is_active_device or not facts:
        return "Not currently carrying the lifeline. Available as an alternate path (see Role above)."
    fact_map = {f["fact"]: f for f in facts}
    lines = []
    for key, label in LIFELINE_STAGE_LABELS:
        f = fact_map.get(key)
        lines.append(f"-  {label}: not reached" if f is None else f"{'OK' if f['ok'] else 'FAIL'}  {label}: {f['detail']}")
    return "\n".join(lines)


def apply_changes(network, netpref, ifname: str, *, alias: str, power_on: bool, admin_up_at_open, role) -> tuple:
    """Save the alias, change the interface's power if it differs from how it was when opened, and set its role. Returns (messages, failed)."""
    if role not in ROLES:
        return ["role must be primary, fallback or unchanged"], True
    messages, failed = [], False
    try:
        network.save_alias(ifname, alias)
    except OSError as exc:
        failed = True
        messages.append(f"alias: {exc}")
    if admin_up_at_open is not None and power_on != admin_up_at_open:
        ok, detail = network.set_admin_state(ifname, power_on)
        messages.append(detail)
        failed = failed or not ok
    if role == "primary":
        ok, detail = netpref.apply_primary(ifname)
        messages.append(detail)
        failed = failed or not ok
    elif role == "fallback":
        try:
            netpref.save_preference(fallback=ifname)
        except OSError as exc:
            failed = True
            messages.append(str(exc))
    return messages, failed
