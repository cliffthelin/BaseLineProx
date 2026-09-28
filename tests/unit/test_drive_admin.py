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


# -- ACTIONS registry / describe_actions / perform_action ----------------------

def test_describe_actions_lists_every_registered_action_with_its_real_description():
    described = da.describe_actions()
    ids = {d["action_id"] for d in described}
    assert ids == set(da.ACTIONS)
    for d in described:
        assert d["description"] == da.ACTIONS[d["action_id"]].description


def test_describe_actions_exposes_requires_device_for_the_web_pages_device_picker():
    """Real regression coverage: describe_actions() once silently
    dropped requires_device entirely, so the web page's device-picker
    modal never appeared for rebuild_persistence_lvm even though the
    ActionSpec itself was correctly flagged - found by driving the
    actual running page, not by code inspection alone."""
    described = {d["action_id"]: d for d in da.describe_actions()}
    assert described["rebuild_persistence_lvm"]["requires_device"] is True
    assert described["switch_persona"]["requires_device"] is False


def test_perform_action_refuses_an_unknown_action_id():
    runner = FakeRunner()
    result = da.perform_action(runner, "nonexistent", {})
    assert result.ok is False


def test_perform_action_dispatches_switch_persona_with_its_params():
    mounts = "/dev/sdb2 /mnt/USER_PERSISTENCE_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = da.perform_action(runner, "switch_persona", {"to_persona": "admin"})
    assert result.ok is True
