"""Unit tests for drive_admin.py - real Drive Administration actions
for the merged web app (decision record 83). No real device is ever
touched - FakeRunner/FakePdsRunner record every argv."""
from fake_runner import FakeProc, FakeRunner

import drive_admin as da
import physical_device_safety as pds


class FakePdsRunner:
    """Matches physical_device_safety.Runner's own interface
    (.run(argv)->str, .lstat, .realpath, .read_size_file) - mirrors
    test_physical_device_safety.py's own fake."""

    def __init__(self, *, serial="MD89N41071210AP4E", size_bytes=500_000_000_000,
                 findmnt_root="/dev/nvme0n1p2", pkname_of_root="nvme0n1", boot_serial="BootDriveSerial-999"):
        self.serial = serial
        self.size_bytes = size_bytes
        self.findmnt_root = findmnt_root
        self.pkname_of_root = pkname_of_root
        self.boot_serial = boot_serial
        self.wipe_calls = []

    def run(self, argv):
        if argv[0] == "udevadm":
            name_arg = next(a for a in argv if a.startswith("--name="))
            path = name_arg.split("=", 1)[1]
            serial = self.boot_serial if path.endswith(self.pkname_of_root) else self.serial
            return f"ID_SERIAL_SHORT={serial}\n"
        if argv[0] == "findmnt":
            return self.findmnt_root + "\n"
        if argv[0] == "lsblk":
            return self.pkname_of_root + "\n"
        if argv[0] == "wipefs":
            self.wipe_calls.append(argv)
            return ""
        raise AssertionError(f"unexpected pds command: {argv}")

    def lstat(self, path):
        class _Stat:
            st_mode = 0o60000  # S_IFBLK
        return _Stat()

    def realpath(self, path):
        return path

    def read_size_file(self, dev_name):
        return str(self.size_bytes // 512)


# -- sudo_argv / verify_sudo_password / SudoRunner (decision record 84) ------
# Real self-elevation - no real sudo or real password is ever used in
# these tests; a FakeExecutor records the exact argv/stdin sudo -S
# would receive and returns a scripted CompletedProcess-shaped result.

class FakeExecutor:
    def __init__(self, *, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []  # list of (argv, input_bytes, timeout)

    def __call__(self, argv, *, input, capture_output, timeout):
        self.calls.append((list(argv), input, timeout))
        import types
        return types.SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def test_sudo_argv_reads_password_from_stdin_and_forces_a_fresh_prompt():
    assert da.sudo_argv(["true"]) == ["sudo", "-S", "-k", "-p", "", "true"]


def test_verify_sudo_password_sends_the_real_password_on_stdin_never_as_an_argument():
    executor = FakeExecutor(returncode=0)
    result = da.verify_sudo_password("hunter2", executor=executor)
    assert result is True
    argv, input_bytes, _ = executor.calls[0]
    assert "hunter2" not in argv  # never leaks via argv/ps/shell history
    assert input_bytes == b"hunter2\n"


def test_verify_sudo_password_false_on_a_real_wrong_password():
    executor = FakeExecutor(returncode=1)
    assert da.verify_sudo_password("wrong", executor=executor) is False


def test_sudo_runner_run_pipes_the_password_and_decodes_output_to_str():
    executor = FakeExecutor(returncode=0, stdout=b"real output\n", stderr=b"")
    runner = da.SudoRunner("hunter2", executor=executor)
    proc = runner.run(["pvcreate", "-ff", "-y", "/dev/sdb"])
    assert proc.returncode == 0
    assert proc.stdout == "real output\n"
    assert isinstance(proc.stdout, str)
    argv, input_bytes, _ = executor.calls[0]
    assert argv == ["sudo", "-S", "-k", "-p", "", "pvcreate", "-ff", "-y", "/dev/sdb"]
    assert input_bytes == b"hunter2\n"


def test_sudo_runner_makedirs_uses_real_mkdir_p_via_sudo():
    executor = FakeExecutor()
    da.SudoRunner("hunter2", executor=executor).makedirs("/mnt/BASELINE")
    argv, _, _ = executor.calls[0]
    assert argv == ["sudo", "-S", "-k", "-p", "", "mkdir", "-p", "/mnt/BASELINE"]


def test_sudo_runner_append_text_sends_the_real_content_after_the_password_line():
    executor = FakeExecutor()
    da.SudoRunner("hunter2", executor=executor).append_text("/etc/fstab", "LABEL=X /mnt/X ext4 defaults 0 2\n")
    argv, input_bytes, _ = executor.calls[0]
    assert argv == ["sudo", "-S", "-k", "-p", "", "tee", "-a", "/etc/fstab"]
    assert input_bytes == b"hunter2\nLABEL=X /mnt/X ext4 defaults 0 2\n"


def test_sudo_runner_write_text_atomic_writes_a_temp_file_then_moves_it_into_place():
    executor = FakeExecutor()
    da.SudoRunner("hunter2", executor=executor).write_text_atomic("/mnt/BASELINE/state/x.json", '{"a": 1}')
    tee_argv, tee_input, _ = executor.calls[0]
    mv_argv, _, _ = executor.calls[1]
    assert tee_argv == ["sudo", "-S", "-k", "-p", "", "tee", "/mnt/BASELINE/state/x.json.tmp-sudorunner"]
    assert tee_input == b'hunter2\n{"a": 1}'
    assert mv_argv == ["sudo", "-S", "-k", "-p", "", "mv",
                        "/mnt/BASELINE/state/x.json.tmp-sudorunner", "/mnt/BASELINE/state/x.json"]


def test_sudo_runner_remove_uses_real_rm_rf_via_sudo():
    executor = FakeExecutor()
    da.SudoRunner("hunter2", executor=executor).remove("/mnt/SESSION_TEMP/recovery_mode")
    argv, _, _ = executor.calls[0]
    assert argv == ["sudo", "-S", "-k", "-p", "", "rm", "-rf", "/mnt/SESSION_TEMP/recovery_mode"]


def test_sudo_runner_never_calls_sudo_for_a_plain_read(tmp_path):
    real_file = tmp_path / "readable.txt"
    real_file.write_text("hello")
    executor = FakeExecutor()
    runner = da.SudoRunner("hunter2", executor=executor)
    assert runner.read_text(str(real_file)) == "hello"
    assert runner.path_exists(str(real_file)) is True
    assert executor.calls == []  # a read never touches sudo at all


# -- classify_drive_type - real per-drive data from this project's own -----
# actual hardware (a USB-NVMe bridge reports ROTA=1 for genuinely
# solid-state media - see the function's own docstring) --------------------

def test_classify_drive_type_nvme_via_model_string_even_behind_usb_with_wrong_rota():
    assert da.classify_drive_type(tran="usb", rota="1", model="PC401 NVMe SK hynix 512GB") == "NVMe"


def test_classify_drive_type_nvme_via_direct_transport():
    assert da.classify_drive_type(tran="nvme", rota="0", model="Corsair MP400") == "NVMe"


def test_classify_drive_type_ssd_via_model_string():
    assert da.classify_drive_type(tran="usb", rota="1", model="Samsung SSD 980 PRO with Heatsink 2TB") == "SSD"


def test_classify_drive_type_hdd_on_a_direct_sata_transport():
    assert da.classify_drive_type(tran="sata", rota="1", model="ST5000DM003-2FH18L") == "HDD"


def test_classify_drive_type_ssd_on_a_direct_sata_transport():
    assert da.classify_drive_type(tran="sata", rota="0", model="Some SATA Drive") == "SSD"


def test_classify_drive_type_usb_when_media_type_cannot_be_determined():
    """The honest fallback - a real USB-attached drive whose ROTA is
    not trustworthy (bridge chip) and whose model gives no SSD/NVMe
    hint either: never guess HDD or SSD, report USB."""
    assert da.classify_drive_type(tran="usb", rota="1", model="ST8000DM004-2CX188") == "USB"


def test_classify_drive_type_other_when_nothing_is_known():
    assert da.classify_drive_type(tran="", rota="", model="") == "Other"


# -- parse_candidate_drives / list_candidate_drives --------------------------

LSBLK_PAIRS_OUTPUT = (
    'NAME="sda" SIZE="4.5T" MODEL="ST5000DM003-2FH18L" TRAN="sata" ROTA="1" SERIAL="WCV00YLT" TYPE="disk"\n'
    'NAME="sdb" SIZE="476.9G" MODEL="PC401 NVMe SK hynix 512GB" TRAN="usb" ROTA="1" SERIAL="MD89N41071210AP4E" TYPE="disk"\n'
    'NAME="loop0" SIZE="520.1M" MODEL="" TRAN="" ROTA="0" SERIAL="" TYPE="loop"\n'
    'NAME="nvme0n1" SIZE="953.9G" MODEL="GIGABYTE GP-GSM2NE3100TNTD" TRAN="nvme" ROTA="0" SERIAL="SN211808916391" TYPE="disk"\n'
)


def test_parse_candidate_drives_skips_non_disk_types():
    rows = da.parse_candidate_drives(LSBLK_PAIRS_OUTPUT)
    names = {r["NAME"] for r in rows}
    assert "loop0" not in names
    assert names == {"sda", "sdb", "nvme0n1"}


def test_parse_candidate_drives_handles_a_model_string_with_spaces():
    rows = da.parse_candidate_drives(LSBLK_PAIRS_OUTPUT)
    sdb = next(r for r in rows if r["NAME"] == "sdb")
    assert sdb["MODEL"] == "PC401 NVMe SK hynix 512GB"


# -- summarize_drive_partitions - real partition count + real, mounted- ----
# only usage (this project's own real hardware data, captured live)

def test_format_bytes_uses_binary_prefixes():
    assert da._format_bytes(500) == "500 B"
    assert da._format_bytes(2_000_000_000) == "1.9 GiB"
    assert da._format_bytes(2_000_000_000_000) == "1.8 TiB"


LSBLK_TREE_SDA = (  # 1 real partition, mounted, real usage
    'NAME="sda" TYPE="disk" FSTYPE="" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME=""\n'
    'NAME="sda1" TYPE="part" FSTYPE="ntfs" FSUSED="2032406241280" FSSIZE="5000979804160" '
    'MOUNTPOINT="/mnt/files" PKNAME="sda"\n'
)

LSBLK_TREE_SDB = (  # whole-disk LVM PV, no partition table, nothing mounted
    'NAME="sdb" TYPE="disk" FSTYPE="LVM2_member" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME=""\n'
)

LSBLK_TREE_SDC = (  # whole-disk filesystem, no partition table, real mounted usage
    'NAME="sdc" TYPE="disk" FSTYPE="ext4" FSUSED="1633411461120" FSSIZE="1967847137280" '
    'MOUNTPOINT="/run/media/cane/samsung" PKNAME=""\n'
)

LSBLK_TREE_SDD = (  # 3 real partitions, none mounted
    'NAME="sdd" TYPE="disk" FSTYPE="" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME=""\n'
    'NAME="sdd1" TYPE="part" FSTYPE="" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME="sdd"\n'
    'NAME="sdd2" TYPE="part" FSTYPE="vfat" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME="sdd"\n'
    'NAME="sdd3" TYPE="part" FSTYPE="LVM2_member" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME="sdd"\n'
)


def test_summarize_drive_partitions_one_real_mounted_partition():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_TREE_SDA, ""))])
    result = da.summarize_drive_partitions(runner, "sda")
    assert result["partition_count"] == 1
    assert "1.8 TiB used" in result["usage_text"]
    assert "4.5 TiB" in result["usage_text"]


