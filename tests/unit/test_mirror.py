"""The compact mirror updates by change and stores no empty space (operator, 2026-10-19). Real rsync proof: tests/integration/test_mirror_real.py."""
import json
from pathlib import Path

import pytest

import mirror
from fake_runner import FakeProc, FakeRunner
import managed_mode as mm

STATS = """Number of files: 12 (reg: 10, dir: 2)
Number of regular files transferred: 3
Total file size: 1.50M bytes
Total transferred file size: 1.20M bytes
Literal data: 4.10K bytes
Matched data: 1.19M bytes
"""


def test_rsync_stats_are_read_as_files_changed_and_literal_bytes_written():
    assert mirror.parse_stats(STATS) == {"files_changed": 3, "bytes_sent": int(4.10 * 1024)}
    assert mirror.parse_stats("nothing") == {"files_changed": 0, "bytes_sent": 0}


def test_the_update_is_in_place_by_block_and_never_whole_file():
    flags = " ".join(mirror.RSYNC)
    assert "--inplace" in flags and "--no-whole-file" in flags and "--delete" in flags and "--modify-window=-1" in flags
    assert "--sparse" not in flags and "preallocate" not in flags                       # the destination never holds reserved or empty space


def test_sync_volume_refuses_a_real_failure_but_not_a_vanished_file(tmp_path):
    ok = FakeRunner(command_responses=[(lambda a: a[0] == "rsync", FakeProc(24, STATS, "file has vanished"))])
    assert mirror.sync_volume(ok, tmp_path / "src", tmp_path / "dst")["files_changed"] == 3
    bad = FakeRunner(command_responses=[(lambda a: a[0] == "rsync", FakeProc(23, "", "permission denied"))])
    with pytest.raises(mirror.MirrorError, match="failed"):
        mirror.sync_volume(bad, tmp_path / "src", tmp_path / "dst")


class Rig:
    def __init__(self, tmp_path, monkeypatch, *, fstype="ext4"):
        import drive_recovery as dr
        import offdrive_backup as ob
        self.tmp = tmp_path
        monkeypatch.setattr(dr.pds, "validate_target_device", lambda *a, **k: {"path": "/dev/sdx", "serial": "SYNTH-A", "size_bytes": 512_110_190_592})
        monkeypatch.setattr(mirror.pds, "validate_target_device", lambda *a, **k: {"path": "/dev/sdx", "serial": "SYNTH-A", "size_bytes": 512_110_190_592})
        monkeypatch.setattr(mirror.pds, "get_boot_device_serial", lambda *a, **k: "BOOT")
        monkeypatch.setattr(mirror.offdrive_backup, "resolve_destination", lambda path, **k: None)
        listing = {"blockdevices": [{"name": "/dev/sdx", "type": "disk", "serial": "SYNTH-A", "size": 512_110_190_592, "mountpoints": [None],
                                     "children": [{"name": "/dev/sdx1", "type": "part", "fstype": fstype, "size": 2 ** 30, "mountpoints": [None]}]}]}
        outer = self

        class Runner(FakeRunner):
            def run(self, argv, timeout=10):
                self.calls.append(list(argv))
                if argv[0] == "lsblk":
                    return FakeProc(0, json.dumps(listing), "")
                if argv[0] == "sgdisk":
                    Path(argv[1].split("=", 1)[1]).write_bytes(b"gpt")
                    return FakeProc(0, "", "")
                if argv[0] == "blkid":
                    return FakeProc(0, f"TYPE={fstype}\nUUID=u-1\nLABEL=EFI\n", "")
                if argv[0] == "rsync":
                    return FakeProc(0, STATS, "")
                return FakeProc(0, "", "")
        self.runner = Runner()

    def refresh(self):
        return mirror.refresh(self.runner, serial="SYNTH-A", child="child-1", combination="c" * 32, root=self.tmp, allowed_serials={"SYNTH-A"}, mount_base=str(self.tmp / "mnt"))


def test_a_refresh_mounts_read_only_copies_the_files_and_marks_the_mirror_complete(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    out = rig.refresh()
    directory = mirror.child_dir(tmp_path, "c" * 32, "child-1")
    mount = [a for a in rig.runner.calls if a[0] == "mount"][0]
    assert "ro,noload" in mount[mount.index("-o") + 1] and "noexec" in mount[mount.index("-o") + 1]
    assert out["files_changed"] == 3 and out["includes_unallocated_space"] is False
    assert json.loads((directory / mirror.STATE).read_text())["complete"] is True
    assert json.loads((directory / "volumes.json").read_text())["volumes"][0]["uuid"] == "u-1" and (directory / "layout.sgdisk").read_bytes() == b"gpt"
    assert [a[0] for a in rig.runner.calls if a[0] in ("mount", "umount")] == ["mount", "umount"]       # unmounted again


def test_an_unchanged_layout_is_not_rewritten_on_the_next_refresh(tmp_path, monkeypatch):
    import os
    rig = Rig(tmp_path, monkeypatch)
    rig.refresh()
    directory = mirror.child_dir(tmp_path, "c" * 32, "child-1")
    before = os.stat(directory / "layout.sgdisk").st_mtime_ns, os.stat(directory / "volumes.json").st_mtime_ns
    rig.refresh()
    assert (os.stat(directory / "layout.sgdisk").st_mtime_ns, os.stat(directory / "volumes.json").st_mtime_ns) == before


def test_a_filesystem_the_mirror_does_not_understand_is_refused_not_copied_whole(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, fstype="zfs_member")
    with pytest.raises(mirror.MirrorError, match="empty space"):
        rig.refresh()


def test_mirror_root_follows_the_parent_vault_in_managed_mode_only(tmp_path):
    f = tmp_path / "m.json"
    assert mm.mirror_root(f) is None
    mm.save({"mode": "managed", "parent_vault": "/mnt/part/vault"}, f)
    assert mm.mirror_root(f) == "/mnt/part"
    mm.save({"mode": "standalone"}, f)
    assert mm.mirror_root(f) is None
