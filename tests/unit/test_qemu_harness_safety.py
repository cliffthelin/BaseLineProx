"""Static safety proof for the TestPersistence QEMU harness (Milestone
3, Phase A) - hostile paths and inputs. No QEMU is actually invoked by
this test file; run_qemu() is only exercised for its own argument/
binary validation, never actually launched."""
import os
import stat

import pytest

import qemu_harness_safety as h


@pytest.fixture
def root(tmp_path):
    return str(tmp_path)


# --- experiment root validation --------------------------------------------

def test_experiment_root_must_exist(tmp_path):
    with pytest.raises(h.HarnessSafetyError):
        h.validate_experiment_root(str(tmp_path / "does-not-exist"))


def test_experiment_root_rejects_a_symlink(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_dir)
    with pytest.raises(h.HarnessSafetyError):
        h.validate_experiment_root(str(link))


@pytest.mark.parametrize("prefix", ["/dev", "/proc", "/sys"])
def test_experiment_root_rejects_forbidden_prefixes(prefix):
    with pytest.raises(h.HarnessSafetyError):
        h.validate_experiment_root(prefix)


# --- image path validation: newly created files ----------------------------

def test_new_image_path_beneath_root_is_accepted(root):
    target = os.path.join(root, "TestSystem-A.qcow2")
    resolved = h.validate_image_path(root, target, must_be_new=True)
    assert resolved == os.path.realpath(target)


def test_new_image_path_must_not_already_exist(root):
    target = os.path.join(root, "existing.qcow2")
    with open(target, "wb"):
        pass
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, target, must_be_new=True)


def test_new_image_path_escaping_root_via_dotdot_is_rejected(tmp_path):
    experiment_root = tmp_path / "experiment"
    experiment_root.mkdir()
    outside = tmp_path / "outside.qcow2"
    escaping = str(experiment_root / ".." / "outside.qcow2")
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(str(experiment_root), escaping, must_be_new=True)
    assert not outside.exists()


def test_new_image_path_via_device_shaped_string_is_rejected(root):
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, "/dev/sdz1", must_be_new=True)


def test_new_image_path_with_symlinked_parent_directory_is_rejected(tmp_path):
    experiment_root = tmp_path / "experiment"
    experiment_root.mkdir()
    real_elsewhere = tmp_path / "elsewhere"
    real_elsewhere.mkdir()
    link_dir = experiment_root / "linked"
    link_dir.symlink_to(real_elsewhere)
    target = str(link_dir / "TestSystem-A.qcow2")
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(str(experiment_root), target, must_be_new=True)


# --- image path validation: existing files (attach/delete) ----------------

def test_existing_regular_file_beneath_root_is_accepted(root):
    target = os.path.join(root, "TestPersistenceDisk-001.qcow2")
    with open(target, "wb"):
        pass
    resolved = h.validate_image_path(root, target, must_be_new=False)
    assert resolved == os.path.realpath(target)


def test_missing_existing_path_is_rejected(root):
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, os.path.join(root, "nope.qcow2"), must_be_new=False)


def test_symlinked_image_is_rejected(root):
    real = os.path.join(root, "real.qcow2")
    with open(real, "wb"):
        pass
    link = os.path.join(root, "link.qcow2")
    os.symlink(real, link)
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, link, must_be_new=False)


def test_hard_linked_image_is_rejected(root):
    real = os.path.join(root, "real.qcow2")
    with open(real, "wb"):
        pass
    hardlink = os.path.join(root, "hardlink.qcow2")
    os.link(real, hardlink)
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, real, must_be_new=False)


def test_fifo_is_rejected(root):
    fifo_path = os.path.join(root, "a.fifo")
    os.mkfifo(fifo_path)
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, fifo_path, must_be_new=False)


