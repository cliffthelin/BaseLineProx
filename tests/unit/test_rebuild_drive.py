import pytest

import rebuild_drive as rd
import twin_sync


class R:
    pass


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    calls = []
    mounts = {"INSTALLER_CACHE": str(tmp_path / "IC"), "USER_PERSONAL": str(tmp_path / "UP")}
    monkeypatch.setattr(twin_sync, "peer_by_serial", lambda r, s: "c" * 32)
    monkeypatch.setattr(twin_sync, "attach_twin", lambda r, c, mount_base: calls.append("attach") or {"vg_uuid": "v", "mounts": dict(mounts)})
    monkeypatch.setattr(twin_sync, "detach_twin", lambda r, a, mount_base: calls.append("detach"))
    monkeypatch.setattr(rd.data_vault, "backup_all", lambda r, vols, dest, message, tag: calls.append(("backup", sorted(vols), str(dest))) or [{"role": "USER_PERSONAL"}])
    return calls


def test_backup_runs_between_attach_and_detach_and_nothing_is_formatted(fakes):
    out = rd.rebuild(R(), serial="S", stamp="t")
    assert fakes[0] == "attach" and fakes[-1] == "detach" and fakes[1][1] == ["USER_PERSONAL"] and fakes[1][2].endswith("backups/rebuild-t")
    assert out["formatted"] is False and "not changed" in out["code_layer"]


def test_update_runs_only_after_the_backup_and_detach(fakes):
    out = rd.rebuild(R(), serial="S", update=lambda: fakes.append("update") or {"ok": 1})
    assert fakes[-1] == "update" and fakes[-2] == "detach" and out["code_layer"] == {"ok": 1}


def test_no_installer_cache_stops_before_any_backup(fakes, monkeypatch):
    monkeypatch.setattr(twin_sync, "attach_twin", lambda r, c, mount_base: {"vg_uuid": "v", "mounts": {"USER_PERSONAL": "/x"}})
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
