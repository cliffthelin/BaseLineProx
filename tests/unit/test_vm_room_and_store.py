"""A fresh drive's first VM, and where VM state goes (found in the QEMU rehearsal 2026-10-15).

1. Role volumes start at 1 GiB and grow on demand (volume_growth), but the VM library compared a new disk with the *current* free space, so on a
   fresh drive it refused every VM ("not enough free space for the standard VM disk"). It now asks the growth mechanism for room first.
2. DR257: VMs never write to USER_ADMIN. The default persistence store moves to USER_PERSONAL; a drive that already has VM records under the
   old USER_ADMIN default keeps using it, so nothing already created is orphaned (and Proxmox's `baseline-user` storage still matches)."""
from pathlib import Path

import pytest

import vm_host as vh
from test_vm_host import FakeRun

GIB = 2**30


def make(tmp_path, free, grow=None, persistence="/mnt/USER_PERSONAL/vm-data", store="/mnt/BASELINE/vm-runtime"):
    """A host whose stores are named like the real ones but live under tmp_path (the mount check is bypassed by naming)."""
    calls = {"free": dict(free)}
    host = vh.VmHost(tmp_path / "store", run=FakeRun(), spawn=lambda a: 1, is_alive=lambda p: False, qmp=lambda s, c: None,
                     kill=lambda p: None, sleep=lambda s: None, free_bytes=lambda p: calls["free"][str(p)],
                     cmdline=lambda p: [], runtime_dir=tmp_path / "run", persistence_store=tmp_path / "persist", grow_volume=grow)
    host._check_store = lambda path: None                                  # the real check wants /mnt/<LABEL> to be a mount point
    host._calls = calls
    return host


def stores(tmp_path):
    return str(tmp_path / "store"), str(tmp_path / "persist")


def test_without_a_growth_hook_a_short_volume_is_still_refused(tmp_path):
    s, p = stores(tmp_path)
    host = make(tmp_path, {s: 100 * GIB, p: 1 * GIB})
    with pytest.raises(vh.VmError, match="not enough free space"):
        host.create_from_iso("vm1", iso="/x.iso", disk_gb=4, memory_mb=1024, cpus=1)


def test_a_short_role_volume_is_grown_to_the_needed_room(tmp_path):
    grown, free = [], {"v": 1 * GIB}

    def grow(label, needed):
        grown.append((label, needed))
        free["v"] = 50 * GIB

    host = make(tmp_path, {}, grow=grow)
    host.free_bytes = lambda path: free["v"]
    host._ensure_room(Path("/mnt/USER_PERSONAL/vm-data"), 11 * GIB, "not enough free space for the standard VM disk")
    assert grown == [("USER_PERSONAL", 11 * GIB)]


def test_a_volume_that_cannot_grow_is_refused_with_the_growth_reason(tmp_path):
    def cannot(label, needed):
        raise RuntimeError("USER_PERSONAL would exceed its 64 GiB ceiling")
    host = make(tmp_path, {}, grow=cannot)
    host.free_bytes = lambda path: 1 * GIB
    with pytest.raises(vh.VmError, match="exceed its 64 GiB ceiling"):
        host._ensure_room(Path("/mnt/USER_PERSONAL/vm-data"), 11 * GIB, "not enough free space for the standard VM disk")


def test_growth_that_did_not_actually_make_room_is_still_a_refusal(tmp_path):
    host = make(tmp_path, {}, grow=lambda label, needed: None)
    host.free_bytes = lambda path: 1 * GIB
    with pytest.raises(vh.VmError, match="not enough free space"):
        host._ensure_room(Path("/mnt/USER_PERSONAL/vm-data"), 11 * GIB, "not enough free space for the standard VM disk")


def test_enough_room_never_calls_the_growth_hook(tmp_path):
    host = make(tmp_path, {}, grow=lambda label, needed: pytest.fail("grew a volume that had room"))
    host.free_bytes = lambda path: 500 * GIB
    host._ensure_room(Path("/mnt/USER_PERSONAL/vm-data"), 11 * GIB, "x")


@pytest.mark.parametrize("path", ["/var/lib/vms", "/mnt", "/mnt/lowercase/x", "/home/user/vm"])
def test_a_path_that_is_not_a_role_volume_is_never_offered_for_growth(tmp_path, path):
    host = make(tmp_path, {}, grow=lambda label, needed: pytest.fail("tried to grow a non-role path"))
    host.free_bytes = lambda p: 1 * GIB
    with pytest.raises(vh.VmError, match="not enough free space"):
        host._ensure_room(Path(path), 11 * GIB, "not enough free space for the standard VM disk")


def test_the_create_paths_ask_for_room_through_this_check_not_a_bare_comparison():
    text = (Path(vh.__file__)).read_text()
    assert text.count("self._ensure_room(") >= 3
    assert "if self.free_bytes(self.persistence_store) <" not in text and "if self.free_bytes(self.store) <" not in text


# --- where VM state goes -----------------------------------------------------------------------------------------------------------

def test_the_default_persistence_store_is_the_users_volume_never_user_admin():
    assert str(vh.DEFAULT_PERSISTENCE_STORE) == "/mnt/USER_PERSONAL/vm-data"
    assert "USER_ADMIN" not in str(vh.DEFAULT_PERSISTENCE_STORE)


def test_a_drive_that_already_has_vms_under_the_old_default_keeps_using_it(tmp_path):
    legacy = tmp_path / "USER_ADMIN" / "vm-data"
    (legacy / "control" / "machines").mkdir(parents=True)
    (legacy / "control" / "machines" / "ubuntu-desk.json").write_text("{}")
    assert vh.default_persistence_store(legacy=legacy) == legacy


def test_an_empty_or_missing_old_store_does_not_hold_a_drive_to_it(tmp_path):
    legacy = tmp_path / "USER_ADMIN" / "vm-data"
    assert vh.default_persistence_store(legacy=legacy) == vh.DEFAULT_PERSISTENCE_STORE
    (legacy / "control" / "machines").mkdir(parents=True)
    assert vh.default_persistence_store(legacy=legacy) == vh.DEFAULT_PERSISTENCE_STORE
