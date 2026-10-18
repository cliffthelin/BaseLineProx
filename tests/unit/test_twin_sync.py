"""Twin sync: two Baseline drives kept the same whenever both are attached. Real rsync on real temporary trees; no device is touched."""
import json
import os
import subprocess
import time

import pytest

import twin_sync as ts

PAIR = "pair-0000-test"


class Runner:
    def run(self, argv, timeout=600):
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        class P:
            returncode, stdout, stderr = done.returncode, done.stdout, done.stderr
        return P()


def volume(tmp_path, name, pair=PAIR):
    root = tmp_path / name
    root.mkdir()
    ts.write_pair_marker(root, pair, role="USER_ADMIN")
    return root


def put(root, rel, text, age=0):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    t = time.time() - age
    os.utime(path, (t, t))


def sync(a, b, mode="newest", **kw):
    return ts.sync_volume(Runner(), a, b, mode=mode, pair_id=PAIR, stamp="t1", require_mount=False, **kw)


def test_a_routine_run_compares_size_and_age_and_a_deep_run_also_compares_content(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    t = time.time() - 50
    for root, text in ((a, "same size A"), (b, "same size B")):
        (root / "f.txt").write_text(text)
        os.utime(root / "f.txt", (t, t))
    assert sync(a, b)["conflicts"] == []                                                       # cheap check cannot see it
    assert sync(a, b, deep=True)["conflicts"] == ["f.txt"]
    put(a, "g.txt", "short")
    put(b, "g.txt", "a longer different one")
    os.utime(a / "g.txt", (t, t)); os.utime(b / "g.txt", (t, t))
    assert "g.txt" in sync(a, b)["conflicts"]                                                  # a different size at the same age is seen by the routine run


def test_each_side_gains_what_only_the_other_has(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    put(a, "only-a.txt", "from a")
    put(b, "dir/only-b.txt", "from b")
    report = sync(a, b)
    assert (b / "only-a.txt").read_text() == "from a" and (a / "dir/only-b.txt").read_text() == "from b"
    assert report["a_to_b"] == 1 and report["b_to_a"] == 1 and report["conflicts"] == []


def test_the_newer_copy_wins_on_both_sides_and_the_older_one_is_kept_aside_not_lost(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    put(a, "notes.txt", "old on a", age=100)
    put(b, "notes.txt", "new on b", age=10)
    put(a, "other.txt", "new on a", age=10)
    put(b, "other.txt", "old on b", age=100)
    sync(a, b)
    assert (a / "notes.txt").read_text() == (b / "notes.txt").read_text() == "new on b"
    assert (a / "other.txt").read_text() == (b / "other.txt").read_text() == "new on a"
    kept = [p.read_text() for p in (a.glob(".baseline-twin/backup/*/notes.txt"))] + [p.read_text() for p in (b.glob(".baseline-twin/backup/*/other.txt"))]
    assert sorted(kept) == ["old on a", "old on b"]                                     # the overwritten versions are under each side's own backup folder


def test_a_second_run_changes_nothing_and_deletions_never_propagate(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    put(a, "x.txt", "x")
    sync(a, b)
    again = sync(a, b)
    assert again["a_to_b"] == 0 and again["b_to_a"] == 0
    (a / "x.txt").unlink()
    sync(a, b)
    assert (a / "x.txt").read_text() == "x"                                             # a deletion on one side is not copied as a deletion: the file comes back, nothing is lost


def test_same_age_but_different_content_is_a_conflict_kept_as_two_files_never_overwritten(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    t = time.time() - 50
    for root, text in ((a, "version A"), (b, "version B")):                                    # the same length: only a checksum run can tell
        (root / "c.txt").write_text(text)
        os.utime(root / "c.txt", (t, t))
    report = sync(a, b, deep=True)
    assert report["conflicts"] == ["c.txt"]
    assert (a / "c.txt").read_text() == "version A" and (b / "c.txt").read_text() == "version B"      # untouched
    assert (a / "c.txt.twin-conflict").read_text() == "version B" and (b / "c.txt.twin-conflict").read_text() == "version A"


def test_the_cache_mode_only_adds_missing_files_and_never_replaces_an_existing_one(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    put(a, "iso/one.iso", "A's", age=10)
    put(b, "iso/one.iso", "B's", age=100)
    put(b, "iso/two.iso", "only b")
    sync(a, b, mode="union")
    assert (b / "iso/one.iso").read_text() == "B's" and (a / "iso/one.iso").read_text() == "A's"
    assert (a / "iso/two.iso").read_text() == "only b"


def test_volumes_that_are_not_a_matching_pair_are_never_synced(tmp_path):
    a = volume(tmp_path, "a")
    stranger = volume(tmp_path, "b", pair="someone-elses-pair")
    with pytest.raises(ts.TwinError, match="pair"):
        sync(a, stranger)
    unmarked = tmp_path / "c"
    unmarked.mkdir()
    with pytest.raises(ts.TwinError, match="not marked"):
        sync(a, unmarked)
    with pytest.raises(ts.TwinError, match="same"):
        sync(a, a)
    with pytest.raises(ts.TwinError, match="inside"):
        ts.sync_volume(Runner(), a, a / "sub", mode="newest", pair_id=PAIR, stamp="t", require_mount=False)


def test_a_volume_that_is_not_a_mounted_filesystem_is_refused_when_mounts_are_required(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    with pytest.raises(ts.TwinError, match="mounted"):
        ts.sync_volume(Runner(), a, b, mode="newest", pair_id=PAIR, stamp="t")             # the temp folders are not mountpoints: an unmounted volume would sync onto the wrong disk


def test_which_layers_sync_how():
    assert ts.mode_for("USER_ADMIN") == ts.mode_for("USER_PERSONAL") == ts.mode_for("APPDATA_ADMIN") == ts.mode_for("APPDATA_PERSONAL") == "newest"
    assert ts.mode_for("INSTALLER_CACHE") == "union"
    for role in ("SESSION_TEMP", "SUBSTRATE", "BASELINE", "SOMETHING_NEW"):
        assert ts.mode_for(role) is None                                                  # disposable, rebuilt by the code layer, or running VM disks: never file-synced, and unknown roles are left alone


def test_the_code_layer_pushes_only_a_healthy_newer_version_and_never_blindly_either_way():
    mine = {"digest": "aaa", "installed_at": 200}
    older = {"digest": "bbb", "installed_at": 100}
    newer = {"digest": "ccc", "installed_at": 300}
    assert ts.plan_code(mine, older, healthy=True)["action"] == "push"
    assert ts.plan_code(mine, older, healthy=False)["action"] == "hold"                  # not boot-tested yet: the twin stays the known-good one
    assert ts.plan_code(mine, {"digest": "aaa", "installed_at": 150}, healthy=True)["action"] == "same"
    assert ts.plan_code(mine, newer, healthy=True)["action"] == "twin-newer"             # never pushed backwards; the twin's version is the one to take
    assert ts.plan_code(mine, None, healthy=True)["action"] == "unknown"
    assert ts.plan_code(None, older, healthy=True)["action"] == "unknown"


def test_live_state_and_host_identity_are_never_file_synced_between_two_hosts(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    put(a, "home/owner/notes.txt", "user file")
    put(a, "settings/layer.json", "settings")
    put(a, "var-lib-pve-cluster/config.db", "proxmox cluster database")        # one host's identity and live database
    put(a, "etc-baseline/own-drives", "this host's own drive list")
    put(a, "var-lib-baseline/sessions.sqlite", "live database")
    put(a, "home/owner/live.sqlite", "a live database inside a user folder")
    put(a, "home/owner/vm.qcow2", "a running VM's disk")
    ts.sync_volume(Runner(), a, b, mode="newest", pair_id=PAIR, stamp="t", require_mount=False, role="USER_ADMIN")
    assert (b / "home/owner/notes.txt").read_text() == "user file" and (b / "settings/layer.json").exists()
    for never in ("var-lib-pve-cluster/config.db", "etc-baseline/own-drives", "var-lib-baseline/sessions.sqlite", "home/owner/live.sqlite", "home/owner/vm.qcow2"):
        assert not (b / never).exists(), never


def test_a_role_without_an_include_list_syncs_everything_except_the_never_list(tmp_path):
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    put(a, "any/folder/file.txt", "kept")
    put(a, "any/db.sqlite", "skipped")
    ts.sync_volume(Runner(), a, b, mode="newest", pair_id=PAIR, stamp="t", require_mount=False, role="APPDATA_PERSONAL")
    assert (b / "any/folder/file.txt").exists() and not (b / "any/db.sqlite").exists()


# --- attaching the twin, pairing, and the whole-pair run (commands are recorded, not executed) ---------------------------------------------------

class Recorder:
    """Answers the read-only inventory from fixed JSON and records every other command."""
    def __init__(self, twin_vg_uuid="uuid-twin", host_vg_uuid="uuid-host", twin_serial="SYNTHTWIN0000001"):
        self.calls, self.twin_vg_uuid, self.host_vg_uuid, self.twin_serial = [], twin_vg_uuid, host_vg_uuid, twin_serial

    def run(self, argv, timeout=60):
        self.calls.append(list(argv))
        out = ""
        if argv[0] == "lsblk":
            out = json.dumps({"blockdevices": [
                {"name": "/dev/sdh", "type": "disk", "serial": "SYNTHHOST0000001", "size": 512, "children": [{"name": "/dev/sdh3", "type": "part", "fstype": "LVM2_member"}]},
                {"name": "/dev/sdl", "type": "disk", "serial": self.twin_serial, "size": 512, "children": [{"name": "/dev/sdl3", "type": "part", "fstype": "LVM2_member"}]}]})
        elif argv[0] == "pvs":
            out = json.dumps({"report": [{"pv": [{"pv_name": "/dev/sdh3", "vg_name": "baseline_host", "vg_uuid": self.host_vg_uuid}, {"pv_name": "/dev/sdl3", "vg_name": "baseline_twin", "vg_uuid": self.twin_vg_uuid}]}]})
        elif argv[0] == "lvs" and "--noheadings" in argv and "lv_name,lv_path" in argv:
            out = "  baseline_user_admin /dev/baseline_twin/baseline_user_admin\n  baseline_installer_cache /dev/baseline_twin/baseline_installer_cache\n  baseline_session_temp /dev/baseline_twin/baseline_session_temp\n  root /dev/baseline_twin/root\n"
        elif argv[0] == "lvs" and "--noheadings" in argv:
            out = self.host_vg_uuid + "\n"
        elif argv[0] == "lvs":
            out = json.dumps({"report": [{"lv": [{"lv_name": "root", "vg_name": "baseline_host", "vg_uuid": self.host_vg_uuid}, {"lv_name": "baseline_user_admin", "vg_name": "baseline_twin", "vg_uuid": self.twin_vg_uuid},
                                              {"lv_name": "root", "vg_name": "baseline_twin", "vg_uuid": self.twin_vg_uuid}]}]})
        elif argv[0] == "findmnt":
            out = "/dev/mapper/baseline_host-root\n"
        class P:
            returncode, stdout, stderr = 0, out, ""
        return P()


def test_the_twin_is_found_by_its_serial_its_group_by_uuid_and_only_syncable_volumes_are_mounted(tmp_path):
    r = Recorder()
    got = ts.attach_twin(r, "SYNTHTWIN0000001", mount_base=str(tmp_path / "TWIN"))
    assert got["vg_uuid"] == "uuid-twin" and sorted(got["mounts"]) == ["INSTALLER_CACHE", "USER_ADMIN"]       # session temp and root are not mounted for syncing
    assert ["vgchange", "-ay", "--select", "vg_uuid=uuid-twin"] in r.calls                                   # by UUID: a shared name could mean either drive
    mounts = [c for c in r.calls if c[0] == "mount"]
    assert all(c[1:3] == ["-o", "nodev,nosuid"] for c in mounts) and {c[-1] for c in mounts} == {str(tmp_path / "TWIN" / "USER_ADMIN"), str(tmp_path / "TWIN" / "INSTALLER_CACHE")}
    ts.detach_twin(r, got, mount_base=str(tmp_path / "TWIN"))
    assert [c for c in r.calls if c[0] == "umount"] and r.calls[-1] == ["vgchange", "-an", "--select", "vg_uuid=uuid-twin"]


def test_the_twin_is_refused_when_it_is_missing_or_is_the_running_drive_itself(tmp_path):
    with pytest.raises(ts.TwinError, match="no drive"):
        ts.attach_twin(Recorder(twin_serial="SYNTHELSE0000001"), "SYNTHTWIN0000001", mount_base=str(tmp_path / "T"))
    with pytest.raises(ts.TwinError, match="running system"):
        ts.attach_twin(Recorder(twin_vg_uuid="uuid-host"), "SYNTHTWIN0000001", mount_base=str(tmp_path / "T"))


def test_a_pair_config_names_the_peer_and_pair_and_nothing_else(tmp_path):
    f = tmp_path / "twin.json"
    assert ts.load_twin_config(f) is None
    ts.save_twin_config(f, pair_id="p1", peer_serial="SYNTHTWIN0000001")
    assert ts.load_twin_config(f) == {"pair": "p1", "peer_serial": "SYNTHTWIN0000001"}
    f.write_text(json.dumps({"pair": "p1", "peer_serial": "bad serial; x"}))
    assert ts.load_twin_config(f) is None                                                                     # malformed data is treated as no pairing, never trusted


def test_a_drives_installed_version_is_a_digest_of_its_source_and_only_a_healthy_one_is_offered(tmp_path):
    root = tmp_path / "root"
    (root / "opt/baseline/lib").mkdir(parents=True)
    (root / "opt/baseline/bin").mkdir(parents=True)
    (root / "opt/baseline/lib/a.py").write_text("one")
    first = ts.write_installed(root, now=100)
    assert ts.read_installed(root) == first and first["installed_at"] == 100
    (root / "opt/baseline/lib/a.py").write_text("two")
    assert ts.installed_digest(root) != first["digest"]                                       # any source change is a different version
    assert ts.read_installed(tmp_path / "nowhere") is None

    class Units:
        def __init__(self, down=()):
            self.down = set(down)

        def run(self, argv, timeout=20):
            class P:
                returncode = 3 if argv[-1] in self.down else 0
            return P()
    second = ts.write_installed(root, now=200)
    assert ts.health_mark(Units(down={"baseline-web.service"}), root=root) == {"healthy": False, "digest": second["digest"], "inactive": ["baseline-web.service"]}
    assert not ts.is_healthy(second["digest"], root=root)
    assert ts.health_mark(Units(), root=root)["healthy"] is True and ts.is_healthy(second["digest"], root=root)
    assert not ts.is_healthy(first["digest"], root=root)                                      # health belongs to one version, not to the drive


def test_a_pass_that_would_not_fit_is_refused_before_anything_is_copied(tmp_path, monkeypatch):
    """Found on the rehearsal: the installer cache did not fit on a small twin volume and rsync failed partway; the room is now checked first."""
    a, b = volume(tmp_path, "a"), volume(tmp_path, "b")
    put(a, "big.bin", "x" * 100000)
    import shutil
    real = shutil.disk_usage
    monkeypatch.setattr(ts.shutil, "disk_usage", lambda p: type("U", (), {"free": 50 * 1024 ** 2, "total": 0, "used": 0})())
    with pytest.raises(ts.TwinError, match="not enough room on b"):
        monkeypatch.setattr(ts, "RESERVE_BYTES", 60 * 1024 ** 2)
        sync(a, b)
    assert not (b / "big.bin").exists()                                                       # nothing was copied
    monkeypatch.setattr(ts.shutil, "disk_usage", real)
    monkeypatch.setattr(ts, "RESERVE_BYTES", 1024)
    assert sync(a, b)["a_to_b"] == 1 and (b / "big.bin").exists()
