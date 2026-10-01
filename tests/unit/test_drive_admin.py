"""Unit tests for drive_admin.py - real Drive Administration actions
for the merged web app (decision record 83). No real device is ever
touched - FakeRunner/FakePdsRunner record every argv."""
import pytest
from fake_runner import FakeProc, FakeRunner

import drive_admin as da
from hitl_helpers import authorize, perform_confirmed
import drive_installer as di
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


# -- PkexecRunner (direct instruction, 2026-09-29: real OS-documented privilege ---
# escalation via PolicyKit, confirmed live on this machine - `pkexec whoami`
# genuinely returned `root` after authenticating through GNOME Shell's own
# built-in dialog, no password ever touching this process/app/HTTP request) ---

def test_pkexec_argv_wraps_the_real_command_with_no_password_anywhere():
    assert da.pkexec_argv(["true"]) == ["pkexec", "true"]


def test_pkexec_runner_run_decodes_output_and_never_sends_a_password():
    executor = FakeExecutor(returncode=0, stdout=b"real output\n", stderr=b"")
    runner = da.PkexecRunner(executor=executor)
    proc = runner.run(["pvcreate", "-ff", "-y", "/dev/sdb"])
    assert proc.returncode == 0
    assert proc.stdout == "real output\n"
    assert isinstance(proc.stdout, str)
    argv, input_bytes, _ = executor.calls[0]
    assert argv == ["pkexec", "pvcreate", "-ff", "-y", "/dev/sdb"]
    assert input_bytes == b""  # no password piped anywhere - pkexec's own agent collects it


def test_pkexec_runner_makedirs_uses_real_mkdir_p():
    executor = FakeExecutor()
    da.PkexecRunner(executor=executor).makedirs("/mnt/BASELINE")
    argv, _, _ = executor.calls[0]
    assert argv == ["pkexec", "mkdir", "-p", "/mnt/BASELINE"]


def test_pkexec_runner_append_text_sends_only_the_real_content_no_password_prefix():
    executor = FakeExecutor()
    da.PkexecRunner(executor=executor).append_text("/etc/fstab", "LABEL=X /mnt/X ext4 defaults 0 2\n")
    argv, input_bytes, _ = executor.calls[0]
    assert argv == ["pkexec", "tee", "-a", "/etc/fstab"]
    assert input_bytes == b"LABEL=X /mnt/X ext4 defaults 0 2\n"


def test_pkexec_runner_write_text_atomic_writes_a_temp_file_then_moves_it_into_place():
    executor = FakeExecutor()
    da.PkexecRunner(executor=executor).write_text_atomic("/mnt/BASELINE/state/x.json", '{"a": 1}')
    tee_argv, tee_input, _ = executor.calls[0]
    mv_argv, _, _ = executor.calls[1]
    assert tee_argv == ["pkexec", "tee", "/mnt/BASELINE/state/x.json.tmp-pkexecrunner"]
    assert tee_input == b'{"a": 1}'
    assert mv_argv == ["pkexec", "mv",
                        "/mnt/BASELINE/state/x.json.tmp-pkexecrunner", "/mnt/BASELINE/state/x.json"]


def test_pkexec_runner_remove_uses_real_rm_rf():
    executor = FakeExecutor()
    da.PkexecRunner(executor=executor).remove("/mnt/SESSION_TEMP/recovery_mode")
    argv, _, _ = executor.calls[0]
    assert argv == ["pkexec", "rm", "-rf", "/mnt/SESSION_TEMP/recovery_mode"]


def test_pkexec_runner_never_calls_pkexec_for_a_plain_read(tmp_path):
    real_file = tmp_path / "readable.txt"
    real_file.write_text("hello")
    executor = FakeExecutor()
    runner = da.PkexecRunner(executor=executor)
    assert runner.read_text(str(real_file)) == "hello"
    assert runner.path_exists(str(real_file)) is True
    assert executor.calls == []  # a read never touches pkexec at all


def test_pkexec_runner_as_pds_runner_implements_the_full_interface(tmp_path):
    adapter = da.PkexecRunner(executor=FakeExecutor()).as_pds_runner()
    real_file = tmp_path / "somefile"
    real_file.write_text("x")
    assert adapter.realpath(str(real_file)) == str(real_file.resolve())
    assert adapter.lstat(str(real_file)).st_size == 1
    assert isinstance(adapter._plain, pds.Runner)


# -- _SudoPdsAdapter (real bug found live) --------------------------------------

def test_sudo_pds_adapter_implements_lstat_and_realpath_for_real(tmp_path):
    """Real bug found live: this adapter used to implement only
    `run()`, crashing `physical_device_safety.validate_target_device`
    (which also calls `lstat`/`realpath`/`read_size_file`) the first
    time `build_self_installer`'s real `pds_runner` path was actually
    exercised against a real request - the client saw a silently
    broken connection ("nothing happened")."""
    adapter = da._SudoPdsAdapter(da.SudoRunner("unused", executor=FakeExecutor()))
    real_file = tmp_path / "somefile"
    real_file.write_text("x")
    assert adapter.realpath(str(real_file)) == str(real_file.resolve())
    st = adapter.lstat(str(real_file))
    assert st.st_size == 1


