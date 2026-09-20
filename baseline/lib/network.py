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


FRIENDLY_DRIVERS = {
    "r8152": "Ethernet (USB/dock)", "r8169": "Ethernet", "r8168": "Ethernet",
    "e1000e": "Ethernet", "igb": "Ethernet", "tg3": "Ethernet", "bnx2": "Ethernet",
    "iwlwifi": "Wi-Fi", "ath9k": "Wi-Fi", "ath10k_pci": "Wi-Fi", "rtl8xxxu": "Wi-Fi",
    "ipheth": "Phone Tether (iPhone)", "rndis_host": "Phone Tether (Android)",
    "cdc_ether": "Phone Tether", "cdc_ncm": "Phone Tether",
    "cdc_mbim": "Cellular Modem", "qmi_wwan": "Cellular Modem", "cdc_wdm": "Cellular Modem",
}

# Drivers for links that need a physical cable - "no carrier" here really
# does mean physically disconnected, and no command can fix that. Every
# other interface (Wi-Fi, Cellular Modem, Phone Tether) can lack carrier
# just because it hasn't associated yet, which is a recoverable, "Available"
# state, not a dead one.
WIRED_DRIVERS = {"r8152", "r8169", "r8168", "e1000e", "igb", "tg3", "bnx2"}


def is_wired(ifname: str) -> bool:
    driver_link = Path("/sys/class/net") / ifname / "device" / "driver"
    try:
        return driver_link.resolve().name in WIRED_DRIVERS
    except OSError:
        return False


ALIAS_FILE = Path("/etc/baseline/interface_aliases.json")


