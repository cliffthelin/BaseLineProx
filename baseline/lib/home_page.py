"""The browser's starting page: what the TUI opens with, then the machine's tools, then administration and the installer."""
from __future__ import annotations

import html

TUI_AREAS = (
    ("/launcher", "Launcher", "every OS as a tile: open it as a console, a window or fullscreen; its settings and applications"),
    ("/hardware", "Hardware", "CPU, memory, drives, PCI devices and what changed since last boot"),
    ("/network", "Network", "connections, gateway, DNS, internet, AI providers and the USB tether"),
    ("/sensors", "Sensors", "temperatures, NVMe and SMART health"),
    ("/audio", "Audio and Bluetooth", "speakers, microphones, headsets and other Bluetooth devices"),
    ("/power", "Power", "shut down or restart this machine"),
    ("/memory", "Memory and swap", "the host's swap: size, and written or just reserved"),
    ("/vms", "Virtual machines", "your VMs and containers, start, stop and create"),
    ("/workspaces", "Workspaces", "Kasm: browsers and desktops in the browser, with profiles that are kept"),
    ("/chat", "Chat", "ask Baseline, with the harness of your choice"),
    ("/shell", "Console", "the TUI's command line: hardware, network, tether, ask"),
)
TOOLS = (
    ("/environments", "Environments", "carried OS images and the five guest applications"),
    ("/tools", "Diagnostic tools", "lm-sensors, nvme-cli, smartmontools, iperf3, ethtool"),
    ("/ai-setup", "AI providers", "sign in to Claude, add other provider keys"),
    ("/vault", "Vault", "passphrase and unlock for stored credentials"),
    ("/security", "Two-factor", "turn on an authenticator code for a Proxmox user"),
    ("/ceph", "Ceph", "install the Ceph packages (needs the internet)"),
    ("/console", "Baseline text console", "show the text console on this machine's own screen"),
)
INSTALLER_GROUP = (
    ("/install-plan", "Installer plan"),
    ("/install-plan?display=desktop", "Installer desktop"),
    ("/installation-readiness", "Installation readiness"),
    ("/installer-cache", "Installer Cache"),
    ("/recipes", "Environment recipes"),
    ("/app-isolation", "App Isolation"),
)
ADMIN_GROUP = (
    ("/settings", "Settings"), ("/admin", "Admin"), ("/recovery", "Recovery"), ("/drive-admin", "Drive Administration"),
    ("/operations", "Operations"), ("/operators", "Operators"), ("/approvals", "Approvals"), ("/audit", "Audit"),
    ("/remote-access", "Remote access"), ("/workloads", "Workload jobs"), ("/master-config", "Master Config"),
)


def _cards(items):
    return "".join(f'<a class="card" href="{html.escape(p, quote=True)}"><b>{html.escape(n)}</b>'
                   f'<span>{html.escape(d)}</span></a>' for p, n, d in items)


def _links(items):
    return " &middot; ".join(f'<a href="{html.escape(p, quote=True)}">{html.escape(n)}</a>' for p, n in items)


PROXMOX_WHERE = (
    ("Storage", "Datacenter > Storage (installer-cache, session-temp, user-admin, ...)"),
    ("Disks", "node > Disks (every drive the host sees, including USB)"),
    ("Firewall", "Datacenter > Firewall (rules, options) and node > Firewall"),
    ("Users, groups, permissions", "Datacenter > Permissions"),
    ("Two-factor authentication", "Datacenter > Permissions > Two Factor"),
    ("Ceph", "node > Ceph (installs from here when you choose)"),
    ("Backup", "Datacenter > Backup"),
    ("VMs and containers", "Create VM / Create CT at the top of the Proxmox page"),
)


def render() -> bytes:
    proxmox = ('<a class="card" href="https://localhost:8006" target="_blank" rel="noopener"><b>Proxmox VE</b>'
               '<span>the Proxmox web interface: storage, firewall, users, two-factor</span></a>')
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Baseline</title><style>"
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:.8rem}"
            ".card{display:block;padding:1rem;border:1px solid #33364a;border-radius:8px;background:#171923;text-decoration:none;color:#e7e9f0}"
            ".card:hover,.card:focus-visible{border-color:#7fa4ec}.card span{display:block;color:#9aa0ba;margin-top:.3rem;font-size:.9rem}"
            "</style></head><body><h1>Baseline</h1><h2>This machine</h2><div class='grid'>"
            f"{_cards(TUI_AREAS)}</div><h2>Tools</h2><div class='grid'>{proxmox}{_cards(TOOLS)}</div>"
            "<h2>Where the Proxmox tools are</h2><ul>"
            + "".join(f"<li><b>{html.escape(n)}</b>: {html.escape(w)}</li>" for n, w in PROXMOX_WHERE) + "</ul>"
            f"<h2>Installer</h2><p>{_links(INSTALLER_GROUP)}</p><h2>Administration</h2><p>{_links(ADMIN_GROUP)}</p></body></html>").encode()
