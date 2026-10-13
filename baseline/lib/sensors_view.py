"""Sensors: the rows both the TUI tab and the web page show (browser parity with the TUI, operator 2026-10-12)."""
from __future__ import annotations

import html


def collect_rows(runner, diagnostics) -> list:
    """[(source, key, value, unit)] from lm-sensors chips, NVMe health and SMART temperatures."""
    rows = []
    for chip in diagnostics.collect_sensors(runner).chips:
        for feature in chip["features"]:
            rows.append(("sensors", f"{chip['chip']}/{feature['label']}", feature["value"], feature.get("unit", "")))
    for device in diagnostics.collect_nvme(runner).devices:
        health = device.get("health") or {}
        for field_name in ("temperature", "percentage_used"):
            if isinstance(health.get(field_name), (int, float)):
                rows.append(("nvme", f"{device['path']}/{field_name}", health[field_name], "C" if field_name == "temperature" else "%"))
    for device in diagnostics.collect_smart(runner).devices:
        if isinstance(device.get("temperature"), (int, float)):
            rows.append(("smart", f"{device['device']}/temperature", device["temperature"], "C"))
    return rows


def render(rows) -> bytes:
    body = "".join(f"<tr><td>{html.escape(str(s))}</td><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td>"
                   f"<td>{html.escape(str(u))}</td></tr>" for s, k, v, u in rows)
    if not rows:
        body = "<tr><td colspan='4'>no sensors/NVMe/SMART data available</td></tr>"
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Sensors</title></head><body><h1>Sensors</h1>"
            "<table><thead><tr><th>Source</th><th>Key</th><th>Value</th><th>Unit</th></tr></thead><tbody>"
            f"{body}</tbody></table></body></html>").encode()
