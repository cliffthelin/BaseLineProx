"""Sensors: the rows both the TUI tab and the web page show (browser parity with the TUI, operator 2026-10-12)."""
from __future__ import annotations

import html
import time


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


def hottest_history(rows, *, db_path, window_s: float, now=None) -> tuple:
    """(label, [values]) for the hottest temperature among `rows`, from the history store the collector timer writes. The same call feeds the TUI's trend line and the console's, so the two cannot differ."""
    import sensors_history
    temps = [r for r in rows if r[3] == "C" and isinstance(r[2], (int, float))]
    if not temps:
        return "", []
    hottest = max(temps, key=lambda r: r[2])
    label = f"{hottest[1]} temperature"
    try:
        from pathlib import Path
        if not Path(db_path).exists():
            return label, []
        conn = sensors_history.open_db(str(db_path))
        try:
            since = (time.time() if now is None else now) - window_s
            return label, [v for _, v in sensors_history.query_history(conn, source=hottest[0], key=hottest[1], since_ts=since)]
        finally:
            conn.close()
    except Exception:                                                     # noqa: BLE001 - no history is shown as "no history yet", never as an error page
        return label, []


def render(rows, history=None) -> bytes:
    body = "".join(f"<tr><td>{html.escape(str(s))}</td><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td>"
                   f"<td>{html.escape(str(u))}</td></tr>" for s, k, v, u in rows)
    if not rows:
        body = "<tr><td colspan='4'>no sensors/NVMe/SMART data available</td></tr>"
    import console_charts
    chart = console_charts.sparkline_svg(history[1], label=history[0] or "Hottest temperature", unit=" C") if history is not None else ""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Sensors</title></head><body><h1>Sensors</h1>"
            + chart + "<table><thead><tr><th>Source</th><th>Key</th><th>Value</th><th>Unit</th></tr></thead><tbody>"
            f"{body}</tbody></table></body></html>").encode()