def test_sudo_pds_adapter_read_size_file_delegates_to_a_plain_unprivileged_runner():
    """None of lstat/realpath/read_size_file need real privilege -
    delegated to a plain physical_device_safety.Runner rather than
    reimplemented (and potentially re-broken) a second time here."""
    adapter = da._SudoPdsAdapter(da.SudoRunner("unused", executor=FakeExecutor()))
    assert isinstance(adapter._plain, pds.Runner)
    assert hasattr(adapter, "read_size_file")


def test_sudo_pds_adapter_run_still_goes_through_real_sudo():
    executor = FakeExecutor(stdout=b"real output\n")
    adapter = da._SudoPdsAdapter(da.SudoRunner("hunter2", executor=executor))
    assert adapter.run(["udevadm", "info"]) == "real output\n"
    assert executor.calls  # the real sudo path genuinely ran


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
    assert "/dev/sdb" in paths           # an allowed SK hynix drive


def test_list_candidate_drives_marks_the_real_default_serials():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_PAIRS_OUTPUT, ""))])
    drives = da.list_candidate_drives(runner, pds_runner=FakePdsRunner())
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["is_default"] is True


def test_list_candidate_drives_returns_real_type_and_model_for_each():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_PAIRS_OUTPUT, ""))])
    drives = da.list_candidate_drives(runner, pds_runner=FakePdsRunner())
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["drive_type"] == "NVMe"
    assert by_path["/dev/sdb"]["model"] == "PC401 NVMe SK hynix 512GB"
    assert "/dev/sda" not in by_path      # a hard disk outside the allowlist is never offered


def test_list_candidate_drives_returns_empty_on_a_real_lsblk_failure():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(1, "", "lsblk: not found"))])
    assert da.list_candidate_drives(runner, pds_runner=FakePdsRunner()) == []


def test_list_candidate_drives_includes_real_partition_count_and_usage():
    """Proves the two real lsblk calls (candidate list + whole-system
    partition tree) are correctly distinguished, and the shared tree
    is applied to the right drive by name - "sdb" gets its own real
    3-partition result. (Drives outside the allowlist are never offered,
    so the tree fixture only needs to cover the allowed one.)"""
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
    assert "/dev/sda" not in by_path


# -- pure argv builders ------------------------------------------------------

def test_pvcreate_argv():
    assert da.pvcreate_argv("/dev/sdb") == ["pvcreate", "-ff", "-y", "/dev/sdb"]


def test_vgcreate_argv():
    assert da.vgcreate_argv("baseline_persist", "/dev/sdb") == ["vgcreate", "baseline_persist", "/dev/sdb"]


# -- the allowlist: Baseline acts only on the SK hynix drives it is set up with --
# Direct instruction, 2026-10-01: "this can't have any effect outside of the SK
# hynix". This reverses an earlier recorded instruction that targets should not
# be locked to two drives (v0.2 row 55).

ALLOWED = ("MD89N41071210AP4E", "FD01N6557110C271B")


def test_resolve_target_accepts_each_allowed_drive():
    for serial in ALLOWED:
        validated = da.resolve_target("/dev/sdb", pds_runner=FakePdsRunner(serial=serial))
        assert validated["serial"] == serial


def test_resolve_target_refuses_every_other_drive():
    import pytest
    for other in ("SomeOtherRealDriveSerial-123", "ZCT2WCM2", "S6WRNS0TA12638A", ""):
        with pytest.raises(pds.PhysicalDeviceSafetyError):
            da.resolve_target("/dev/sdX", pds_runner=FakePdsRunner(serial=other))


def test_the_candidate_list_never_offers_a_drive_outside_the_allowlist():
    from fake_runner import FakeRunner as _FR
    runner = _FR(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK_PAIRS_OUTPUT, ""))])
    drives = da.list_candidate_drives(runner, pds_runner=FakePdsRunner())
    assert drives, "the allowed drive should still be offered"
    assert {d["path"] for d in drives} <= {"/dev/sdb"}
    assert "/dev/sda" not in {d["path"] for d in drives}


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


def test_rebuild_persistence_lvm_refuses_a_drive_outside_the_allowlist():
    """Baseline acts only on the SK hynix drives it is set up with (v0.2 row 55):
    a real, large, non-boot drive of any other make is refused and nothing runs."""
    runner = FakeRunner()
    pds_runner = FakePdsRunner(serial="SomeCompletelyDifferentDrive-42")
    result = da.rebuild_persistence_lvm(runner, device_path="/dev/sdz", pds_runner=pds_runner)
    assert result.ok is False
    assert runner.calls == []
    assert pds_runner.wipe_calls == []


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
        (lambda a: "vgs" in a, FakeProc(0, "1099511627776\n", "")),  # 1TiB free
        (lambda a: "lvs" in a, FakeProc(0, "", "")),
    ])
    result = da.create_baseline_volumes(runner, vg_name="baseline_persist")
    assert result.ok is True
    assert any(c[0] == "lvcreate" for c in runner.calls)