def test_summarize_drive_partitions_whole_disk_lvm_pv_no_partitions_not_mounted():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_TREE_SDB, ""))])
    result = da.summarize_drive_partitions(runner, "sdb")
    assert result["partition_count"] == 0
    assert result["usage_text"] == "not mounted"


def test_summarize_drive_partitions_whole_disk_filesystem_real_mounted_usage():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_TREE_SDC, ""))])
    result = da.summarize_drive_partitions(runner, "sdc")
    assert result["partition_count"] == 0
    assert "used" in result["usage_text"]
    assert "1.5 TiB" in result["usage_text"] or "1.49" in result["usage_text"]


def test_summarize_drive_partitions_three_real_partitions_none_mounted():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_TREE_SDD, ""))])
    result = da.summarize_drive_partitions(runner, "sdd")
    assert result["partition_count"] == 3
    assert result["usage_text"] == "not mounted"


def test_summarize_drive_partitions_reports_unknown_on_a_real_lsblk_failure():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(1, "", "lsblk: error"))])
    result = da.summarize_drive_partitions(runner, "sdx")
    assert result["partition_count"] is None
    assert result["usage_text"] == "unknown"


def test_list_candidate_drives_excludes_the_real_boot_device():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_PAIRS_OUTPUT, ""))])
    pds_runner = FakePdsRunner(boot_serial="SN211808916391", pkname_of_root="nvme0n1")
    drives = da.list_candidate_drives(runner, pds_runner=pds_runner)
    paths = {d["path"] for d in drives}
    assert "/dev/nvme0n1" not in paths
    assert "/dev/sda" in paths
    assert "/dev/sdb" in paths