def load_aliases() -> dict:
    try:
        return json.loads(ALIAS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_alias(ifname: str, alias: str) -> None:
    """An operator-chosen name overriding the driver-based default, e.g.
    renaming "Ethernet" to "Office Uplink". Empty alias clears it, going
    back to the driver-based default."""
    aliases = load_aliases()
    alias = alias.strip()
    if alias:
        aliases[ifname] = alias
    else:
        aliases.pop(ifname, None)
    ALIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALIAS_FILE.write_text(json.dumps(aliases))


def friendly_name(ifname: str, show_hardware_id: bool = False) -> str:
    """Human label for an interface: an operator-set alias if one exists,
    else a driver-based default ("Wi-Fi" instead of "wlp2s0"). With
    show_hardware_id, appends the raw device name too."""
    aliases = load_aliases()
    label = aliases.get(ifname)
    if label is None:
        driver_link = Path("/sys/class/net") / ifname / "device" / "driver"
        try:
            label = FRIENDLY_DRIVERS.get(driver_link.resolve().name)
        except OSError:
            label = None
    if label is None:
        label = "Bridge" if (Path("/sys/class/net") / ifname / "bridge").exists() else ifname
    if show_hardware_id and label != ifname:
        return f"{label} ({ifname})"
    return label


def device_details(ifname: str) -> dict:
    """Best-effort hardware identity for one interface, pulled from udev's
    own hardware database - works uniformly for onboard (PCI) and
    external (USB dock/tether) devices without hand-parsing lspci/lsusb.
    Baseline's own inxi-based Hardware tab lists the same physical device
    again as a separate row (inxi's Network section isn't correlated back
    to a specific ifname); this is the reliable, ifname-keyed source for
    "which manufacturer, on what bus, using which driver" bridged into
    the Network tab's own modal instead of sending the operator to
    cross-reference the Hardware tab by hand."""
    try:
        out = subprocess.run(["udevadm", "info", "-q", "property", f"/sys/class/net/{ifname}"],
                              capture_output=True, text=True, timeout=5).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        out = ""
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    driver_link = Path("/sys/class/net") / ifname / "device" / "driver"
    try:
        driver = driver_link.resolve().name
    except OSError:
        driver = None
    bus = props.get("ID_BUS")
    connection = {"pci": "Onboard (PCI)", "usb": "External (USB)"}.get(bus, bus or "unknown")
    # ID_OUI_FROM_DATABASE is the manufacturer that put the part on the
    # board/dock (e.g. "Dell Inc."), distinct from ID_VENDOR_FROM_DATABASE,
    # the chipset maker (e.g. "Intel Corporation") - both are useful, so
    # both are kept rather than picking one.
    return {
        "driver": driver or "unknown",
        "connection": connection,
        "chipset_vendor": props.get("ID_VENDOR_FROM_DATABASE") or props.get("ID_VENDOR", ""),
        "model": props.get("ID_MODEL_FROM_DATABASE") or props.get("ID_MODEL", ""),
        "manufacturer": props.get("ID_OUI_FROM_DATABASE", ""),
    }


def is_admin_up(ifname: str) -> bool:
    """Administrative state (has this interface been told to come up),
    distinct from carrier (is a cable/AP actually connected). Read via
    the IFF_UP bit rather than parsing `ip link show` text."""
    try:
        flags = int(Path(f"/sys/class/net/{ifname}/flags").read_text().strip(), 16)
        return bool(flags & 0x1)
    except (OSError, ValueError):
        return True


def set_admin_state(ifname: str, up: bool):
    """Genuinely bring the interface up or down (`ip link set`), not a
    cosmetic toggle - disabling the interface you're using to reach this
    console over the network will actually disconnect it."""
    action = "up" if up else "down"
    result = subprocess.run(["ip", "link", "set", ifname, action], capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        return False, (result.stderr or f"ip link set {ifname} {action} failed").strip()
    return True, f"{ifname} set {action}"


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def interface_stats(ifname: str):
    """(rx_bytes, tx_bytes) lifetime counters for this interface, or
    (None, None) if unreadable. Non-zero even on a currently-down
    interface that carried traffic earlier this boot."""
    stats = Path("/sys/class/net") / ifname / "statistics"
    try:
        rx = int((stats / "rx_bytes").read_text().strip())
        tx = int((stats / "tx_bytes").read_text().strip())
        return rx, tx
    except (OSError, ValueError):
        return None, None


def interface_traffic_label(ifname: str) -> str:
    """e.g. 'down 1.2MB up 340.0KB', or '' if no traffic has ever
    passed (nothing worth showing for a device that's never been used).
    ASCII only, deliberately - this renders on a bare TERM=linux console,
    which doesn't reliably have Unicode arrow glyphs in its font."""
    rx, tx = interface_stats(ifname)
    if not rx and not tx:
        return ""
    return f"down {_human_bytes(rx or 0)} up {_human_bytes(tx or 0)}"


def _carrier(ifname: str):
    try:
        return (Path("/sys/class/net") / ifname / "carrier").read_text().strip() == "1"
    except OSError:
        return None


def list_interfaces():
    """Cheap inventory: every physical NIC with its driver-bound and
    carrier state. Shared by the Hardware tab (driver/hardware facts) and
    the Network tab (connectivity grouping) - no full lifeline probe
    (DNS/gateway/internet checks) needed just to list what's there."""
    out = []
    for name in _physical_nics():
        out.append({
            "name": name,
            "friendly": friendly_name(name),
            "driver_bound": os.path.exists(f"/sys/class/net/{name}/device/driver"),
            "carrier": bool(_carrier(name)),
            "wired": is_wired(name),
        })
    return out


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


DNS_PROBE_HOST = "www.proxmox.com"


def _dns_probe(host: str, timeout: float = 3.0):
    socket.setdefaulttimeout(timeout)
    try:
        addr = socket.gethostbyname(host)
        return True, f"{host} -> {addr}"
    except OSError as e:
        return False, f"{host}: {e}"


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
    # a gateway may not have port 1 open; fall back to a ping-style reachability,
    # explicitly bound to the device we picked (-I dev). Without this, a second
    # interface sharing the gateway's subnet (e.g. a dead bridge still holding a
    # stale same-subnet address) can win the kernel's route lookup for that
    # specific destination even though the *default* route correctly named a
    # different, live device - found live during the V0.1 bare-metal test, see
    # docs/BAREMETAL_BRINGUP_NOTES.md.
    if not gw_ok:
        try:
            ping = subprocess.run(["ping", "-c", "1", "-W", "2", "-I", dev, gw],
                                   capture_output=True, timeout=5)
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