def test_create_baseline_volumes_reports_failure_when_vg_has_no_free_space():
    runner = FakeRunner(command_responses=[
        (lambda a: "vgs" in a, FakeProc(1, "", "no such VG")),
    ])
    result = da.create_baseline_volumes(runner, vg_name="baseline_persist")
    assert result.ok is False


# -- switch_persona -------------------------------------------------------------

def test_switch_persona_reuses_persist_bind_mounts_directly():
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
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
    settings_store.set_setting("volumes", "installer_cache_mode", "read-only")
    result = da.apply_volume_mode(runner, label="INSTALLER_CACHE")
    assert result.ok is True
    assert ["mount", "-o", "remount,ro", "/mnt/INSTALLER_CACHE"] in runner.calls


def test_apply_volume_mode_refuses_a_non_shared_label():
    runner = FakeRunner()
    result = da.apply_volume_mode(runner, label="USER_ADMIN")
    assert result.ok is False


# -- install_drive --------------------------------------------------------------

def test_install_drive_runs_rebuild_then_creates_volumes_on_success():
    runner = FakeRunner(command_responses=[
        (lambda a: "vgs" in a, FakeProc(0, "1099511627776\n", "")),  # 1TiB free
        (lambda a: "lvs" in a, FakeProc(0, "", "")),
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


# -- check_cache_updates / update_selected --------------------------------------
# Direct instruction, 2026-09-29: "Update selected" now means checking
# each selected Baseline volume for a newer compatible version of what
# it caches (not the old mount-mode/persona-switch behavior, which has
# no web-UI entry point anymore - see drive_admin.py's own comment on
# the removed "install"/"create_volumes_on_existing_vg" actions).

def test_check_cache_updates_returns_a_real_empty_list_not_a_fabricated_one():
    """No real "is a newer version available" source is wired up for
    any cached artifact yet - a real empty list, not a per-item
    "checked, nothing found" that was never actually checked."""
    assert da.check_cache_updates(FakeRunner()) == []


def test_update_selected_refuses_with_nothing_selected():
    result = da.update_selected(FakeRunner(), selected=[])
    assert result.ok is False
    assert "no volumes selected" in result.detail


def test_update_selected_is_an_honest_not_implemented_placeholder():
    result = da.update_selected(FakeRunner(), selected=["INSTALLER_CACHE"])
    assert result.ok is False
    assert "not implemented" in result.detail


# -- find_vg_for_device / detect_baseline_drive ---------------------------------

def test_find_vg_for_device_matches_by_prefix_since_a_pv_is_usually_a_partition():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
    ])
    assert da.find_vg_for_device(runner, "/dev/sdd") == "pve"


def test_find_vg_for_device_returns_none_when_the_drive_has_no_real_pv():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdb   baseline_persist\n", "")),
    ])
    assert da.find_vg_for_device(runner, "/dev/sdz") is None


def test_detect_baseline_drive_false_when_no_volume_group_exists():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "", "")),
    ])
    result = da.detect_baseline_drive(runner, "/dev/sdz")
    assert result["is_baseline_drive"] is False
    assert result["vg_name"] is None
    assert result["missing_baseline_volumes"] == []


def test_detect_baseline_drive_true_and_lists_missing_volumes_for_a_partial_install():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: "lvs" in a, FakeProc(0, "  pve  root\n  pve  baseline_app_state\n", "")),
    ])
    result = da.detect_baseline_drive(runner, "/dev/sdd")
    assert result["is_baseline_drive"] is True
    assert result["vg_name"] == "pve"
    assert "baseline_installer_cache" in result["missing_baseline_volumes"]
    assert "baseline_app_state" not in result["missing_baseline_volumes"]


def test_detect_baseline_drive_false_when_volume_group_exists_but_has_no_baseline_volumes():
    """A real Proxmox host with no Baseline install on it yet - has a
    VG, but none of the real Baseline volumes."""
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: "lvs" in a, FakeProc(0, "  pve  root\n", "")),
    ])
    result = da.detect_baseline_drive(runner, "/dev/sdd")
    assert result["is_baseline_drive"] is False
    assert result["missing_baseline_volumes"] == []


# -- repair_scan_and_fix (real, per-drive) --------------------------------------

def test_repair_scan_and_fix_refuses_when_the_drive_has_no_real_volume_group():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "", "")),
    ])
    result = da.repair_scan_and_fix(runner, device_path="/dev/sdz")
    assert result.ok is False
    assert "no real LVM volume group" in result.detail


def test_repair_scan_and_fix_reports_nothing_to_repair_when_already_complete():
    all_lvs = "\n".join(f"  pve  {lv}" for lv, *_ in di.BASELINE_VOLUMES)
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: "lvs" in a, FakeProc(0, all_lvs + "\n", "")),
    ])
    result = da.repair_scan_and_fix(runner, device_path="/dev/sdd")
    assert result.ok is True
    assert "nothing to repair" in result.detail


def test_repair_scan_and_fix_creates_only_what_is_actually_missing():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: "lvs" in a, FakeProc(0, "  pve  root\n", "")),
        (lambda a: "vgs" in a, FakeProc(0, "600000000000\n", "")),  # 600GB free
    ])
    result = da.repair_scan_and_fix(runner, device_path="/dev/sdd")
    assert result.ok is True
    assert any(c[0] == "lvcreate" for c in runner.calls)
    assert not any(c[0] in ("pvcreate", "vgcreate", "wipefs") for c in runner.calls)


