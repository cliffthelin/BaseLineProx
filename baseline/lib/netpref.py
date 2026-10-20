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
    """Use an observed installed default route; never invent a gateway."""
    proc = subprocess.run(["ip", "-4", "route", "show", "dev", dev],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[:2] == ["default", "via"]:
            return parts[2]
    return None


def apply_primary(dev: str):
    """Make `dev` the kernel's actual default route (metric 0). Any other
    currently-live default route is demoted to metric 100, not deleted -
    it remains a real, working fallback path rather than something that
    has to be manually re-added later."""
    gw = _device_gateway(dev)
    if not gw:
        return False, f"REAL-007: no observed default gateway for {dev}; route preference not applied"

    proc = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True)
    if proc.returncode != 0:
        return False, "REAL-007: default route discovery failed; preference not applied"
    for line in proc.stdout.splitlines():
        parts = line.split()
        if "dev" not in parts:
            continue
        other_dev = parts[parts.index("dev") + 1]
        if other_dev == dev:
            continue
        other_gw = parts[parts.index("via") + 1] if "via" in parts else None
        if not other_gw:
            return False, "REAL-007: cannot demote a gateway-less route safely; no success claimed"
        removed = subprocess.run(["ip", "route", "del", "default", "dev", other_dev], capture_output=True)
        if removed.returncode != 0:
            return False, "REAL-007: fallback route removal failed; preference not saved"
        if other_gw:
            added = subprocess.run(["ip", "route", "add", "default", "via", other_gw, "dev", other_dev, "metric", "100"], capture_output=True)
            if added.returncode != 0:
                return False, "REAL-007: fallback route re-add failed after removal; routes may be partially changed; preference not saved"

    result = subprocess.run(["ip", "route", "replace", "default", "via", gw, "dev", dev, "metric", "0"],
                             capture_output=True, text=True)
    if result.returncode != 0:
        return False, (result.stderr or "ip route replace failed").strip()

    save_preference(primary=dev)
    return True, f"default route now via {dev} ({gw}); other live paths demoted to metric 100, not removed"
