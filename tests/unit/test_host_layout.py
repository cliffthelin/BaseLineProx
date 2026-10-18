"""Swap moves into SESSION_TEMP: the fstab edits (PC601's real lines) and the order of the steps. The real commands are proven in the rehearsal VM."""
import os
from pathlib import Path

import pytest

import host_layout as hl
from fake_runner import FakeProc, FakeRunner

PC601_FSTAB = """# <file system> <mount point> <type> <options> <dump> <pass>
/dev/pve/root / ext4 errors=remount-ro 0 1
/dev/pve/swap none swap sw 0 0
proc /proc proc defaults 0 0
UUID=ca4d7b97-079e-4b54-8afd-9d093ba4c730 /mnt/SESSION_TEMP ext4 defaults,nosuid,nodev,noexec 0 2
"""


def test_the_old_swap_volume_line_is_removed_and_nothing_else_is_touched():
    out = hl.fstab_without_swap_volume(PC601_FSTAB, "pve")
    assert "/dev/pve/swap" not in out and "/dev/pve/root / ext4" in out and "# <file system>" in out and "SESSION_TEMP" in out
    assert hl.fstab_without_swap_volume(out, "pve") == out


def test_a_commented_swap_line_and_another_groups_swap_are_left_alone():
    text = "# /dev/pve/swap none swap sw 0 0\n/dev/other/swap none swap sw 0 0\n"
    assert hl.fstab_without_swap_volume(text, "pve") == text


def test_the_swap_file_line_is_added_once():
    once = hl.fstab_with_swap_file(PC601_FSTAB)
    assert once.count("/mnt/SESSION_TEMP/swapfile none swap sw 0 0") == 1
    assert hl.fstab_with_swap_file(once) == once


class Recording(FakeRunner):
    """Scripted answers for the four state queries; everything else succeeds and is recorded in order."""
    def __init__(self, *, active_path=None, volume_present=True):
        super().__init__()
        self.active_path, self.volume_present = active_path, volume_present

    def run(self, argv, timeout=10):
        self.calls.append(list(argv))
        if argv[:2] == ["swapon", "--noheadings"]:
            return FakeProc(0, (self.active_path or "/dev/dm-0") + "\n", "")
        if argv[:1] == ["lvs"] and argv[-1].endswith("/swap"):
            return FakeProc(0, "swap\n" if self.volume_present else "", "")
        return FakeProc(0, "", "")


def test_the_new_swap_is_on_before_the_old_one_is_removed_and_fstab_follows(tmp_path, monkeypatch):
    fstab = tmp_path / "fstab"
    fstab.write_text(PC601_FSTAB)
    swapfile = tmp_path / "swapfile"
    monkeypatch.setattr(hl.volume_growth, "ensure_room", lambda *a, **k: None)
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)
    runner = Recording()
    done = hl.move_swap_to_session_temp(runner, "pve", path=str(swapfile), fstab=str(fstab))
    order = [c[0] for c in runner.calls if c[0] in {"dd", "mkswap", "swapon", "swapoff", "lvremove"} and "--noheadings" not in c]
    assert order == ["dd", "mkswap", "swapon", "swapoff", "lvremove"]
    assert done == {"created_file": True, "removed_volume": True, "fstab": True}
    text = fstab.read_text()
    assert "/dev/pve/swap" not in text and f"{swapfile} none swap sw 0 0" in text


def test_a_failure_before_the_old_swap_is_touched_leaves_it_in_place(tmp_path, monkeypatch):
    fstab = tmp_path / "fstab"
    fstab.write_text(PC601_FSTAB)
    monkeypatch.setattr(hl.volume_growth, "ensure_room", lambda *a, **k: (_ for _ in ()).throw(hl.volume_growth.GrowthError("no room")))
    runner = Recording()
    with pytest.raises(hl.volume_growth.GrowthError):
        hl.move_swap_to_session_temp(runner, "pve", path=str(tmp_path / "swapfile"), fstab=str(fstab))
    assert not any(c[0] in {"swapoff", "lvremove"} for c in runner.calls) and fstab.read_text() == PC601_FSTAB


def test_a_rerun_after_everything_is_done_changes_nothing(tmp_path):
    swapfile = str(tmp_path / "sf")
    fstab = tmp_path / "fstab"
    fstab.write_text(hl.fstab_with_swap_file(hl.fstab_without_swap_volume(PC601_FSTAB, "pve"), swapfile))
    before = fstab.read_text()
    runner = Recording(active_path=swapfile, volume_present=False)
    done = hl.move_swap_to_session_temp(runner, "pve", path=swapfile, fstab=str(fstab))
    assert done == {"created_file": False, "removed_volume": False, "fstab": False}
    assert fstab.read_text() == before
    assert not any(c[0] in {"dd", "mkswap", "swapoff", "lvremove"} for c in runner.calls)


def test_first_boot_moves_swap_after_the_roles_exist_and_before_the_installer_is_copied():
    import importlib.machinery, importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "baseline/bin/baseline-first-boot-install"
    loader = importlib.machinery.SourceFileLoader("fbi", str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("fbi", loader))
    loader.exec_module(module)
    names = [n for n, _ in module.STEPS]
    assert names.index("storage") < names.index("host-volumes") < names.index("installer")


