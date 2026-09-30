"""Full hardware enumeration for the Hardware tab.

Direct instruction, 2026-09-30: "All hardware must show, its not a cpu
memory dashboard." `gpu_admin.detect_gpus` deliberately filters lspci
down to GPU classes; `diagnostics.py` covers sensors/NVMe/SMART only.
Neither answers "what is actually in this machine" - this module does,
across all four real buses: PCI, USB, block, network.

Every collector is Runner-injected (repair.Runner / FakeRunner, this
project's established pattern) and never raises: a missing tool yields
an empty list plus, per device, an honest `driver_status` rather than a
blank field. A device with no driver bound is the single most useful
fact this page can surface for an installer operator, so it is stated
explicitly, never rendered as absence.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

_LSPCI_LINE = re.compile(
    r'^(?P<addr>\S+)\s+"(?P<pci_class>[^"]+?)\s*\[[0-9a-fA-F]{4}\]"\s+'
    r'"(?P<vendor>[^"]+?)\s*\[(?P<vendor_id>[0-9a-fA-F]{4})\]"\s+'
    r'"(?P<model>[^"]+?)\s*\[(?P<device_id>[0-9a-fA-F]{4})\]"'
)

_LSUSB_LINE = re.compile(
    r'^Bus (?P<bus>\d+) Device (?P<device>\d+): ID (?P<usb_id>[0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s*(?P<description>.*)$'
)

_IP_LINK_LINE = re.compile(
    r'^\d+:\s+(?P<name>[^:@]+)[:@].*?state (?P<state>\S+).*?link/(?P<kind>\S+)\s+(?P<mac>[0-9a-f:]{17})?',
    re.S,
)

# PCI class prefix -> the category an operator actually thinks in.
_PCI_GROUPS = (
    (("VGA compatible controller", "3D controller", "Display controller"), "Graphics"),
    (("Ethernet controller", "Network controller", "Wireless controller"), "Network"),
    (("Non-Volatile memory controller", "SATA controller", "RAID bus controller",
      "Mass storage controller", "IDE interface", "SCSI storage controller"), "Storage"),
    (("USB controller",), "USB Controllers"),
    (("Audio device", "Multimedia audio controller", "Multimedia controller"), "Audio"),
    (("Host bridge", "PCI bridge", "ISA bridge", "SMBus", "IOMMU",
      "Signal processing controller", "Encryption controller"), "System / Bridges"),
)


@dataclass
class PciDevice:
    address: str
    pci_class: str
    vendor: str
    model: str
    pci_id: str
    kernel_driver: str | None = None

    @property
    def driver_status(self) -> str:
        return self.kernel_driver or "no driver bound"


@dataclass
class UsbDevice:
    bus: str
    device: str
    usb_id: str
    description: str


@dataclass
class BlockDevice:
    name: str
    size: str = ""
    model: str = ""
    serial: str = ""
    transport: str = ""


@dataclass
class NetInterface:
    name: str
    state: str = ""
    mac: str = ""


def _run(runner, argv, timeout=15):
    """Real output, or None if the tool is absent/failed. Never raises."""
    try:
        proc = runner.run(argv, timeout=timeout)
    except Exception:
        return None
    return proc.stdout if getattr(proc, "returncode", 1) == 0 else None


def _kernel_driver_for(runner, pci_address: str) -> str | None:
    """sysfs `uevent` carries `DRIVER=<name>` as plain text, so this
    needs only `read_text` - part of repair.Runner's own interface.
    The `driver` symlink would need `realpath`, which that interface
    does not define (it lives on physical_device_safety.Runner)."""
    try:
        for line in runner.read_text(f"/sys/bus/pci/devices/{pci_address}/uevent").splitlines():
            if line.startswith("DRIVER="):
                return line[len("DRIVER="):].strip() or None
    except Exception:
        pass
    return None


def collect_pci(runner) -> list:
    """Every PCI device, all classes - explicitly not gpu_admin's filter."""
    out = _run(runner, ["lspci", "-Dmmnnk"])
    if out is None:
        return []
    devices = []
    for line in out.splitlines():
        m = _LSPCI_LINE.match(line)
        if not m:
            continue
        addr = m.group("addr")
        devices.append(PciDevice(
            address=addr,
            pci_class=m.group("pci_class"),
            vendor=m.group("vendor").strip(),
            model=m.group("model").strip(),
            pci_id=f'{m.group("vendor_id").lower()}:{m.group("device_id").lower()}',
            kernel_driver=_kernel_driver_for(runner, addr),
        ))
    return devices


def group_pci(devices: list) -> dict:
    """Groups by the category an operator thinks in, preserving
    _PCI_GROUPS order; anything unrecognized lands in "Other"."""
    groups: dict = {}
    for dev in devices:
        label = "Other"
        for classes, name in _PCI_GROUPS:
            if dev.pci_class in classes:
                label = name
                break
        groups.setdefault(label, []).append(dev)
    ordered = [name for _, name in _PCI_GROUPS] + ["Other"]
    return {name: groups[name] for name in ordered if name in groups}


def collect_usb(runner) -> list:
    """Real USB peripherals; root hubs are bus plumbing, not hardware
    an operator is looking for, so they are dropped."""
    out = _run(runner, ["lsusb"])
    if out is None:
        return []
    devices = []
    for line in out.splitlines():
        m = _LSUSB_LINE.match(line.strip())
        if not m:
            continue
        description = m.group("description").strip()
        if "root hub" in description.lower():
            continue
        devices.append(UsbDevice(
            bus=m.group("bus"), device=m.group("device"),
            usb_id=m.group("usb_id"), description=description,
        ))
    return devices


def collect_block(runner) -> list:
    """Whole disks only (-d): the drive inventory, not every partition."""
    out = _run(runner, ["lsblk", "-d", "-P", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN"])
    if out is None:
        return []
    disks = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            fields = dict(kv.split("=", 1) for kv in shlex.split(line) if "=" in kv)
        except ValueError:
            continue
        name = fields.get("NAME", "")
        if not name or name.startswith("loop"):
            continue
        disks.append(BlockDevice(
            name=name, size=fields.get("SIZE", ""), model=fields.get("MODEL", "").strip(),
            serial=fields.get("SERIAL", "").strip(), transport=fields.get("TRAN", "").strip(),
        ))
    return disks


def collect_net(runner) -> list:
    """Real interfaces, loopback excluded - it is never what the
    operator is configuring."""
    out = _run(runner, ["ip", "-o", "link", "show"])
    if out is None:
        return []
    ifaces = []
    for line in out.splitlines():
        m = _IP_LINK_LINE.match(line.strip())
        if not m:
            continue
        name = m.group("name").strip()
        if name == "lo":
            continue
        ifaces.append(NetInterface(name=name, state=m.group("state"), mac=m.group("mac") or ""))
    return ifaces


def collect_all(runner) -> dict:
    """Every bus at once. A failing collector yields [] for its own
    key and never hides the others."""
    return {
        "pci": collect_pci(runner),
        "usb": collect_usb(runner),
        "block": collect_block(runner),
        "net": collect_net(runner),
    }
