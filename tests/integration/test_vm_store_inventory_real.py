"""Live-path checks that invalid VM stores never appear as empty inventories."""
import unittest
import os

import vm_host
import proxmox_vm_host


class VmStoreInventoryRealTests(unittest.TestCase):
    def setUp(self):
        self.host = vm_host.VmHost(
            "/mnt/INSTALLER_CACHE/vms",
            persistence_store="/mnt/INSTALLER_CACHE/user-data",
            runtime_dir="/run/user/1000/baseline-inventory-check",
        )

    def test_vm_inventory_rejects_installer_cache_instead_of_reporting_empty(self):
        with self.assertRaisesRegex(vm_host.VmError, "INSTALLER_CACHE"):
            self.host.list_vms()

    def test_base_inventory_rejects_installer_cache_instead_of_reporting_empty(self):
        with self.assertRaisesRegex(vm_host.VmError, "INSTALLER_CACHE"):
            self.host.list_bases()

    def test_local_vm_inventory_rejects_an_unmounted_configured_volume(self):
        mount = "/mnt/baseline-dr229-unmounted"
        if os.path.ismount(mount):
            self.skipTest("chosen probe mountpoint is currently mounted")
        host = vm_host.VmHost(mount + "/vms", runtime_dir="/run/user/1000/baseline-inventory-check")
        with self.assertRaisesRegex(vm_host.VmError, "must be mounted"):
            host.list_vms()

    def test_proxmox_vm_inventory_rejects_an_unmounted_configured_volume(self):
        mount = "/mnt/baseline-dr229-unmounted-pve"
        if os.path.ismount(mount):
            self.skipTest("chosen probe mountpoint is currently mounted")
        host = proxmox_vm_host.ProxmoxVmHost(
            mount + "/vms", persistence_store="/mnt/baseline-dr229-unmounted-user",
            runtime_dir="/run/user/1000/baseline-inventory-check",
        )
        with self.assertRaisesRegex(vm_host.VmError, "must be mounted"):
            host.list_vms()


if __name__ == "__main__":
    unittest.main()
