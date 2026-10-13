"""Network rows: one builder for the TUI's Network tab and the web /network page (browser parity with the TUI, operator 2026-10-12).

A row is (key, category, label, status, detail). `network` is the lib/network module, injected so the builder reads no real NIC in tests.
"""
from __future__ import annotations

import html

import providers

CATEGORY_ORDER = ["Network", "AI Provider"]
STATUS_ORDER = ["Active", "Reachable", "Available", "Not set up", "Unreachable", "Unknown"]
STATUS_STYLE = {"Active": "#87ff87", "Reachable": "#5faf5f", "Available": "#ffd700", "Not set up": "#ffaf5f",
                "Unreachable": "#ff5f5f", "Unknown": "#afafff"}
STAGES = (("nic_detected", "Physical network adapters"), ("driver_bound", "Network driver"), ("carrier_present", "Network link"),
          ("interface_inventory", "Interface details"), ("gateway_reachable", "Gateway"), ("dns_functioning", "DNS"),
          ("internet_reachable", "Internet"))


def build_rows(facts, interfaces, provider_states, network, show_ids=False):
    fact_map = {f["fact"]: f for f in facts}
    rows = []
    active_members = set()
    addr_fact = fact_map.get("address_assigned")
    if addr_fact and addr_fact["ok"] and ":" in addr_fact["detail"]:
        active_dev, ip = (p.strip() for p in addr_fact["detail"].split(":", 1))
        active_members.add(active_dev)
        try:
            active_members.update(network._bridge_members(active_dev))
            bridge_members_error = None
        except network.NetworkProbeError as exc:
            bridge_members_error = str(exc)
        display_dev = next((m for m in active_members if m != active_dev), active_dev)
        try:
            traffic = network.interface_traffic_label(display_dev)
        except network.NetworkProbeError as exc:
            traffic = f"traffic counters unavailable: {exc}"
        rows.append((f"iface:{display_dev}", "Network", network.friendly_name(display_dev, show_ids), "Active",
                     f"{ip} | {traffic}" if traffic else ip))
        if bridge_members_error:
            rows.append(("info:bridge-members", "Network", "Bridge members", "Unknown",
                         f"bridge member inventory unavailable: {bridge_members_error}"))
    for stage, label in STAGES:
        f = fact_map.get(stage)
        if f is not None and not f["ok"]:
            rows.append((f"info:{label}", "Network", label, "Unreachable", f["detail"]))
    for iface in interfaces:
        if iface["name"] in active_members:
            continue
        name = network.friendly_name(iface["name"], show_ids)
        key = f"iface:{iface['name']}"
        if iface["carrier"] is None:
            rows.append((key, "Network", name, "Unknown", iface.get("carrier_error") or "carrier state unavailable"))
        elif iface["carrier"]:
            try:
                traffic = network.interface_traffic_label(iface["name"])
            except network.NetworkProbeError as exc:
                traffic = f"traffic counters unavailable: {exc}"
            rows.append((key, "Network", name, "Available", traffic or "connected, not in use"))
        elif iface.get("driver_bound") is None or iface.get("wired") is None:
            rows.append((key, "Network", name, "Unknown",
                         iface.get("driver_error") or "driver/link type unavailable; connection state cannot be inferred"))
        elif iface["wired"]:
            rows.append((key, "Network", name, "Unreachable", "not physically connected"))      # no command can fix a missing cable
        else:
            rows.append((key, "Network", name, "Available", "not connected"))                   # Wi-Fi / modem / tether: recoverable
    claude = next((p for p in provider_states if p["name"] == "Claude Subscription"), None)
    for p in ([claude] if claude else []) + [p for p in provider_states if p is not claude]:
        rows.append((f"info:{p['name']}", "AI Provider", p["name"], providers.display_status(p["state"]), p["detail"]))
    return rows


def sort_rows(rows):
    return sorted(rows, key=lambda r: (CATEGORY_ORDER.index(r[1]), STATUS_ORDER.index(r[3])))


def render(rows) -> bytes:
    body = "".join(f"<tr><td>{html.escape(c)}</td><td>{html.escape(l)}</td><td>{html.escape(s)}</td><td>{html.escape(d)}</td></tr>"
                   for _k, c, l, s, d in sort_rows(rows)) or "<tr><td colspan='4'>no network information</td></tr>"
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Network</title></head><body><h1>Network</h1>"
            "<table><thead><tr><th>Group</th><th>Connection</th><th>Status</th><th>Detail</th></tr></thead><tbody>"
            f"{body}</tbody></table><p><a href='/ai-setup'>Set up AI providers</a></p></body></html>").encode()