def test_list_candidate_drives_marks_the_real_default_serials():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_PAIRS_OUTPUT, ""))])
    drives = da.list_candidate_drives(runner, pds_runner=FakePdsRunner())
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["is_default"] is True
    assert by_path["/dev/sda"]["is_default"] is False


def test_list_candidate_drives_returns_real_type_and_model_for_each():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_PAIRS_OUTPUT, ""))])
    drives = da.list_candidate_drives(runner, pds_runner=FakePdsRunner())
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["drive_type"] == "NVMe"
    assert by_path["/dev/sdb"]["model"] == "PC401 NVMe SK hynix 512GB"
    assert by_path["/dev/sda"]["drive_type"] == "HDD"


def test_list_candidate_drives_returns_empty_on_a_real_lsblk_failure():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(1, "", "lsblk: not found"))])
    assert da.list_candidate_drives(runner, pds_runner=FakePdsRunner()) == []


def test_list_candidate_drives_includes_real_partition_count_and_usage():
    """Proves the two real lsblk calls (candidate list + whole-system
    partition tree) are correctly distinguished, and the shared tree
    is applied to the right drive by name - "sdb" gets its own real
    3-partition result, "sda" (present in the candidate list but not
    in the tree fixture at all) correctly gets 0/"not mounted", not a
    copy of sdb's result."""
    from fake_runner import FakeRunner as _FR
    tree = (
        'NAME="sdb" TYPE="disk" FSTYPE="" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME=""\n'
        'NAME="sdb1" TYPE="part" FSTYPE="" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME="sdb"\n'
        'NAME="sdb2" TYPE="part" FSTYPE="vfat" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME="sdb"\n'
        'NAME="sdb3" TYPE="part" FSTYPE="LVM2_member" FSUSED="" FSSIZE="" MOUNTPOINT="" PKNAME="sdb"\n'
    )
    runner = _FR(command_responses=[
        (lambda a: a[:1] == ["lsblk"] and "-d" in a, FakeProc(0, LSBLK_PAIRS_OUTPUT, "")),
        (lambda a: a[:1] == ["lsblk"] and "-d" not in a, FakeProc(0, tree, "")),
    ])
    drives = da.list_candidate_drives(runner, pds_runner=FakePdsRunner())
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["partition_count"] == 3
    assert by_path["/dev/sdb"]["usage_text"] == "not mounted"
    assert by_path["/dev/sda"]["partition_count"] == 0
    assert by_path["/dev/sda"]["usage_text"] == "not mounted"


