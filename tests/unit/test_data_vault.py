import subprocess

import pytest

import data_vault as dv
from repair import RealRunner


def git_out(volume, *args):
    return subprocess.run(["git", "--git-dir", str(volume / dv.VAULT), *args], capture_output=True, text=True).stdout


@pytest.fixture
def vol(tmp_path):
    v = tmp_path / "USER_PERSONAL"
    (v / "docs").mkdir(parents=True)
    (v / "docs" / "a.txt").write_text("one")
    return v


def test_first_snapshot_puts_the_volume_under_git(vol):
    out = dv.snapshot(RealRunner(), vol, "USER_PERSONAL", message="build")
    assert out["created"] and out["changed"] and (vol / dv.VAULT / "HEAD").exists()
    assert "docs/a.txt" in git_out(vol, "ls-tree", "-r", "--name-only", "HEAD")


def test_unchanged_volume_makes_no_new_commit_and_changes_do(vol):
    r = RealRunner()
    a = dv.snapshot(r, vol, "USER_PERSONAL", message="m1")
    b = dv.snapshot(r, vol, "USER_PERSONAL", message="m2")
    assert b["commit"] == a["commit"] and not b["changed"]
    (vol / "docs" / "a.txt").write_text("two")
    assert dv.snapshot(r, vol, "USER_PERSONAL", message="m3")["commit"] != a["commit"]


def test_live_databases_images_and_oversize_files_are_not_versioned(vol, monkeypatch):
    monkeypatch.setattr(dv, "MAX_FILE_BYTES", 10)
    (vol / "x.sqlite").write_text("db")
    (vol / "vm.qcow2").write_text("img")
    (vol / "big.bin").write_text("0123456789ABCDEF")
    out = dv.snapshot(RealRunner(), vol, "USER_PERSONAL", message="m")
    tracked = git_out(vol, "ls-tree", "-r", "--name-only", "HEAD")
    assert "docs/a.txt" in tracked and "x.sqlite" not in tracked and "vm.qcow2" not in tracked and "big.bin" not in tracked
    assert out["left_out_too_large"] == ["big.bin"]


def test_vault_and_twin_state_never_enter_the_history(vol):
    (vol / ".baseline-twin").mkdir()
    (vol / ".baseline-twin" / "s").write_text("x")
    dv.snapshot(RealRunner(), vol, "USER_PERSONAL", message="m")
    assert ".baseline" not in git_out(vol, "ls-tree", "-r", "--name-only", "HEAD")


def test_user_admin_versions_only_the_users_own_folders(tmp_path):
    v = tmp_path / "USER_ADMIN"
    (v / "home").mkdir(parents=True)
    (v / "home" / "f").write_text("mine")
    (v / "secrets").mkdir()
    (v / "secrets" / "k").write_text("host identity")
    dv.snapshot(RealRunner(), v, "USER_ADMIN", message="m")
    tracked = git_out(v, "ls-tree", "-r", "--name-only", "HEAD")
    assert "home/f" in tracked and "secrets" not in tracked


def test_bundle_restores_the_history_after_the_volume_is_lost(vol, tmp_path):
    r = RealRunner()
    dv.snapshot(r, vol, "USER_PERSONAL", message="m", tag="rebuild-1")
    path = dv.bundle(r, vol, tmp_path / "out", name="b")
    clone = tmp_path / "restored"
    done = subprocess.run(["git", "clone", "-q", path, str(clone)], capture_output=True, text=True)
    assert done.returncode == 0 and (clone / "docs" / "a.txt").read_text() == "one"


def test_backup_all_reports_a_missing_volume(vol, tmp_path):
    out = dv.backup_all(RealRunner(), {"USER_PERSONAL": str(vol)}, tmp_path / "bk", message="m", tag="t")
    assert any(e["role"] == "USER_PERSONAL" and e["bundle"].endswith(".bundle") for e in out)
    assert {"role": "APPDATA_ADMIN", "skipped": "not mounted"} in out
