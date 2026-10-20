"""Full hardware enumeration for the Hardware tab.

Direct instruction, 2026-09-30: "All hardware must show, its not a cpu
memory dashboard." `gpu_admin.detect_gpus` deliberately filters lspci
down to GPU classes; `diagnostics.py` covers sensors/NVMe/SMART only.
Neither answers "what is actually in this machine" - this module does,
across all four real buses: PCI, USB, block, network.

Collectors use injectable runners. Failed commands raise InventoryError;
collect_all retains successful observations and includes explicit errors. A device with no driver bound is the single most useful
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
    r'^\d+:\s+(?P<name>[^:@]+)[:@].*?state (?P<state>\S+).*?link/(?P<kind>\S+)(?:\s+(?P<mac>[0-9a-f:]{17}))?',
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
    driver_error: str | None = None

    @property
    def driver_status(self) -> str:
        if self.driver_error:
            return f"driver metadata unavailable: {self.driver_error}"
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


class InventoryError(RuntimeError):
    """REAL-006: hardware observation failed, not an empty bus."""


def require_bus_output(bus: str, output: str, *, allow_empty=False) -> str:
    """Reject blank command output where a running host must have devices."""
    if not isinstance(output,str):
        raise InventoryError(f"REAL-006: {bus} probe output unavailable")
    if not allow_empty and not output.strip():
        raise InventoryError(f"REAL-006: {bus} probe returned empty output")
    return output


def _run(runner, argv, timeout=15):
    try:
        proc = runner.run(argv, timeout=timeout)
    except Exception as exc:
        raise InventoryError(f"REAL-006: {argv[0]} probe unavailable") from exc
    if getattr(proc, "returncode", 1) != 0:
        raise InventoryError(f"REAL-006: {argv[0]} probe failed (exit {proc.returncode})")
    output = getattr(proc, "stdout", None)
    if not isinstance(output, str):
        raise InventoryError(f"REAL-006: {argv[0]} output unavailable")
    return output


def _kernel_driver_for(runner, pci_address: str) -> tuple[str | None, str | None]:
    """sysfs `uevent` carries `DRIVER=<name>` as plain text, so this
    needs only `read_text` - part of repair.Runner's own interface.
    The `driver` symlink would need `realpath`, which that interface
    does not define (it lives on physical_device_safety.Runner)."""
    try:
        content = runner.read_text(f"/sys/bus/pci/devices/{pci_address}/uevent")
    except Exception as exc:
        return None, type(exc).__name__
    for line in content.splitlines():
        if line.startswith("DRIVER="):
            return line[len("DRIVER="):].strip() or None, None
    return None, None


def collect_pci(runner) -> list:
    """Every PCI device, all classes - explicitly not gpu_admin's filter."""
    out = require_bus_output('PCI',_run(runner, ["lspci", "-Dmmnnk"]))
    devices = []
    for line in out.splitlines():
        if not line.strip():
            continue
        m = _LSPCI_LINE.match(line)
        if not m:
            raise InventoryError("REAL-006: lspci returned malformed device output")
        addr = m.group("addr")
        driver, driver_error = _kernel_driver_for(runner, addr)
        devices.append(PciDevice(
            address=addr,
            pci_class=m.group("pci_class"),
            vendor=m.group("vendor").strip(),
            model=m.group("model").strip(),
            pci_id=f'{m.group("vendor_id").lower()}:{m.group("device_id").lower()}',
            kernel_driver=driver,
            driver_error=driver_error,
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
    out = require_bus_output('USB',_run(runner, ["lsusb"]),allow_empty=True)
    devices = []
    for line in out.splitlines():
        if not line.strip():
            continue
        m = _LSUSB_LINE.match(line.strip())
        if not m:
            raise InventoryError("REAL-006: lsusb returned malformed device output")
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
    out = require_bus_output('block',_run(runner, ["lsblk", "-d", "-P", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN"]))
    disks = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            pairs = [kv.split("=", 1) for kv in shlex.split(line)]
            fields = dict(pairs)
        except ValueError as exc:
            raise InventoryError("REAL-006: lsblk returned malformed device output") from exc
        if (len(fields) != len(pairs)
                or set(fields) != {"NAME", "SIZE", "MODEL", "SERIAL", "TRAN"}
                or not fields["NAME"] or not fields["SIZE"]):
            raise InventoryError("REAL-006: lsblk returned malformed device output")
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
    out = require_bus_output('network',_run(runner, ["ip", "-o", "link", "show"]))
    ifaces = []
    for line in out.splitlines():
        if not line.strip():
            continue
        m = _IP_LINK_LINE.match(line.strip())
        if not m:
            raise InventoryError("REAL-006: ip returned malformed device output")
        name = m.group("name").strip()
        if name == "lo":
            continue
        ifaces.append(NetInterface(name=name, state=m.group("state"), mac=m.group("mac") or ""))
    return ifaces


def collect_all(runner) -> dict:
    """Keep successful bus results and explicitly report failed observations."""
    results = {}
    errors = []
    for name, collector in (("pci", collect_pci), ("usb", collect_usb),
                            ("block", collect_block), ("net", collect_net)):
        try:
            results[name] = collector(runner)
        except InventoryError as exc:
            results[name] = None
            errors.append({"bus": name, "error": str(exc)})
    if errors:
        results["errors"] = errors
    return results
