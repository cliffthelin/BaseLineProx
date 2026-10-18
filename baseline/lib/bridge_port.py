"""Point a bridge at a NIC that exists on this machine (ADR 0001's "not yet done" step).

An image installed under QEMU keeps the virtual NIC's name in `/etc/network/interfaces` (`bridge-ports ens4`); on real hardware that device
does not exist, the bridge has no port and the machine has no network. Run before networking starts, this finds each `bridge-ports` line whose
devices ALL are absent and, when exactly one wired NIC on this machine has a link, writes that NIC's name there. Nothing else changes:
a bridge with any existing port is left alone, an ambiguous or linkless machine is reported and left alone (the bridge was already unusable,
so a refusal never makes it worse), and the file is backed up before it is touched. Stdlib only, so it runs on the installed system as is.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

_PORTS = re.compile(r"^(?P<indent>[ \t]*)bridge[-_]ports[ \t]+(?P<value>[^#\r\n]+?)[ \t]*(?P<tail>#.*)?$")
LOG = Path("/var/log/baseline/bridge-port.log")


def _present(sys_net: Path) -> set:
    return {p.name for p in Path(sys_net).iterdir() if p.is_dir() or p.is_symlink()}


def wired_nics(sys_net) -> list:
    """Physical wired NICs: a real device behind it, not a bridge, not wireless, not a software device."""
    out = []
    for entry in sorted(Path(sys_net).iterdir()):
        if entry.name == "lo" or not entry.is_dir():
            continue
        if (entry / "bridge").exists() or (entry / "wireless").exists() or (entry / "phy80211").exists():
            continue
        if _not_ethernet(entry):
            continue
        if (entry / "device").exists():
            out.append(entry.name)
    return out


def _not_ethernet(entry: Path) -> bool:
    """A cellular modem (wwan), wireless, bridge, VLAN or bond is a network device with a device behind it, but never the wired uplink.
    PC601 on a Dell Latitude (2026-10-12) bridged the modem `wwp0s20f0u2i12` because it already reported a carrier, while the ethernet
    port beside it had no link yet."""
    if entry.name.startswith(("ww", "wl")):
        return True
    try:
        kind = dict(line.split("=", 1) for line in (entry / "uevent").read_text().splitlines() if "=" in line).get("DEVTYPE", "")
    except OSError:
        return False
    return kind in {"wwan", "wlan", "bridge", "vlan", "bond"}


def _on_usb(sys_net, name) -> bool:
    try:
        return "/usb" in str((Path(sys_net) / name / "device").resolve())
    except OSError:
        return False


def carrier(sys_net, name):
    """True/False, or None when the kernel will not say (link administratively down)."""
    try:
        return (Path(sys_net) / name / "carrier").read_text().strip() == "1"
    except OSError:
        return None


def plan(text: str, present: set, linked: list) -> dict:
    """Pure. `linked` are the wired NICs with a link. Which `bridge-ports` lines are broken, and what to do about them."""
    broken = []
    for number, line in enumerate(text.splitlines()):
        m = _PORTS.match(line)
        if not m:
            continue
        names = m["value"].split()
        if names and names != ["none"] and not any(n in present or any(c in n for c in "*?[") for n in names):
            broken.append({"line": number, "ports": names})
    if not broken:
        return {"action": "none", "reason": "every bridge has a port that exists"}
    if len(linked) == 1:
        return {"action": "rewrite", "nic": linked[0], "broken": broken}
    if not linked:
        return {"action": "none", "reason": "no wired NIC reports a link", "broken": broken}
    return {"action": "none", "reason": f"more than one wired NIC has a link ({', '.join(linked)}); not guessing", "broken": broken}


def rewrite(text: str, broken: list, nic: str) -> str:
    lines = text.splitlines(keepends=True)
    for item in broken:
        old = lines[item["line"]]
        m = _PORTS.match(old.rstrip("\r\n"))
        ending = old[len(old.rstrip("\r\n")):]
        lines[item["line"]] = f"{m['indent']}bridge-ports {nic}" + (f" {m['tail']}" if m["tail"] else "") + ending
    return "".join(lines)


def _write_backup(interfaces: Path, text: str, timestamp: int) -> Path:
    """Create a complete backup without replacing one from an earlier repair."""
    base = interfaces.with_name(interfaces.name + f".baseline-bridge-port.{timestamp}")
    suffix = 0
    while True:
        backup = base if suffix == 0 else base.with_name(base.name + f".{suffix}")
        try:
            with backup.open("x") as handle:
                handle.write(text)
            return backup
        except FileExistsError:
            suffix += 1


def _bring_up(names):
    failures = []
    for name in names:
        try:
            result = subprocess.run(
                ["ip", "link", "set", name, "up"], capture_output=True, text=True
            )
        except OSError as exc:
            failures.append({"nic": name, "error": str(exc)})
            continue
        if result.returncode:
            failures.append({
                "nic": name,
                "returncode": result.returncode,
                "stderr": (result.stderr or "").strip(),
            })
    return failures


def run(interfaces="/etc/network/interfaces", sys_net="/sys/class/net", *, bring_up=True, wait_seconds=15.0, log=None, now=time.time, reload=False) -> dict:
    """Find the machine's wired NICs, give links a few seconds to come up, decide, rewrite (with a backup) when it is unambiguous."""
    interfaces, text = Path(interfaces), Path(interfaces).read_text()
    nics = wired_nics(sys_net)
    present = _present(sys_net)
    bring_up_failures = []
    if "broken" not in plan(text, present, ["probe"]):
        result = {"action": "none", "reason": "every bridge has a port that exists"}
    else:
        if bring_up:
            bring_up_failures = _bring_up(nics)
        # Wait for all links to negotiate; the first carrier may be a dock adapter.
        deadline = time.monotonic() + wait_seconds
        while True:
            linked = [n for n in nics if carrier(sys_net, n)]
            if len(linked) == len(nics) or time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        if len(linked) > 1:                       # a docked laptop: the machine's own port and a dock's USB adapter; the own port is the uplink
            internal = [n for n in linked if not _on_usb(sys_net, n)]
            if len(internal) == 1:
                linked = internal
        result = plan(text, present, linked)
        if result.get("reason") == "no wired NIC reports a link" and bring_up_failures:
            failed = "; ".join(
                f"{item['nic']}: {item.get('stderr') or item.get('error') or 'ip link failed'}"
                for item in bring_up_failures
            )
            result["reason"] += f"; could not bring up {failed}"
        if result["action"] == "rewrite":
            backup = _write_backup(interfaces, text, int(now()))
            temporary = interfaces.with_name(interfaces.name + ".baseline-new")
            temporary.write_text(rewrite(text, result["broken"], result["nic"]))
            temporary.chmod(interfaces.stat().st_mode & 0o777)
            temporary.replace(interfaces)
            result["backup"] = str(backup)
            if reload:
                done = subprocess.run(["ifreload", "-a"], capture_output=True, text=True)
                result["reloaded"] = done.returncode == 0
    result.update(wired=nics, time=int(now()), bring_up_failures=bring_up_failures)
    path = Path(log) if log else LOG
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps(result) + "\n")
    except OSError:
        pass
    return result
