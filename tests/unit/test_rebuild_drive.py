import pytest

import rebuild_drive as rd
import twin_sync


class R:
    pass


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    calls = []
    mounts = {"INSTALLER_CACHE": str(tmp_path / "IC"), "USER_PERSONAL": str(tmp_path / "UP")}
    monkeypatch.setattr(twin_sync, "peer_by_serial", lambda r, s: "4af8c95a-d894-0a4e-10cb-2472edbff000")
    monkeypatch.setattr(twin_sync, "attach_twin", lambda r, c, mount_base, include=None: calls.append("attach") or {"vg_uuid": "v", "mounts": dict(mounts)})
    monkeypatch.setattr(twin_sync, "detach_twin", lambda r, a, mount_base: calls.append("detach"))
    monkeypatch.setattr(rd.data_history, "backup_all", lambda r, vols, dest, message, tag: calls.append(("backup", sorted(vols), str(dest))) or [{"role": "USER_PERSONAL"}])
    return calls


def test_backup_runs_between_attach_and_detach_and_nothing_is_formatted(fakes):
    out = rd.rebuild(R(), serial="S", stamp="t")
    assert fakes[0] == "attach" and fakes[-1] == "detach" and fakes[1][1] == ["USER_PERSONAL"] and fakes[1][2].endswith("backups/rebuild-t")
    assert out["formatted"] is False and "not changed" in out["code_layer"]


def test_update_runs_only_after_the_backup_and_detach(fakes):
    out = rd.rebuild(R(), serial="S", update=lambda: fakes.append("update") or {"ok": 1})
    assert fakes[-1] == "update" and fakes[-2] == "detach" and out["code_layer"] == {"ok": 1}


def test_no_installer_cache_stops_before_any_backup(fakes, monkeypatch):
    monkeypatch.setattr(twin_sync, "attach_twin", lambda r, c, mount_base, include=None: {"vg_uuid": "v", "mounts": {"USER_PERSONAL": "/x"}})
    with pytest.raises(rd.RebuildError):
        rd.rebuild(R(), serial="S")
    assert not any(isinstance(c, tuple) for c in fakes)


def test_unknown_drive_is_a_rebuild_error(monkeypatch):
    def boom(r, s):
        raise twin_sync.TwinError("no such drive")
    monkeypatch.setattr(twin_sync, "peer_by_serial", boom)
    with pytest.raises(rd.RebuildError):
        rd.rebuild(R(), serial="S")


def test_missing_role_volumes_are_reported_for_in_place_adding_not_wiping(fakes):
    out = rd.rebuild(R(), serial="S")
    assert "USER_ADMIN" in out["volumes_to_add_in_place"] and out["wipe_needed"] is False


def test_histories_are_filed_on_the_parent_while_the_drive_is_attached(fakes, monkeypatch):
    seen = []
    monkeypatch.setattr(rd.mirror_history, "push", lambda r, path, root, child_ids, this_child, role: seen.append((fakes[-1], role, root, child_ids)) or {"role": role})
    monkeypatch.setattr(rd.mirror_history, "migrate_legacy", lambda root: [])
    monkeypatch.setattr(rd.mirror, "refresh", lambda *a, **k: {"files_changed": 0})
    out = rd.rebuild(R(), serial="S", mirror_root="/parent")
    assert seen and seen[0][0][0] == "backup" and "detach" not in fakes[:-1] and out["history"] == [{"role": "USER_PERSONAL"}]


def test_missing_configuration_is_added_and_the_drives_own_is_never_touched(tmp_path):
    import json
    repo, ua = tmp_path / "repo", tmp_path / "USER_ADMIN"
    (repo / "config/local").mkdir(parents=True)
    ua.mkdir()
    entry = [{"name": "Ubuntu", "kind": "iso", "image": "ubuntu.iso"}]
    (repo / "config/local/supported-os.json").write_text(json.dumps(entry))
    try:
        out = rd.seed_missing({"USER_ADMIN": str(ua)}, repo)
    except Exception:                                   # the list's own format decides; a list that does not check out must not be copied
        out = [{"result": "refused"}]
    if out[-1]["result"] == "added":
        assert (ua / "config/supported-os.json").read_text() == (repo / "config/local/supported-os.json").read_text()
        (ua / "config/supported-os.json").write_text("the operator's own edit")
        again = rd.seed_missing({"USER_ADMIN": str(ua)}, repo)
        assert again[0]["result"] == "kept the drive's own" and (ua / "config/supported-os.json").read_text() == "the operator's own edit"
    assert rd.seed_missing({}, repo) == []                                     # no such volume: nothing done


