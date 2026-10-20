"""The recovery snapshot holds only what the drive is using (operator 2026-10-19). Real-tool proof of the imaging itself:
tests/integration/test_used_backup_real.py. These check the plan, the refusals and the manifest with a fake runner."""
import hashlib
import json

import pytest

from fake_runner import FakeProc, FakeRunner

MIB = 2 ** 20
SIZE = 512_110_190_592


def lsblk(parts):
    return {"blockdevices": [{"name": "/dev/sdx", "type": "disk", "serial": "SYNTH-A", "size": SIZE, "mountpoints": [None],
                              "children": [{"name": f"/dev/sdx{i}", "type": "part", "fstype": fs, "size": size, "mountpoints": [None]} for i, (fs, size) in enumerate(parts, 1)]}]}


class Setup:
    def __init__(self, tmp_path, monkeypatch, parts, lvs=()):
        import drive_recovery as dr
        import offdrive_backup as ob
        self.dr = dr
        self.tmp = tmp_path
        monkeypatch.setattr(dr.pds, "validate_target_device", lambda *a, **k: {"path": "/dev/sdx", "serial": "SYNTH-A", "size_bytes": SIZE})
        monkeypatch.setattr(dr.pds, "get_boot_device_serial", lambda *a, **k: "BOOT")
        monkeypatch.setattr(ob, "resolve_destination", lambda path, **k: ob.Destination(path=str(tmp_path), backup_dir=tmp_path / "b", source="x", fstype="ext4", serial="D", disks=("sdz",)))
        monkeypatch.setattr(ob, "_free_and_total", lambda path: (800 * 2 ** 30, 1000 * 2 ** 30))
        listing = lsblk(parts)
        responses = [
            (lambda a: a[0] == "lsblk" and "-J" in a, FakeProc(0, json.dumps(listing), "")),
            (lambda a: a[0] == "sgdisk", FakeProc(0, "", "")),
            (lambda a: a[0] in ("vgchange", "vgcfgbackup"), FakeProc(0, "", "")),
            (lambda a: a[0] == "pvs", FakeProc(0, json.dumps({"report": [{"pv": [{"pv_name": "/dev/sdx3", "vg_name": "vg0", "vg_uuid": "UUID0"}]}]}), "")),
            (lambda a: a[0] == "lvs", FakeProc(0, json.dumps({"report": [{"lv": list(lvs)}]}), "")),
        ]
        class Runner(FakeRunner):
            def run(self, argv, timeout=10):
                if argv[0] == "blkid":
                    self.calls.append(list(argv))
                    return FakeProc(0, "swap\n" if argv[-1].endswith("/swap") else "ext4\n", "")
                return super().run(argv, timeout=timeout)
        self.runner = Runner(command_responses=responses)
        self.imaged = []

    def imager(self, source, out_dir, name, *, fstype=None):
        self.imaged.append((source, name, fstype))
        image = out_dir / f"{name}.{fstype}.pc.zst"
        image.write_bytes(b"x" * 100)
        return {"name": name, "fstype": fstype, "device_bytes": 10 * MIB, "used_bytes": 1 * MIB, "image": image.name, "image_bytes": 100,
                "sha256": hashlib.sha256(b"x" * 100).hexdigest(), "includes_unallocated_space": False}

    def run(self, **kw):
        import drive_recovery_used as du
        return du.create_snapshot_used(self.runner, serial="SYNTH-A", destination=str(self.tmp), allowed_serials={"SYNTH-A"}, imager=self.imager,
                                       detector=kw.get("detector", lambda p: "ext4"), raw_copier=lambda s, o, n, size: {
                                           "name": n, "fstype": None, "kind": "raw-small", "device_bytes": size, "used_bytes": size, "image": n + ".raw.zst",
                                           "image_bytes": 10, "sha256": "x", "includes_unallocated_space": False})


LV = {"lv_name": "root", "lv_path": "/dev/vg0/root", "lv_size": "34359738368", "segtype": "linear", "lv_attr": "-wi-a-----"}
SWAP = {"lv_name": "swap", "lv_path": "/dev/vg0/swap", "lv_size": "4294967296", "segtype": "linear", "lv_attr": "-wi-a-----"}
POOL = {"lv_name": "data", "lv_path": "/dev/vg0/data", "lv_size": "64424509440", "segtype": "thin-pool", "lv_attr": "twi-a-tz--"}