# -- mount_logical_volume / unmount_logical_volume (direct instruction, 2026- ---
# 09-29: "The application has to handle not manual scripts nobody will
# remember" - a real, discoverable, repeatable feature instead) --------------

def test_mount_logical_volume_activates_the_vg_and_mounts_read_write():
    runner = FakeRunner(
        files={"/dev/pve/root": "x"},
        command_responses=[
            (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
            (lambda a: a[:1] == ["vgchange"], FakeProc(0, "  7 logical volume(s) active\n", "")),
            (lambda a: a[:1] == ["mount"], FakeProc(0, "", "")),
        ],
    )
    result = da.mount_logical_volume(runner, device_path="/dev/sdd")
    assert result.ok is True
    assert "/dev/pve/root mounted read-write at /mnt/pve-root-inspect" in result.detail
    assert ["vgchange", "-ay", "pve"] in runner.calls
    assert ["mount", "-o", "rw", "/dev/pve/root", "/mnt/pve-root-inspect"] in runner.calls
    assert "/mnt/pve-root-inspect" in runner.dirs


def test_mount_logical_volume_refuses_when_the_drive_has_no_real_vg():
    runner = FakeRunner(command_responses=[(lambda a: "pvs" in a, FakeProc(0, "", ""))])
    result = da.mount_logical_volume(runner, device_path="/dev/sdz")
    assert result.ok is False
    assert "no real LVM volume group" in result.detail


def test_mount_logical_volume_refuses_cleanly_when_activation_fails():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: a[:1] == ["vgchange"], FakeProc(5, "", "Volume group \"pve\" not found")),
    ])
    result = da.mount_logical_volume(runner, device_path="/dev/sdd")
    assert result.ok is False
    assert "activating pve failed" in result.detail
    assert not any(c[0] == "mount" for c in runner.calls)  # never attempted after activation fails


def test_mount_logical_volume_refuses_when_the_named_lv_does_not_exist():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: a[:1] == ["vgchange"], FakeProc(0, "", "")),
    ])
    result = da.mount_logical_volume(runner, device_path="/dev/sdd", lv_name="nonexistent")
    assert result.ok is False
    assert "/dev/pve/nonexistent does not exist" in result.detail


def test_mount_logical_volume_accepts_a_custom_lv_name_and_mountpoint():
    runner = FakeRunner(
        files={"/dev/pve/data": "x"},
        command_responses=[
            (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
            (lambda a: a[:1] == ["vgchange"], FakeProc(0, "", "")),
            (lambda a: a[:1] == ["mount"], FakeProc(0, "", "")),
        ],
    )
    result = da.mount_logical_volume(runner, device_path="/dev/sdd", lv_name="data", mountpoint="/mnt/custom")
    assert result.ok is True
    assert ["mount", "-o", "rw", "/dev/pve/data", "/mnt/custom"] in runner.calls


def test_mount_logical_volume_reports_real_progress():
    runner = FakeRunner(
        files={"/dev/pve/root": "x"},
        command_responses=[
            (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
            (lambda a: a[:1] == ["vgchange"], FakeProc(0, "", "")),
            (lambda a: a[:1] == ["mount"], FakeProc(0, "", "")),
        ],
    )
    lines = []
    da.mount_logical_volume(runner, device_path="/dev/sdd", on_progress=lines.append)
    assert any("Activating volume group pve" in line for line in lines)
    assert any("Mounting /dev/pve/root" in line for line in lines)


def test_unmount_logical_volume_unmounts_the_real_target():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: a[:1] == ["umount"], FakeProc(0, "", "")),
    ])
    result = da.unmount_logical_volume(runner, device_path="/dev/sdd")
    assert result.ok is True
    assert ["umount", "/mnt/pve-root-inspect"] in runner.calls


def test_unmount_logical_volume_refuses_cleanly_when_not_actually_mounted():
    runner = FakeRunner(command_responses=[
        (lambda a: "pvs" in a, FakeProc(0, "  /dev/sdd3   pve\n", "")),
        (lambda a: a[:1] == ["umount"], FakeProc(32, "", "not mounted")),
    ])
    result = da.unmount_logical_volume(runner, device_path="/dev/sdd")
    assert result.ok is False
    assert "unmounting" in result.detail


def test_mount_and_unmount_volume_are_registered_real_actions():
    assert "mount_volume" in da.ACTIONS
    assert "unmount_volume" in da.ACTIONS
    described = {d["action_id"]: d for d in da.describe_actions()}
    assert described["mount_volume"]["requires_device"] is True
    assert described["unmount_volume"]["requires_device"] is True


# -- ACTIONS registry / describe_actions / perform_action ----------------------

def test_describe_actions_lists_every_registered_action_with_its_real_description():
    described = da.describe_actions()
    ids = {d["action_id"] for d in described}
    assert ids == set(da.ACTIONS)
    for d in described:
        assert d["description"] == da.ACTIONS[d["action_id"]].description