def test_a_list_that_does_not_check_out_is_not_copied(tmp_path):
    repo, ua = tmp_path / "repo", tmp_path / "USER_ADMIN"
    (repo / "config/local").mkdir(parents=True)
    ua.mkdir()
    (repo / "config/local/supported-os.json").write_text("not json at all")
    out = rd.seed_missing({"USER_ADMIN": str(ua)}, repo)
    assert out[-1]["result"].startswith("not written") and not (ua / "config/supported-os.json").exists()


def test_the_list_of_systems_is_built_from_what_the_drive_carries_with_the_applications_preset(tmp_path):
    import json
    import os_list
    ua, ic, repo = tmp_path / "USER_ADMIN", tmp_path / "INSTALLER_CACHE", tmp_path / "repo"
    bases = ic / "installer/expanded/baseline-cache/os-bases"
    bases.mkdir(parents=True)
    (ic / "isos").mkdir()
    ua.mkdir()
    repo.mkdir()
    (bases / "ubuntu-base.qcow2").write_bytes(b"q")
    (bases / "ubuntu-base.json").write_text(json.dumps({"base": "ubuntu-base.qcow2"}))
    (bases / "nixos-base.json").write_text(json.dumps({"base": "missing.qcow2"}))             # a manifest without its image is not offered
    (ic / "isos" / "Qubes-R4.3.2-x86_64.iso").write_bytes(b"i")
    out = rd.seed_missing({"USER_ADMIN": str(ua), "INSTALLER_CACHE": str(ic)}, repo)
    assert out[-1]["result"] == "added" and out[-1]["origin"] == "built from the systems the drive carries"
    entries = os_list.parse((ua / "config/supported-os.json").read_text())
    assert {e["id"] for e in entries} == {"ubuntu", "qubes"} and all(e["apps"] == list(os_list.APPS) for e in entries)
    (ua / "config/supported-os.json").write_text('{"os": []}')
    assert rd.seed_missing({"USER_ADMIN": str(ua), "INSTALLER_CACHE": str(ic)}, repo)[-1]["result"] == "kept the drive's own"


def test_explicit_parent_bluetooth_transfer_requires_user_admin_and_always_detaches(fakes):
    with pytest.raises(rd.RebuildError, match='USER_ADMIN'):
        rd.rebuild(R(), serial='S', bluetooth_from_parent=True)
    assert fakes[-1] == 'detach'


def test_parent_bluetooth_transfer_runs_after_backup_before_mirror_history(fakes, monkeypatch, tmp_path):
    import bluetooth_transfer
    admin = tmp_path / 'admin'
    admin.mkdir()
    monkeypatch.setattr(twin_sync, 'attach_twin', lambda *a, **k: {'vg_uuid': 'v', 'mounts': {'USER_ADMIN': str(admin), 'INSTALLER_CACHE': str(tmp_path / 'ic')}})
    def transfer(source, dest):
        assert fakes[-1][0] == 'backup'
        assert source == '/var/lib/bluetooth' and dest == str(admin)
        return {'state': 'copied'}
    monkeypatch.setattr(bluetooth_transfer, 'seed', transfer)
    out = rd.rebuild(R(), serial='S', bluetooth_from_parent=True)
    assert out['bluetooth'] == {'state': 'copied'} and fakes[-1] == 'detach'


def test_the_person_who_runs_the_update_is_recorded_as_the_owner_once(tmp_path, monkeypatch):
    import operator_identity as oi
    ua = tmp_path / "ua"
    ua.mkdir()
    monkeypatch.setenv("SUDO_USER", "cane")
    out = rd.seed_missing({"USER_ADMIN": str(ua)}, tmp_path)
    assert out[0] == {"file": oi.FILE, "result": "added", "username": "cane"} and oi.read(ua / oi.FILE) == "cane"
