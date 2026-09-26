"""Live per-VM resource metrics via Proxmox's own `pvesh` CLI (Track A5,
the sensors + per-VM dashboard). Queries only - never creates, modifies,
or destroys any guest.

Deliberately reuses Proxmox's own already-running metrics collection and
its own retained RRD history rather than sampling independently - see
sensors_history.py for the host-hardware-sensor half of the dashboard,
which has no equivalent existing source and so needs its own small
periodic collector and store.

Goes through the same `Runner`-injectable subprocess boundary repair.py
established, so this is unit-testable with no real pvesh, no real
hardware, no root.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


def _parse_json(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


@dataclass
class VmStatus:
    vmid: int
    name: str = ""
    type: str = "qemu"  # "qemu" | "lxc"
    status: str = "unknown"
    cpu: float = 0.0
    mem: int = 0
    maxmem: int = 0
    disk: int = 0
    maxdisk: int = 0
    netin: int = 0
    netout: int = 0
    uptime: int = 0


def _list_guests(runner: Runner, node: str, kind: str) -> list:
    proc = runner.run(["pvesh", "get", f"/nodes/{node}/{kind}", "--output-format", "json"], timeout=10)
    if proc.returncode != 0:
        return []
    data = _parse_json(proc.stdout)
    return data if isinstance(data, list) else []


def list_vms(runner: Runner, node: str = "localhost") -> list:
    """Every QEMU VM and LXC container's current live status on `node`.
    Returns [] (never raises) if pvesh is unavailable or the node has
    zero guests - both normal, expected outcomes on a machine that
    hasn't created any VMs yet, not errors."""
    results = []
    for kind, type_name in (("qemu", "qemu"), ("lxc", "lxc")):
        for entry in _list_guests(runner, node, kind):
            results.append(VmStatus(
                vmid=entry.get("vmid", 0),
                name=entry.get("name", "") or "",
                type=type_name,
                status=entry.get("status", "unknown") or "unknown",
                cpu=entry.get("cpu", 0.0) or 0.0,
                mem=entry.get("mem", 0) or 0,
                maxmem=entry.get("maxmem", 0) or 0,
                disk=entry.get("disk", 0) or 0,
                maxdisk=entry.get("maxdisk", 0) or 0,
                netin=entry.get("netin", 0) or 0,
                netout=entry.get("netout", 0) or 0,
                uptime=entry.get("uptime", 0) or 0,
            ))
    return results


def vm_rrd_history(runner: Runner, node: str, vmid: int, vm_type: str = "qemu", timeframe: str = "hour") -> list:
    """Historical resource-usage samples for one VM/container, reusing
    Proxmox's own already-retained RRD data rather than a store of our
    own. Returns [] (never raises) on pvesh failure or no history yet."""
    proc = runner.run(
        ["pvesh", "get", f"/nodes/{node}/{vm_type}/{vmid}/rrddata",
         "--timeframe", timeframe, "--output-format", "json"],
        timeout=10,
    )
    if proc.returncode != 0:
        return []
    data = _parse_json(proc.stdout)
    return data if isinstance(data, list) else []
