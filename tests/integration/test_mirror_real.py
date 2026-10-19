"""Real-rsync proof (run by hand: python3 -m pytest tests/integration/test_mirror_real.py -q): the mirror updates only what changed (operator, 2026-10-19:
"if 10 files changed that is all you update, if a million changed that is all you update"). No device and no root: plain directories."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import mirror  # noqa: E402


class Real:
    def run(self, argv, timeout=None):
        return subprocess.run(argv, capture_output=True, text=True)


def tree(root, count=300):
    for i in range(count):
        d = root / f"d{i % 10}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"f{i}.txt").write_text(f"file {i}\n" * 20)


def test_only_changed_files_are_written_and_the_rest_is_not_touched(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    tree(src)
    first = mirror.sync_volume(Real(), src, dst)
    assert first["files_changed"] == 300
    untouched = dst / "d3" / "f3.txt"
    before = (os.stat(untouched).st_ino, os.stat(untouched).st_mtime_ns)
    again = mirror.sync_volume(Real(), src, dst)
    assert again == {"files_changed": 0, "bytes_sent": 0}                                  # nothing changed: nothing written
    for i in range(0, 100, 10):                                                           # ten files change
        (src / f"d{i % 10}" / f"f{i}.txt").write_text("changed\n" * 30)
    (src / "d1" / "gone.txt").write_text("x")
    mirror.sync_volume(Real(), src, dst)
    (src / "d1" / "gone.txt").unlink()                                                    # a deletion
    (src / "new").mkdir()
    (src / "new" / "added.txt").write_text("added\n")
    ten = mirror.sync_volume(Real(), src, dst)
    assert ten["files_changed"] == 1 and not (dst / "d1" / "gone.txt").exists() and (dst / "new" / "added.txt").read_text() == "added\n"
    assert (os.stat(untouched).st_ino, os.stat(untouched).st_mtime_ns) == before             # an unchanged file is never rewritten


def test_ten_changed_files_write_ten_files_not_the_volume(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    tree(src)
    mirror.sync_volume(Real(), src, dst)
    for i in range(10):
        (src / f"d{i}" / f"f{i}.txt").write_text(f"edited {i}\n" * 25)
    assert mirror.sync_volume(Real(), src, dst)["files_changed"] == 10


def test_a_change_inside_a_big_file_writes_only_the_changed_blocks(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    big = src / "big.bin"
    big.write_bytes(os.urandom(8 * 2 ** 20))
    mirror.sync_volume(Real(), src, dst)
    with open(big, "r+b") as stream:
        stream.seek(4 * 2 ** 20)
        stream.write(b"EDIT")
    os.utime(big, None)
    out = mirror.sync_volume(Real(), src, dst)
    assert out["files_changed"] == 1 and out["bytes_sent"] < 256 * 1024                          # a few blocks of an 8 MiB file, not the file
    assert (dst / "big.bin").read_bytes() == big.read_bytes()


def test_links_and_empty_directories_survive_and_holes_are_not_expanded(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / "a").write_text("same")
    os.link(src / "a", src / "b")
    (src / "empty").mkdir()
    (src / "link").symlink_to("a")
    with open(src / "holey", "wb") as stream:
        stream.truncate(64 * 2 ** 20)
        stream.seek(0)
        stream.write(b"head")
    mirror.sync_volume(Real(), src, dst)
    assert os.stat(dst / "a").st_ino == os.stat(dst / "b").st_ino and (dst / "empty").is_dir() and os.readlink(dst / "link") == "a"
    assert os.stat(dst / "holey").st_blocks * 512 < 1 * 2 ** 20                                    # the 64 MiB of hole is not stored


def test_cache_sync_adds_only_what_is_missing_and_never_deletes(tmp_path):
    import cache_sync
    src, dst = tmp_path / "src", tmp_path / "dst"
    tree(src, 40)
    (dst / "d0").mkdir(parents=True)
    import shutil
    shutil.copy2(src / "d0" / "f0.txt", dst / "d0" / "f0.txt")                   # already there, same content and time
    (dst / "only-here.txt").write_text("keep me")                              # not in the source
    measured = cache_sync.measure(Real(), src, dst)
    assert measured["files_changed"] == 39                                      # 40 files, one already there
    done = Real().run([*cache_sync.FLAGS, str(src) + "/", str(dst) + "/"])
    assert done.returncode == 0 and (dst / "only-here.txt").read_text() == "keep me"
    again = cache_sync.measure(Real(), src, dst)
    assert again["files_changed"] == 0
