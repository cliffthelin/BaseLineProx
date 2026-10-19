"""Naming the drives this machine builds for (parity with the installer's drives file). Synthetic serials only: no hardware identifier belongs
in the repository. Real files under tmp_path; lsblk output shapes are real."""
import json
import os
import stat

import pytest

import drive_names as dn

LSBLK = json.dumps({"blockdevices": [
    {"name": "sda", "size": 500107862016, "model": "Fast NVMe 512GB", "serial": "SYNTHAAAA111111", "tran": "usb", "type": "disk",
     "children": [{"name": "sda1", "mountpoints": [None]}]},
    {"name": "sdb", "size": 500107862016, "model": "Fast NVMe 512GB", "serial": "SYNTHBBBB222222", "tran": "usb", "type": "disk",
     "children": [{"name": "sdb1", "mountpoints": ["/"]}]},
    {"name": "sr0", "size": 1073741312, "model": "DVD", "serial": None, "tran": "sata", "type": "rom"}]})


class Runner:
    def run(self, argv, timeout=0):
        from types import SimpleNamespace as NS
        return NS(returncode=0, stdout=LSBLK, stderr="")


def test_attached_lists_real_disks_and_marks_the_one_the_machine_runs_from():
    disks = dn.attached(Runner())
    assert [d["serial"] for d in disks] == ["SYNTHAAAA111111", "SYNTHBBBB222222"]
    assert [d["boot"] for d in disks] == [False, True]
    assert disks[0]["size_gib"] == 466


def test_a_drive_is_named_in_a_private_file_and_the_name_and_serial_are_each_used_once(tmp_path):
    path = tmp_path / "drives.json"
    disks = dn.attached(Runner())
    dn.assign(path, "BUILD1", "SYNTHAAAA111111", disks)
    assert json.loads(path.read_text()) == {"drives": {"BUILD1": "SYNTHAAAA111111"}}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="already"):
        dn.assign(path, "BUILD1", "SYNTHAAAA111111", disks)
    with pytest.raises(ValueError, match="already"):
        dn.assign(path, "BUILD2", "SYNTHAAAA111111", disks)


@pytest.mark.parametrize("name", ["", "has space", "x" * 21, "../x", "a;b"])
def test_a_name_is_a_short_plain_label(tmp_path, name):
    with pytest.raises(ValueError):
        dn.assign(tmp_path / "d.json", name, "SYNTHAAAA111111", dn.attached(Runner()))


def test_only_an_attached_drive_can_be_named_and_never_the_one_the_machine_runs_from(tmp_path):
    disks = dn.attached(Runner())
    with pytest.raises(ValueError, match="not attached"):
        dn.assign(tmp_path / "d.json", "BUILD1", "SYNTHZZZZ999999", disks)
    with pytest.raises(ValueError, match="runs from"):
        dn.assign(tmp_path / "d.json", "BUILD1", "SYNTHBBBB222222", disks)
    assert not (tmp_path / "d.json").exists()


def test_a_name_can_be_removed_and_other_names_stay(tmp_path):
    path = tmp_path / "drives.json"
    disks = dn.attached(Runner())
    dn.assign(path, "BUILD1", "SYNTHAAAA111111", disks)
    path.write_text(json.dumps({"drives": {"BUILD1": "SYNTHAAAA111111", "OTHER": "SYNTHCCCC333333"}}))
    dn.remove(path, "BUILD1")
    assert dn.load(path) == {"OTHER": "SYNTHCCCC333333"}


def test_load_accepts_exactly_what_the_installer_accepts():
    import importlib.machinery, importlib.util
    from pathlib import Path
    loader = importlib.machinery.SourceFileLoader("aai", str(Path(__file__).resolve().parents[2] / "baseline/bin/baseline-allscript-install"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("aai", loader))
    loader.exec_module(module)
    import tempfile
    cases = {"drives": {"OK": "SYNTHAAAA111111", "bad name": "SYNTHAAAA111111", "SHORT": "x", "FINE-2": "ABCDEFGH", "N" * 30: "SYNTHAAAA111111"}}
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "d.json"
        p.write_text(json.dumps(cases))
        assert dn.load(p) == module.load_drives(p)


def test_the_page_lists_drives_with_a_name_box_for_unnamed_ones_and_shows_no_serial_in_the_url(tmp_path):
    disks = dn.attached(Runner())
    named = dn.render(disks, {"BUILD1": "SYNTHAAAA111111"}).decode()
    assert "BUILD1" in named and 'action="/drive-names/remove"' in named and 'action="/drive-names/assign"' not in named
    assert "the drive this machine runs from" in named.lower()
    unnamed = dn.render(disks, {}).decode()
    assert 'action="/drive-names/assign"' in unnamed and "not named" in unnamed
