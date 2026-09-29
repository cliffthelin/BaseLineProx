"""GPU Administration (decision record 94, direct instruction): real GPU
detection plus real, evidenced per-device mode compatibility - the same
"selectable, never typed" and "auto-detect the hardware, never
auto-decide the choice" principles `drive_admin.py` already established
for drives, applied to GPUs.

**What gets auto-detected, and what never does**: which physical GPUs
exist on this machine, and which of the real modes below are even
*possible* for each one, given real, live evidence (a sysfs file
existing, a render node present, a tool installed) - never which mode
the operator should use. A consumer GeForce card genuinely cannot do
vGPU/mdev splitting; that's not offered as a choice because offering it
would just fail, not because Baseline decided the "better" mode for
you. Every mode that IS genuinely possible stays a live, always-
reselectable choice - nothing gets locked in by having been detected or
previously chosen (direct instruction: "those choices don't
necessarily go away unless we force modes a user doesn't want").

**The six real modes** (researched directly, not assumed - see decision
record 94's own citations):

- `host_display` - this GPU drives a real monitor for the host itself.
  Only offered when the device actually has video output (a "3D
  controller"/compute-only card like a Tesla P40 has none).
- `vfio_passthrough` - the whole card handed to one VM via VFIO,
  exclusively. Generically available for any real, non-root-complex
  PCI GPU.
- `vgpu_mdev_split` - one physical GPU split into several mediated
  devices, each assigned to a different VM. Real signal:
  `/sys/bus/pci/devices/<addr>/mdev_supported_types/` existing and
  listing types means it works *right now*; a device's PCI ID being in
  `KNOWN_VGPU_CAPABLE_IDS` means the hardware supports it but the
  vGPU-enabled driver isn't currently loaded - two different, both
  honestly labeled, kinds of evidence, never collapsed into one bit.
- `sriov` - hardware-level virtual functions via
  `sriov_totalvfs` (nonzero when real).
- `virtio_gpu_shared` - paravirtual (VirGL/Venus), needs only a working
  DRM render node on the host - works on essentially any GPU with a
  loaded driver.
- `container_passthrough` - the whole card handed directly to one
  Podman/Docker container (NVIDIA Container Toolkit + CDI, or a plain
  `--device` for AMD/Intel). Needs a render node, and, for an NVIDIA
  card specifically, the container toolkit actually installed - checked
  for real, not assumed present.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import registry

TYPE_ID = "gpu_devices"

HOST_DISPLAY = "host_display"
VFIO_PASSTHROUGH = "vfio_passthrough"
VGPU_MDEV_SPLIT = "vgpu_mdev_split"
SRIOV = "sriov"
VIRTIO_GPU_SHARED = "virtio_gpu_shared"
CONTAINER_PASSTHROUGH = "container_passthrough"
ALL_MODES = (HOST_DISPLAY, VFIO_PASSTHROUGH, VGPU_MDEV_SPLIT, SRIOV, VIRTIO_GPU_SHARED, CONTAINER_PASSTHROUGH)

# Real, sourced seed of PCI [vendor:device] IDs known to support NVIDIA
# vGPU even when the currently-loaded driver isn't the vGPU-enabled one
# (so `mdev_supported_types` wouldn't exist yet to prove it live) - a
# seed, not the ceiling, matching every other manifest in this
# codebase's own "grows via registration, never guessed" precedent.
# 10de:1b38 = Tesla P40 (GP102GL) - confirmed vGPU-capable, NVIDIA
# Virtual GPU Software releases 5.0-16.x (decision record 94).
KNOWN_VGPU_CAPABLE_IDS = {
    "10de:1b38",  # Tesla P40
}


class Runner:
    def run(self, argv: list, timeout: float = 10) -> "GpuProc":
        raise NotImplementedError

    def path_exists(self, path: str) -> bool:
        raise NotImplementedError

    def listdir(self, path: str) -> list:
        raise NotImplementedError

    def realpath(self, path: str) -> str:
        raise NotImplementedError

    def which(self, name: str) -> str | None:
        raise NotImplementedError


@dataclass
class GpuProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class RealRunner(Runner):
    def run(self, argv, timeout=10):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return GpuProc(proc.returncode, proc.stdout, proc.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return GpuProc(returncode=-1, stderr=str(exc))

    def path_exists(self, path):
        return Path(path).exists()

    def listdir(self, path):
        return [p.name for p in Path(path).iterdir()] if Path(path).is_dir() else []

    def realpath(self, path):
        return str(Path(path).resolve())

    def which(self, name):
        return shutil.which(name)


@dataclass
class GpuDevice:
    pci_address: str
    pci_class: str          # e.g. "VGA compatible controller", "3D controller"
    vendor: str
    model: str
    pci_id: str              # "vvvv:dddd", e.g. "10de:1b38"
    kernel_driver: str | None
    render_node: str | None  # e.g. "/dev/dri/renderD128", or None


@dataclass
class ModeAvailability:
    mode: str
    available: bool
    evidence: str


# ---------------------------------------------------------------------------
# Detection - real lspci/sysfs parsing, no guessing where a live check
# is possible.
# ---------------------------------------------------------------------------

_LSPCI_LINE = re.compile(
    r'^(?P<addr>\S+)\s+"(?P<pci_class>[^"]+?)\s*\[[0-9a-fA-F]{4}\]"\s+'
    r'"(?P<vendor>[^"]+?)\s*\[(?P<vendor_id>[0-9a-fA-F]{4})\]"\s+'
    r'"(?P<model>[^"]+?)\s*\[(?P<device_id>[0-9a-fA-F]{4})\]"'
)
_GPU_CLASSES = ("VGA compatible controller", "3D controller", "Display controller")


def _parse_lspci(text: str) -> list:
    rows = []
    for line in text.splitlines():
        m = _LSPCI_LINE.match(line)
        if not m or m.group("pci_class") not in _GPU_CLASSES:
            continue
        rows.append(m.groupdict())
    return rows


def _render_node_for(runner: Runner, pci_address: str) -> str | None:
    if not runner.path_exists("/sys/class/drm"):
        return None
    for entry in runner.listdir("/sys/class/drm"):
        if not entry.startswith("renderD"):
            continue
        device_link = f"/sys/class/drm/{entry}/device"
        if not runner.path_exists(device_link):
            continue
        if runner.realpath(device_link).endswith(pci_address):
            return f"/dev/dri/{entry}"
    return None


def _kernel_driver_for(runner: Runner, pci_address: str) -> str | None:
    driver_link = f"/sys/bus/pci/devices/{pci_address}/driver"
    if not runner.path_exists(driver_link):
        return None
    return Path(runner.realpath(driver_link)).name


def detect_gpus(runner: Runner) -> list:
    """Every real GPU-class PCI device on this machine, right now - not
    cached, not assumed from a prior run. Call this fresh whenever the
    operator opens GPU Administration, same as
    `drive_admin.list_candidate_drives` does for drives."""
    proc = runner.run(["lspci", "-Dmmnnk"], timeout=15)
    if proc.returncode != 0:
        return []
    devices = []
    for row in _parse_lspci(proc.stdout):
        addr = row["addr"]
        devices.append(GpuDevice(
            pci_address=addr,
            pci_class=row["pci_class"],
            vendor=row["vendor"].strip(),
            model=row["model"].strip(),
            pci_id=f"{row['vendor_id'].lower()}:{row['device_id'].lower()}",
            kernel_driver=_kernel_driver_for(runner, addr),
            render_node=_render_node_for(runner, addr),
        ))
    return devices


def _mdev_evidence(runner: Runner, device: GpuDevice) -> ModeAvailability:
    mdev_path = f"/sys/bus/pci/devices/{device.pci_address}/mdev_supported_types"
    if runner.path_exists(mdev_path):
        types = runner.listdir(mdev_path)
        return ModeAvailability(VGPU_MDEV_SPLIT, True, f"active now - mdev types available: {types}")
    if device.pci_id in KNOWN_VGPU_CAPABLE_IDS:
        return ModeAvailability(
            VGPU_MDEV_SPLIT, True,
            f"hardware supports this ({device.model} is a known vGPU-capable card) but not "
            f"active right now - the vGPU-enabled driver isn't loaded")
    return ModeAvailability(VGPU_MDEV_SPLIT, False, "no known vGPU capability for this card")


def _sriov_evidence(runner: Runner, device: GpuDevice) -> ModeAvailability:
    path = f"/sys/bus/pci/devices/{device.pci_address}/sriov_totalvfs"
    if not runner.path_exists(path):
        return ModeAvailability(SRIOV, False, "no sriov_totalvfs - this device has no SR-IOV capability")
    proc = runner.run(["cat", path])
    try:
        total = int((proc.stdout or "0").strip())
    except ValueError:
        total = 0
    if total > 0:
        return ModeAvailability(SRIOV, True, f"sriov_totalvfs={total} - up to {total} virtual functions")
    return ModeAvailability(SRIOV, False, "sriov_totalvfs is 0")


def available_modes(runner: Runner, device: GpuDevice) -> list:
    """Every mode with its own honest evidence - real signals only,
    nothing silently assumed. The caller (a web UI, an API) shows the
    operator every `available=True` entry as a real, always-
    reselectable choice; `available=False` entries explain why a mode
    isn't offered, for troubleshooting, not hidden entirely."""
    has_video_output = device.pci_class == "VGA compatible controller"
    results = [
        ModeAvailability(HOST_DISPLAY, has_video_output,
                          "has real video output" if has_video_output
                          else f"{device.pci_class} - no video output, cannot drive a display"),
        ModeAvailability(VFIO_PASSTHROUGH, True, "generically available for a discrete PCI GPU"),
        _mdev_evidence(runner, device),
        _sriov_evidence(runner, device),
        ModeAvailability(VIRTIO_GPU_SHARED, device.render_node is not None,
                          f"render node {device.render_node}" if device.render_node
                          else "no DRM render node found for this device"),
    ]
    if device.render_node is None:
        results.append(ModeAvailability(CONTAINER_PASSTHROUGH, False, "no DRM render node found for this device"))
    elif "nvidia" in device.vendor.lower():
        toolkit = runner.which("nvidia-ctk") or runner.which("nvidia-container-cli")
        results.append(ModeAvailability(
            CONTAINER_PASSTHROUGH, toolkit is not None,
            f"NVIDIA Container Toolkit found at {toolkit}" if toolkit
            else "render node present, but the NVIDIA Container Toolkit (nvidia-ctk/nvidia-container-cli) "
                 "is not installed on this host"))
    else:
        results.append(ModeAvailability(CONTAINER_PASSTHROUGH, True, f"render node {device.render_node}"))
    return results