def test_describe_actions_lists_every_real_action():
    """Direct instruction, 2026-09-29: "The only installer is a self
    installer" - "install" and "create_volumes_on_existing_vg" are
    gone; "run_health_check" moved to its own Hardware tab, no longer
    a Drive Administration action. Asserts presence, not exclusivity -
    a future action being added is expected, not a regression to
    catch."""
    assert {"update_selected", "repair", "build_self_installer"} <= set(da.ACTIONS)
    assert "install" not in da.ACTIONS
    assert "create_volumes_on_existing_vg" not in da.ACTIONS
    assert "run_health_check" not in da.ACTIONS


def test_build_self_installer_forwards_the_submitted_password_as_the_new_root_password(monkeypatch):
    """Direct instruction, 2026-09-29: "It has to accept my root
    password in Linux now" - the exact password the operator submitted
    to authorize this run must reach self_installer.py as the new
    Proxmox install's own root password, not a randomly generated one
    they'd have to go find."""
    import self_installer as si
    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return si.SelfInstallerResult("applied", "fake ok")

    monkeypatch.setattr(si, "build_and_write_self_installer", fake_build)
    runner = da.SudoRunner("the-real-shared-password", executor=FakeExecutor())
    result = da.build_self_installer(runner, device_path="/dev/sdd", pds_runner=FakePdsRunner())
    assert result.ok is True
    assert captured["admin_password"] == "the-real-shared-password"


def test_build_self_installer_never_wraps_its_own_device_validation_in_pkexec(monkeypatch):
    """Real bug found live, 2026-09-29: `pds_runner` used to default to
    `runner.as_pds_runner()` whenever available - correct for
    `SudoRunner` (its adapter already delegates reads to a plain
    runner internally) but wrong for `PkexecRunner`, whose adapter
    wraps *every* call, including plain unprivileged reads, in a real
    `pkexec` authentication dialog. Confirmed live: `udevadm info` for
    the target, then `findmnt`/`lsblk`/`udevadm` again for the
    boot-device self-check, each spawned its own separate, genuinely
    blocking dialog. This action's own validation never needed
    privilege at all - `pds_runner` must default to a plain
    `pds.Runner()`, never derived from a `PkexecRunner`."""
    import self_installer as si
    import physical_device_safety as pds

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return si.SelfInstallerResult("applied", "fake ok")

    monkeypatch.setattr(si, "build_and_write_self_installer", fake_build)
    executor = FakeExecutor()
    runner = da.PkexecRunner(executor=executor)
    result = da.build_self_installer(runner, device_path="/dev/sdd")
    assert result.ok is True
    # The real point: a plain, unprivileged Runner - not the PkexecRunner's
    # own adapter - so validation never spawns a real pkexec dialog.
    assert isinstance(captured["pds_runner"], pds.Runner)
    assert executor.calls == []  # no pkexec call was ever made for this action's own setup


def test_repo_root_default_finds_this_files_own_real_repo_checkout():
    """Real bug found live, 2026-09-29: the old default was a
    hardcoded `Path("/opt/baseline").parent` (`/opt`) - wrong even on
    its own terms, and `/opt/baseline` doesn't exist outside a real
    systemd-deployed install, crashing `build_self_installer` with
    `FileNotFoundError: [Errno 2] No such file or directory:
    '/opt/boot'` the moment it reached the real ISO-build stage.
    `REPO_ROOT` must instead resolve to wherever this actual file
    lives, which always has real `boot/` and `baseline/` children."""
    assert (da.REPO_ROOT / "boot").exists()
    assert (da.REPO_ROOT / "baseline").exists()


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
    )
    assert result.ok is False
    assert "device safety check failed" in result.detail


def _corrupt_lvm_size_preset_directly():
    """Bypasses settings_store.set_setting's own validation on purpose
    - simulates a stale/corrupted value getting into the database some
    other way (an old schema version, a manual edit), which is exactly
    the real-world case decision record 88's dependency check exists
    to catch. Writes directly into registry.py's own PROTECTED-scope
    database, under the "self_installer" group's own registry type
    (decision record 95 - each settings group is its own type now, not
    a shared "settings" type)."""
    import registry
    registry.upsert_entry("self_installer", "lvm_size_preset",
                           attributes={"default": "medium"}, scope=registry.PROTECTED, value="gigantic")


def test_build_self_installer_refuses_before_anything_else_on_a_loud_dependency_failure():
    """Decision record 88, direct instruction: dependencies "should be
    predefined and validated before install begins." A stale/invalid
    self_installer.lvm_size_preset value is registered as a LOUD
    dependency specifically because it would otherwise only surface as
    a bare KeyError deep inside self_installer.py - this proves the
    real refusal happens up front instead, before the safety gate is
    even reached (a real, valid drive is used here so the ONLY thing
    that can be refusing is the dependency check)."""
    _corrupt_lvm_size_preset_directly()
    pds_fake = FakePdsRunner()  # a real, valid drive
    result = da.build_self_installer(FakeRunner(), device_path="/dev/sdd", pds_runner=pds_fake)
    assert result.ok is False
    assert "loud dependency check" in result.detail
    assert "install.self_installer_lvm_preset_valid" in result.detail