def test_unix_socket_is_rejected(root):
    import socket
    sock_path = os.path.join(root, "a.sock")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(sock_path)
        with pytest.raises(h.HarnessSafetyError):
            h.validate_image_path(root, sock_path, must_be_new=False)
    finally:
        s.close()


def test_directory_is_rejected_not_a_regular_file(root):
    subdir = os.path.join(root, "subdir")
    os.mkdir(subdir)
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, subdir, must_be_new=False)


def test_mountpoint_is_rejected(root, monkeypatch):
    target = os.path.join(root, "mounted.qcow2")
    with open(target, "wb"):
        pass
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, target, must_be_new=False)


def test_path_outside_root_is_rejected(tmp_path):
    experiment_root = tmp_path / "experiment"
    experiment_root.mkdir()
    outside_file = tmp_path / "outside.qcow2"
    with open(outside_file, "wb"):
        pass
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(str(experiment_root), str(outside_file), must_be_new=False)


def test_device_shaped_existing_path_is_rejected_even_before_stat(root):
    with pytest.raises(h.HarnessSafetyError):
        h.validate_image_path(root, "/dev/null", must_be_new=False)


# --- QEMU argument builder never accepts physical-device-shaped input -----

def test_build_qemu_args_accepts_valid_synthetic_images(root):
    system_disk = os.path.join(root, "TestSystem-A.qcow2")
    persistence_disk = os.path.join(root, "TestPersistenceDisk-001.qcow2")
    for p in (system_disk, persistence_disk):
        with open(p, "wb"):
            pass
    args = h.build_qemu_args(root, system_disk=system_disk, persistence_disk=persistence_disk)
    assert not any("/dev/" in a for a in args)
    joined = " ".join(args)
    assert "TestSystem-A.qcow2" in joined
    assert "TestPersistenceDisk-001.qcow2" in joined


@pytest.mark.parametrize("hostile", [
    "/dev/sda", "/dev/sdb1", "/dev/nvme0n1", "/dev/mapper/foo", "/dev/disk/by-id/x",
])
def test_build_qemu_args_rejects_device_shaped_system_disk(root, hostile):
    with pytest.raises(h.HarnessSafetyError):
        h.build_qemu_args(root, system_disk=hostile)


def test_build_qemu_args_rejects_device_shaped_persistence_disk(root):
    system_disk = os.path.join(root, "TestSystem-A.qcow2")
    with open(system_disk, "wb"):
        pass
    with pytest.raises(h.HarnessSafetyError):
        h.build_qemu_args(root, system_disk=system_disk, persistence_disk="/dev/sdb")


def test_build_qemu_args_rejects_device_shaped_extra_arg(root):
    system_disk = os.path.join(root, "TestSystem-A.qcow2")
    with open(system_disk, "wb"):
        pass
    with pytest.raises(h.HarnessSafetyError):
        h.build_qemu_args(root, system_disk=system_disk, extra_args=("/dev/sdc",))


def test_build_qemu_args_rejects_proc_and_sys_extra_args(root):
    system_disk = os.path.join(root, "TestSystem-A.qcow2")
    with open(system_disk, "wb"):
        pass
    for hostile in ("/proc/self/mem", "/sys/class/block/sda"):
        with pytest.raises(h.HarnessSafetyError):
            h.build_qemu_args(root, system_disk=system_disk, extra_args=(hostile,))


# --- run_qemu binary allowlist, no host privilege tools --------------------

def test_run_qemu_rejects_non_allowlisted_binaries(root):
    for hostile_binary in ("sudo", "pkexec", "mount", "losetup", "udisksctl", "sh", "bash"):
        with pytest.raises(h.HarnessSafetyError):
            h.run_qemu(hostile_binary, [])


def test_run_qemu_rejects_device_shaped_args_even_for_allowed_binary(root):
    with pytest.raises(h.HarnessSafetyError):
        h.run_qemu("qemu-system-x86_64", ["-drive", "file=/dev/sda,format=raw"])


