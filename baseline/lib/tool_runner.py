"""One address per diagnostic tool (/tools/<name>), each running only fixed commands from the browser (operator, 2026-10-19: the tools have their own URLs, not console
commands). A value a person picks (a drive, a network card, a host to test against) is checked against what this host really has or a plain host name, never passed on as typed."""
from __future__ import annotations

import html
import os
import re
import subprocess

_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
LIMIT = 90

TOOLS = {
    "lm-sensors": {"title": "Temperatures and fans", "about": "Temperatures, fan speeds and voltages (sensors).", "actions": {
        "readings": {"label": "Current readings", "argv": ["sensors"]},
        "json": {"label": "As data (JSON)", "argv": ["sensors", "-j"]}}},
    "nvme-cli": {"title": "NVMe drives", "about": "Health, firmware and namespaces of the NVMe drives.", "actions": {
        "list": {"label": "List NVMe drives", "argv": ["nvme", "list"]},
        "smart": {"label": "Health log of a drive", "argv": ["nvme", "smart-log", "{}"], "pick": "nvme"}}},
    "smartmontools": {"title": "Drive health (SMART)", "about": "SMART health of every drive.", "actions": {
        "scan": {"label": "Find drives", "argv": ["smartctl", "--scan"]},
        "health": {"label": "Health verdict of a drive", "argv": ["smartctl", "-H", "{}"], "pick": "smart"},
        "all": {"label": "Full report of a drive", "argv": ["smartctl", "-a", "{}"], "pick": "smart"}}},
    "iperf3": {"title": "Network speed test", "about": "Throughput between this host and another.", "actions": {
        "test": {"label": "Test against a server", "argv": ["iperf3", "-c", "{}", "-t", "5"], "pick": "host", "post": True},
        "serve": {"label": "Listen for one test (60 s)", "argv": ["timeout", "60", "iperf3", "-s", "-1"], "post": True}}},
    "ethtool": {"title": "Network card link", "about": "Link speed, driver and offloads of a network card.", "actions": {
        "link": {"label": "Link and speed", "argv": ["ethtool", "{}"], "pick": "nic"},
        "driver": {"label": "Driver", "argv": ["ethtool", "-i", "{}"], "pick": "nic"}}},
}


def _nics(net_dir):
    try:
        return sorted(n for n in os.listdir(net_dir) if n != "lo" and re.fullmatch(r"[A-Za-z0-9_.-]+", n))
    except OSError:
        return []


def _drives(runner, kind):
    try:
        out = runner(["smartctl", "--scan"], capture_output=True, text=True, timeout=LIMIT).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    drives = [line.split()[0] for line in out.splitlines() if line.startswith("/dev/")]
    return [d for d in drives if kind != "nvme" or "nvme" in d]


def choices(tool, action, runner=subprocess.run, net_dir="/sys/class/net"):
    pick = (TOOLS.get(tool, {}).get("actions", {}).get(action) or {}).get("pick")
    if pick == "nic":
        return _nics(net_dir)
    if pick in ("smart", "nvme"):
        return _drives(runner, pick)
    return []


def run(tool, action, value="", runner=subprocess.run, net_dir="/sys/class/net"):
    spec = (TOOLS.get(tool) or {}).get("actions", {}).get(action)
    if spec is None:
        return {"ok": False, "tool": tool, "action": action, "output": "That tool or action does not exist."}
    argv = list(spec["argv"])
    if spec.get("pick"):
        if spec["pick"] == "host":
            allowed = _HOST.fullmatch(value or "") is not None and not value.startswith("-")
        else:
            allowed = value in choices(tool, action, runner, net_dir)
        if not allowed:
            return {"ok": False, "tool": tool, "action": action, "output": "Choose one of the offered values."}
        argv = [value if part == "{}" else part for part in argv]
    try:
        done = runner(argv, capture_output=True, text=True, timeout=LIMIT)
    except FileNotFoundError:
        return {"ok": False, "tool": tool, "action": action, "output": f"{tool} is not installed on this host."}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "tool": tool, "action": action, "output": f"Could not run: {exc}"[:300]}
    text = ((done.stdout or "") + (done.stderr or ""))[:60000]
    return {"ok": done.returncode == 0, "tool": tool, "action": action, "output": text or "(no output)"}


def render(tool, result=None, runner=subprocess.run, net_dir="/sys/class/net") -> bytes:
    spec = TOOLS[tool]
    links = "".join(f"<a href='/tools/{n}'{' class=active' if n == tool else ''}>{html.escape(t['title'])}</a> " for n, t in TOOLS.items())
    forms = ""
    for key, action in spec["actions"].items():
        pick = action.get("pick")
        if pick == "host":
            field = "<input name='value' placeholder='host name or address' required> "
        elif pick:
            options = "".join(f"<option>{html.escape(c)}</option>" for c in choices(tool, key, runner, net_dir))
            field = f"<select name='value'>{options or '<option value=\"\">None found</option>'}</select> "
        else:
            field = ""
        method = "post" if action.get("post") else "get"
        forms += (f"<form method='{method}' action='/tools/{tool}'><input type='hidden' name='action' value='{key}'>{field}"
                  f"<button type='submit'>{html.escape(action['label'])}</button></form>")
    out = ""
    if result:
        state = "worked" if result["ok"] else "did not work"
        out = f"<section><h2>Result ({state})</h2><pre>{html.escape(result['output'])}</pre></section>"
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(spec['title'])}</title></head><body>"
            f"<h1>{html.escape(spec['title'])}</h1><p>{html.escape(spec['about'])}</p><nav>{links}</nav>{forms}{out}</body></html>").encode()
