"""The build host's lane files (drives.json and own-drives) are found the same way by every tool, so a tool run on its own (sudo, a service, a
one-off command) sees the drives the installer sees. Synthetic serials; real files under tmp_path."""
import os

import drive_admin
import lane_files


def test_defaults_name_the_own_drives_file_beside_the_drives_file(tmp_path, monkeypatch):
    (tmp_path / "own-drives").write_text("SYNTHAAAA111111\n")
    monkeypatch.setattr(lane_files, "BUILD_DRIVES_FILE", str(tmp_path / "drives.json"))
    env = {}
    lane_files.apply_defaults(env)
    assert env["BASELINE_DRIVES_FILE"] == str(tmp_path / "drives.json")
    assert env["BASELINE_OWN_DRIVES_FILE"] == str(tmp_path / "own-drives")


def test_an_installed_system_without_the_build_volume_keeps_its_own_default(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_files, "BUILD_DRIVES_FILE", str(tmp_path / "absent" / "drives.json"))
    env = {}
    lane_files.apply_defaults(env)
    assert env == {}                                           # drive_guard then reads /etc/baseline/own-drives


def test_an_operator_set_location_is_never_overridden():
    env = {"BASELINE_DRIVES_FILE": "/elsewhere/drives.json"}
    lane_files.apply_defaults(env)
    assert env["BASELINE_OWN_DRIVES_FILE"] == "/elsewhere/own-drives"
    env = {"BASELINE_DRIVES_FILE": "/a/drives.json", "BASELINE_OWN_DRIVES_FILE": "/b/mine"}
    lane_files.apply_defaults(env)
    assert env["BASELINE_OWN_DRIVES_FILE"] == "/b/mine" and env["BASELINE_DRIVES_FILE"] == "/a/drives.json"


def test_a_tool_started_with_nothing_set_finds_the_lane_drives_after_the_defaults(tmp_path, monkeypatch):
    own = tmp_path / "own-drives"
    own.write_text("SYNTHAAAA111111 disposable\n")
    monkeypatch.delenv("BASELINE_OWN_DRIVES_FILE", raising=False)
    assert "SYNTHAAAA111111" not in drive_admin.allowed_target_serials()                 # the failure the operator hit
    monkeypatch.setattr(lane_files, "BUILD_DRIVES_FILE", str(tmp_path / "drives.json"))
    monkeypatch.delenv("BASELINE_DRIVES_FILE", raising=False)
    lane_files.apply_defaults(os.environ)
    assert "SYNTHAAAA111111" in drive_admin.allowed_target_serials()


def test_the_rebuild_tool_applies_the_defaults_before_anything_else():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "baseline/bin/baseline-rebuild-drive").read_text()
    assert "lane_files.apply_defaults(os.environ)" in source
    assert source.index("lane_files.apply_defaults") < source.index("import managed_mode")