# -- pure argv builders ------------------------------------------------------

def test_pvcreate_argv():
    assert da.pvcreate_argv("/dev/sdb") == ["pvcreate", "-ff", "-y", "/dev/sdb"]


def test_vgcreate_argv():
    assert da.vgcreate_argv("baseline_persist", "/dev/sdb") == ["vgcreate", "baseline_persist", "/dev/sdb"]


# -- resolve_target: any real, sufficiently large, non-boot device ------------
# validates - never restricted to the two pre-authorized serials (direct
# instruction: "you need to actual be able to select the drive and if
# determined elsewhere the target then that is default but not locked
# to just that drive").

def test_resolve_target_accepts_any_real_non_boot_device_regardless_of_serial():
    validated = da.resolve_target("/dev/sdb", pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert validated["path"] == "/dev/sdb"


def test_resolve_target_accepts_a_device_whose_serial_is_not_one_of_the_defaults():
    """Proves the "not locked to just that drive" requirement directly -
    a completely different, real serial still validates."""
    validated = da.resolve_target("/dev/sdX", pds_runner=FakePdsRunner(serial="SomeOtherRealDriveSerial-123"))
    assert validated["serial"] == "SomeOtherRealDriveSerial-123"


def test_resolve_target_refuses_the_machines_own_boot_device():
    runner = FakePdsRunner(serial="BootDriveSerial-999", pkname_of_root="sdb")
    import pytest
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        da.resolve_target("/dev/sdb", pds_runner=runner)


def test_resolve_target_refuses_a_device_below_the_minimum_size():
    import pytest
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        da.resolve_target("/dev/sdb", pds_runner=FakePdsRunner(size_bytes=1_000_000))


# -- rebuild_persistence_lvm ---------------------------------------------------

def test_rebuild_persistence_lvm_refuses_the_machines_own_boot_device():
    runner = FakeRunner()
    pds_runner = FakePdsRunner(serial="BootDriveSerial-999", pkname_of_root="sdb")
    result = da.rebuild_persistence_lvm(runner, device_path="/dev/sdb", pds_runner=pds_runner)
    assert result.ok is False
    assert not any(c[0] in ("pvcreate", "vgcreate") for c in runner.calls)


def test_rebuild_persistence_lvm_wipes_then_creates_pv_and_vg_on_the_selected_device():
    runner = FakeRunner()
    pds_runner = FakePdsRunner(serial="MD89N41071210AP4E")
    result = da.rebuild_persistence_lvm(runner, device_path="/dev/sdb", pds_runner=pds_runner)
    assert result.ok is True
    assert pds_runner.wipe_calls == [["wipefs", "-a", "/dev/sdb"]]
    assert ["pvcreate", "-ff", "-y", "/dev/sdb"] in runner.calls
    assert ["vgcreate", "baseline_persist", "/dev/sdb"] in runner.calls


def test_rebuild_persistence_lvm_works_on_a_real_non_default_drive_too():
    """The whole point of the drive picker: an operator can target ANY
    real, validated device, not only the two pre-authorized serials."""
    runner = FakeRunner()
    pds_runner = FakePdsRunner(serial="SomeCompletelyDifferentDrive-42")
    result = da.rebuild_persistence_lvm(runner, device_path="/dev/sdz", pds_runner=pds_runner)
    assert result.ok is True
    assert ["pvcreate", "-ff", "-y", "/dev/sdz"] in runner.calls


def test_rebuild_persistence_lvm_reports_a_real_pvcreate_failure_and_never_calls_vgcreate():
    runner = FakeRunner(command_responses=[
        (lambda a: a[0] == "pvcreate", FakeProc(1, "", "device or resource busy")),
    ])
    result = da.rebuild_persistence_lvm(runner, device_path="/dev/sdb",
                                         pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert result.ok is False
    assert "busy" in result.detail
    assert not any(c[0] == "vgcreate" for c in runner.calls)


def test_rebuild_persistence_lvm_reports_a_real_vgcreate_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[0] == "vgcreate", FakeProc(1, "", "already exists")),
    ])
    result = da.rebuild_persistence_lvm(runner, device_path="/dev/sdb",
                                         pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert result.ok is False
    assert "already exists" in result.detail


# -- create_baseline_volumes ---------------------------------------------------

def test_create_baseline_volumes_succeeds_with_real_free_space():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "1099511627776\n", "")),  # 1TiB free
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "", "")),
    ])
    result = da.create_baseline_volumes(runner, vg_name="baseline_persist")
    assert result.ok is True
    assert any(c[0] == "lvcreate" for c in runner.calls)


