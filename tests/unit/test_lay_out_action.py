"""lay_out_baseline_drive: erase and re-lay the Baseline drive. Every command is a scripted fake; nothing real runs."""
from types import SimpleNamespace

import pytest
from fake_runner import FakeRunner
from test_drive_admin import FakePdsRunner

import drive_admin as da
import drive_guard as dg
import hitl
from hitl_helpers import perform_confirmed, perform_with_origin

GUID = "11111111-2222-3333-4444-555555555555"
BLANK = f"sdb disk  {GUID} \n"
OWN = f"sdb disk  {GUID} \nsdb1 part ext4  BASELINE\nsdb2 part ext4  USER_ADMIN\n"
PROXMOX = f"sdb disk  {GUID} \nsdb1 part vfat  \nsdb2 part LVM2_member  \n"
SOMEONES = f"sdb disk  {GUID} \nsdb1 part ntfs  Media\n"
SIZE = 512_110_190_592


def pds(table, **kw):
    return FakePdsRunner(drive_table=table, size_bytes=SIZE, **kw)


class Runner(FakeRunner):
    """lsblk MOUNTPOINT answers `mounts`; everything else is recorded and succeeds."""

    def __init__(self, mounts=""):
        super().__init__()
        self.mounts = mounts

    def run(self, argv, timeout=10):
        self.calls.append(list(argv))
        if argv[0] == "lsblk":
            return SimpleNamespace(returncode=0, stdout=self.mounts, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture(autouse=True)
def _blank_unless_stated(monkeypatch):
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, BLANK))


def test_the_action_is_destructive_and_never_pre_approved_and_needs_a_confirmation():
    assert "lay_out_baseline_drive" in da.DESTRUCTIVE_ACTIONS
    assert "lay_out_baseline_drive" in hitl.NEVER_PRE_APPROVED and hitl.VERBS["lay_out_baseline_drive"] == "LAYOUT"
    runner = Runner()
    result = perform_with_origin(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"}, pds_runner=pds(BLANK))
    assert result.ok is False and "human confirmation" in result.detail
    assert not any(c[0] in ("wipefs", "sgdisk") or c[0].startswith("mkfs") for c in runner.calls)


@pytest.mark.parametrize("table", [PROXMOX, SOMEONES])
def test_it_never_prepares_a_drive_that_is_not_empty_or_baselines_own(table):
    with pytest.raises(ValueError, match="not the Baseline drive"):
        da.prepare_action("lay_out_baseline_drive", {"device_path": "/dev/sdb"}, pds_runner=pds(table))


def test_a_baseline_drive_without_an_installer_identity_is_refused_then_adopted_then_allowed(monkeypatch):
    with pytest.raises(ValueError, match="installer"):
        da.prepare_action("lay_out_baseline_drive", {"device_path": "/dev/sdb"}, pds_runner=pds(OWN))
    dg.register_installer_uuid(GUID, serial="MD89N41071210AP4E")
    assert da.prepare_action("lay_out_baseline_drive", {"device_path": "/dev/sdb"}, pds_runner=pds(OWN))


def test_a_baseline_drive_with_data_needs_a_recent_backup(monkeypatch):
    dg.register_installer_uuid(GUID, serial="MD89N41071210AP4E")
    monkeypatch.setattr(da, "backup_is_fresh", lambda: False)
    with pytest.raises(ValueError, match="backup"):
        da.prepare_action("lay_out_baseline_drive", {"device_path": "/dev/sdb"}, pds_runner=pds(OWN))


def test_a_confirmed_layout_wipes_creates_the_volumes_and_stamps_the_drive(monkeypatch):
    table = {"v": BLANK}
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, table["v"]))
    runner = Runner()
    orig = runner.run

    def run(argv, timeout=10):
        if argv[:2] == ["sgdisk", "-U"]:
            table["v"] = f"sdb disk  {argv[2]} \nsdb1 part ext4  BASELINE\n"
        return orig(argv, timeout)
    runner.run = run
    class Live(FakePdsRunner):
        @property
        def drive_table(self):
            return table["v"]

        @drive_table.setter
        def drive_table(self, value):
            pass
    live = Live(size_bytes=SIZE)
    result = perform_confirmed(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"}, pds_runner=live)
    assert result.ok is True, result.detail
    names = [c[0] for c in runner.calls]
    assert names.index("wipefs") < names.index("sgdisk") and any(n.startswith("mkfs") for n in names)
    assert any(c[:2] == ["sgdisk", "-U"] for c in runner.calls)
    assert dg.is_installer_uuid(table["v"].split()[2])
    assert all(c[-1] in ("/dev/sdb",) or "/dev/sdb" in " ".join(c) or c[0] == "lsblk" for c in runner.calls)


def test_a_mounted_drive_is_not_touched():
    runner = Runner(mounts="/mnt/BASELINE\n/mnt/USER_ADMIN\n")
    result = perform_confirmed(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"}, pds_runner=pds(BLANK))
    assert result.ok is False and "unmount first" in result.detail
    assert not any(c[0] in ("wipefs", "sgdisk") or c[0].startswith("mkfs") for c in runner.calls)


def test_the_machines_boot_drive_is_refused_even_when_blank():
    runner = Runner()
    result = perform_with_origin(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"},
                                 pds_runner=pds(BLANK, serial="BootDriveSerial-999", pkname_of_root="sdb"))
    assert result.ok is False
    assert not any(c[0] in ("wipefs", "sgdisk") for c in runner.calls)


def test_a_drive_outside_the_sk_hynix_allowlist_is_refused():
    runner = Runner()
    result = perform_with_origin(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"},
                                 pds_runner=pds(BLANK, serial="SomeOtherDrive"))
    assert result.ok is False and runner.calls == []