def test_run_health_check_reports_ok_when_every_dependency_passes():
    result = da.run_health_check(FakeRunner())
    assert result.ok is True
    assert "system.sqlite3_importable" in result.detail


def test_run_health_check_fails_the_action_on_a_loud_dependency_failure():
    _corrupt_lvm_size_preset_directly()
    result = da.run_health_check(FakeRunner())
    assert result.ok is False
    assert "LOUD-FAIL" in result.detail


def test_describe_actions_exposes_requires_device_for_the_web_pages_device_picker():
    """Real regression coverage: describe_actions() once silently
    dropped requires_device entirely, so the web page's device-picker
    modal never appeared for the device-targeted action even though
    the ActionSpec itself was correctly flagged - found by driving the
    actual running page, not by code inspection alone."""
    described = {d["action_id"]: d for d in da.describe_actions()}
    assert described["update_selected"]["requires_device"] is True
    assert described["repair"]["requires_device"] is True
    assert described["build_self_installer"]["requires_device"] is True


def test_perform_action_refuses_an_unknown_action_id():
    runner = FakeRunner()
    result = da.perform_action(runner, "nonexistent", {})
    assert result.ok is False


def test_perform_action_does_not_choke_on_on_progress_for_an_action_that_ignores_it():
    """`update_selected`'s own lambda doesn't forward on_progress -
    passing one anyway must never raise."""
    result = da.perform_action(FakeRunner(), "update_selected", {"selected": []}, on_progress=lambda line: None)
    assert result.ok is False  # "no volumes selected" - the real point is that it didn't crash


def test_perform_action_dispatches_update_selected_with_its_params():
    runner = FakeRunner()
    result = perform_confirmed(runner, "update_selected", {"selected": ["INSTALLER_CACHE"], "device_path": "/dev/sdd"})
    assert result.ok is False  # honest placeholder - see test_update_selected_is_an_honest_not_implemented_placeholder
    assert "not implemented" in result.detail



# -- perform_action: nothing runs against a drive outside the allowlist -------

DEVICE_ACTIONS = [aid for aid, spec in da.ACTIONS.items() if spec.requires_device and aid != "update_selected"]


def test_there_are_device_actions_to_guard():
    assert {"build_self_installer", "repair", "mount_volume", "unmount_volume"} <= set(DEVICE_ACTIONS)


@pytest.mark.parametrize("action_id", DEVICE_ACTIONS)
def test_an_action_on_a_drive_outside_the_allowlist_is_refused_and_runs_nothing(action_id):
    runner = FakeRunner()
    result = da.perform_action(runner, action_id, {"device_path": "/dev/sda"},
                               pds_runner=FakePdsRunner(serial="ZCT2WCM2"))
    assert result.ok is False and "allowed" in result.detail.lower()
    assert runner.calls == [], f"{action_id} ran commands against a drive outside the allowlist"


