"""The same VM library uses Proxmox for lifecycle, without a parallel QEMU process."""
import json
from pathlib import Path

import pytest

import proxmox_vm_host as pv
import vm_host as vh


class ProxmoxRunner:
    def __init__(self):
        self.calls = []
        self.running = False
        self.failed = None
        self.storages = []

    def __call__(self, argv):
        self.calls.append(argv)
        if self.failed and argv[:2] == self.failed:
            return 1, "", "real operation failed"
        if argv[:3] == ["pvesh", "get", "/cluster/nextid"]:
            return 0, "910", ""
        if argv[:3] == ["pvesh", "get", "/storage"]:
            return 0, json.dumps(self.storages), ""
        if argv[:2] == ["qemu-img", "create"]:
            Path(argv[-1] if argv[-1].startswith("/") else argv[-2]).write_bytes(b"qcow2")
        if argv[0] == "xorriso":
            Path(argv[argv.index("-o") + 1]).write_bytes(b"seed ISO")
        if argv[:2] == ["qm", "start"]:
            self.running = True
        if argv[:2] == ["qm", "stop"]:
            self.running = False
        if argv[:2] == ["qm", "status"]:
            return 0, "status: " + ("running" if self.running else "stopped"), ""
        return 0, "", ""


def host(tmp_path):
    run = ProxmoxRunner()
    h = pv.ProxmoxVmHost(tmp_path / "os", persistence_store=tmp_path / "user", run=run,
                         free_bytes=lambda p: 500 * vh.GIB)
    h.bases_dir.mkdir(parents=True)
    (h.bases_dir / "ubuntu.qcow2").write_bytes(b"base")
    return h, run


def test_guest_homepage_uses_the_host_bridge_address_not_the_browser_loopback(tmp_path):
    h, _ = host(tmp_path)
    h.run = lambda args: (0, json.dumps([{"addr_info": [
        {"family": "inet", "scope": "global", "local": "192.168.20.5"}
    ]}]), "")
    assert h.guest_homepage() == "https://192.168.20.5:8006"


def test_unknown_guest_homepage_is_left_for_the_operator_to_fill(tmp_path):
    h, _ = host(tmp_path)
    h.run = lambda args: (1, "", "bridge unavailable")
    assert h.guest_homepage() == ""


def test_vm_is_registered_with_two_separate_proxmox_storage_volumes_and_started_by_qm(tmp_path):
    h, run = host(tmp_path)
    h.create_overlay("desktop", base="ubuntu")
    create = next(a for a in run.calls if a[:2] == ["qm", "create"])
    assert create[2] == "910"
    assert create[create.index("--virtio0") + 1].startswith("baseline-os:")
    assert create[create.index("--virtio1") + 1].startswith("baseline-user:")
    assert "serial=baseline-home" in create[create.index("--virtio1") + 1]
    assert (h.store / "images" / "910" / "vm-910-disk-0.qcow2").is_file()
    assert (h.persistence_store / "images" / "910" / "vm-910-disk-1.qcow2").is_file()
    assert h.start("desktop")["running"]
    assert ["qm", "start", "910"] in run.calls
    assert not any(a[0] == "qemu-system-x86_64" for a in run.calls)
    h.force_stop("desktop")
    assert not h.status("desktop")["running"]


def test_rebuild_keeps_same_vmid_and_home_and_never_destroys_the_vm(tmp_path):
    h, run = host(tmp_path)
    spec = h.create_overlay("desktop", base="ubuntu")
    data = Path(spec["persistence_disk"])
    data.write_bytes(b"my documents")
    h.rollback("desktop")
    assert data.read_bytes() == b"my documents"
    assert h.status("desktop")["vmid"] == 910
    assert not any(a[:2] == ["qm", "destroy"] for a in run.calls)


def test_proxmox_failure_cannot_be_reported_as_success(tmp_path):
    h, run = host(tmp_path)
    h.create_overlay("desktop", base="ubuntu")
    run.failed = ["qm", "start"]
    with pytest.raises(vh.VmError, match="failed"):
        h.start("desktop")
    assert not h.status("desktop")["running"]


def test_existing_storage_with_the_wrong_path_is_not_adopted(tmp_path):
    h, run = host(tmp_path)
    run.storages = [{"storage": "baseline-user", "type": "dir", "path": "/wrong"}]
    with pytest.raises(vh.VmError, match="storage"):
        h.create_overlay("desktop", base="ubuntu")
    assert not any(a[0] in ("qm", "qemu-img") for a in run.calls)


def test_deleting_a_persistent_vm_is_explicitly_refused_until_safe_retirement_exists(tmp_path):
    h, run = host(tmp_path)
    h.create_overlay("desktop", base="ubuntu")
    with pytest.raises(vh.VmError, match="retained"):
        h.delete_vm("desktop")
    assert not any(a[:2] == ["qm", "destroy"] for a in run.calls)


def test_invalid_base_does_not_register_storage_or_reserve_a_vmid(tmp_path):
    h, run = host(tmp_path)
    with pytest.raises(vh.VmError, match="base"):
        h.create_overlay("desktop", base="missing")
    assert run.calls == []
    assert not h.names_dir.exists()


def test_resized_ubuntu_root_size_is_refreshed_in_proxmox_config(tmp_path):
    import ubuntu_environment as u
    h, run = host(tmp_path)
    h.base_path(u.BASE_NAME).write_bytes(b"source")
    u.create(h, "desktop", disk_gb=20, password_factory=lambda: b"throwaway", password_hasher=lambda _: "$6$salt$hash")
    assert ["qm", "disk", "rescan", "--vmid", "910"] in run.calls


def test_standard_proxmox_vm_uses_user_storage_without_a_backing_image(tmp_path):
    h, run = host(tmp_path)
    (tmp_path / "installer.iso").write_bytes(b"ISO")
    h.create_from_iso("standard", iso=str(tmp_path / "installer.iso"), disk_gb=10)
    root = h.disk_path("standard")
    assert root.is_relative_to(h.persistence_store)
    create = next(a for a in run.calls if a[:2] == ["qm", "create"])
    assert create[create.index("--virtio0") + 1].startswith("baseline-user:")
    assert "--virtio1" not in create
