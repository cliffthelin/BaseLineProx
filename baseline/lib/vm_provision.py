"""Full-VM provisioning (Track A6 follow-on) - generalizes Track A4's
proven manual `qm` workflow into reusable, Runner-tested code.

Full VMs (`qm`), deliberately not LXC (`pct`): a container shares the
host kernel and can only ever run Linux, which contradicts this
project's stated "spin up any OS and collect data from it" goal
outright. LXC remains the right tool for a different job - lightweight
always-on Linux utility services - handled separately, not here.

Every pure command shape below has its own `*_argv` builder so the
exact `qm`/`pvesh` invocation is testable with no real Proxmox, no
root, and no real VM - goes through the same `Runner`-injectable
subprocess boundary `repair.py` established (see `proxmox_vm_metrics.py`
for the same convention applied to read-only queries; this module is
the create/attach/destroy half).

The destroy-without-losing-persistence ordering in
`retire_vm_preserving_persistence` is not a guess - it is exactly what
Track A4 proved live and by hand: `qm set --delete` alone leaves a
persistence-backed disk still "owned" by the doomed VMID (confirmed
via `qm help destroy`'s own text - `qm destroy` would delete it too),
so the disk is always reassigned to a fresh VMID via `qm disk move
<vmid> <unusedN> --target-vmid <new_vmid>` (a real `lvrename`, not a
copy) *before* the original VM is destroyed, never the other order -
and never destroyed at all if that reassignment fails.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


DEFAULT_BRIDGE = "vmbr0"
DEFAULT_VM_STORAGE = "local-lvm"
DEFAULT_PERSISTENCE_STORAGE = "baseline-persist"


@dataclass
class CommandResult:
    ok: bool
    detail: str


# ---------------------------------------------------------------------------
# Pure argv builders - the actual command contract, independent of any
# runner or real Proxmox.
# ---------------------------------------------------------------------------

def next_free_vmid_argv() -> list:
    return ["pvesh", "get", "/cluster/nextid"]


def create_vm_argv(vmid, name: str, *, iso: str, memory_mb: int = 2048,
                    cores: int = 2, disk_gb: int = 8,
                    bridge: str = DEFAULT_BRIDGE,
                    storage: str = DEFAULT_VM_STORAGE) -> list:
    return [
        "qm", "create", str(vmid),
        "--name", name,
        "--memory", str(memory_mb),
        "--cores", str(cores),
        "--net0", f"virtio,bridge={bridge}",
        "--scsi0", f"{storage}:{disk_gb}",
        "--ide2", f"{iso},media=cdrom",
        "--boot", "order=ide2;scsi0",
    ]


def attach_persistence_disk_argv(vmid, *, size_gb: int,
                                  storage: str = DEFAULT_PERSISTENCE_STORAGE,
                                  disk_slot: str = "scsi1") -> list:
    return ["qm", "set", str(vmid), f"--{disk_slot}", f"{storage}:{size_gb}"]


def start_vm_argv(vmid) -> list:
    return ["qm", "start", str(vmid)]


def stop_vm_argv(vmid) -> list:
    return ["qm", "stop", str(vmid)]


def reassign_persistence_disk_argv(old_vmid, unused_key: str, new_vmid) -> list:
    return ["qm", "disk", "move", str(old_vmid), unused_key, "--target-vmid", str(new_vmid)]


def destroy_vm_argv(vmid, *, purge: bool = True) -> list:
    argv = ["qm", "destroy", str(vmid)]
    if purge:
        argv.append("--purge")
    return argv


# ---------------------------------------------------------------------------
# Runner-executed operations - thin; all the actual command shape lives in
# the *_argv builders above so it's testable without a real qm/pvesh.
# ---------------------------------------------------------------------------

def next_free_vmid(runner: Runner) -> int:
    proc = runner.run(next_free_vmid_argv(), timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"pvesh get /cluster/nextid failed: {proc.stderr.strip()}")
    return int(proc.stdout.strip())


def create_vm(runner: Runner, vmid, name: str, *, iso: str, memory_mb: int = 2048,
               cores: int = 2, disk_gb: int = 8, bridge: str = DEFAULT_BRIDGE,
               storage: str = DEFAULT_VM_STORAGE) -> CommandResult:
    argv = create_vm_argv(vmid, name, iso=iso, memory_mb=memory_mb, cores=cores,
                           disk_gb=disk_gb, bridge=bridge, storage=storage)
    proc = runner.run(argv, timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"qm create exited {proc.returncode}")
    return CommandResult(True, f"VM {vmid} ({name}) created")


def attach_persistence_disk(runner: Runner, vmid, *, size_gb: int,
                             storage: str = DEFAULT_PERSISTENCE_STORAGE,
                             disk_slot: str = "scsi1") -> CommandResult:
    argv = attach_persistence_disk_argv(vmid, size_gb=size_gb, storage=storage, disk_slot=disk_slot)
    proc = runner.run(argv, timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"qm set exited {proc.returncode}")
    return CommandResult(True, f"persistence disk attached to VM {vmid} on {disk_slot} ({storage}:{size_gb})")


def start_vm(runner: Runner, vmid) -> CommandResult:
    proc = runner.run(start_vm_argv(vmid), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"qm start exited {proc.returncode}")
    return CommandResult(True, f"VM {vmid} started")


def stop_vm(runner: Runner, vmid) -> CommandResult:
    proc = runner.run(stop_vm_argv(vmid), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"qm stop exited {proc.returncode}")
    return CommandResult(True, f"VM {vmid} stopped")


def retire_vm_preserving_persistence(runner: Runner, old_vmid, new_vmid, *,
                                      unused_key: str, purge: bool = True) -> CommandResult:
    """The only safe way this module destroys a VM that has a
    persistence-backed disk attached - always reassigns the disk to
    `new_vmid` first, and never destroys `old_vmid` at all if that
    reassignment fails."""
    reassign = runner.run(reassign_persistence_disk_argv(old_vmid, unused_key, new_vmid), timeout=30)
    if reassign.returncode != 0:
        return CommandResult(
            False,
            f"disk reassignment failed, VM {old_vmid} NOT destroyed: {reassign.stderr.strip()}",
        )
    destroy = runner.run(destroy_vm_argv(old_vmid, purge=purge), timeout=30)
    if destroy.returncode != 0:
        return CommandResult(
            False,
            f"persistence disk reassigned to VM {new_vmid}, but destroying "
            f"VM {old_vmid} failed: {destroy.stderr.strip()}",
        )
    return CommandResult(True, f"VM {old_vmid} destroyed; persistence disk now owned by VM {new_vmid}")
