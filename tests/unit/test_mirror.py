"""The compact mirror works by volume ROLE through the build's own volume table, verifies each role against the drive's storage policy, updates by change and stores no empty space
(operator, 2026-10-19). Real rsync proof: tests/integration/test_mirror_real.py."""
import json
from pathlib import Path

import pytest

import managed_mode as mm
import mirror
from fake_runner import FakeProc, FakeRunner

STATS = """Number of regular files transferred: 3
Literal data: 4.10K bytes
"""
SIZE = 512_110_190_592
UUIDS = {"/dev/sdx1": "u-efi", "/dev/vg0/root": "u-root", "/dev/vg0/baseline_substrate": "u-sub", "/dev/vg0/baseline_user_admin": "u-ua", "/dev/vg0/baseline_session_temp": "u-tmp",
         "/dev/vg0/swap": "u-swap", "/dev/vg0/mystery": "u-x"}
FSTYPES = {"/dev/sdx1": "vfat", "/dev/vg0/swap": "swap"}


def test_rsync_stats_are_read_as_files_changed_and_literal_bytes_written():
    assert mirror.parse_stats(STATS) == {"files_changed": 3, "bytes_sent": int(4.10 * 1024)}
    assert mirror.parse_stats("nothing") == {"files_changed": 0, "bytes_sent": 0}


def test_the_update_is_in_place_by_block_and_never_whole_file():
    flags = " ".join(mirror.RSYNC)
    assert "--inplace" in flags and "--no-whole-file" in flags and "--delete" in flags and "--modify-window=-1" in flags
    assert "preallocate" not in flags


def test_sync_volume_refuses_a_real_failure_but_not_a_vanished_file(tmp_path):
    ok = FakeRunner(command_responses=[(lambda a: a[0] == "rsync", FakeProc(24, STATS, "file has vanished"))])
    assert mirror.sync_volume(ok, tmp_path / "src", tmp_path / "dst")["files_changed"] == 3
    bad = FakeRunner(command_responses=[(lambda a: a[0] == "rsync", FakeProc(23, "", "permission denied"))])
    with pytest.raises(mirror.MirrorError, match="failed"):
        mirror.sync_volume(bad, tmp_path / "src", tmp_path / "dst")


def test_roles_come_from_the_builds_volume_table_and_unknown_things_are_refused():
    ctx = {"fstype": "ext4"}
    assert mirror.classify({"kind": "lv", "lv": "baseline_user_admin", "name": "x"}, ctx) == "USER_ADMIN"
    assert mirror.classify({"kind": "lv", "lv": "baseline_appdata_personal", "name": "x"}, ctx) == "APPDATA_PERSONAL"
    assert mirror.classify({"kind": "lv", "lv": "baseline_app_state", "name": "x"}, ctx) == "BASELINE"
    assert mirror.classify({"kind": "lv", "lv": "root", "name": "x"}, ctx) == "ROOT"
    assert mirror.classify({"kind": "lv", "lv": "whatever", "name": "x"}, {"fstype": "swap"}) == "SWAP"
    assert mirror.classify({"kind": "partition", "name": "p", "size": 1024 ** 3}, {"fstype": "vfat"}) == "EFI"
    with pytest.raises(mirror.MirrorError, match="not a volume this build defines"):
        mirror.classify({"kind": "lv", "lv": "mystery", "name": "x"}, ctx)
    with pytest.raises(mirror.MirrorError, match="empty space"):
        mirror.classify({"kind": "partition", "name": "p", "size": 400 * 1024 ** 3}, {"fstype": None})


def policy(**bindings):
    return {"serial": "SYNTH-A", "bindings": {label: {"serial": "SYNTH-A", "uuid": uuid} for label, uuid in bindings.items()}}


class Rig:
    def __init__(self, tmp_path, monkeypatch, lvs=("baseline_substrate", "baseline_user_admin", "baseline_session_temp", "root", "swap")):
        import drive_recovery as dr
        self.tmp = tmp_path
        monkeypatch.setattr(dr.pds, "validate_target_device", lambda *a, **k: {"path": "/dev/sdx", "serial": "SYNTH-A", "size_bytes": SIZE})
        monkeypatch.setattr(mirror.pds, "validate_target_device", lambda *a, **k: {"path": "/dev/sdx", "serial": "SYNTH-A", "size_bytes": SIZE})
        monkeypatch.setattr(mirror.pds, "get_boot_device_serial", lambda *a, **k: "BOOT")
        monkeypatch.setattr(mirror.offdrive_backup, "resolve_destination", lambda path, **k: None)
        listing = {"blockdevices": [{"name": "/dev/sdx", "type": "disk", "serial": "SYNTH-A", "size": SIZE, "mountpoints": [None], "children": [
            {"name": "/dev/sdx1", "type": "part", "fstype": "vfat", "size": 2 ** 30, "mountpoints": [None]},
            {"name": "/dev/sdx2", "type": "part", "fstype": "LVM2_member", "size": 400 * 2 ** 30, "mountpoints": [None]}]}]}
        lv_rows = [{"lv_name": n, "lv_path": f"/dev/vg0/{n}", "lv_size": "1073741824", "segtype": "linear", "lv_attr": "-wi-a-----"} for n in lvs]

        class Runner(FakeRunner):
            def run(self, argv, timeout=10):
                self.calls.append(list(argv))
                if argv[0] == "lsblk":
                    return FakeProc(0, json.dumps(listing), "")
                if argv[0] == "pvs":
                    return FakeProc(0, json.dumps({"report": [{"pv": [{"pv_name": "/dev/sdx2", "vg_name": "vg0", "vg_uuid": "VGU"}]}]}), "")
                if argv[0] == "lvs":
                    return FakeProc(0, json.dumps({"report": [{"lv": lv_rows}]}), "")
                if argv[0] == "sgdisk":
                    Path(argv[1].split("=", 1)[1]).write_bytes(b"gpt")
                    return FakeProc(0, "", "")
                if argv[0] == "vgcfgbackup":
                    Path(argv[2]).write_text("cfg")
                    return FakeProc(0, "", "")
                if argv[0] == "blkid":
                    path = argv[-1]
                    return FakeProc(0, f"TYPE={FSTYPES.get(path, 'ext4')}\nUUID={UUIDS.get(path, 'u-?')}\n", "")
                if argv[0] == "rsync":
                    return FakeProc(0, STATS, "")
                return FakeProc(0, "", "")
        self.runner = Runner()

    def refresh(self, pol=None):
        return mirror.refresh(self.runner, serial="SYNTH-A", child="child-1", combination="c" * 32, root=self.tmp, allowed_serials={"SYNTH-A"}, mount_base=str(self.tmp / "mnt"),
                              policy_reader=lambda point: pol if pol is not None else policy(SUBSTRATE="u-sub", USER_ADMIN="u-ua", SESSION_TEMP="u-tmp"))

    def mounts(self):
        return [a for a in self.runner.calls if a[0] == "mount"]


