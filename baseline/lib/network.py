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

import references
import registry

EVENT_LOG = Path("/var/log/baseline/network.events.jsonl")
LLM_PROBE_HOST = "api.anthropic.com"
LLM_PROBE_PORT = 443
INTERNET_PROBE_HOST = "1.1.1.1"
INTERNET_PROBE_PORT = 53


class NetworkProbeError(RuntimeError):
    """A required host-network observation failed and is not an empty result."""


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


def _physical_nics(base=None):
    """Real NICs under /sys/class/net - excludes lo and software bridges."""
    out = []
    base = Path("/sys/class/net") if base is None else base
    try:
        entries = sorted(base.iterdir())
    except OSError as exc:
        raise NetworkProbeError(f"physical NIC inventory unavailable at {base}: {exc}") from exc
    for entry in entries:
        name = entry.name
        if name == "lo":
            continue
        if not entry.is_dir():
            continue  # e.g. bonding_masters, a plain file present whenever the bonding module is loaded
        if _sysfs_path_exists(entry / "bridge"):
            continue  # this is a bridge (e.g. vmbr0), not a physical NIC
        if _sysfs_path_exists(entry / "device"):
            out.append(name)
    return out


def _sysfs_path_exists(path):
    try:
        path.stat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise NetworkProbeError(f"could not inspect sysfs path {path}: {exc}") from exc


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


def _driver_name(ifname: str) -> str | None:
    driver_link = Path("/sys/class/net") / ifname / "device" / "driver"
    try:
        return driver_link.resolve(strict=True).name
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError) as exc:
        raise NetworkProbeError(f"driver observation unavailable for {ifname}: {exc}") from exc


def is_wired(ifname: str) -> bool | None:
    """True/False for an observed driver; None when no driver is bound."""
    driver = _driver_name(ifname)
    return driver in WIRED_DRIVERS if driver is not None else None


# Interface aliases moved onto registry.py directly (decision record
# 91), not through settings_store.py's SettingDef layer: one interface
# name per real, physically-present NIC is a dynamic key space known
# only at runtime, not a fixed set of (group, key) pairs settings_store
# expects to be declared up front - exactly the case registry.py's own
# generic entries exist for.
ALIASES_TYPE_ID = "network_aliases"


def load_aliases() -> dict:
    entries = registry.list_entries(ALIASES_TYPE_ID, scope=registry.PROTECTED)
    return {ifname: e["value"] for ifname, e in entries.items() if e["value"]}


def save_alias(ifname: str, alias: str) -> None:
    """An operator-chosen name overriding the driver-based default, e.g.
    renaming "Ethernet" to "Office Uplink". Empty alias clears it, going
    back to the driver-based default."""
    registry.register_type(ALIASES_TYPE_ID, "Operator-chosen interface display names (network.py)",
                            default_scope=registry.PROTECTED)
    registry.upsert_entry(ALIASES_TYPE_ID, ifname, attributes={}, scope=registry.PROTECTED)
    references.link(ALIASES_TYPE_ID, ifname, kind="hardware", name="nic-" + ifname)
    alias = alias.strip()
    registry.set_value(ALIASES_TYPE_ID, ifname, alias if alias else None, scope=registry.PROTECTED)


def friendly_name(ifname: str, show_hardware_id: bool = False) -> str:
    """Human label for an interface: an operator-set alias if one exists,
    else a driver-based default ("Wi-Fi" instead of "wlp2s0"). With
    show_hardware_id, appends the raw device name too."""
    aliases = load_aliases()
    label = aliases.get(ifname)
    if label is None:
        try:
            label = FRIENDLY_DRIVERS.get(_driver_name(ifname))
        except NetworkProbeError:
            label = None
    if label is None:
        label = "Bridge" if (Path("/sys/class/net") / ifname / "bridge").exists() else ifname
    if show_hardware_id and label != ifname:
        return f"{label} ({ifname})"
    return label