# --- SESSION_TEMP's thin pool (operator, 2026-10-11: "Data is session_temp") -------------------------------------------------------

class PoolRunner(FakeRunner):
    """Scripted lvs/pvesm answers for the pool rename; everything is recorded in order."""
    def __init__(self, *, pools=("data",), storages=("local", "local-lvm")):
        super().__init__()
        self.pools, self.storages = set(pools), list(storages)

    def run(self, argv, timeout=10):
        self.calls.append(list(argv))
        if argv[:1] == ["lvs"]:
            name = argv[-1].split("/")[-1]
            return FakeProc(0 if name in self.pools else 5, name + "\n" if name in self.pools else "", "")
        if argv[:2] == ["pvesm", "status"]:
            return FakeProc(0, "Name Type Status\n" + "".join(f"{s} dir active\n" for s in self.storages), "")
        if argv[:2] == ["lvrename", "pve"]:
            self.pools.discard(argv[2]); self.pools.add(argv[3])
        return FakeProc(0, "", "")


def test_the_data_pool_is_renamed_and_local_lvm_is_replaced_by_the_session_temp_storage(tmp_path):
    runner = PoolRunner()
    done = hl.name_the_pool_for_session_temp(runner, "pve", conf=str(tmp_path / "lvmlocal.conf"))
    cmds = [c[:2] for c in runner.calls if c[0] in {"lvrename", "pvesm", "lvchange"} and c[1] != "status"]
    assert cmds == [["lvrename", "pve"], ["pvesm", "remove"], ["pvesm", "add"], ["lvchange", "--monitor"]]
    add = next(c for c in runner.calls if c[:2] == ["pvesm", "add"])
    assert add[2:] == ["lvmthin", hl.GUEST_STORAGE, "--vgname", "pve", "--thinpool", hl.POOL_NAME, "--content", "rootdir,images"]
    assert done == {"renamed_pool": True, "registered_storage": True, "autoextend": True}
    assert "thin_pool_autoextend_threshold = 80" in (tmp_path / "lvmlocal.conf").read_text()


def test_the_pool_rename_is_idempotent_and_never_repeats_the_autoextend_setting(tmp_path):
    conf = tmp_path / "lvmlocal.conf"
    conf.write_text(hl.AUTOEXTEND)
    runner = PoolRunner(pools=(hl.POOL_NAME,), storages=("local", hl.GUEST_STORAGE))
    done = hl.name_the_pool_for_session_temp(runner, "pve", conf=str(conf))
    assert done == {"renamed_pool": False, "registered_storage": False, "autoextend": False}
    assert conf.read_text().count("thin_pool_autoextend_threshold") == 1
    assert not any(c[0] == "lvrename" or c[:2] in (["pvesm", "add"], ["pvesm", "remove"]) for c in runner.calls)


def test_it_refuses_when_there_is_no_pool_at_all(tmp_path):
    with pytest.raises(hl.LayoutError, match="does not exist"):
        hl.name_the_pool_for_session_temp(PoolRunner(pools=()), "pve", conf=str(tmp_path / "c"))


def test_a_thin_session_temp_is_created_as_a_thin_volume_in_the_pool_not_a_thick_one():
    import drive_installer as di
    assert di.create_logical_volume_argv("pve", "baseline_session_temp", "62G", thin_pool="data") == [
        "lvcreate", "-n", "baseline_session_temp", "-V", "62G", "--thinpool", "data", "pve"]
    assert di.create_logical_volume_argv("pve", "baseline_user_admin", "1G") == ["lvcreate", "-n", "baseline_user_admin", "-L", "1G", "pve"]


def test_the_group_name_is_the_drives_own_and_matches_the_offline_isolation():
    import single_drive_storage as sds
    import hashlib
    assert hl.volume_group_name_for("FD01N6557110C271B") == "baseline_" + hashlib.sha256(b"FD01N6557110C271B").hexdigest()[:12]
    assert hl.volume_group_name_for("FD01N6557110C271B") != hl.volume_group_name_for("MD89N41071210AP4E")
    with pytest.raises(hl.LayoutError):
        hl.volume_group_name_for("bad serial")
    assert hasattr(sds, "isolate_volume_group")


def test_only_paths_that_name_the_group_are_rewritten():
    text = "/dev/pve/root / ext4 errors=remount-ro 0 1\nroot=/dev/mapper/pve-root ro\n# pve data\nUUID=abc /mnt/X ext4 defaults 0 2\n"
    out = hl.text_with_group_renamed(text, "pve", "baseline_x")
    assert "/dev/baseline_x/root" in out and "/dev/mapper/baseline_x-root" in out
    assert "# pve data" in out and "UUID=abc" in out and "/dev/pve/" not in out


class GroupRunner(FakeRunner):
    def __init__(self, other=""):
        super().__init__()
        self.other = other

    def run(self, argv, timeout=10):
        self.calls.append(list(argv))
        if argv[:1] == ["vgs"]:
            return FakeProc(0, self.other, "")
        return FakeProc(0, "", "")


