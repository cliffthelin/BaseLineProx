"""How each supported operating system is created as a VM from its carried image (DR262).

A plan is what the launcher hands to the existing `create_iso` action: name, image, disk, memory, CPUs and firmware. The numbers are starting sizes for a desktop
install that the person can change afterwards (VM settings); they are not requirements published by the projects. Some systems cannot honestly be made as a plain
VM here, and then the entry says why instead of failing later: a refusal is a `blocked` reason, shown to the person, never a silent skip.
"""
from __future__ import annotations

GIB_MB = 1024
# id -> (disk_gb, memory_mb, cpus)
SIZES = {
    "omarchy": (64, 8192, 4),      # a Hyprland desktop on Arch with an encrypted-disk installer
    "cachyos": (64, 6144, 4),
    "debian": (32, 4096, 2),
    "nixos": (40, 4096, 2),
    "bazzite": (80, 8192, 4),      # a Fedora Atomic image, large on disk
    "ubuntu": (40, 4096, 2),
    "fydeos": (50, 4096, 4),
}
DEFAULT = (32, 4096, 2)
BLOCKED = {
    "qubes": "Qubes OS runs its own Xen hypervisor and wants the hardware to itself; it is not created as a plain VM here.",
}
PREBUILT = ("debian", "ubuntu", "nixos", "cachyos", "omarchy", "bazzite", "fydeos")        # systems with a ready-made base that can be used as a plain VM (DR267)
OVA_REASON = "this image is an appliance (OVA), not an installer ISO, and importing appliances is not built yet."
HOST_SHARE = 2         # a VM may be given at most half of the host's memory


def plan_for(entry: dict, *, image_carried: bool, host_mb=None, carried_as=None, base_carried: bool = False) -> dict:
    """{plan: {...}} or {blocked: reason} for one VM entry of the supported-OS list. `carried_as` is the image's name as the host lists it (a Proxmox volume name
    differs from the list's file name); the plan names the image that way, because that is what the create action looks up."""
    ident, iso = entry["id"], entry.get("iso") or ""
    if ident in BLOCKED:
        return {"blocked": BLOCKED[ident]}
    if base_carried and ident in PREBUILT:             # a ready-made base is carried: no installer to run
        disk_gb, memory_mb, cpus = SIZES.get(ident, DEFAULT)
        if host_mb is not None and memory_mb > host_mb // HOST_SHARE:
            memory_mb = max(2048, (host_mb // HOST_SHARE) // 512 * 512)
        return {"plan": {"name": ident, "prebuilt": True, "os": ident, "disk_gb": disk_gb, "memory_mb": memory_mb, "cpus": cpus, "firmware": "uefi"}}
    if not iso:
        return {"blocked": "the list names no image for it."}
    if iso.lower().endswith(".ova"):
        return {"blocked": OVA_REASON}
    if not image_carried:
        return {"blocked": f"its image ({iso}) is not carried on this machine."}
    disk_gb, memory_mb, cpus = SIZES.get(ident, DEFAULT)
    if host_mb is not None and memory_mb > host_mb // HOST_SHARE:
        fits = max(1024, (host_mb // HOST_SHARE) // 512 * 512)
        if fits < 2048:
            return {"blocked": f"this machine has {host_mb // GIB_MB} GiB of memory; too little to share with a desktop VM."}
        memory_mb = fits
    return {"plan": {"name": ident, "iso": carried_as or iso, "disk_gb": disk_gb, "memory_mb": memory_mb, "cpus": cpus, "firmware": "uefi"}}


def host_memory_mb() -> int | None:
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None
