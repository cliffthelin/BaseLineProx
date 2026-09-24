import pytest

from inventory import pathsafety


def test_refuses_path_inside_repo_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path(str(repo / "out.json"), str(repo), overwrite=False)


def test_refuses_path_inside_etc(tmp_path):
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path("/etc/inventory-out.json", str(tmp_path), overwrite=False)


def test_refuses_path_inside_etc_pve(tmp_path):
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path("/etc/pve/inventory-out.json", str(tmp_path), overwrite=False)


def test_refuses_path_inside_var_lib_baseline(tmp_path):
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path("/var/lib/baseline/out.json", str(tmp_path), overwrite=False)


def test_refuses_symlink_at_final_path(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path(str(link), str(tmp_path / "unrelated-repo"), overwrite=True)


def test_refuses_parent_symlink_into_forbidden_dir(tmp_path):
    fake_etc = tmp_path / "fake-etc-link"
    fake_etc.symlink_to("/etc")
    target = fake_etc / "out.json"
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path(str(target), str(tmp_path / "unrelated-repo"), overwrite=False)


def test_refuses_dotdot_traversal_into_forbidden_dir(tmp_path):
    outside = str(tmp_path) + "/../../../../../../etc/out.json"
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path(outside, str(tmp_path / "unrelated-repo"), overwrite=False)


def test_refuses_overwrite_without_flag(tmp_path):
    existing = tmp_path / "out.json"
    existing.write_text("{}")
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.validate_output_path(str(existing), str(tmp_path / "unrelated-repo"), overwrite=False)


def test_allows_overwrite_with_flag(tmp_path):
    existing = tmp_path / "out.json"
    existing.write_text("{}")
    resolved = pathsafety.validate_output_path(str(existing), str(tmp_path / "unrelated-repo"), overwrite=True)
    assert resolved == str(existing.resolve())


def test_allows_a_normal_new_path(tmp_path):
    target = tmp_path / "new" / "out.json"
    target.parent.mkdir()
    resolved = pathsafety.validate_output_path(str(target), str(tmp_path / "unrelated-repo"), overwrite=False)
    assert resolved == str(target.resolve())


def test_atomic_write_creates_mode_0600(tmp_path):
    target = tmp_path / "out.json"
    pathsafety.atomic_write(str(target), b'{"a": 1}\n', overwrite=False)
    assert target.exists()
    assert oct(target.stat().st_mode)[-3:] == "600"
    assert target.read_bytes() == b'{"a": 1}\n'


def test_atomic_write_leaves_no_temp_file_behind_on_success(tmp_path):
    target = tmp_path / "out.json"
    pathsafety.atomic_write(str(target), b"{}", overwrite=False)
    remaining = [p for p in tmp_path.iterdir() if p.name != "out.json"]
    assert remaining == []


def test_atomic_write_refuses_when_a_symlink_appears_at_the_final_path(tmp_path):
    """Proves the re-validation is independent of validate_output_path -
    atomic_write() is called directly here, simulating a symlink that
    appeared at the final path after an earlier validation passed."""
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.atomic_write(str(link), b"{}", overwrite=True)


def test_atomic_write_refuses_overwrite_without_flag_even_if_called_directly(tmp_path):
    existing = tmp_path / "out.json"
    existing.write_text("{}")
    with pytest.raises(pathsafety.OutputPathError):
        pathsafety.atomic_write(str(existing), b"{}", overwrite=False)