def test_the_group_is_renamed_by_uuid_files_follow_and_the_boot_loader_is_regenerated(tmp_path, monkeypatch):
    fstab = tmp_path / "fstab"
    fstab.write_text(PC601_FSTAB)
    monkeypatch.setattr(hl, "BOOT_TOOL_UUIDS", str(tmp_path / "absent"))
    grub = tmp_path / "grub.cfg"
    grub.write_text("linux /boot/vmlinuz root=/dev/mapper/pve-root ro quiet\nset root='lvm/pve-root'\n")
    runner = GroupRunner()
    done = hl.name_the_volume_group_for_drive(runner, serial="FD01N6557110C271B", vg="pve", vg_uuid="U-1", name_files=(str(fstab),),
                                              grub_config=str(grub), mapper_dir=str(tmp_path / "mapper"))
    new = hl.volume_group_name_for("FD01N6557110C271B")
    assert done == {"renamed": True, "files": [str(fstab), str(grub)], "name": new, "regenerated": True}
    assert not (tmp_path / "mapper").exists()          # no device node behind the new name here: nothing is linked, and never in /dev
    assert grub.read_text() == f"linux /boot/vmlinuz root=/dev/mapper/{new}-root ro quiet\nset root='lvm/{new}-root'\n"
    order = [c[0] for c in runner.calls if c[0] in {"vgrename", "update-initramfs", "update-grub"}]
    assert order == ["vgrename", "update-initramfs", "update-grub"]
    assert ["vgrename", "U-1", new] in runner.calls
    assert f"/dev/{new}/root / ext4" in fstab.read_text() and "/dev/pve/" not in fstab.read_text()


def test_a_second_run_changes_nothing_and_a_name_owned_by_another_group_is_refused(tmp_path):
    new = hl.volume_group_name_for("FD01N6557110C271B")
    fstab = tmp_path / "fstab"
    fstab.write_text(PC601_FSTAB.replace("/dev/pve/", f"/dev/{new}/"))
    runner = GroupRunner()
    done = hl.name_the_volume_group_for_drive(runner, serial="FD01N6557110C271B", vg=new, vg_uuid="U-1", name_files=(str(fstab),),
                                              grub_config=str(tmp_path / "none"), mapper_dir=str(tmp_path / "mapper"))
    assert done == {"renamed": False, "files": [], "name": new} and runner.calls == []
    with pytest.raises(hl.LayoutError):
        hl.name_the_volume_group_for_drive(GroupRunner(other="U-OTHER\n"), serial="FD01N6557110C271B", vg="pve", vg_uuid="U-1",
                                           name_files=(str(fstab),), grub_config=str(tmp_path / "none"), mapper_dir=str(tmp_path / "mapper"))


def test_failed_boot_regeneration_is_pending_and_retry_finishes_after_vg_already_renamed(tmp_path, monkeypatch):
    """Injected command responses are unit evidence, not a VM or physical boot."""
    monkeypatch.setattr(hl, "BOOT_TOOL_UUIDS", str(tmp_path / "absent"))
    fstab = tmp_path / "fstab"
    fstab.write_text(PC601_FSTAB)
    grub = tmp_path / "grub.cfg"
    grub.write_text("linux /boot/vmlinuz root=/dev/mapper/pve-root ro\n")
    runner = GroupRunner()
    original_run = runner.run

    def failed_grub(argv, timeout=10):
        if argv == ["update-grub"]:
            return FakeProc(1, "", "regeneration failed")
        return original_run(argv, timeout=timeout)

    monkeypatch.setattr(runner, "run", failed_grub)
    options = dict(serial="FD01N6557110C271B", vg_uuid="U-1", name_files=(str(fstab),),
                   grub_config=str(grub), mapper_dir=str(tmp_path / "mapper"))
    with pytest.raises(hl.LayoutError, match="pending"):
        hl.name_the_volume_group_for_drive(runner, vg="pve", **options)
    pending = Path(str(grub) + ".baseline-vg-rename.json")
    assert pending.is_file()
    monkeypatch.setattr(runner, "run", original_run)
    runner.calls.clear()
    result = hl.name_the_volume_group_for_drive(runner, vg=hl.volume_group_name_for(options["serial"]), **options)
    assert result["regenerated"] is True
    assert not any(call[0] == "vgrename" for call in runner.calls)
    assert ["update-initramfs", "-u", "-k", "all"] in runner.calls
    assert ["update-grub"] in runner.calls
    assert not pending.exists()


def test_unknown_destination_vg_ownership_refuses_before_rename(tmp_path, monkeypatch):
    runner = GroupRunner()
    monkeypatch.setattr(runner, "run", lambda argv, timeout=10: FakeProc(1, "", "cannot read VGs"))
    with pytest.raises(hl.LayoutError, match="ownership"):
        hl.name_the_volume_group_for_drive(runner, serial="FD01N6557110C271B", vg="pve", vg_uuid="U-1",
            name_files=(), grub_config=str(tmp_path / "grub.cfg"), mapper_dir=str(tmp_path / "mapper"))
    assert not Path(str(tmp_path / "grub.cfg") + ".baseline-vg-rename.json").exists()