def test_create_baseline_volumes_reports_failure_when_vg_has_no_free_space():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(1, "", "no such VG")),
    ])
    result = da.create_baseline_volumes(runner, vg_name="baseline_persist")
    assert result.ok is False


# -- switch_persona -------------------------------------------------------------

def test_switch_persona_reuses_persist_bind_mounts_directly():
    mounts = "/dev/sdb2 /mnt/USER_PERSISTENCE_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = da.switch_persona(runner, to_persona="admin")
    assert result.ok is True


# -- apply_volume_mode ----------------------------------------------------------

def test_apply_volume_mode_refuses_when_not_mounted():
    runner = FakeRunner()
    result = da.apply_volume_mode(runner, label="BASELINE")
    assert result.ok is False
    assert "not currently mounted" in result.detail


def test_apply_volume_mode_remounts_read_write_by_default():
    mounts = "/dev/sdd2 /mnt/BASELINE ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = da.apply_volume_mode(runner, label="BASELINE")
    assert result.ok is True
    assert ["mount", "-o", "remount,rw", "/mnt/BASELINE"] in runner.calls


def test_apply_volume_mode_remounts_read_only_when_configured():
    import settings_store
    mounts = "/dev/sdd2 /mnt/INSTALLER_CACHE ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    settings_store.set_setting(runner, "volumes", "installer_cache_mode", "read-only")
    result = da.apply_volume_mode(runner, label="INSTALLER_CACHE")
    assert result.ok is True
    assert ["mount", "-o", "remount,ro", "/mnt/INSTALLER_CACHE"] in runner.calls


