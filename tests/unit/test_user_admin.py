"""USER_ADMIN is set up on each install: its folders, a record tying it to that install, and refusals that keep it private (DR257)."""
import json
import stat

import pytest

import user_admin as ua

HOST = "4af8c95a-beea-aa01-10de-57575cce4d00"


@pytest.fixture
def volume(tmp_path):
    root = tmp_path / "USER_ADMIN"
    root.mkdir()
    return root


def setup(root, **kw):
    return ua.setup(root, is_mount=lambda p: True, now=lambda: "2026-10-17T00:00:00+0000", **kw)


def test_a_new_volume_gets_its_folders_with_the_vault_private_and_a_record_for_this_install(volume):
    report = setup(volume, host_id=HOST)
    assert report["created"] == ["config", "settings", "vault", "chromium", "chromium/kiosk"] and report["kept"] == [] and not report["adopted_existing"]
    assert stat.S_IMODE((volume / "vault").stat().st_mode) == 0o700 and stat.S_IMODE((volume / "config").stat().st_mode) == 0o755
    record = json.loads((volume / ua.MANIFEST).read_text())
    assert record["format"] == ua.FORMAT and record["role"] == "USER_ADMIN" and record["host_id"] == HOST and record["created"] == "2026-10-17T00:00:00+0000"
    assert "never publish" in record["notice"]


def test_running_it_again_changes_nothing_and_keeps_the_original_creation_time(volume):
    setup(volume, host_id=HOST)
    (volume / "config" / "supported-os.json").write_text("kept")
    again = ua.setup(volume, host_id=HOST, is_mount=lambda p: True, now=lambda: "LATER")
    assert again["created"] == [] and again["adopted_existing"] and (volume / "config" / "supported-os.json").read_text() == "kept"
    assert json.loads((volume / ua.MANIFEST).read_text())["created"] == "2026-10-17T00:00:00+0000"


def test_it_refuses_to_write_when_the_path_is_not_a_mounted_volume(tmp_path):
    with pytest.raises(ua.UserAdminError, match="not a mounted volume"):
        ua.setup(tmp_path / "USER_ADMIN", host_id=HOST, is_mount=lambda p: False)
    assert not (tmp_path / "USER_ADMIN").exists()                         # nothing was created on the root volume


def test_a_volume_that_belongs_to_another_install_is_not_adopted(volume):
    setup(volume, host_id=HOST)
    with pytest.raises(ua.UserAdminError, match="different install"):
        setup(volume, host_id="00000000-0000-0000-0000-000000000000")


def test_an_unknown_record_format_is_not_adopted(volume):
    (volume / ua.MANIFEST).write_text(json.dumps({"format": "something.else/v9"}))
    with pytest.raises(ua.UserAdminError, match="does not understand"):
        setup(volume, host_id=HOST)


def test_a_looser_vault_folder_is_tightened_and_a_link_is_refused(volume, tmp_path):
    (volume / "vault").mkdir(mode=0o755)
    (volume / "vault").chmod(0o755)
    setup(volume, host_id=HOST)
    assert stat.S_IMODE((volume / "vault").stat().st_mode) == 0o700
    other = tmp_path / "elsewhere"
    other.mkdir()
    (volume / "chromium" / "kiosk").rmdir()
    (volume / "chromium" / "kiosk").symlink_to(other)
    with pytest.raises(ua.UserAdminError, match="link"):
        setup(volume, host_id=HOST)


def test_ready_means_mounted_and_set_up_by_this_module(volume):
    assert not ua.is_ready(volume, is_mount=lambda p: True)               # mounted but never set up
    setup(volume, host_id=HOST)
    assert ua.is_ready(volume, is_mount=lambda p: True) and not ua.is_ready(volume, is_mount=lambda p: False)


def test_it_works_without_a_host_identifier_yet_and_adopts_one_later(volume):
    setup(volume)
    assert "host_id" not in json.loads((volume / ua.MANIFEST).read_text())
    setup(volume, host_id=HOST)
    assert json.loads((volume / ua.MANIFEST).read_text())["host_id"] == HOST