def device_details(ifname: str) -> dict:
    """Hardware identity for one interface, pulled from udev's
    own hardware database - works uniformly for onboard (PCI) and
    external (USB dock/tether) devices without hand-parsing lspci/lsusb.
    Baseline's own inxi-based Hardware tab lists the same physical device
    again as a separate row (inxi's Network section isn't correlated back
    to a specific ifname); this is the reliable, ifname-keyed source for
    "which manufacturer, on what bus, using which driver" bridged into
    the Network tab's own modal instead of sending the operator to
    cross-reference the Hardware tab by hand."""
    errors = []
    props = {}
    try:
        result = subprocess.run(["udevadm", "info", "-q", "property", f"/sys/class/net/{ifname}"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        else:
            detail = (result.stderr or result.stdout or f"udevadm exited with status {result.returncode}").strip()
            errors.append(f"udev hardware identity unavailable: {detail}")
    except (subprocess.TimeoutExpired, OSError) as exc:
        errors.append(f"udev hardware identity unavailable: {exc}")
    try:
        driver = _driver_name(ifname)
    except NetworkProbeError as exc:
        driver = None
        errors.append(str(exc))
    bus = props.get("ID_BUS")
    connection = {"pci": "Onboard (PCI)", "usb": "External (USB)"}.get(bus, bus or "unknown")
    # ID_OUI_FROM_DATABASE is the manufacturer that put the part on the
    # board/dock (e.g. "Dell Inc."), distinct from ID_VENDOR_FROM_DATABASE,
    # the chipset maker (e.g. "Intel Corporation") - both are useful, so
    # both are kept rather than picking one.
    return {
        "driver": driver or "unknown",
        "connection": connection,
        "chipset_vendor": props.get("ID_VENDOR_FROM_DATABASE") or props.get("ID_VENDOR") or "unknown",
        "model": props.get("ID_MODEL_FROM_DATABASE") or props.get("ID_MODEL") or "unknown",
        "manufacturer": props.get("ID_OUI_FROM_DATABASE") or "unknown",
        "errors": errors,
    }


def is_admin_up(ifname: str) -> bool:
    """Administrative state (has this interface been told to come up),
    distinct from carrier (is a cable/AP actually connected). Read via
    the IFF_UP bit rather than parsing `ip link show` text."""
    try:
        flags = int(Path(f"/sys/class/net/{ifname}/flags").read_text().strip(), 16)
    except OSError as exc:
        raise NetworkProbeError(f"administrative state unavailable for {ifname}: {exc}") from exc
    except ValueError as exc:
        raise NetworkProbeError(f"malformed admin state for {ifname}") from exc
    if flags < 0:
        raise NetworkProbeError(f"malformed admin state for {ifname}: negative flags")
    return bool(flags & 0x1)


def set_admin_state(ifname: str, up: bool):
    """Genuinely bring the interface up or down (`ip link set`), not a
    cosmetic toggle - disabling the interface you're using to reach this
    console over the network will actually disconnect it."""
    action = "up" if up else "down"
    try:
        result = subprocess.run(["ip", "link", "set", ifname, action], capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"ip link set {ifname} {action} unavailable: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or f"ip link set {ifname} {action} failed").strip()
    try:
        observed = is_admin_up(ifname)
    except NetworkProbeError as exc:
        return False, f"ip accepted {ifname} {action}, but administrative-state readback failed: {exc}"
    if observed is not up:
        return False, f"ip accepted {ifname} {action}, but readback mismatch: observed {'up' if observed else 'down'}"
    return True, f"{ifname} is {'enabled' if up else 'disabled'} (readback verified)"


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def interface_stats(ifname: str):
    """(rx_bytes, tx_bytes) lifetime counters for this interface.

    Non-zero even on a currently-down interface that carried traffic
    earlier this boot. Read and parse failures remain explicit errors,
    never a fabricated zero-traffic result.
    """
    stats = Path("/sys/class/net") / ifname / "statistics"
    try:
        rx = int((stats / "rx_bytes").read_text().strip())
        tx = int((stats / "tx_bytes").read_text().strip())
        return rx, tx
    except OSError as exc:
        raise NetworkProbeError(f"traffic counters unavailable for {ifname}: {exc}") from exc
    except ValueError as exc:
        raise NetworkProbeError(f"malformed traffic counters for {ifname}") from exc


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
    path = Path("/sys/class/net") / ifname / "carrier"
    try:
        value = path.read_text().strip()
    except OSError as exc:
        raise NetworkProbeError(f"carrier state unavailable for {ifname}: {exc}") from exc
    if value not in ("0", "1"):
        raise NetworkProbeError(f"malformed carrier state for {ifname}: {value!r}")
    return value == "1"


def list_interfaces():
    """Cheap inventory: every physical NIC with its driver-bound and
    carrier state. Shared by the Hardware tab (driver/hardware facts) and
    the Network tab (connectivity grouping) - no full lifeline probe
    (DNS/gateway/internet checks) needed just to list what's there."""
    out = []
    for name in _physical_nics():
        try:
            carrier = _carrier(name)
            carrier_error = None
        except NetworkProbeError as exc:
            carrier = None
            carrier_error = str(exc)
        try:
            driver_name = _driver_name(name)
            driver_bound = driver_name is not None
            wired = driver_name in WIRED_DRIVERS if driver_name is not None else None
            driver_error = None
        except NetworkProbeError as exc:
            driver_bound = None
            wired = None
            driver_error = str(exc)
        out.append({
            "name": name,
            "friendly": friendly_name(name),
            "driver_bound": driver_bound,
            "driver_error": driver_error,
            "carrier": carrier,
            "carrier_error": carrier_error,
            "wired": wired,
        })
    return out


def _bridge_members(brname: str):
    brif = Path("/sys/class/net") / brname / "brif"
    try:
        return [p.name for p in brif.iterdir()]
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise NetworkProbeError(f"could not inspect bridge members for {brname}: {exc}") from exc


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
        proc = subprocess.run(["ip", "-4", "route", "show", "default"],
                              capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise NetworkProbeError(f"default route query unavailable: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"ip exited with status {proc.returncode}").strip()
        raise NetworkProbeError(f"default route query failed: {detail}")
    out = proc.stdout
    routes = []
    for line in out.splitlines():
        parts = line.split()
        if not parts or parts[0] != "default" or "dev" not in parts:
            continue
        dev_index = parts.index("dev")
        if dev_index + 1 >= len(parts):
            continue
        gw = parts[parts.index("via") + 1] if "via" in parts and parts.index("via") + 1 < len(parts) else None
        routes.append((gw, parts[dev_index + 1]))
    if not routes:
        return None, None
    for gw, dev in routes:
        if _route_dev_is_live(dev, up_nics):
            return gw, dev
    return routes[0]


def _addr_for(ifname: str):
    try:
        proc = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", ifname],
                              capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise NetworkProbeError(f"address query unavailable for {ifname}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"ip exited with status {proc.returncode}").strip()
        raise NetworkProbeError(f"address query failed for {ifname}: {detail}")
    out = proc.stdout
    for line in out.splitlines():
        parts = line.split()
        if "inet" in parts:
            address_index = parts.index("inet") + 1
            if address_index >= len(parts):
                raise NetworkProbeError(f"malformed IPv4 address output from ip for {ifname}: {line!r}")
            cidr = parts[address_index]
            try:
                return str(ipaddress.ip_interface(cidr).ip)
            except ValueError as exc:
                raise NetworkProbeError(f"malformed IPv4 address from ip for {ifname}: {cidr!r}") from exc
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

    try:
        nics = _physical_nics()
    except NetworkProbeError as exc:
        record("nic_detected", False, f"physical NIC inventory unavailable: {exc}")
        return facts
    if not record("nic_detected", bool(nics), ", ".join(nics) or "no physical NIC found"):
        return facts

    up_nics = []
    carrier_errors = []
    for name in nics:
        try:
            if _carrier(name):
                up_nics.append(name)
        except NetworkProbeError as exc:
            carrier_errors.append(str(exc))
    if carrier_errors and not up_nics:
        record("carrier_present", False, f"carrier observation unavailable: {'; '.join(carrier_errors)}")
        return facts
    bound_drivers = []
    driver_errors = []
    for name in nics:
        try:
            if _driver_name(name) is not None:
                bound_drivers.append(name)
        except NetworkProbeError as exc:
            driver_errors.append((name, str(exc)))
    if not bound_drivers and driver_errors:
        record("driver_bound", False, "driver observation unavailable: " + "; ".join(
            f"{name}: {detail}" for name, detail in driver_errors))
        return facts
    unknown_names = {name for name, _detail in driver_errors}
    unbound = [name for name in nics if name not in bound_drivers and name not in unknown_names]
    driver_detail = f"bound={bound_drivers} unbound={unbound}"
    if driver_errors:
        driver_detail += " unknown=" + "; ".join(f"{name}: {detail}" for name, detail in driver_errors)
    if not record("driver_bound", bool(bound_drivers), driver_detail):
        return facts

    carrier_detail = f"up={up_nics} down={[n for n in nics if n not in up_nics]}"
    if carrier_errors:
        carrier_detail += f" unknown={carrier_errors}"
    if not record("carrier_present", bool(up_nics), carrier_detail):
        return facts

    try:
        gw, dev = _route_default(up_nics)
    except NetworkProbeError as exc:
        record("address_assigned", False, f"default route query unavailable: {exc}")
        return facts
    try:
        ip_addr = _addr_for(dev) if dev else None
    except NetworkProbeError as exc:
        record("address_assigned", False, f"address query unavailable: {exc}")
        return facts
    address_detail = (f"{dev}: {ip_addr}" if ip_addr else
                      (f"no IPv4 address assigned to {dev}" if dev else "no default-route device found; address cannot be attributed"))
    if not record("address_assigned", bool(ip_addr), address_detail):
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
