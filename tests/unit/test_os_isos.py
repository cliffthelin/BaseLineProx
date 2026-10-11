"""OS install images carried onto the drive's INSTALLER_CACHE/isos by the installed system itself.

Real files in real directories; the copy is verified against sums computed on the machine that offered the images."""
import hashlib

import pytest

import os_isos


def _offer(folder, **files):
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, data in files.items():
        (folder / name).write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    (folder / os_isos.SUMS).write_text("\n".join(lines) + "\n")
    return folder


def test_sums_are_parsed_and_unsafe_names_are_refused():
    ok = "a" * 64
    assert os_isos.parse_sums(f"{ok}  one.iso\n{ok} *two.iso\n") == {"one.iso": ok, "two.iso": ok}
    for bad in (f"{ok}  ../x.iso", f"{ok}  sub/x.iso", f"{ok}  .hidden", "short  x.iso", f"{ok}  "):
        with pytest.raises(ValueError):
            os_isos.parse_sums(bad + "\n")


def test_images_are_copied_and_read_back_identically(tmp_path):
    src = _offer(tmp_path / "offer", **{"a.iso": b"A" * 5000, "b.iso": b"B" * 7000})
    report = os_isos.carry(src, tmp_path / "isos", reserve_bytes=0)
    assert [c["name"] for c in report["carried"]] == ["a.iso", "b.iso"] and not report["skipped"]
    assert (tmp_path / "isos/a.iso").read_bytes() == b"A" * 5000
    assert not list((tmp_path / "isos").glob("*.partial"))


def test_an_image_that_does_not_match_its_sum_is_never_kept(tmp_path):
    src = _offer(tmp_path / "offer", **{"a.iso": b"A" * 100})
    (src / "a.iso").write_bytes(b"corrupted in transit")
    with pytest.raises(RuntimeError):
        os_isos.carry(src, tmp_path / "isos", reserve_bytes=0)
    assert not (tmp_path / "isos/a.iso").exists() and not list((tmp_path / "isos").glob("*.partial"))


def test_images_that_do_not_fit_are_skipped_by_name_not_silently(tmp_path):
    src = _offer(tmp_path / "offer", **{"a.iso": b"A" * 100})
    free = __import__("shutil").disk_usage(tmp_path).free
    report = os_isos.carry(src, tmp_path / "isos", reserve_bytes=free)   # leave everything free: nothing fits
    assert not report["carried"] and report["skipped"][0]["name"] == "a.iso"
    assert "space" in report["skipped"][0]["reason"]


def test_a_second_run_keeps_verified_images_and_copies_nothing_again(tmp_path):
    src = _offer(tmp_path / "offer", **{"a.iso": b"A" * 100})
    os_isos.carry(src, tmp_path / "isos", reserve_bytes=0)
    report = os_isos.carry(src, tmp_path / "isos", reserve_bytes=0)
    assert [c["name"] for c in report["already"]] == ["a.iso"] and not report["carried"]


def test_an_offer_without_sums_is_refused(tmp_path):
    (tmp_path / "offer").mkdir()
    (tmp_path / "offer/a.iso").write_bytes(b"x")
    with pytest.raises(RuntimeError):
        os_isos.carry(tmp_path / "offer", tmp_path / "isos", reserve_bytes=0)


def test_the_offer_is_built_from_real_files_with_their_real_sums(tmp_path):
    (tmp_path / "isos").mkdir()
    (tmp_path / "isos/a.iso").write_bytes(b"A" * 100)
    (tmp_path / "isos/notes.txt").write_text("not an image")
    offer = os_isos.build_offer(tmp_path / "isos", ["a.iso"], tmp_path / "offer")
    assert (offer / "a.iso").read_bytes() == b"A" * 100 and not (offer / "notes.txt").exists()
    assert os_isos.parse_sums((offer / os_isos.SUMS).read_text()) == {"a.iso": hashlib.sha256(b"A" * 100).hexdigest()}
    with pytest.raises(ValueError):
        os_isos.build_offer(tmp_path / "isos", ["missing.iso"], tmp_path / "offer2")


def test_the_cache_folder_gets_the_layout_proxmox_lists_isos_from(tmp_path):
    (tmp_path / "isos").mkdir()
    (tmp_path / "isos/a.iso").write_bytes(b"x")
    os_isos.link_iso_folder(tmp_path)
    assert (tmp_path / "template/iso").is_symlink() and (tmp_path / "template/iso/a.iso").read_bytes() == b"x"
    os_isos.link_iso_folder(tmp_path)                       # repeating changes nothing
    other = tmp_path / "other"
    (other / "template/iso").mkdir(parents=True)
    with pytest.raises(RuntimeError):                       # a real folder already there is never replaced
        (other / "isos").mkdir()
        os_isos.link_iso_folder(other)


def test_the_iso_storage_is_added_once_and_a_conflicting_one_is_refused(tmp_path):
    root = "/mnt/INSTALLER_CACHE"
    argv = os_isos.storage_add_argv([{"storage": "local", "type": "dir", "path": "/var/lib/vz"}], root)
    assert argv == ["pvesm", "add", "dir", os_isos.ISO_STORAGE, "--path", root, "--content", "iso",
                    "--is_mountpoint", root]
    same = [{"storage": os_isos.ISO_STORAGE, "type": "dir", "path": root, "content": "iso"}]
    assert os_isos.storage_add_argv(same, root) is None
    with pytest.raises(RuntimeError):
        os_isos.storage_add_argv([{"storage": os_isos.ISO_STORAGE, "type": "dir", "path": "/elsewhere"}], root)


def test_an_image_that_does_not_fit_asks_for_room_once_and_is_skipped_if_none_comes(tmp_path):
    import hashlib
    import os_isos
    source, dest = tmp_path / "offer", tmp_path / "isos"
    source.mkdir()
    (source / "a.iso").write_bytes(b"x" * 4096)
    (source / os_isos.SUMS).write_text(f"{hashlib.sha256(b'x' * 4096).hexdigest()}  a.iso\n")
    asked = []
    report = os_isos.carry(source, dest, reserve_bytes=1 << 60, make_room=asked.append)       # more reserve than any disk has
    assert asked == [4096 + (1 << 60)] and [i["name"] for i in report["skipped"]] == ["a.iso"] and report["carried"] == []
    asked.clear()
    report = os_isos.carry(source, dest, reserve_bytes=0, make_room=asked.append)
    assert asked == [] and [i["name"] for i in report["carried"]] == ["a.iso"]
