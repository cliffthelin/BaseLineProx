"""Compare inventory against actual host commands; no FakeRunner or fixtures."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import hardware_inventory
from repair import RealRunner


def verify():
    runner = RealRunner()
    links = json.loads(subprocess.check_output(["ip", "-j", "link", "show"], text=True))
    expected = {link["ifname"] for link in links if link["ifname"] != "lo"}
    observed = hardware_inventory.collect_net(runner)
    actual = {link.name for link in observed}
    assert actual == expected, {"missing": sorted(expected - actual), "unexpected": sorted(actual - expected)}
    pci = hardware_inventory.collect_pci(runner)
    expected_pci = {path.name for path in Path("/sys/bus/pci/devices").iterdir()}
    actual_pci = {device.address for device in pci}
    assert actual_pci == expected_pci, {"missing_pci": sorted(expected_pci - actual_pci)}
    for device in pci:
        driver = Path("/sys/bus/pci/devices", device.address, "driver")
        expected_driver = driver.resolve().name if driver.is_symlink() else None
        assert device.kernel_driver == expected_driver, device.address
    blocks = json.loads(subprocess.check_output(["lsblk", "-d", "-J", "-o", "NAME"], text=True))
    expected_disks = {disk["name"] for disk in blocks["blockdevices"] if not disk["name"].startswith("loop")}
    actual_disks = {disk.name for disk in hardware_inventory.collect_block(runner)}
    assert actual_disks == expected_disks, {"missing_disks": sorted(expected_disks - actual_disks)}
    print(json.dumps({"scope": "real host network/PCI/driver/block inventory; read-only",
                      "network_interfaces": sorted(actual), "pci_devices": len(pci),
                      "pci_driver_bindings_checked": len(pci), "block_devices": sorted(actual_disks)}))


if __name__ == "__main__":
    verify()
