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


class TetherProbeError(RuntimeError):
    """A tether observation failed, so absence cannot be concluded."""


def _path_exists(path: Path) -> bool:
    try:
        path.stat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise TetherProbeError(f"cannot inspect {path}: {exc}") from exc

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
        return driver_link.resolve(strict=True).name
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError) as exc:
        raise TetherProbeError(f"cannot inspect driver for {ifname}: {exc}") from exc


def find_tether_candidates(known_at_boot=frozenset()):
    """Net interfaces bound to a known phone-tether driver. `known_at_boot`
    is accepted for backward compatibility but no longer used to exclude
    anything - driver identity is a reliable signal on its own."""
    base = Path("/sys/class/net")
    if not _path_exists(base):
        raise TetherProbeError(f"network interface inventory is unavailable at {base}")
    out = []
    try:
        entries = sorted(base.iterdir())
    except OSError as exc:
        raise TetherProbeError(f"cannot enumerate network interfaces: {exc}") from exc
    for entry in entries:
        if _path_exists(entry / "bridge"):
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
    try:
        proc = subprocess.run(["ip", "link", "set", ifname, "up"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "stage": "command_error", "detail": f"cannot bring {ifname} up: {exc}", "address": None}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"ip exited {proc.returncode}").strip()
        return {"ok": False, "stage": "command_error", "detail": f"cannot bring {ifname} up: {detail}", "address": None}
    time.sleep(1)

    carrier_path = Path("/sys/class/net") / ifname / "carrier"
    try:
        carrier = carrier_path.read_text().strip()
    except OSError as exc:
        return {"ok": False, "stage": "probe_error", "detail": f"cannot read carrier for {ifname}: {exc}", "address": None}
    if carrier not in {"0", "1"}:
        return {"ok": False, "stage": "probe_error", "detail": f"invalid carrier value for {ifname}: {carrier!r}", "address": None}
    has_carrier = carrier == "1"
    if not has_carrier:
        return {"ok": False, "stage": "no_carrier", "detail": f"{ifname} has no carrier - is a cable/phone actually connected?", "address": None}

    last_detail = ""
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(["dhclient", "-r", ifname], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "stage": "command_error", "detail": f"cannot release existing DHCP lease on {ifname}: {exc}", "address": None}
        # ISC dhclient has no "-timeout" flag of its own (that's a
        # dhclient.conf directive, not a CLI option) - bound the wall-clock
        # time with the external `timeout` command instead. Passing a
        # nonexistent flag directly to dhclient fails immediately with a
        # usage error, which looks exactly like "no DHCP offer" if you
        # don't read the output closely - a real bug hit while hardening
        # this, not a phone/hotspot problem.
        try:
            proc = subprocess.run(
                ["timeout", str(attempt_timeout + 2), "dhclient", "-1", ifname],
                capture_output=True, text=True, timeout=attempt_timeout + 4,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "stage": "command_error", "detail": f"DHCP command failed on {ifname}: {exc}", "address": None}
        if proc.returncode in {125, 126, 127}:
            detail = (proc.stderr or proc.stdout or f"timeout/dhclient exited {proc.returncode}").strip()
            return {"ok": False, "stage": "command_error", "detail": f"DHCP command could not run on {ifname}: {detail}", "address": None}
        try:
            addr = _current_v4_address(ifname)
        except TetherProbeError as exc:
            return {"ok": False, "stage": "probe_error", "detail": str(exc), "address": None}
        if addr:
            return {"ok": True, "stage": "ok", "detail": f"bound after {attempt} attempt(s)", "address": addr}
        if proc.returncode != 0:
            diagnostic = (proc.stderr or proc.stdout or "").strip().lower()
            if not any(marker in diagnostic for marker in ("no lease", "no response", "timed out", "timeout", "no offer")):
                detail = (proc.stderr or proc.stdout or f"dhclient exited {proc.returncode}").strip()
                return {"ok": False, "stage": "command_error", "detail": f"DHCP client failed on {ifname}: {detail}", "address": None}
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
    try:
        proc = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", ifname],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TetherProbeError(f"cannot query IPv4 address for {ifname}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"ip exited {proc.returncode}").strip()
        raise TetherProbeError(f"cannot query IPv4 address for {ifname}: {detail}")
    for line in proc.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            import ipaddress
            try:
                return str(ipaddress.ip_interface(parts[parts.index("inet") + 1]).ip)
            except (IndexError, ValueError) as exc:
                raise TetherProbeError(f"invalid IPv4 address output for {ifname}: {line!r}") from exc
    return None


def auto_tether(known_at_boot=frozenset()):
    """Find and bring up whatever tether-looking interface just appeared.
    Returns bring_up_tether()'s result dict, plus "candidates" tried."""
    try:
        candidates = find_tether_candidates(known_at_boot)
    except TetherProbeError as exc:
        return {"ok": False, "stage": "probe_error", "detail": str(exc), "address": None, "candidates": []}
    if not candidates:
        return {"ok": False, "stage": "no_candidate", "detail": "no USB network interface found - plug in a phone with tethering enabled", "address": None, "candidates": []}
    # Prefer whichever candidate already has carrier, if any do.
    for name in candidates:
        try:
            carrier = (Path("/sys/class/net") / name / "carrier").read_text().strip()
        except OSError as exc:
            return {"ok": False, "stage": "probe_error", "detail": f"cannot read carrier for {name}: {exc}", "address": None, "candidates": candidates, "interface": name}
        if carrier not in {"0", "1"}:
            return {"ok": False, "stage": "probe_error", "detail": f"invalid carrier value for {name}: {carrier!r}", "address": None, "candidates": candidates, "interface": name}
        if carrier == "1":
            result = bring_up_tether(name)
            result["candidates"] = candidates
            result["interface"] = name
            return result
    result = bring_up_tether(candidates[0])
    result["candidates"] = candidates
    result["interface"] = candidates[0]
    return result


if __name__ == "__main__":
    import sys
    r = auto_tether()
    print(r)
    sys.exit(0 if r["ok"] else 1)