def test_a_snapshot_images_each_filesystem_through_its_allocation_map_and_records_swap_by_size(tmp_path, monkeypatch):
    import used_backup as ub

    def detect(path):
        if path == "/dev/sdx1":
            raise ub.UsedBackupError("no filesystem")                    # the BIOS boot area has none
        return "ext4"
    s = Setup(tmp_path, monkeypatch, [(None, 1 * MIB), ("vfat", 1024 * MIB), ("LVM2_member", 400 * 2 ** 30)], lvs=[LV, SWAP, POOL])
    folder = s.run(detector=detect)
    manifest = json.loads((folder / "MANIFEST.json").read_text())
    assert manifest["format"] == "baseline-drive-recovery-v2" and manifest["includes_unallocated_space"] is False
    kinds = {v["name"]: v["kind"] for v in manifest["volumes"]}
    assert kinds["sdx1"] == "raw-small" and kinds["sdx2"] == "partition" and kinds["vg0.root"] == "lv" and "vg0.data" not in kinds       # the thin pool itself is not imaged
    assert not any(src == "/dev/sdx3" for src, _, _ in s.imaged)                                                                      # the PV partition is never copied whole
    assert (folder / "layout.sgdisk").parent == folder and manifest["layout"]["vgcfg"] == {"UUID0": "vg-UUID0.cfg"}
    assert not (folder / "INCOMPLETE.json").exists()


def test_the_volume_group_is_activated_to_read_and_always_deactivated(tmp_path, monkeypatch):
    s = Setup(tmp_path, monkeypatch, [("LVM2_member", 400 * 2 ** 30)], lvs=[LV])
    s.run()
    verbs = [a[:2] for a in s.runner.calls if a[0] == "vgchange"]
    assert verbs[0] == ["vgchange", "-ay"] and verbs[-1] == ["vgchange", "-an"]


def test_a_volume_with_an_unknown_filesystem_is_refused_never_copied_whole(tmp_path, monkeypatch):
    import drive_recovery as dr
    import used_backup as ub

    def refuse(path):
        raise ub.UsedBackupError("no filesystem")
    s = Setup(tmp_path, monkeypatch, [("LVM2_member", 400 * 2 ** 30)], lvs=[LV])
    with pytest.raises(dr.RecoveryError, match="never|refused|empty space"):
        s.run(detector=refuse)
    assert [a[:2] for a in s.runner.calls if a[0] == "vgchange"][-1] == ["vgchange", "-an"]        # even a refusal leaves the volume group as it was found


def test_whole_drive_images_are_no_longer_made_by_default(tmp_path):
    import drive_recovery as dr
    with pytest.raises(dr.RecoveryError, match="empty space"):
        dr.create_snapshot(FakeRunner(), serial="X", destination=str(tmp_path), allowed_serials={"X"})


def test_verification_checks_every_image_and_refuses_one_that_holds_empty_space(tmp_path):
    import drive_recovery_used as du
    import drive_recovery as dr
    (tmp_path / "layout.sgdisk").write_bytes(b"x")
    image = tmp_path / "v.ext4.pc.zst"
    image.write_bytes(b"x" * 100)
    vol = {"name": "v", "kind": "lv", "fstype": "ext4", "device_bytes": 10 * MIB, "used_bytes": 1 * MIB, "image": image.name, "image_bytes": 100,
           "sha256": hashlib.sha256(b"x" * 100).hexdigest(), "includes_unallocated_space": False}
    base = {"format": du.FORMAT, "serial": "SYNTH-A", "layout": {"sgdisk": "layout.sgdisk", "vgcfg": {}}, "volumes": [vol], "complete": True, "includes_unallocated_space": False}
    (tmp_path / "MANIFEST.json").write_text(json.dumps(base))
    assert du.verify_used_snapshot(tmp_path, expected_serial="SYNTH-A", checker=lambda i, f: True)["volumes"][0]["name"] == "v"
    with pytest.raises(dr.RecoveryError, match="did not verify"):
        du.verify_used_snapshot(tmp_path, expected_serial="SYNTH-A", checker=lambda i, f: False)
    bloated = dict(vol, used_bytes=1000, image_bytes=100 + 300 * MIB)
    image.write_bytes(b"x" * bloated["image_bytes"])
    bloated["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    (tmp_path / "MANIFEST.json").write_text(json.dumps(dict(base, volumes=[bloated])))
    import used_backup as ub
    with pytest.raises(ub.UsedBackupError, match="empty space"):
        du.verify_used_snapshot(tmp_path, expected_serial="SYNTH-A", checker=lambda i, f: True)
    with pytest.raises(dr.RecoveryError):
        du.verify_used_snapshot(tmp_path, expected_serial="OTHER", checker=lambda i, f: True)


def test_verify_snapshot_dispatches_on_the_manifest_format(tmp_path):
    import drive_recovery as dr
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"format": "baseline-drive-recovery-v2", "serial": "S", "layout": {"sgdisk": "missing", "vgcfg": {}}, "volumes": [], "complete": True,
                                                         "includes_unallocated_space": False}))
    with pytest.raises(dr.RecoveryError, match="missing"):
        dr.verify_snapshot(FakeRunner(), tmp_path, expected_serial="S")


def test_a_grown_volume_listed_once_per_segment_is_still_one_volume(tmp_path, monkeypatch):
    two_segments = dict(LV, lv_name="root")
    s = Setup(tmp_path, monkeypatch, [("LVM2_member", 400 * 2 ** 30)], lvs=[two_segments, dict(two_segments), dict(SWAP)])
    import drive_recovery_used as du
    names = [v["name"] for v in du.plan_volumes(s.runner, "/dev/sdx")]
    assert names == ["vg0.root", "vg0.swap"]
