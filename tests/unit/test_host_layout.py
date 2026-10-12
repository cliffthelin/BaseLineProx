"""Swap moves into SESSION_TEMP: the fstab edits (PC601's real lines) and the order of the steps. The real commands are proven in the rehearsal VM."""
import os

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
    order = [c[0] for c in runner.calls if c[0] in {"fallocate", "mkswap", "swapon", "swapoff", "lvremove"} and "--noheadings" not in c]
    assert order == ["fallocate", "mkswap", "swapon", "swapoff", "lvremove"]
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
    assert not any(c[0] in {"fallocate", "mkswap", "swapoff", "lvremove"} for c in runner.calls)


def test_first_boot_moves_swap_after_the_roles_exist_and_before_the_installer_is_copied():
    import importlib.machinery, importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "baseline/bin/baseline-first-boot-install"
    loader = importlib.machinery.SourceFileLoader("fbi", str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("fbi", loader))
    loader.exec_module(module)
    names = [n for n, _ in module.STEPS]
    assert names.index("storage") < names.index("host-volumes") < names.index("installer")