# ---------------------------------------------------------------------------
# Storage - registry.py directly (GLOBAL scope, dynamic per-device
# entries), same reasoning as network.py's interface aliases: the set
# of GPUs is hardware-dependent and only knowable per real machine, so
# it can't be a fixed settings_store.SettingDef schema. GLOBAL because
# "which mode this machine's substrate runs each GPU in" is a
# machine-wide hardware fact, not a per-persona preference.
# ---------------------------------------------------------------------------

def sync_detected_gpus(runner: Runner) -> list:
    """Detects every real GPU right now and syncs its definition
    (attributes: pci_class/vendor/model/render_node + the full,
    evidenced mode list) into the registry - never touching a
    previously-chosen mode (`value`), matching
    `registry.upsert_entry`'s own "value=None leaves an existing value
    untouched" contract. Returns the detected devices for immediate use
    by a caller that doesn't want a second registry round trip."""
    registry.register_type(TYPE_ID, "Real GPU devices detected on this machine (gpu_admin.py)",
                            default_scope=registry.GLOBAL)
    devices = detect_gpus(runner)
    for d in devices:
        modes = available_modes(runner, d)
        registry.upsert_entry(
            TYPE_ID, d.pci_address, scope=registry.GLOBAL,
            attributes={
                "pci_class": d.pci_class, "vendor": d.vendor, "model": d.model, "pci_id": d.pci_id,
                "kernel_driver": d.kernel_driver, "render_node": d.render_node,
                "modes": [{"mode": m.mode, "available": m.available, "evidence": m.evidence} for m in modes],
            },
        )
    return devices


