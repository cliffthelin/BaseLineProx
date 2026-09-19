#!/usr/bin/env python3
"""Baseline Lifeline Networking - Step 5.

Observed state and desired action are kept as separate, individually
reportable facts (not one collapsed "online/offline" flag), per the PRD:
NIC detected -> driver bound -> carrier present -> address assigned ->
gateway reachable -> DNS functioning -> Internet reachable ->
LLM provider reachable.

Each check stops reporting further-downstream facts once one fails, since
a later fact can't be meaningfully true if an earlier one is false - but
every fact attempted is still returned, pass or fail, for the caller to
print in full.
"""
import ipaddress
import json
import os
import socket
import subprocess
import time
from pathlib import Path

EVENT_LOG = Path("/var/log/baseline/network.events.jsonl")
LLM_PROBE_HOST = "api.anthropic.com"
LLM_PROBE_PORT = 443
INTERNET_PROBE_HOST = "1.1.1.1"
INTERNET_PROBE_PORT = 53


def _log_event(step: str, status: str, detail: str) -> None:
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "component": "network",
        "step": step,
        "status": status,
        "detail": detail,
    }
    with EVENT_LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def _physical_nics():
    """Real NICs under /sys/class/net - excludes lo and software bridges."""
    out = []
    base = Path("/sys/class/net")
    if not base.exists():
        return out
    for entry in sorted(base.iterdir()):
        name = entry.name
        if name == "lo":
            continue
        if (entry / "bridge").exists():
            continue  # this is a bridge (e.g. vmbr0), not a physical NIC
        if (entry / "device").exists():
            out.append(name)
    return out


def _carrier(ifname: str):
    try:
        return (Path("/sys/class/net") / ifname / "carrier").read_text().strip() == "1"
    except OSError:
        return None


def _bridge_members(brname: str):
    brif = Path("/sys/class/net") / brname / "brif"
    try:
        return [p.name for p in brif.iterdir()]
    except OSError:
        return []


def _route_dev_is_live(dev: str, up_nics: list) -> bool:
    """A route's device is live if it's an up physical NIC directly, or a
    bridge whose underlying member NIC is up (e.g. vmbr0 -> enp0s31f6)."""
    if dev in up_nics:
        return True
    return any(m in up_nics for m in _bridge_members(dev))


def _route_default(up_nics=None):
    """Return (gw, dev) for the default route that's actually usable right
    now. Multiple default routes can coexist (e.g. a stale bridge route to
    a dead wired NIC alongside a freshly-tethered interface) - picking the
    routing table's first line regardless of which device is actually live
    is how a real, working tether connection got silently ignored in favor
    of a dead cached one. Prefer a route whose device has carrier; fall
    back to the first route line only if none do, so a genuine total
    failure still reports the same "no live device" detail as before."""
    up_nics = up_nics or []
    try:
        out = subprocess.run(["ip", "-4", "route", "show", "default"],
                              capture_output=True, text=True, timeout=5).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, None
    routes = []
    for line in out.splitlines():
        parts = line.split()
        if "via" in parts and "dev" in parts:
            routes.append((parts[parts.index("via") + 1], parts[parts.index("dev") + 1]))
    if not routes:
        return None, None
    for gw, dev in routes:
        if _route_dev_is_live(dev, up_nics):
            return gw, dev
    return routes[0]


def _addr_for(ifname: str):
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", ifname],
                              capture_output=True, text=True, timeout=5).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if "inet" in parts:
            cidr = parts[parts.index("inet") + 1]
            return str(ipaddress.ip_interface(cidr).ip)
    return None


def _tcp_probe(host: str, port: int, timeout: float = 3.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as e:
        return False, str(e)


def _dns_probe(host: str, timeout: float = 3.0):
    socket.setdefaulttimeout(timeout)
    try:
        socket.gethostbyname(host)
        return True, ""
    except OSError as e:
        return False, str(e)


def check_lifeline():
    """Run every fact in order; stop attempting once a fact fails, but
    always return the full list of (fact, ok, detail) attempted so far."""
    facts = []

    def record(name, ok, detail=""):
        facts.append({"fact": name, "ok": ok, "detail": detail})
        _log_event(name, "pass" if ok else "fail", detail)
        return ok

    nics = _physical_nics()
    if not record("nic_detected", bool(nics), ", ".join(nics) or "no physical NIC found"):
        return facts

    up_nics = [n for n in nics if _carrier(n)]
    driver_ok = any(os.path.exists(f"/sys/class/net/{n}/device/driver") for n in nics)
    if not record("driver_bound", driver_ok, ", ".join(nics)):
        return facts

    if not record("carrier_present", bool(up_nics), f"up={up_nics} down={[n for n in nics if n not in up_nics]}"):
        return facts

    gw, dev = _route_default(up_nics)
    ip_addr = _addr_for(dev) if dev else None
    if not record("address_assigned", bool(ip_addr), f"{dev}: {ip_addr}" if ip_addr else f"no address on {dev or 'default route device'}"):
        return facts

    if not gw:
        record("gateway_reachable", False, "no default gateway in routing table")
        return facts
    gw_ok, gw_detail = _tcp_probe(gw, 1, timeout=2.0)
    # a gateway may not have port 1 open; fall back to a ping-style reachability
    if not gw_ok:
        try:
            ping = subprocess.run(["ping", "-c", "1", "-W", "2", gw], capture_output=True, timeout=5)
            gw_ok = ping.returncode == 0
            gw_detail = "" if gw_ok else "no ping reply"
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            gw_detail = str(e)
    if not record("gateway_reachable", gw_ok, gw if gw_ok else f"{gw}: {gw_detail}"):
        return facts

    dns_ok, dns_detail = _dns_probe("www.proxmox.com")
    if not record("dns_functioning", dns_ok, dns_detail):
        return facts

    inet_ok, inet_detail = _tcp_probe(INTERNET_PROBE_HOST, INTERNET_PROBE_PORT)
    if not record("internet_reachable", inet_ok, inet_detail):
        return facts

    llm_ok, llm_detail = _tcp_probe(LLM_PROBE_HOST, LLM_PROBE_PORT)
    record("llm_provider_reachable", llm_ok, LLM_PROBE_HOST if llm_ok else f"{LLM_PROBE_HOST}: {llm_detail}")

    return facts


if __name__ == "__main__":
    for f in check_lifeline():
        mark = "OK  " if f["ok"] else "FAIL"
        print(f"[{mark}] {f['fact']:<24} {f['detail']}")