def test_allowed_binaries_set_has_no_privilege_or_mount_tools():
    forbidden = {"sudo", "pkexec", "polkit", "mount", "losetup", "udisks", "udisksctl"}
    assert forbidden.isdisjoint(h.QEMU_ALLOWED_BINARIES)


# --- bounded evidence hashing -----------------------------------------------

def test_hash_small_evidence_file_succeeds_under_cap(root):
    target = os.path.join(root, "ledger.json")
    with open(target, "w") as f:
        f.write('{"event": "TestGrant-001"}')
    digest = h.hash_small_evidence_file(target)
    assert len(digest) == 64  # sha256 hex


def test_hash_small_evidence_file_refuses_over_cap(root):
    target = os.path.join(root, "big.bin")
    with open(target, "wb") as f:
        f.write(b"\0" * (h.MAX_EVIDENCE_FILE_BYTES + 1))
    with pytest.raises(h.HarnessSafetyError):
        h.hash_small_evidence_file(target)


def test_hash_small_evidence_file_refuses_a_sparse_multi_gb_file_without_reading_it(root):
    """Proves the size check happens via stat before any read - a
    sparse multi-GB file must be refused instantly, not scanned."""
    target = os.path.join(root, "sparse.img")
    with open(target, "wb") as f:
        f.truncate(4 * 1024 * 1024 * 1024)  # 4GB sparse, allocates ~0 bytes
    with pytest.raises(h.HarnessSafetyError):
        h.hash_small_evidence_file(target)


# --- exact-path deletion, never recursive/glob -----------------------------

def test_delete_validated_image_removes_exactly_one_file(root):
    target = os.path.join(root, "TestSystem-A.qcow2")
    sibling = os.path.join(root, "TestPersistenceDisk-001.qcow2")
    for p in (target, sibling):
        with open(p, "wb"):
            pass
    h.delete_validated_image(root, target)
    assert not os.path.exists(target)
    assert os.path.exists(sibling)  # untouched - proves no glob/recursive behavior


def test_delete_validated_image_refuses_a_directory(root):
    subdir = os.path.join(root, "subdir")
    os.mkdir(subdir)
    with pytest.raises(h.HarnessSafetyError):
        h.delete_validated_image(root, subdir)
    assert os.path.isdir(subdir)  # never removed


def test_delete_validated_image_refuses_a_symlink(root):
    real = os.path.join(root, "real.qcow2")
    with open(real, "wb"):
        pass
    link = os.path.join(root, "link.qcow2")
    os.symlink(real, link)
    with pytest.raises(h.HarnessSafetyError):
        h.delete_validated_image(root, link)
    assert os.path.exists(real)  # the symlink target must survive a refused delete


# --- evidence sanitization --------------------------------------------------

def test_sanitize_evidence_text_strips_absolute_home_paths():
    text = "harness ran at /home/synthetic-test-user/experiments/run1"
    sanitized = h.sanitize_evidence_text(text)
    assert "/home/synthetic-test-user" not in sanitized
    assert "<redacted-host-path>" in sanitized


def test_sanitize_evidence_text_strips_removable_media_paths():
    text = "image lives at /run/media/synthetic-test-user/CACHE/baseline_repo"
    sanitized = h.sanitize_evidence_text(text)
    assert "/run/media/synthetic-test-user" not in sanitized


def test_sanitize_evidence_text_strips_caller_supplied_deny_substrings():
    text = "operator was synthetic-test-hostname during the run"
    sanitized = h.sanitize_evidence_text(text, deny_substrings=("synthetic-test-hostname",))
    assert "synthetic-test-hostname" not in sanitized
    assert "<redacted>" in sanitized


def test_sanitize_evidence_text_leaves_synthetic_identifiers_alone():
    text = "TestSystem-A created TestPersistence-001 with TestGrant-001"
    sanitized = h.sanitize_evidence_text(text)
    assert sanitized == text
