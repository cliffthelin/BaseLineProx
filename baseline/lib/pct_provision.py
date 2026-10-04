"""LXC container provisioning (Track A6, LXC half) - the complementary
primitive to vm_provision.py's full-VM half, for lightweight,
always-on Linux utility services (a future Guardian instance, or any
single-purpose service that doesn't need its own kernel).

Which specific app/service to actually run this way is explicitly not
decided by this module (see decision record 34's "Deferred,
explicitly" and its own follow-up record) - this is the generic
create/start/stop/destroy primitive, usable the moment a target is
chosen, not tied to any one app.

LXC containers share the host kernel and can only ever run Linux - the
wrong tool for "spin up any OS" (that's vm_provision.py's job), the
right tool here specifically because a small always-on service doesn't
need its own kernel and benefits from LXC's much lower overhead.

VMIDs are one shared namespace across both VMs and containers in
Proxmox - `next_free_vmid`/`next_free_vmid_argv` are imported directly
from `vm_provision` rather than reimplemented, since it's the same
real fact, not a coincidental duplicate.

Unlike `vm_provision.retire_vm_preserving_persistence`, this module
has **no** equivalent safe-retire helper yet: Track A4 proved the
disk-reassignment-before-destroy sequence for VMs by hand, but never
did the equivalent for a container's mount point, so this module does
not assert or guess at that command shape - it will be added once
that's actually proven, not fabricated now.
"""
from __future__ import annotations

from vm_provision import CommandResult, next_free_vmid, next_free_vmid_argv  # noqa: F401 - re-exported, same VMID namespace

from repair import Runner


DEFAULT_BRIDGE = "vmbr0"
DEFAULT_STORAGE = "local-lvm"


# ---------------------------------------------------------------------------
# Pure argv builders
# ---------------------------------------------------------------------------

def create_ct_argv(vmid, template: str, *, hostname: str, memory_mb: int = 512,
                    cores: int = 1, disk_gb: int = 4, bridge: str = DEFAULT_BRIDGE,
                    storage: str = DEFAULT_STORAGE, unprivileged: bool = True) -> list:
    return [
        "pct", "create", str(vmid), template,
        "--hostname", hostname,
        "--memory", str(memory_mb),
        "--cores", str(cores),
        "--rootfs", f"{storage}:{disk_gb}",
        "--net0", f"name=eth0,bridge={bridge},ip=dhcp",
        "--unprivileged", "1" if unprivileged else "0",
    ]


def start_ct_argv(vmid) -> list:
    return ["pct", "start", str(vmid)]


def stop_ct_argv(vmid) -> list:
    return ["pct", "stop", str(vmid)]


def destroy_ct_argv(vmid, *, purge: bool = True) -> list:
    argv = ["pct", "destroy", str(vmid)]
    if purge:
        argv.append("--purge")
    return argv


def list_available_templates_argv() -> list:
    return ["pveam", "available"]


# ---------------------------------------------------------------------------
# Runner-executed operations
# ---------------------------------------------------------------------------

def create_ct(runner: Runner, vmid, template: str, *, hostname: str, memory_mb: int = 512,
               cores: int = 1, disk_gb: int = 4, bridge: str = DEFAULT_BRIDGE,
               storage: str = DEFAULT_STORAGE, unprivileged: bool = True) -> CommandResult:
    argv = create_ct_argv(vmid, template, hostname=hostname, memory_mb=memory_mb,
                           cores=cores, disk_gb=disk_gb, bridge=bridge,
                           storage=storage, unprivileged=unprivileged)
    proc = runner.run(argv, timeout=60)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"pct create exited {proc.returncode}")
    return CommandResult(True, f"CT {vmid} ({hostname}) created from {template}")


def start_ct(runner: Runner, vmid) -> CommandResult:
    proc = runner.run(start_ct_argv(vmid), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"pct start exited {proc.returncode}")
    return CommandResult(True, f"CT {vmid} started")


def stop_ct(runner: Runner, vmid) -> CommandResult:
    proc = runner.run(stop_ct_argv(vmid), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"pct stop exited {proc.returncode}")
    return CommandResult(True, f"CT {vmid} stopped")


def destroy_ct(runner: Runner, vmid, *, purge: bool = True) -> CommandResult:
    proc = runner.run(destroy_ct_argv(vmid, purge=purge), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"pct destroy exited {proc.returncode}")
    return CommandResult(True, f"CT {vmid} destroyed")


def list_available_templates(runner: Runner) -> list:
    proc = runner.run(list_available_templates_argv(), timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(f"pveam available failed: {proc.stderr.strip()}")
    templates = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if parts:
            templates.append(parts[-1])
    return templates