@pytest.mark.parametrize("action_id", ["repair", "mount_volume", "unmount_volume"])
def test_an_action_on_an_allowed_drive_is_let_through(action_id):
    runner = FakeRunner()
    perform_confirmed(runner, action_id, {"device_path": "/dev/sdb"}, pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert runner.calls, f"{action_id} should have reached the real action for an allowed drive"


def test_the_action_receives_the_validated_path_not_the_raw_string():
    seen = {}
    spec = da.ActionSpec("probe", "probe", lambda runner, device_path, **p: seen.setdefault("p", device_path) or da.ActionResult(True, "ok"),
                         requires_device=True)
    da.ACTIONS["probe"] = spec
    da.ACTION_PARAMS["probe"] = frozenset({"device_path"})
    try:
        class Resolving(FakePdsRunner):
            def realpath(self, path):
                return "/dev/sdb" if path == "/dev/disk/by-id/some-link" else path
        # a path that resolves to the real device: the action must get the resolved one
        da.perform_action(FakeRunner(), "probe", {"device_path": "/dev/sdb"},
                          pds_runner=Resolving(serial="MD89N41071210AP4E"))
        assert seen["p"] == "/dev/sdb"
    finally:
        del da.ACTIONS["probe"]
        del da.ACTION_PARAMS["probe"]


def test_a_device_action_with_no_device_path_is_refused():
    runner = FakeRunner()
    result = da.perform_action(runner, "repair", {}, pds_runner=FakePdsRunner())
    assert result.ok is False
    assert runner.calls == []


def test_actions_that_need_no_device_are_unaffected():
    result = da.perform_action(FakeRunner(), "update_selected", {"selected": []}, pds_runner=FakePdsRunner())
    assert result.ok is not None


# -- request parameters are an allowlist, and each one is validated -------------
# The page posts {action_id, params}; params used to be splatted straight into privileged functions. A volume
# name like "../../sda1" built /dev/<vg>/../../sda1 and so reached a drive outside the allowlist.

ALLOWED_DEV = {"device_path": "/dev/sdb"}


def _runner_with_a_volume_group():
    """A drive that really has a volume group and volumes, so any unsafe value would reach vgchange/mount/umount
    unless it is refused first."""
    return FakeRunner(command_responses=[(lambda a: a[:3] == ["sudo", "-n", "pvs"], FakeProc(0, "  /dev/sdb3 pve\n", ""))],
                      files={"/dev/pve/root": "", "/dev/pve/data-vol": "", "/dev/pve/x": ""})


def _act(action_id, **params):
    """Valid requests are confirmed through the real flow; invalid ones cannot be (they never get a challenge),
    so a refusal here must come from validation, never from a missing confirmation."""
    runner = _runner_with_a_volume_group()
    pds_runner = FakePdsRunner(serial="MD89N41071210AP4E")
    request = {**ALLOWED_DEV, **params}
    try:
        auth, store = authorize(action_id, request, pds_runner=pds_runner)
    except ValueError:
        auth, store = None, None
    result = da.perform_action(runner, action_id, request, pds_runner=pds_runner, authorization=auth, hitl_store=store)
    if not result.ok and auth is None:
        assert "human confirmation" not in result.detail, "refused for a missing confirmation, not for the bad value"
    return result, runner


@pytest.mark.parametrize("action_id,extra", [
    ("repair", {"lv_name": "root"}), ("repair", {"anything": "x"}), ("mount_volume", {"selected": ["A"]}),
    ("unmount_volume", {"expected_serial": "MD89N41071210AP4E"}), ("build_self_installer", {"lv_name": "root"}),
    ("build_self_installer", {"pds_runner": "x"}), ("build_self_installer", {"on_progress": "x"}),
])
def test_unknown_parameters_are_refused_and_nothing_runs(action_id, extra):
    result, runner = _act(action_id, **extra)
    assert result.ok is False and "parameter" in result.detail.lower()
    assert runner.calls == []


@pytest.mark.parametrize("bad", ["../../sda1", "../sda1", "a/b", "root --force", "-x", "", "r" * 65, "ro\not", "$(id)", "a;b"])
@pytest.mark.parametrize("action_id", ["mount_volume", "unmount_volume"])
def test_a_volume_name_that_could_leave_the_volume_group_is_refused(action_id, bad):
    result, runner = _act(action_id, lv_name=bad)
    assert result.ok is False
    assert not any(c[:1] in (["mount"], ["umount"], ["vgchange"]) for c in runner.calls)


@pytest.mark.parametrize("bad", ["/", "/etc", "/mnt", "/mnt/", "/mnt/../etc", "mnt/x", "/mnt/a b", "/mnt/a/../../etc",
                                 "/mnt/BASELINE", "/mnt/USER_ADMIN", "/mnt/x\nmore", "/mnt/a/b/c/d/e", "/home/x", "/mnt/-x"])
@pytest.mark.parametrize("action_id", ["mount_volume", "unmount_volume"])
def test_a_mountpoint_outside_a_safe_place_under_mnt_is_refused(action_id, bad):
    result, runner = _act(action_id, mountpoint=bad)
    assert result.ok is False
    assert not any(c[:1] in (["mount"], ["umount"], ["vgchange"]) for c in runner.calls)


def test_a_valid_volume_name_and_mountpoint_still_work():
    runner = FakeRunner(command_responses=[(lambda a: a[:3] == ["sudo", "-n", "pvs"], FakeProc(0, "  /dev/sdb3 pve\n", ""))],
                        files={"/dev/pve/data-vol": ""})
    result = perform_confirmed(runner, "mount_volume",
                               {"device_path": "/dev/sdb", "lv_name": "data-vol", "mountpoint": "/mnt/pve-inspect"},
                               pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert result.ok is True and any(c[0] == "mount" for c in runner.calls)


def test_the_sink_functions_check_their_own_inputs_too():
    runner = FakeRunner(command_responses=[(lambda a: a[:3] == ["sudo", "-n", "pvs"], FakeProc(0, "  /dev/sdd3 pve\n", ""))],
                        files={"/dev/pve/root": ""})
    assert da.mount_logical_volume(runner, device_path="/dev/sdd", lv_name="../../sda1").ok is False
    assert da.mount_logical_volume(runner, device_path="/dev/sdd", mountpoint="/etc").ok is False
    assert da.unmount_logical_volume(runner, device_path="/dev/sdd", lv_name="../x").ok is False
    assert not any(c[:1] in (["mount"], ["umount"], ["vgchange"]) for c in runner.calls)


@pytest.mark.parametrize("params", [
    {"expected_serial": "SomeOtherDrive-1"},                 # a drive outside the allowlist
    {"proxmox_source_iso": "/etc/shadow"}, {"proxmox_source_iso": "relative.iso"}, {"cert_path": "/mnt/INSTALLER_CACHE/../../etc/passwd"},
    {"key_path": "/root/.ssh/id_rsa"}, {"server_host": "evil host; rm -rf /"}, {"server_host": "a\nb"},
    {"target_mac": "not-a-mac"}, {"target_dmi_product": 'x"; evil'}, {"target_dmi_product": "a" * 100},
])
def test_installer_overrides_are_validated_before_anything_runs(params):
    result, runner = _act("build_self_installer", **params)
    assert result.ok is False and runner.calls == []


def test_valid_installer_overrides_are_accepted_by_the_validator():
    ok = {"expected_serial": "MD89N41071210AP4E", "proxmox_source_iso": "/mnt/INSTALLER_CACHE/isos/proxmox.iso",
          "server_host": "10.0.2.2", "cert_path": "/etc/baseline/cert.pem", "key_path": "/var/lib/baseline/key.pem",
          "target_mac": "aa:bb:cc:dd:ee:ff", "target_dmi_product": "ASUS ROG STRIX B650E-F"}
    assert da.validate_action_params("build_self_installer", {"device_path": "/dev/sdb", **ok}) == {"device_path": "/dev/sdb", **ok}


def test_update_selected_only_takes_a_list_of_volume_labels():
    assert da.validate_action_params("update_selected", {"selected": ["INSTALLER_CACHE", "USER_ADMIN"]})
    for bad in ({"selected": "INSTALLER_CACHE"}, {"selected": ["../x"]}, {"selected": [1]}, {"selected": ["A"] * 50}):
        with pytest.raises(ValueError):
            da.validate_action_params("update_selected", bad)


def test_an_unsafe_value_would_have_reached_mount_if_it_were_not_refused():
    """Guards the guard: with a real volume group present, a SAFE request does reach mount, so the refusals above
    are the validators working and not just 'no volume group'."""
    result, runner = _act("mount_volume", lv_name="root", mountpoint="/mnt/safe-name")
    assert result.ok is True and any(c[0] == "mount" for c in runner.calls)


@pytest.mark.parametrize("value", ["SomeOtherDrive-1", "ZCT2WCM2", "", "a"])
def test_expected_serial_must_be_one_of_the_allowed_drives(value):
    with pytest.raises(ValueError):
        da.validate_action_params("build_self_installer", {"device_path": "/dev/sdb", "expected_serial": value})



# -- every drive action needs a human confirmation: the core function itself refuses ---------------

@pytest.mark.parametrize("action_id,extra", [
    ("repair", {}), ("mount_volume", {}), ("unmount_volume", {}), ("build_self_installer", {}),
])
def test_no_drive_action_runs_without_a_confirmation_and_no_command_is_issued(action_id, extra):
    runner = _runner_with_a_volume_group()
    result = da.perform_action(runner, action_id, {**ALLOWED_DEV, **extra}, pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"))
    assert result.ok is False and "human confirmation" in result.detail
    assert runner.calls == []


def test_update_selected_also_needs_a_confirmation():
    runner = FakeRunner()
    result = da.perform_action(runner, "update_selected", {"selected": ["BASELINE"]})
    assert result.ok is False and "human confirmation" in result.detail


@pytest.mark.parametrize("bogus", ["yes", True, 1, "approved", {"ok": 1}, object()])
def test_a_made_up_authorization_does_not_work(bogus):
    runner = _runner_with_a_volume_group()
    result = da.perform_action(runner, "repair", ALLOWED_DEV, pds_runner=FakePdsRunner(serial="MD89N41071210AP4E"),
                               authorization=bogus)
    assert result.ok is False and runner.calls == []


def test_an_authorization_for_one_request_does_not_run_a_different_one():
    pds_runner = FakePdsRunner(serial="MD89N41071210AP4E")
    auth, store = authorize("repair", ALLOWED_DEV, pds_runner=pds_runner)
    runner = _runner_with_a_volume_group()
    result = da.perform_action(runner, "mount_volume", ALLOWED_DEV, pds_runner=pds_runner, authorization=auth, hitl_store=store)
    assert result.ok is False and runner.calls == []


def test_an_authorization_works_once_and_a_replay_is_refused():
    pds_runner = FakePdsRunner(serial="MD89N41071210AP4E")
    auth, store = authorize("repair", ALLOWED_DEV, pds_runner=pds_runner)
    first = _runner_with_a_volume_group()
    assert da.perform_action(first, "repair", ALLOWED_DEV, pds_runner=pds_runner, authorization=auth, hitl_store=store).ok is not None
    assert first.calls, "the confirmed action should have run"
    replay = _runner_with_a_volume_group()
    result = da.perform_action(replay, "repair", ALLOWED_DEV, pds_runner=pds_runner, authorization=auth, hitl_store=store)
    assert result.ok is False and replay.calls == []


def test_an_authorization_from_a_different_store_is_refused():
    pds_runner = FakePdsRunner(serial="MD89N41071210AP4E")
    auth, _ = authorize("repair", ALLOWED_DEV, pds_runner=pds_runner)
    other_store = __import__("hitl_helpers").new_store()
    runner = _runner_with_a_volume_group()
    result = da.perform_action(runner, "repair", ALLOWED_DEV, pds_runner=pds_runner, authorization=auth, hitl_store=other_store)
    assert result.ok is False and runner.calls == []


def test_the_confirmation_is_checked_after_validation_so_a_bad_drive_is_still_refused_for_the_right_reason():
    result = da.perform_action(FakeRunner(), "repair", {"device_path": "/dev/sda"},
                               pds_runner=FakePdsRunner(serial="ZCT2WCM2"))
    assert "allowed drives" in result.detail
