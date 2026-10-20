"""Start, shut down and details for the TUI's VMs tab (operator 2026-10-14).

Two fixed Proxmox commands per kind (`qm`/`pct` start and shutdown) and nothing a person types reaches one: the kind and action are
allowlisted and the ID must be a Proxmox-range integer. A clean shutdown only; forcing a machine off is left to the browser launcher,
which asks first."""
from __future__ import annotations

_TOOL = {"qemu": "qm", "lxc": "pct"}
_ACTIONS = ("start", "shutdown")
_KIND_WORDS = {"qemu": "virtual machine", "lxc": "container"}


def power_argv(kind, vmid, action) -> list:
    if kind not in _TOOL:
        raise ValueError("kind must be qemu or lxc")
    if action not in _ACTIONS:
        raise ValueError("action must be start or shutdown")
    if isinstance(vmid, bool) or not isinstance(vmid, int) or not 100 <= vmid <= 999_999_999:
        raise ValueError("the Proxmox ID must be a whole number from 100 up")
    return [_TOOL[kind], action, str(vmid)]


def allowed_action(vm):
    """What a row offers: start when stopped, shut down when running, nothing when the status is not known."""
    return {"stopped": "start", "running": "shutdown"}.get(vm.status)


def result_message(action: str, name: str, vmid: int, *, returncode, output: str) -> str:
    verb = action.capitalize()
    if returncode is None:
        return f"{verb} of {name} ({vmid}): Proxmox was unavailable; nothing was done."
    if returncode != 0:
        detail = (output or "").strip().splitlines()[-1:] or ["no detail given"]
        return f"{verb} of {name} ({vmid}) failed: {detail[0][:160]}"
    return f"{verb} requested for {name} ({vmid}). Proxmox reports the result in its task log; the table refreshes shortly."


def _gib(value) -> str:
    return f"{value / 2**30:.1f} GiB" if value is not None else "unknown"


def _mib(value) -> str:
    return f"{value // 2**20} MiB" if value is not None else "unknown"


def details(vm) -> str:
    cpu = f"{vm.cpu * 100:.1f}%" if vm.cpu is not None and vm.status == "running" else "unknown"
    memory = f"{_mib(vm.mem)} of {_mib(vm.maxmem)}" if vm.mem is not None and vm.maxmem is not None else "unknown"
    disk = f"{_gib(vm.disk)} of {_gib(vm.maxdisk)}" if vm.disk is not None and vm.maxdisk is not None else "unknown"
    uptime = f"{vm.uptime // 3600}h{(vm.uptime % 3600) // 60}m" if vm.uptime is not None else "unknown"
    rows = [("Name", vm.name or "unnamed"), ("Proxmox ID", str(vm.vmid)), ("Kind", _KIND_WORDS.get(vm.type, vm.type)),
            ("State", vm.status), ("CPU", cpu), ("Memory", memory), ("Disk", disk), ("Uptime", uptime)]
    return "\n".join(f"{k}: {v}" for k, v in rows)
