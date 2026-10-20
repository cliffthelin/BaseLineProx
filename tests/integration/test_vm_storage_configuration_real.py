"""Real filesystem checks for VM storage configuration observation."""
import unittest

import vm_page
import vm_host
import baseline_web
import container_page


class VmStorageConfigurationRealTests(unittest.TestCase):
    def test_malformed_existing_config_is_not_reported_as_default_storage(self):
        with self.assertRaisesRegex(vm_host.VmError, "VM storage configuration.*could not be read"):
            vm_page.load_store("/proc/self/mounts", default="/var/lib/baseline/vms")

    def test_directory_config_is_not_reported_as_default_persistence_storage(self):
        with self.assertRaisesRegex(vm_host.VmError, "VM storage configuration.*could not be read"):
            vm_page.load_persistence_store("/etc", default="/var/lib/baseline/user-data")

    def test_real_vm_host_resolution_refuses_malformed_existing_config(self):
        with self.assertRaisesRegex(vm_host.VmError, "VM storage configuration.*could not be read"):
            baseline_web._vm_host_for({"vm_config_path": "/proc/self/mounts"})

    def test_storage_path_validation_rejects_system_and_installer_cache_paths(self):
        self.assertFalse(vm_page._valid_store_path("/etc/baseline"))
        self.assertFalse(vm_page._valid_store_path("/mnt/INSTALLER_CACHE/vms"))
        self.assertFalse(vm_page._valid_store_path("/mnt/BASELINE/../etc"))
        self.assertTrue(vm_page._valid_store_path("/mnt/USER_ADMIN/vms"))

    def test_missing_first_run_config_uses_the_declared_default(self):
        self.assertEqual(
            vm_page.load_store("/proc/baseline-no-such-config", default="/mnt/BASELINE/vms"),
            "/mnt/BASELINE/vms",
        )
        self.assertEqual(container_page.load_data("/proc/baseline-no-such-config"),
                         "/mnt/USER_ADMIN/ct-data")

    def test_vm_store_save_does_not_replace_unreadable_configuration(self):
        result = vm_page.save_store("/proc/self/mounts", "/mnt/USER_ADMIN/vms")
        self.assertFalse(result["ok"])
        self.assertIn("could not be read", result["message"])

    def test_container_config_read_errors_are_not_reported_as_default_data(self):
        with self.assertRaisesRegex(vm_host.VmError, "container data configuration.*could not be read"):
            container_page.load_data("/proc/self/mounts")
        with self.assertRaisesRegex(vm_host.VmError, "container data configuration.*could not be read"):
            container_page.load_data("/etc")
        with self.assertRaisesRegex(vm_host.VmError, "container data configuration.*could not be read"):
            container_page._read_config_document("/proc/self/mounts")

    def test_container_data_path_validation_rejects_disposable_and_system_paths(self):
        self.assertFalse(container_page._valid_data_path("/etc/baseline"))
        self.assertFalse(container_page._valid_data_path("/mnt/INSTALLER_CACHE/ct-data"))
        self.assertFalse(container_page._valid_data_path("/mnt/USER_ADMIN/../etc"))
        self.assertTrue(container_page._valid_data_path("/mnt/USER_ADMIN/ct-data"))


if __name__ == "__main__":
    unittest.main()
