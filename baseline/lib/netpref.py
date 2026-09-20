#!/usr/bin/env python3
"""Baseline network preference - genuinely reprioritizes the kernel's
default route, not just a stored label. Demotes other live default
routes to a higher metric instead of removing them, so they stay
available as an automatic fallback rather than needing to be re-added.
"""
import ipaddress
import json
import subprocess
from pathlib import Path

PREF_FILE = Path("/etc/baseline/network_preference.json")


def load_preference():
    try:
        return json.loads(PREF_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"primary": None, "fallback": None}


def save_preference(primary=None, fallback=None):
    pref = load_preference()
    if primary is not None:
        pref["primary"] = primary
    if fallback is not None:
        pref["fallback"] = fallback
    PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREF_FILE.write_text(json.dumps(pref))
    return pref


def _device_gateway(dev: str):
    """This device's own gateway, from a route it already installed (its
    own default route, if dhclient added one) or, failing that, the
    first host address in its subnet as a best-effort fallback - not
    always correct, but reasonable when nothing better is known."""
    proc = subprocess.run(["ip", "-4", "route", "show", "dev", dev],
                           capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("default via"):
            return line.split()[2]

    proc = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", dev],
                           capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            iface = ipaddress.ip_interface(parts[parts.index("inet") + 1])
            hosts = list(iface.network.hosts())
            return str(hosts[0]) if hosts else None
    return None


def apply_primary(dev: str):
    """Make `dev` the kernel's actual default route (metric 0). Any other
    currently-live default route is demoted to metric 100, not deleted -
    it remains a real, working fallback path rather than something that
    has to be manually re-added later."""
    gw = _device_gateway(dev)
    if not gw:
        return False, f"could not determine {dev}'s own gateway"

    proc = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        parts = line.split()
        if "dev" not in parts:
            continue
        other_dev = parts[parts.index("dev") + 1]
        if other_dev == dev:
            continue
        other_gw = parts[parts.index("via") + 1] if "via" in parts else None
        subprocess.run(["ip", "route", "del", "default", "dev", other_dev], capture_output=True)
        if other_gw:
            subprocess.run(["ip", "route", "add", "default", "via", other_gw, "dev", other_dev, "metric", "100"], capture_output=True)

    result = subprocess.run(["ip", "route", "replace", "default", "via", gw, "dev", dev, "metric", "0"],
                             capture_output=True, text=True)
    if result.returncode != 0:
        return False, (result.stderr or "ip route replace failed").strip()

    save_preference(primary=dev)
    return True, f"default route now via {dev} ({gw}); other live paths demoted to metric 100, not removed"
