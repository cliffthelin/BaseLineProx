#!/usr/bin/env python3
"""Baseline USB Tether Bring-Up - hardened, per lessons from V0.1 bring-up.

Manually driving a tether connection tonight required: recognizing the
new interface, bringing it up, retrying DHCP (a single attempt often
lands mid-activation and gets nothing), and telling "link up but no DHCP
server" (phone's hotspot isn't actually active) apart from "no link at
all" (nothing plugged in) or genuine failure. This module does all of
that as one bounded, scriptable operation instead of a human repeating
`dhclient -v` by hand and guessing at what a blank retry means.
"""
import subprocess
import time
from pathlib import Path

# Kernel drivers that specifically mean "this is a tethered phone," not a
# permanent USB-attached NIC like a dock's Ethernet adapter (r8152) or a
# WWAN modem. Identifying by driver, not "wasn't there at boot," since the
# latter breaks the moment Baseline itself restarts while a phone is still
# plugged in - the USB device doesn't disappear just because the phone's
# hotspot got toggled off and on.
TETHER_DRIVERS = {"ipheth", "rndis_host", "cdc_ether", "cdc_ncm"}


def _driver_name(ifname: str):
    driver_link = Path("/sys/class/net") / ifname / "device" / "driver"
    try:
        return driver_link.resolve().name
    except OSError:
        return None


def find_tether_candidates(known_at_boot=frozenset()):
    """Net interfaces bound to a known phone-tether driver. `known_at_boot`
    is accepted for backward compatibility but no longer used to exclude
    anything - driver identity is a reliable signal on its own."""
    base = Path("/sys/class/net")
    if not base.exists():
        return []
    out = []
    for entry in sorted(base.iterdir()):
        if (entry / "bridge").exists():
            continue
        if _driver_name(entry.name) in TETHER_DRIVERS:
            out.append(entry.name)
    return out


def bring_up_tether(ifname: str, attempts: int = 5, attempt_timeout: int = 6):
    """Bring an interface up and get a DHCP lease, retrying with bounded
    attempts (each a real dhclient run, not a hung background daemon).

    Returns a dict: {"ok": bool, "stage": str, "detail": str, "address": str|None}
    "stage" distinguishes exactly where it stopped, matching the PRD's
    observed-state-not-collapsed-flag philosophy: "no_carrier" (nothing
    plugged in / link down), "no_dhcp_offer" (link is real but nothing
    answered DHCP - almost always means the phone's hotspot isn't
    actually toggled on, not a Baseline problem), or "ok".
    """
    subprocess.run(["ip", "link", "set", ifname, "up"], capture_output=True)
    time.sleep(1)

    carrier_path = Path("/sys/class/net") / ifname / "carrier"
    try:
        has_carrier = carrier_path.read_text().strip() == "1"
    except OSError:
        has_carrier = False
    if not has_carrier:
        return {"ok": False, "stage": "no_carrier", "detail": f"{ifname} has no carrier - is a cable/phone actually connected?", "address": None}

    last_detail = ""
    for attempt in range(1, attempts + 1):
        subprocess.run(["dhclient", "-r", ifname], capture_output=True)
        # ISC dhclient has no "-timeout" flag of its own (that's a
        # dhclient.conf directive, not a CLI option) - bound the wall-clock
        # time with the external `timeout` command instead. Passing a
        # nonexistent flag directly to dhclient fails immediately with a
        # usage error, which looks exactly like "no DHCP offer" if you
        # don't read the output closely - a real bug hit while hardening
        # this, not a phone/hotspot problem.
        proc = subprocess.run(
            ["timeout", str(attempt_timeout + 2), "dhclient", "-1", ifname],
            capture_output=True, text=True,
        )
        addr = _current_v4_address(ifname)
        if addr:
            return {"ok": True, "stage": "ok", "detail": f"bound after {attempt} attempt(s)", "address": addr}
        last_detail = (proc.stderr or proc.stdout or "no response").strip().splitlines()[-1] if (proc.stderr or proc.stdout) else "no response"
        time.sleep(1)

    return {
        "ok": False,
        "stage": "no_dhcp_offer",
        "detail": (f"{ifname} has carrier but got no DHCP offer after {attempts} attempts "
                   f"({last_detail}). On iPhone: Personal Hotspot must be explicitly toggled "
                   "ON (not just 'Trust This Computer') - try toggling it off, unplug/replug, "
                   "then on again."),
        "address": None,
    }


def _current_v4_address(ifname: str):
    proc = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", ifname],
                           capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            return parts[parts.index("inet") + 1].split("/")[0]
    return None


def auto_tether(known_at_boot=frozenset()):
    """Find and bring up whatever tether-looking interface just appeared.
    Returns bring_up_tether()'s result dict, plus "candidates" tried."""
    candidates = find_tether_candidates(known_at_boot)
    if not candidates:
        return {"ok": False, "stage": "no_candidate", "detail": "no USB network interface found - plug in a phone with tethering enabled", "address": None, "candidates": []}
    # Prefer whichever candidate already has carrier, if any do.
    for name in candidates:
        try:
            if (Path("/sys/class/net") / name / "carrier").read_text().strip() == "1":
                result = bring_up_tether(name)
                result["candidates"] = candidates
                result["interface"] = name
                return result
        except OSError:
            continue
    result = bring_up_tether(candidates[0])
    result["candidates"] = candidates
    result["interface"] = candidates[0]
    return result


if __name__ == "__main__":
    import sys
    r = auto_tether()
    print(r)
    sys.exit(0 if r["ok"] else 1)
