"""Pure ownership contract for the Proxmox retirement operation."""
import unittest

import proxmox_vm_host as pv
import vm_host as vh


class ProxmoxRetirementContractTests(unittest.TestCase):
    def setUp(self):
        self.record = {"vmid": 910}
        self.spec = {"recipe": "ubuntu-desktop", "persistence_disk": "/mnt/USER_ADMIN/images/910/vm-910-disk-1.qcow2"}
        self.config = {
            "name": "desktop",
            "virtio0": "baseline-os:910/vm-910-disk-0.qcow2,discard=on",
            "virtio1": "baseline-user:910/vm-910-disk-1.qcow2,serial=baseline-home",
            "ide2": "baseline-os:iso/desktop-installer.iso,media=cdrom",
        }

    def test_retirement_accepts_only_the_managed_root_and_retained_home(self):
        self.assertEqual(
            pv.retirement_volumes("desktop", self.spec, self.record, self.config),
            ["baseline-os:910/vm-910-disk-0.qcow2", "baseline-user:910/vm-910-disk-1.qcow2"],
        )

    def test_retirement_refuses_a_changed_retained_home_attachment(self):
        changed = dict(self.config, virtio1="baseline-user:911/other-disk.qcow2,serial=baseline-home")
        with self.assertRaisesRegex(vh.VmError, "retained-home attachment changed"):
            pv.retirement_volumes("desktop", self.spec, self.record, changed)

    def test_retirement_refuses_any_unowned_attached_volume(self):
        changed = dict(self.config, scsi0="other-storage:400/valuable-disk.raw")
        with self.assertRaisesRegex(vh.VmError, "additional attached volume"):
            pv.retirement_volumes("desktop", self.spec, self.record, changed)

    def test_retirement_refuses_unavailable_configuration(self):
        with self.assertRaisesRegex(vh.VmError, "configuration is unavailable"):
            pv.retirement_volumes("desktop", self.spec, self.record, None)

    def test_iso_vm_retirement_allows_only_its_root_and_cdrom(self):
        spec = {"iso": "/mnt/INSTALLER_CACHE/desktop.iso"}
        config = {
            "name": "desktop",
            "virtio0": "baseline-os:910/vm-910-disk-0.qcow2",
            "ide2": "baseline-os:iso/desktop-installer.iso,media=cdrom",
        }
        self.assertEqual(
            pv.retirement_volumes("desktop", spec, self.record, config),
            ["baseline-os:910/vm-910-disk-0.qcow2"],
        )

    def test_cluster_resource_lookup_requires_one_qemu_owner(self):
        resource = {"vmid": 910, "type": "qemu", "node": "pve"}
        self.assertEqual(pv._cluster_resource([resource], 910), resource)
        self.assertIsNone(pv._cluster_resource([], 910))
        with self.assertRaisesRegex(vh.VmError, "ambiguous"):
            pv._cluster_resource([resource, resource], 910)
        with self.assertRaisesRegex(vh.VmError, "non-VM"):
            pv._cluster_resource([dict(resource, type="lxc")], 910)
        with self.assertRaisesRegex(vh.VmError, "invalid cluster inventory"):
            pv._cluster_resource({"vmid": 910}, 910)

    def test_qm_config_parser_rejects_ambiguous_or_malformed_settings(self):
        self.assertEqual(pv._parse_qm_config("name: desktop\nvirtio0: baseline-os:910/disk.qcow2"),
                         {"name": "desktop", "virtio0": "baseline-os:910/disk.qcow2"})
        for value in ("", "name: desktop\nname: attacker", "not a setting"):
            with self.subTest(value=value), self.assertRaises(vh.VmError):
                pv._parse_qm_config(value)


if __name__ == "__main__":
    unittest.main()
