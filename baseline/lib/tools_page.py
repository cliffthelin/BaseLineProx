"""The five diagnostic tools Baseline installs on every host (docs/design/current-drive-inventory-plan.md, "The five-tool manifest"):
lm-sensors, nvme-cli, smartmontools, iperf3, ethtool. Installed by first boot from the drive's own repository; this page is what shows
the operator that they are there (operator, 2026-10-12: "I still do not see any of the Proxmox installed tools").

Read-only: detection runs each tool's own version command through the inventory collector, never anything that changes the host.
"""
from __future__ import annotations

import html

PURPOSE = {
    "lm-sensors": "temperatures, fan speeds and voltages (`sensors`)",
    "nvme-cli": "NVMe drive health, firmware and namespaces (`nvme list`, `nvme smart-log`)",
    "smartmontools": "SMART health of every drive, and the smartd monitor (`smartctl -a`)",
    "iperf3": "network throughput tests between this host and another (`iperf3 -s` / `-c`)",
    "ethtool": "network card link speed, driver and offloads (`ethtool <nic>`)",
}


def gather(runner=None, manifest=None) -> dict:
    """{tool: detection} for the manifest's five tools. Imported lazily: the inventory package lives beside this module on the host."""
    from inventory.collectors import tools
    if runner is None:
        from inventory.runner import RealRunner
        runner = RealRunner()
    return tools.collect(runner, manifest)


def rows(results: dict) -> list:
    out = []
    for name in PURPOSE:
        detection = results.get(name) or {"available": False, "reason": "not in the manifest"}
        if detection.get("available"):
            version = detection.get("package_version") or (detection.get("version_output") or "").splitlines()[0:1]
            version = version if isinstance(version, str) else (version[0] if version else "")
            out.append({"tool": name, "state": "installed", "version": version, "path": detection.get("binary_path", "")})
        else:
            out.append({"tool": name, "state": "missing", "version": "", "path": detection.get("reason", "")})
    return out


def render(results: dict) -> bytes:
    body = []
    for row in rows(results):
        mark = "installed" if row["state"] == "installed" else "NOT INSTALLED"
        body.append("<tr><td>%s</td><td class='%s'>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            "<a href='/tools/%s'>%s</a>" % (row["tool"], html.escape(row["tool"])), row["state"], mark, html.escape(row["version"]), html.escape(row["path"]),
            html.escape(PURPOSE[row["tool"]])))
    installed = sum(1 for r in rows(results) if r["state"] == "installed")
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Diagnostic tools</title><style>"
            ".installed{color:#6fcf97}.missing{color:#eb5757;font-weight:600}</style></head><body>"
            f"<h1>Diagnostic tools ({installed} of {len(PURPOSE)} installed)</h1>"
            "<p>Installed on this host from the drive's own package repository at first boot. Open a tool to run it here in the browser.</p><table><thead><tr><th>Tool</th><th>State</th><th>Version</th><th>Where</th><th>Use</th></tr>"
            "</thead><tbody>" + "".join(body) + "</tbody></table></body></html>").encode()