def get_gpu_mode(pci_address: str) -> str | None:
    entry = registry.get_entry(TYPE_ID, pci_address, scope=registry.GLOBAL)
    return entry["value"] if entry is not None else None


def set_gpu_mode(pci_address: str, mode: str) -> None:
    """Refuses a mode that this specific device's own last-synced
    detection didn't mark available - real, per-device validation
    (mirroring settings_store.set_setting's own options enforcement),
    never a global "is this mode valid anywhere" check."""
    entry = registry.get_entry(TYPE_ID, pci_address, scope=registry.GLOBAL)
    if entry is None:
        raise KeyError(f"no detected GPU at {pci_address} - run sync_detected_gpus first")
    available = {m["mode"] for m in entry["attributes"]["modes"] if m["available"]}
    if mode not in available:
        raise ValueError(f"{pci_address} ({entry['attributes']['model']}) cannot run in {mode!r} - "
                          f"available modes: {sorted(available)}")
    registry.set_value(TYPE_ID, pci_address, mode, scope=registry.GLOBAL)


def list_gpus_with_modes(runner: Runner) -> list:
    """Fresh detection merged with each device's currently-chosen mode
    (if any) - what a real GPU Administration page renders."""
    devices = sync_detected_gpus(runner)
    result = []
    for d in devices:
        entry = registry.get_entry(TYPE_ID, d.pci_address, scope=registry.GLOBAL)
        result.append({
            "pci_address": d.pci_address, "pci_class": d.pci_class, "vendor": d.vendor, "model": d.model,
            "render_node": d.render_node, "modes": entry["attributes"]["modes"], "current_mode": entry["value"],
        })
    return result
