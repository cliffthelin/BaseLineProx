import json

import pytest

import managed_mode as mm


def test_default_is_standalone_and_no_parent_is_named(tmp_path):
    p = tmp_path / "m.json"
    assert mm.load(p)["mode"] == "standalone" and mm.parent_vault(p) is None and not mm.remote_rebuild_enabled(p)


def test_a_broken_file_never_turns_managed_mode_on(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("{not json")
    assert not mm.is_managed(p)
    p.write_text(json.dumps({"mode": "weird", "parent_vault": "/x"}))
    assert not mm.is_managed(p)


def test_managed_needs_a_vault_folder_and_remote_needs_managed(tmp_path):
    p = tmp_path / "m.json"
    with pytest.raises(mm.ManagedError):
        mm.save({"mode": "managed"}, p)
    with pytest.raises(mm.ManagedError):
        mm.save({"mode": "standalone", "remote_rebuild": True}, p)


def test_enabled_then_disabled_returns_to_standalone(tmp_path):
    p = tmp_path / "m.json"
    mm.save({"mode": "managed", "parent_vault": "/v", "remote_rebuild": True}, p)
    assert mm.parent_vault(p) == "/v" and mm.remote_rebuild_enabled(p)
    mm.save({"mode": "standalone"}, p)
    assert mm.parent_vault(p) is None and not mm.remote_rebuild_enabled(p)


def test_config_follows_the_drives_file_on_a_build_host():
    assert str(mm.config_path({"BASELINE_DRIVES_FILE": "/b/drives.json"})) == "/b/managed.json"
    assert str(mm.config_path({"BASELINE_MANAGED_FILE": "/m.json"})) == "/m.json"


def test_candidate_folders_offer_each_mounted_data_volume_without_typing():
    mounts = ("/dev/sda1 / ext4 rw 0 0\ntmpfs /run tmpfs rw 0 0\n/dev/sdb1 /run/media/u/CACHE ext4 rw 0 0\n"
              "/dev/sdc1 /mnt/10TB ext4 rw 0 0\n/dev/sdc1 /mnt/10TB ext4 rw 0 0\n/dev/loop0 /snap/x squashfs ro 0 0\n")
    out = mm.candidate_folders(mounts)
    assert [o["folder"] for o in out] == ["/run/media/u/CACHE/baseline-vault", "/mnt/10TB/baseline-vault"]
    assert mm.candidate_folders("") == []
