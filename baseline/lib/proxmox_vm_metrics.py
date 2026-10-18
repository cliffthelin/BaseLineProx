"""Live per-VM resource metrics via Proxmox's own `pvesh` CLI (Track A5,
the sensors + per-VM dashboard). Queries only - never creates, modifies,
or destroys any VM or container.

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
import math
from dataclasses import dataclass

from repair import Runner


class MetricsError(RuntimeError):
    """REAL-001: Proxmox observation failed; absence cannot be inferred."""


def _read_list(runner, argv):
    try:
        proc = runner.run(argv, timeout=10)
    except Exception as exc:
        raise MetricsError("REAL-001: Proxmox metrics query unavailable") from exc
    if proc.returncode != 0:
        raise MetricsError(f"REAL-001: Proxmox metrics query failed (exit {proc.returncode})")
    try:
        data = json.loads(proc.stdout)
    except (TypeError, ValueError) as exc:
        raise MetricsError("REAL-001: Proxmox metrics returned invalid JSON") from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise MetricsError("REAL-001: Proxmox metrics returned an invalid list")
    return data


@dataclass
class VmStatus:
    vmid: int
    name: str = ""
    type: str = "qemu"  # "qemu" | "lxc"
    status: str = "unknown"
    cpu: float | None = None
    mem: int | None = None
    maxmem: int | None = None
    disk: int | None = None
    maxdisk: int | None = None
    netin: int | None = None
    netout: int | None = None
    uptime: int | None = None


def _list_machines(runner: Runner, node: str, kind: str) -> list:
    return _read_list(runner, ["pvesh", "get", f"/nodes/{node}/{kind}", "--output-format", "json"])


def list_vms(runner: Runner, node: str = "localhost") -> list:
    """Every QEMU VM and LXC container's current live status on `node`.
    Confirmed empty lists return []; failed observations raise MetricsError."""
    results = []
    for kind, type_name in (("qemu", "qemu"), ("lxc", "lxc")):
        for entry in _list_machines(runner, node, kind):
            if type(entry.get("vmid")) is not int or entry["vmid"] <= 0:
                raise MetricsError("REAL-001: Proxmox returned a missing or invalid VM identity")
            for key in ("cpu", "mem", "maxmem", "disk", "maxdisk", "netin", "netout", "uptime"):
                value = entry.get(key)
                if value is None:
                    continue
                valid_type = type(value) in (int, float) if key == "cpu" else type(value) is int
                if not valid_type or value < 0 or (type(value) is float and not math.isfinite(value)):
                    raise MetricsError(f"REAL-001: Proxmox returned an invalid {key} measurement")
            results.append(VmStatus(
                vmid=entry["vmid"],
                name=entry.get("name", "") or "",
                type=type_name,
                status=entry.get("status", "unknown") or "unknown",
                cpu=entry.get("cpu"),
                mem=entry.get("mem"),
                maxmem=entry.get("maxmem"),
                disk=entry.get("disk"),
                maxdisk=entry.get("maxdisk"),
                netin=entry.get("netin"),
                netout=entry.get("netout"),
                uptime=entry.get("uptime"),
            ))
    return results


def vm_rrd_history(runner: Runner, node: str, vmid: int, vm_type: str = "qemu", timeframe: str = "hour") -> list:
    """Historical resource-usage samples for one VM/container, reusing
    Proxmox's own already-retained RRD data rather than a store of our
    own. Failed observations raise MetricsError; confirmed empty history is []."""
    return _read_list(runner, [
        "pvesh", "get", f"/nodes/{node}/{vm_type}/{vmid}/rrddata",
        "--timeframe", timeframe, "--output-format", "json",
    ])


def running_cpu_history(runner, vms, *, window_s: float, node: str = "localhost", now=None) -> tuple:
    """(name, [cpu values], error) for the first running VM or container, from Proxmox's own retained data. The same call feeds the TUI's graph and the console's."""
    import time
    running = next((v for v in vms if v.status == "running"), None)
    if running is None:
        return "", [], ""
    since = (time.time() if now is None else now) - window_s
    try:
        samples = vm_rrd_history(runner, node, running.vmid, vm_type=running.type)
    except MetricsError as exc:
        return running.name, [], str(exc)
    return running.name, [s["cpu"] for s in samples if s.get("time", 0) >= since and isinstance(s.get("cpu"), (int, float))], ""