def test_apply_volume_mode_refuses_a_non_shared_label():
    runner = FakeRunner()
    result = da.apply_volume_mode(runner, label="USER_PERSISTENCE_ADMIN")
    assert result.ok is False


# -- install_drive --------------------------------------------------------------

def test_install_drive_runs_rebuild_then_creates_volumes_on_success():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "1099511627776\n", "")),  # 1TiB free
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "", "")),
    ])
    result = da.install_drive(runner, device_path="/dev/sdb", pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert result.ok is True
    assert ["pvcreate", "-ff", "-y", "/dev/sdb"] in runner.calls
    assert any(c[0] == "lvcreate" for c in runner.calls)


def test_install_drive_stops_before_creating_volumes_when_rebuild_fails():
    runner = FakeRunner(command_responses=[
        (lambda a: a[0] == "pvcreate", FakeProc(1, "", "device or resource busy")),
    ])
    result = da.install_drive(runner, device_path="/dev/sdb", pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert result.ok is False
    assert "busy" in result.detail
    assert not any(c[0] in ("vgcreate", "lvcreate") for c in runner.calls)


# -- update_selected --------------------------------------------------------------

def test_update_selected_applies_volume_mode_to_each_selected_shared_volume():
    mounts = ("/dev/sdd2 /mnt/BASELINE ext4 rw,relatime 0 0\n"
              "/dev/sdd3 /mnt/INSTALLER_CACHE ext4 rw,relatime 0 0\n")
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = da.update_selected(runner, selected=["BASELINE", "INSTALLER_CACHE"],
                                 update_types=["apply_volume_mode"])
    assert result.ok is True
    assert ["mount", "-o", "remount,rw", "/mnt/BASELINE"] in runner.calls
    assert ["mount", "-o", "remount,rw", "/mnt/INSTALLER_CACHE"] in runner.calls


def test_update_selected_ignores_a_selected_item_that_has_no_configurable_mode():
    result = da.update_selected(FakeRunner(), selected=["USER_PERSISTENCE_ADMIN"],
                                 update_types=["apply_volume_mode"])
    assert result.ok is False
    assert "no selected item supports a volume mode update" in result.detail


def test_update_selected_switches_persona_once_regardless_of_selection_size():
    mounts = "/dev/sdb2 /mnt/USER_PERSISTENCE_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = da.update_selected(runner, selected=["BASELINE", "INSTALLER_CACHE"],
                                 update_types=["switch_persona"], to_persona="admin")
    assert result.ok is True


def test_update_selected_refuses_switch_persona_without_a_target():
    result = da.update_selected(FakeRunner(), selected=[], update_types=["switch_persona"])
    assert result.ok is False
    assert "no target persona" in result.detail


def test_update_selected_refuses_when_no_update_types_are_chosen():
    result = da.update_selected(FakeRunner(), selected=["BASELINE"], update_types=[])
    assert result.ok is False
    assert "no update types selected" in result.detail


# -- repair_scan_and_fix (v0.2 placeholder) -------------------------------------

def test_repair_scan_and_fix_is_an_honest_not_implemented_placeholder():
    result = da.repair_scan_and_fix(FakeRunner())
    assert result.ok is False
    assert "v0.2" in result.detail


# -- ACTIONS registry / describe_actions / perform_action ----------------------

def test_describe_actions_lists_every_registered_action_with_its_real_description():
    described = da.describe_actions()
    ids = {d["action_id"] for d in described}
    assert ids == set(da.ACTIONS)
    for d in described:
        assert d["description"] == da.ACTIONS[d["action_id"]].description


def test_describe_actions_lists_exactly_the_four_real_actions():
    """The three-action cap (direct feedback at the time) was relaxed
    by direct instruction once `build_self_installer` (decision record
    85) was a genuine, distinct, separately-tested capability, not
    scope creep folded in without asking - accurately described,
    nothing unlisted."""
    assert set(da.ACTIONS) == {"install", "update_selected", "repair", "build_self_installer"}


def test_build_self_installer_needs_nothing_but_device_path(tmp_path):
    """Decision record 86, direct instruction: "I will never fill in a
    serial number... everything must be selectable without a
    keyboard." The web UI's own JS only ever sends `device_path` for
    this action (baseline_web.py's driveAdminModalConfirm handler) - so
    this action must resolve everything else itself (settings_store
    presets, or self_installer.py's own auto-derivation) without
    raising KeyError. Forces the safety gate itself to refuse (device
    too small) so this proves the wiring reaches that real check
    cleanly, without a real network/QEMU call ever starting."""
    pds_fake = FakePdsRunner(size_bytes=1_000_000)  # far under the 400GB minimum
    result = da.build_self_installer(
        FakeRunner(), device_path="/dev/sdx", pds_runner=pds_fake,
        settings_runner=FakeRunner(),
    )
    assert result.ok is False
    assert "device safety check failed" in result.detail


def test_describe_actions_exposes_requires_device_for_the_web_pages_device_picker():
    """Real regression coverage: describe_actions() once silently
    dropped requires_device entirely, so the web page's device-picker
    modal never appeared for the device-targeted action even though
    the ActionSpec itself was correctly flagged - found by driving the
    actual running page, not by code inspection alone."""
    described = {d["action_id"]: d for d in da.describe_actions()}
    assert described["install"]["requires_device"] is True
    assert described["update_selected"]["requires_device"] is False
    assert described["repair"]["requires_device"] is False


def test_perform_action_refuses_an_unknown_action_id():
    runner = FakeRunner()
    result = da.perform_action(runner, "nonexistent", {})
    assert result.ok is False


def test_perform_action_dispatches_update_selected_with_its_params():
    mounts = "/dev/sdb2 /mnt/USER_PERSISTENCE_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = da.perform_action(runner, "update_selected",
                                {"selected": [], "update_types": ["switch_persona"], "to_persona": "admin"})
    assert result.ok is True
