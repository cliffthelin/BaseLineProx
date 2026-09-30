"""Read-only host readiness report for the hardened-appliance work
(hardened-appliance-prd.md, H1). `collect` reads sysfs/procfs through an
injected reader and `evaluate` is pure, so neither changes anything on the
host. A host NVIDIA driver is reported as info only: which GPU mode applies
is the operator's choice (gpu_admin), never something detection decides.
"""
from __future__ import annotations

import os

_TOOLS = ("tpm2_pcrextend", "cryptsetup", "systemd-cryptenroll")
_DISPLAY_CLASS_PREFIX = "0x03"
_PCI = "/sys/bus/pci/devices"


def _finding(fid: str, status: str, detail: str) -> dict:
    return {"id": fid, "status": status, "detail": detail}


def _read(fs, path: str):
    try:
        return fs.read_text(path).strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _group_number(fs, dev: str):
    name = os.path.basename(fs.realpath(f"{dev}/iommu_group"))
    return int(name) if name.isdigit() else None


def collect(fs) -> dict:
    gpus = []
    for addr in sorted(fs.listdir(_PCI)):
        dev = f"{_PCI}/{addr}"
        if not (_read(fs, f"{dev}/class") or "").startswith(_DISPLAY_CLASS_PREFIX):
            continue
        driver = os.path.basename(fs.realpath(f"{dev}/driver"))
        gpus.append({
            "addr": addr,
            "vendor": (_read(fs, f"{dev}/vendor") or "").removeprefix("0x"),
            "driver": driver if driver != "driver" else None,
            "group": _group_number(fs, dev),
        })
    return {
        "cmdline": _read(fs, "/proc/cmdline") or "",
        "iommu_groups": len(fs.listdir("/sys/kernel/iommu_groups")),
        "gpus": gpus,
        "tpm_version": _read(fs, "/sys/class/tpm/tpm0/tpm_version_major"),
        "secure_boot": None,
        "tools": {t: fs.which(t) is not None for t in _TOOLS},
    }


def evaluate(snap: dict) -> list[dict]:
    out = []
    cmd = snap.get("cmdline", "")
    missing = [f for f in ("amd_iommu=on", "iommu=pt") if f not in cmd.split()]
    out.append(_finding("iommu-cmdline", "warn" if missing else "ok",
                        f"kernel cmdline lacks {', '.join(missing)}" if missing else "IOMMU flags set"))
    groups = snap.get("iommu_groups", 0)
    out.append(_finding("iommu-groups", "ok" if groups else "fail",
                        f"{groups} IOMMU groups" if groups else "no IOMMU groups: enable SVM/IOMMU in BIOS"))
    gpus = snap.get("gpus", [])
    has_igpu = any(g["vendor"] == "1002" for g in gpus)
    out.append(_finding("igpu-present", "ok" if has_igpu else "fail",
                        "AMD iGPU visible" if has_igpu else "no AMD iGPU on the PCI bus: enable it and set UMA frame buffer in BIOS"))
    nvidia = [g for g in gpus if g["vendor"] == "10de"]
    on_host = [g["addr"] for g in nvidia if g["driver"] == "nvidia"]
    out.append(_finding("nvidia-host-driver", "info" if on_host else "ok",
                        f"host nvidia driver bound to {', '.join(on_host)} (fine unless VFIO mode is chosen)" if on_host
                        else "no NVIDIA card on the host driver"))
    groups_seen = [g["group"] for g in nvidia if g["group"] is not None]
    shared = len(groups_seen) != len(set(groups_seen))
    out.append(_finding("gpu-group-isolation", "warn" if shared else "ok",
                        "NVIDIA cards share an IOMMU group" if shared else "each NVIDIA card has its own IOMMU group"))
    tpm = snap.get("tpm_version")
    out.append(_finding("tpm2", "ok" if tpm == "2" else "fail", f"TPM version {tpm}" if tpm else "no TPM found"))
    sb = snap.get("secure_boot")
    out.append(_finding("secure-boot", "ok" if sb else "warn", "Secure Boot on" if sb else "Secure Boot off or unknown"))
    for tool, present in sorted(snap.get("tools", {}).items()):
        out.append(_finding(f"tool-{tool}", "ok" if present else "warn", "installed" if present else "not installed"))
    return out
