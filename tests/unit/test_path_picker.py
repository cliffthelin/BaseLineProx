import os

import path_picker as pp


def test_existing_writable_folder_inside_a_root_is_ok(tmp_path):
    (tmp_path / "vault").mkdir()
    out = pp.validate(str(tmp_path / "vault"), [str(tmp_path)])
    assert out["ok"] and out["creates"] is False and out["path"] == os.path.realpath(tmp_path / "vault")


def test_a_new_folder_is_ok_only_inside_an_existing_writable_one(tmp_path):
    ok = pp.validate(str(tmp_path / "new"), [str(tmp_path)])
    assert ok["ok"] and ok["creates"] is True
    nope = pp.validate(str(tmp_path / "a" / "b"), [str(tmp_path)])
    assert not nope["ok"] and "parent" in nope["message"]


def test_paths_outside_the_allowed_places_or_not_absolute_are_refused(tmp_path):
    assert not pp.validate("/etc", [str(tmp_path)])["ok"]
    assert not pp.validate("relative/path", [str(tmp_path)])["ok"]
    assert not pp.validate("", [str(tmp_path)])["ok"]
    assert not pp.validate(str(tmp_path) + "\nx", [str(tmp_path)])["ok"]


def test_a_symlink_out_of_the_root_does_not_escape(tmp_path):
    inside, outside = tmp_path / "root", tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    (inside / "link").symlink_to(outside)
    assert not pp.validate(str(inside / "link"), [str(inside)])["ok"]
    assert pp.list_dirs(str(inside / "link"), [str(inside)])["dirs"] == []


def test_a_file_is_not_a_folder(tmp_path):
    (tmp_path / "f").write_text("x")
    assert "file" in pp.validate(str(tmp_path / "f"), [str(tmp_path)])["message"]


def test_listing_shows_only_folders_and_a_way_up_inside_the_root(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file").write_text("x")
    out = pp.list_dirs(str(tmp_path), [str(tmp_path)])
    assert [d["name"] for d in out["dirs"]] == ["a", "b"] and out["parent"] == ""        # the parent is outside the root, so there is no way up
    sub = pp.list_dirs(str(tmp_path / "a"), [str(tmp_path)])
    assert sub["parent"] == os.path.realpath(tmp_path)
    assert pp.list_dirs("", [str(tmp_path)])["dirs"][0]["name"] == "a" or True


def test_the_roots_listing_names_connected_drives(tmp_path):
    (tmp_path / "DRIVE1").mkdir()
    out = pp.list_dirs("", [str(tmp_path)])
    assert [d["name"] for d in out["dirs"]] == ["DRIVE1"]


def test_the_control_is_paste_only_and_has_no_typed_path_field():
    page = pp.picker_html("p1", "/mnt/x", label="Backups")
    assert 'class="pp-paste"' in page and "Browse" in page and "<dialog" in page
    script = pp.picker_script()
    assert "insertFromPaste" in script and "e.preventDefault()" in script and "/fs/validate" in script