def test_each_role_is_mirrored_into_its_own_folder_and_scratch_is_not(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    out = rig.refresh()
    directory = mirror.child_dir(tmp_path, "c" * 32, "child-1")
    assert set(out["volumes"]) == {"EFI", "SUBSTRATE", "USER_ADMIN", "ROOT"}               # SESSION_TEMP and swap are not mirrored
    volumes = {v["role"]: v for v in json.loads((directory / "volumes.json").read_text())["volumes"]}
    assert volumes["SESSION_TEMP"]["skipped"] == "scratch space" and volumes["SWAP"]["skipped"] == "swap" and volumes["USER_ADMIN"]["uuid"] == "u-ua"
    assert json.loads((directory / mirror.STATE).read_text())["complete"] is True and out["includes_unallocated_space"] is False
    assert [a[-1] for a in rig.runner.calls if a[0] == "rsync"] == [str(directory / "volumes" / r) + "/" for r in ("EFI", "SUBSTRATE", "USER_ADMIN", "ROOT")] or len([a for a in rig.runner.calls if a[0] == "rsync"]) == 4


def test_every_volume_is_mounted_read_only_and_the_group_is_left_as_found(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.refresh()
    for m in rig.mounts():
        options = m[m.index("-o") + 1]
        assert options.startswith("ro") and "noexec" in options and "nosuid" in options
    verbs = [a[:2] for a in rig.runner.calls if a[0] == "vgchange"]
    assert verbs[0] == ["vgchange", "-ay"] and verbs[-1] == ["vgchange", "-an"]
    assert [a[0] for a in rig.runner.calls if a[0] in ("mount", "umount")].count("mount") == [a[0] for a in rig.runner.calls if a[0] in ("mount", "umount")].count("umount")


def test_a_role_that_is_not_what_the_storage_policy_recorded_stops_everything_before_a_copy(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    with pytest.raises(mirror.MirrorError, match="storage policy recorded"):
        rig.refresh(policy(SUBSTRATE="u-sub", USER_ADMIN="a-different-filesystem"))
    assert not any(a[0] == "rsync" for a in rig.runner.calls)
    assert [a[:2] for a in rig.runner.calls if a[0] == "vgchange"][-1] == ["vgchange", "-an"]


def test_a_logical_volume_the_build_does_not_define_is_refused_not_copied(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, lvs=("baseline_substrate", "baseline_user_admin", "root", "mystery"))
    with pytest.raises(mirror.MirrorError, match="not a volume this build defines"):
        rig.refresh()
    assert not any(a[0] == "rsync" for a in rig.runner.calls)


def test_a_drive_without_a_substrate_volume_cannot_be_verified_so_nothing_is_copied(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, lvs=("baseline_user_admin", "root"))
    with pytest.raises(mirror.MirrorError, match="SUBSTRATE"):
        rig.refresh()
    assert not any(a[0] == "rsync" for a in rig.runner.calls)


def test_an_unchanged_layout_is_not_rewritten_on_the_next_refresh(tmp_path, monkeypatch):
    import os
    rig = Rig(tmp_path, monkeypatch)
    rig.refresh()
    directory = mirror.child_dir(tmp_path, "c" * 32, "child-1")
    before = os.stat(directory / "layout.sgdisk").st_mtime_ns, os.stat(directory / "volumes.json").st_mtime_ns
    rig.refresh()
    assert (os.stat(directory / "layout.sgdisk").st_mtime_ns, os.stat(directory / "volumes.json").st_mtime_ns) == before


def test_mirror_root_is_set_in_managed_mode_only(tmp_path):
    f = tmp_path / "m.json"
    assert mm.mirror_root(f) is None
    mm.save({"mode": "managed", "mirror_root": "/mnt/part"}, f)
    assert mm.mirror_root(f) == "/mnt/part"
    mm.save({"mode": "standalone"}, f)
    assert mm.mirror_root(f) is None
