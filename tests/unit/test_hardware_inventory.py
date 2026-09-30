"""Unit tests for hardware_inventory.py - full enumeration of every
real device on the machine, not a CPU/memory summary (direct
instruction, 2026-09-30: "All hardware must show, its not a cpu
memory dashboard").

No real lspci/lsusb/lsblk is ever invoked - FakeRunner supplies real
captured output shapes.
"""
from fake_runner import FakeProc, FakeRunner

import hardware_inventory as hi

LSPCI = (
    '0000:00:00.0 "Host bridge [0600]" "Advanced Micro Devices, Inc. [AMD] [1022]" '
    '"Raphael/Granite Ridge Root Complex [14d8]" -p00 "ASUSTeK Computer Inc. [1043]" "Device [8877]"\n'
    '0000:01:00.0 "VGA compatible controller [0300]" "NVIDIA Corporation [10de]" '
    '"GA104 [GeForce RTX 3070] [2484]" -p00 "ASUSTeK Computer Inc. [1043]" "Device [8877]"\n'
    '0000:0c:00.0 "Ethernet controller [0200]" "Intel Corporation [8086]" '
    '"Ethernet Controller I225-V [15f3]" -p00 "ASUSTeK Computer Inc. [1043]" "Device [8877]"\n'
    '0000:0d:00.0 "Non-Volatile memory controller [0108]" "Sandisk Corp [15b7]" '
    '"WD Black SN850 [5011]" -p02 "" ""\n'
)

LSUSB = (
    "Bus 002 Device 003: ID 046d:c52b Logitech, Inc. Unifying Receiver\n"
    "Bus 001 Device 002: ID 8087:0029 Intel Corp. AX200 Bluetooth\n"
)

LSBLK = (
    'NAME="sda" SIZE="4.5T" MODEL="ST5000DM003-2FH18L" SERIAL="WCV00YLT" TRAN="sata"\n'
    'NAME="nvme0n1" SIZE="1.8T" MODEL="Corsair MP400" SERIAL="212079230001307818BC" TRAN="nvme"\n'
)

IP_LINK = (
    '1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN \\    link/loopback 00:00:00:00:00:00\n'
    '2: eno1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP \\    link/ether a8:5e:45:cd:11:22\n'
)


def _runner(**extra):
    responses = [
        (lambda a: a[:1] == ["lspci"], FakeProc(0, LSPCI)),
        (lambda a: a[:1] == ["lsusb"], FakeProc(0, LSUSB)),
        (lambda a: a[:1] == ["lsblk"], FakeProc(0, LSBLK)),
        (lambda a: a[:2] == ["ip", "-o"], FakeProc(0, IP_LINK)),
    ]
    return FakeRunner(command_responses=responses, **extra)


# -- PCI ---------------------------------------------------------------

def test_collect_pci_returns_every_device_not_just_gpus():
    """The whole point: gpu_admin filters to GPU classes, this must not."""
    devices = hi.collect_pci(_runner())
    classes = {d.pci_class for d in devices}
    assert "Host bridge" in classes
    assert "VGA compatible controller" in classes
    assert "Ethernet controller" in classes
    assert "Non-Volatile memory controller" in classes
    assert len(devices) == 4


def test_collect_pci_reports_the_real_bound_kernel_driver():
    runner = _runner(files={
        "/sys/bus/pci/devices/0000:01:00.0/uevent":
            "DRIVER=nvidia\nPCI_CLASS=30000\nPCI_ID=10DE:2484\n",
    })
    devices = {d.address: d for d in hi.collect_pci(runner)}
    assert devices["0000:01:00.0"].kernel_driver == "nvidia"
    assert devices["0000:01:00.0"].driver_status == "nvidia"


def test_collect_pci_says_no_driver_bound_rather_than_going_silent():
    """A device with no driver is the single most useful thing this page
    can surface - it must never render as a blank field."""
    devices = {d.address: d for d in hi.collect_pci(_runner())}
    assert devices["0000:01:00.0"].kernel_driver is None
    assert devices["0000:01:00.0"].driver_status == "no driver bound"


def test_collect_pci_is_empty_not_an_exception_when_lspci_is_missing():
    runner = FakeRunner(command_responses=[(lambda a: a[:1] == ["lspci"], FakeProc(127, "", "not found"))])
    assert hi.collect_pci(runner) == []


def test_pci_devices_are_grouped_into_real_categories():
    groups = hi.group_pci(hi.collect_pci(_runner()))
    assert "Graphics" in groups
    assert "Network" in groups
    assert "Storage" in groups
    assert groups["Graphics"][0].model == "GA104 [GeForce RTX 3070]"


# -- USB ---------------------------------------------------------------

def test_collect_usb_returns_real_devices():
    devices = hi.collect_usb(_runner())
    assert len(devices) == 2
    assert devices[0].usb_id == "046d:c52b"
    assert "Unifying Receiver" in devices[0].description


def test_collect_usb_skips_root_hubs_but_keeps_real_peripherals():
    runner = FakeRunner(command_responses=[(
        lambda a: a[:1] == ["lsusb"],
        FakeProc(0, "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n" + LSUSB),
    )])
    devices = hi.collect_usb(runner)
    assert all("root hub" not in d.description for d in devices)
    assert len(devices) == 2


# -- Block -------------------------------------------------------------

def test_collect_block_returns_every_disk_with_identity():
    disks = hi.collect_block(_runner())
    assert len(disks) == 2
    assert disks[0].name == "sda"
    assert disks[0].serial == "WCV00YLT"
    assert disks[1].transport == "nvme"


# -- Network -----------------------------------------------------------

def test_collect_net_returns_interfaces_with_state():
    ifaces = {i.name: i for i in hi.collect_net(_runner())}
    assert ifaces["eno1"].state == "UP"
    assert ifaces["eno1"].mac == "a8:5e:45:cd:11:22"


def test_collect_net_excludes_loopback():
    assert all(i.name != "lo" for i in hi.collect_net(_runner()))


# -- Aggregate ---------------------------------------------------------

def test_collect_all_returns_every_category_and_never_raises():
    inv = hi.collect_all(_runner())
    assert set(inv) == {"pci", "usb", "block", "net"}
    assert inv["pci"] and inv["usb"] and inv["block"] and inv["net"]


def test_collect_all_with_every_tool_missing_returns_empty_lists_not_an_error():
    runner = FakeRunner(command_responses=[(lambda a: True, FakeProc(127, "", "not found"))])
    inv = hi.collect_all(runner)
    assert inv == {"pci": [], "usb": [], "block": [], "net": []}
