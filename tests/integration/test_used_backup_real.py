"""Real-tool proof (tests/integration, run by hand: python3 -m pytest tests/integration/test_used_backup_real.py -q): backups never store empty space
(operator, 2026-10-01 and 2026-10-19). Real partclone, zstd and mkfs.ext4 on files (no device, no root): ext4 images whose free blocks are FILLED WITH RANDOM
DATA first (the leftovers a reinstall leaves, which a whole-device copy would store), then imaged."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import os
import subprocess

import pytest

import used_backup as ub

MIB = 2 ** 20


def make_ext4(tmp_path, name, *, size_mib, files_mib, stale=True):
    image = tmp_path / name
    tree = tmp_path / (name + "-tree")
    tree.mkdir()
    (tree / "payload.bin").write_bytes(os.urandom(files_mib * MIB))
    with open(image, "wb") as stream:
        stream.truncate(size_mib * MIB)
        if stale:                                                      # leftover data in what will be free space
            stream.seek(0)
            for _ in range(size_mib):
                stream.write(os.urandom(MIB))
    subprocess.run(["mkfs.ext4", "-q", "-F", "-d", str(tree), str(image)], check=True)
    return image


def test_an_ext4_volume_is_stored_by_its_used_blocks_not_its_size_even_when_its_free_space_holds_old_data(tmp_path):
    image = make_ext4(tmp_path, "vol.img", size_mib=128, files_mib=8)
    done = ub.image_volume(image, tmp_path / "out", "vol")
    assert done["fstype"] == "ext4" and done["device_bytes"] == 128 * MIB
    assert done["image_bytes"] < 20 * MIB                                  # about the 8 MiB of data, nowhere near 128
    assert done["used_bytes"] >= 8 * MIB and done["image_bytes"] <= done["used_bytes"] + 16 * MIB
    assert ub.check_image(tmp_path / "out" / done["image"], "ext4") is True


def test_a_second_volume_of_the_same_data_is_the_same_size_whatever_the_volume_size(tmp_path):
    small = ub.image_volume(make_ext4(tmp_path, "a.img", size_mib=64, files_mib=6), tmp_path / "o1", "a")
    large = ub.image_volume(make_ext4(tmp_path, "b.img", size_mib=192, files_mib=6), tmp_path / "o2", "b")
    assert abs(small["image_bytes"] - large["image_bytes"]) < 4 * MIB


def test_an_image_is_restorable_to_the_same_files(tmp_path):
    image = make_ext4(tmp_path, "src.img", size_mib=64, files_mib=4)
    done = ub.image_volume(image, tmp_path / "out", "src")
    restored = tmp_path / "restored.img"
    restored.write_bytes(b"")
    os.truncate(restored, done["device_bytes"])                    # the target is a volume of the right size, as on a drive
    ub.restore_volume(tmp_path / "out" / done["image"], restored, "ext4")
    listing = subprocess.run(["debugfs", "-R", "ls -l /", str(restored)], capture_output=True, text=True).stdout
    assert "payload.bin" in listing
    subprocess.run(["e2fsck", "-fn", str(restored)], check=True, capture_output=True)


def test_an_unknown_filesystem_is_refused_never_copied_whole(tmp_path):
    blank = tmp_path / "raw.img"
    blank.write_bytes(os.urandom(4 * MIB))
    with pytest.raises(ub.UsedBackupError, match="filesystem"):
        ub.image_volume(blank, tmp_path / "out", "raw")
    assert not list((tmp_path / "out").glob("*")) if (tmp_path / "out").exists() else True


def test_an_image_larger_than_the_data_it_holds_is_a_failure_not_a_backup(tmp_path):
    assert ub.accept_size(used_bytes=10 * MIB, image_bytes=11 * MIB) is True
    with pytest.raises(ub.UsedBackupError, match="empty space"):
        ub.accept_size(used_bytes=10 * MIB, image_bytes=300 * MIB)


def test_an_unchanged_volume_is_linked_not_written_again_and_a_changed_one_is_imaged(tmp_path):
    """Real partclone: the second image of an unchanged filesystem is a hard link to the first (no new data), and a changed one is a new image."""
    fs = make_ext4(tmp_path, "vol.img", size_mib=32, files_mib=4)
    first = ub.image_volume(fs, tmp_path / "one", "vol", fstype="ext4")
    again = ub.image_volume(fs, tmp_path / "two", "vol", fstype="ext4", previous=first, previous_dir=tmp_path / "one")
    assert again.get("reused") is True and os.stat(tmp_path / "two" / again["image"]).st_ino == os.stat(tmp_path / "one" / first["image"]).st_ino
    subprocess.run(["debugfs", "-w", "-R", "write /etc/hostname changed.txt", str(fs)], check=True, capture_output=True)
    changed = ub.image_volume(fs, tmp_path / "three", "vol", fstype="ext4", previous=first, previous_dir=tmp_path / "one")
    assert not changed.get("reused") and changed["sha256"] != first["sha256"]
