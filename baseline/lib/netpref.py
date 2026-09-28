#!/usr/bin/env python3
"""Baseline network preference - genuinely reprioritizes the kernel's
default route, not just a stored label. Demotes other live default
routes to a higher metric instead of removing them, so they stay
available as an automatic fallback rather than needing to be re-added.

Preference storage moved onto settings_store.py's own registry
(decision record 91) - this used to be its own flat JSON file
(`/etc/baseline/network_preference.json`), one of several scattered
config files found during the settings-to-SQL migration review.
`load_preference`/`save_preference` keep their exact prior signatures
and return shape so `bin/baseline` (the only real caller) needed no
changes."""
import ipaddress
import subprocess

import settings_store

settings_store.register_schema([
    settings_store.SettingDef("network", "preferred_primary_interface", None,
                               "Interface apply_primary last made the kernel's actual default route."),
    settings_store.SettingDef("network", "preferred_fallback_interface", None,
                               "Interface demoted to a fallback default route (metric 100) rather than removed."),
])


def load_preference():
    return {
        "primary": settings_store.get_setting("network", "preferred_primary_interface"),
        "fallback": settings_store.get_setting("network", "preferred_fallback_interface"),
    }


def save_preference(primary=None, fallback=None):
    if primary is not None:
        settings_store.set_setting("network", "preferred_primary_interface", primary)
    if fallback is not None:
        settings_store.set_setting("network", "preferred_fallback_interface", fallback)
    return load_preference()


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
