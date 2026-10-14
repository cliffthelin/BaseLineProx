"""Audio and Bluetooth devices for the host's own browser session (operator, 2026-10-14).

Reads what PipeWire (through pactl) and BlueZ (through bluetoothctl) report and issues the few device actions a person needs: connect,
disconnect, pair, trust, remove. A device address is validated before it becomes an argument; nothing else a user types reaches a command.
"""
from __future__ import annotations

import html
import re
import shutil

_MAC = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
ACTIONS = ("connect", "disconnect", "pair", "trust", "remove")


def parse_bt_devices(text: str) -> list:
    out = []
    for line in text.splitlines():
        m = re.match(r"^Device ([0-9A-Fa-f:]{17}) (.*)$", line.strip())
        if m:
            out.append({"mac": m.group(1).upper(), "name": m.group(2).strip()})
    return out


def parse_bt_info(text: str) -> dict:
    def flag(key):
        m = re.search(rf"^\s*{key}: (yes|no)\s*$", text, re.M)
        return bool(m and m.group(1) == "yes")
    return {"paired": flag("Paired"), "trusted": flag("Trusted"), "connected": flag("Connected")}


def parse_pactl_short(text: str) -> list:
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 5:
            out.append({"id": parts[0], "name": parts[1], "format": parts[3], "state": parts[4]})
    return out


def action_argv(action: str, mac: str) -> list:
    if action not in ACTIONS:
        raise ValueError("unknown Bluetooth action")
    if not isinstance(mac, str) or not _MAC.fullmatch(mac):
        raise ValueError("a Bluetooth address looks like AA:BB:CC:DD:EE:FF")
    return ["bluetoothctl", action, mac.upper()]


def collect(runner, which=shutil.which) -> dict:
    tools = {"pactl": bool(which("pactl")), "bluetoothctl": bool(which("bluetoothctl"))}
    result = {"tools": tools, "sinks": None, "sources": None, "bluetooth": None}
    if tools["pactl"]:
        sinks = runner.run(["pactl", "list", "short", "sinks"], timeout=10)
        sources = runner.run(["pactl", "list", "short", "sources"], timeout=10)
        result["sinks"] = parse_pactl_short(sinks.stdout) if sinks.returncode == 0 else None
        result["sources"] = ([s for s in parse_pactl_short(sources.stdout) if not s["name"].endswith(".monitor")]
                             if sources.returncode == 0 else None)
    if tools["bluetoothctl"]:
        listing = runner.run(["bluetoothctl", "devices"], timeout=10)
        if listing.returncode == 0:
            devices = parse_bt_devices(listing.stdout)
            for device in devices:
                info = runner.run(["bluetoothctl", "info", device["mac"]], timeout=10)
                device.update(parse_bt_info(info.stdout) if info.returncode == 0 else {})
            result["bluetooth"] = devices
    return result


def render(data: dict, notice: str = "") -> bytes:
    def table(rows, columns):
        if rows is None:
            return "<p>unavailable</p>"
        if not rows:
            return "<p>none found</p>"
        head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
        body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in columns) + "</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    tools = data.get("tools", {})
    missing = [name for name, present in tools.items() if not present]
    banner = (f"<p role='alert'>Not installed yet: {html.escape(', '.join(missing))}. The host installs the sound and Bluetooth packages "
              "itself when it is online (every 15 minutes).</p>") if missing else ""
    bt = data.get("bluetooth")
    rows = ""
    for d in bt or []:
        mac = html.escape(d["mac"], quote=True)
        buttons = "".join(f'<form method="post" action="/audio/bluetooth" style="display:inline"><input type="hidden" name="mac" value="{mac}">'
                          f'<input type="hidden" name="action" value="{a}"><button type="submit">{a}</button></form> '
                          for a in ("disconnect" if d.get("connected") else "connect", "trust", "remove"))
        rows += (f"<tr><td>{html.escape(d['name'])}</td><td>{mac}</td><td>{'connected' if d.get('connected') else 'not connected'}"
                 f"{', paired' if d.get('paired') else ''}</td><td>{buttons}</td></tr>")
    bt_html = ("<p>unavailable</p>" if bt is None else
               ("<p>none paired</p>" if not bt else f"<table><thead><tr><th>Device</th><th>Address</th><th>State</th><th></th></tr></thead>"
                                                      f"<tbody>{rows}</tbody></table>"))
    pair = ('<form method="post" action="/audio/bluetooth"><input name="mac" placeholder="AA:BB:CC:DD:EE:FF" required> '
            '<input type="hidden" name="action" value="pair"><button type="submit">Pair a device</button></form>')
    note = f"<p>{html.escape(notice)}</p>" if notice else ""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Audio and Bluetooth</title></head><body>"
            f"<h1>Audio and Bluetooth</h1>{note}{banner}<h2>Outputs</h2>{table(data.get('sinks'), ['name', 'state', 'format'])}"
            f"<h2>Inputs</h2>{table(data.get('sources'), ['name', 'state', 'format'])}<h2>Bluetooth</h2>{bt_html}{pair}"
            "</body></html>").encode()
