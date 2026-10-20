"""The console's file manager: browse, download, upload, new folder, rename, delete, only inside the connected drives and never through a link that leaves them."""
import os
import pytest

import file_manager as fm


@pytest.fixture
def area(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    (root / "docs").mkdir(); (root / "a.txt").write_text("hello")
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "secret").write_text("x")
    return root, outside, (str(root),)


def test_listing_shows_folders_first_with_sizes(area):
    root, _, allowed = area
    listing = fm.listing(str(root), allowed)
    assert [e["name"] for e in listing["entries"]] == ["docs", "a.txt"]
    assert listing["entries"][1]["size"] == 5 and listing["entries"][0]["dir"]


def test_the_top_lists_the_connected_drives(area):
    root, _, allowed = area
    top = fm.listing("", allowed)
    assert top["path"] == "" and any(e["path"] == str(root / "docs") for e in top["entries"])


def test_nothing_outside_the_drives_is_reachable(area):
    root, outside, allowed = area
    assert "error" in fm.listing(str(outside), allowed)
    assert "error" in fm.listing(str(root) + "/../outside", allowed)
    (root / "link").symlink_to(outside)
    assert "error" in fm.listing(str(root / "link"), allowed)
    with pytest.raises(fm.FileManagerError):
        fm.open_for_download(str(root / "link" / "secret"), allowed)


def test_download_returns_a_file_and_refuses_a_folder(area):
    root, _, allowed = area
    path, size = fm.open_for_download(str(root / "a.txt"), allowed)
    assert size == 5
    with pytest.raises(fm.FileManagerError):
        fm.open_for_download(str(root / "docs"), allowed)


def test_make_folder_rename_and_delete(area):
    root, _, allowed = area
    fm.make_folder(str(root), "new", allowed)
    assert (root / "new").is_dir()
    fm.rename(str(root / "a.txt"), "b.txt", allowed)
    assert (root / "b.txt").exists() and not (root / "a.txt").exists()
    fm.delete(str(root / "b.txt"), allowed)
    fm.delete(str(root / "new"), allowed)
    assert not (root / "b.txt").exists() and not (root / "new").exists()


def test_names_are_plain_names_never_paths(area):
    root, _, allowed = area
    for bad in ("", ".", "..", "a/b", "../x", "x\0y"):
        with pytest.raises(fm.FileManagerError):
            fm.make_folder(str(root), bad, allowed)
    with pytest.raises(fm.FileManagerError):
        fm.rename(str(root / "a.txt"), "../escape", allowed)


def test_a_folder_with_things_inside_is_not_deleted(area):
    root, _, allowed = area
    (root / "docs" / "x").write_text("1")
    with pytest.raises(fm.FileManagerError):
        fm.delete(str(root / "docs"), allowed)
    assert (root / "docs" / "x").exists()


def test_a_drive_itself_cannot_be_renamed_or_deleted(area):
    root, _, allowed = area
    with pytest.raises(fm.FileManagerError):
        fm.delete(str(root), allowed)
    with pytest.raises(fm.FileManagerError):
        fm.rename(str(root), "x", allowed)


def test_renaming_or_deleting_a_symlink_does_not_change_its_target(area):
    root, outside, allowed = area
    link = root / "link-to-secret"
    link.symlink_to(outside / "secret")
    fm.rename(str(link), "renamed-link", allowed)
    assert not link.is_symlink() and (root / "renamed-link").is_symlink()
    assert (outside / "secret").read_text() == "x"
    fm.delete(str(root / "renamed-link"), allowed)
    assert not (root / "renamed-link").exists() and (outside / "secret").read_text() == "x"


def test_upload_never_overwrites_and_writes_what_it_was_sent(area):
    root, _, allowed = area
    import io
    fm.save_upload(str(root), "new.bin", io.BytesIO(b"abc"), 3, allowed)
    assert (root / "new.bin").read_bytes() == b"abc"
    with pytest.raises(fm.FileManagerError):
        fm.save_upload(str(root), "a.txt", io.BytesIO(b"zzz"), 3, allowed)
    assert (root / "a.txt").read_text() == "hello"
    with pytest.raises(fm.FileManagerError):
        fm.save_upload(str(root), "../p", io.BytesIO(b"zzz"), 3, allowed)


def test_a_short_upload_leaves_no_half_file(area):
    root, _, allowed = area
    import io
    with pytest.raises(fm.FileManagerError):
        fm.save_upload(str(root), "cut.bin", io.BytesIO(b"ab"), 10, allowed)
    assert not (root / "cut.bin").exists() and not any(n.startswith(".upload-") for n in os.listdir(root))


def test_page_escapes_names_and_has_the_actions(area):
    root, _, allowed = area
    (root / "<b>x<i>").write_text("1")
    page = fm.render(fm.listing(str(root), allowed), allowed).decode()
    assert "<b>x<i>" not in page and "&lt;b&gt;x" in page
    assert "/files/download" in page and "New folder" in page and "Upload" in page
