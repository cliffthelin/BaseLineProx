import os

import write_once as wo
import twin_sync as ts


def test_unchanged_content_is_not_rewritten(tmp_path):
    p = tmp_path / "a" / "f"
    assert wo.write_if_changed(p, "x") is True
    before = os.stat(p).st_mtime_ns
    assert wo.write_if_changed(p, "x") is False and os.stat(p).st_mtime_ns == before
    assert wo.write_if_changed(p, "y") is True and p.read_text() == "y"


def test_same_build_keeps_its_record_and_install_time(tmp_path):
    (tmp_path / "opt/baseline/lib").mkdir(parents=True)
    (tmp_path / "opt/baseline/bin").mkdir(parents=True)
    (tmp_path / "opt/baseline/lib/a.py").write_text("1")
    (tmp_path / ts.INSTALLED_FILE.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
    first = ts.write_installed(tmp_path, now=100)
    again = ts.write_installed(tmp_path, now=999)
    assert again == first and again["installed_at"] == 100
    (tmp_path / "opt/baseline/lib/a.py").write_text("2")
    assert ts.write_installed(tmp_path, now=500)["installed_at"] == 500


def test_provision_copy_skips_identical_files(tmp_path):
    import re
    import subprocess
    text = open(os.path.join(os.path.dirname(__file__), "..", "..", "boot", "provision.sh")).read()
    fn = re.search(r"^cp\(\) \{.*?^\}", text, re.S | re.M).group(0)
    src, same, other = tmp_path / "s", tmp_path / "same", tmp_path / "other"
    src.write_text("v")
    same.write_text("v")
    other.write_text("old")
    os.utime(same, ns=(1, 1))
    subprocess.run(["bash", "-c", f'{fn}\ncp "{src}" "{same}"\ncp "{src}" "{other}"'], check=True)
    assert os.stat(same).st_mtime_ns == 1 and other.read_text() == "v"


def _provision_function(name):
    import re
    text = open(os.path.join(os.path.dirname(__file__), "..", "..", "boot", "provision.sh")).read()
    return re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.S | re.M).group(0)


def test_provision_put_writes_a_file_only_when_its_content_changes(tmp_path):
    import subprocess
    target = tmp_path / "conf"
    script = f'{_provision_function("put")}\nput "{target}" <<\'X\'\nline one\nX\n'
    subprocess.run(["bash", "-c", script], check=True)
    assert target.read_text() == "line one\n"
    os.utime(target, ns=(1, 1))
    subprocess.run(["bash", "-c", script], check=True)
    assert os.stat(target).st_mtime_ns == 1                                          # same content: not rewritten
    subprocess.run(["bash", "-c", script.replace("line one", "line two")], check=True)
    assert target.read_text() == "line two\n"


def test_provision_sync_tree_copies_only_files_that_differ(tmp_path):
    import subprocess
    src, dst = tmp_path / "s", tmp_path / "d"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "same.py").write_text("same")
    (src / "pkg" / "edit.py").write_text("new")
    (src / "pkg" / "__pycache__").mkdir()
    (src / "pkg" / "__pycache__" / "x.pyc").write_text("junk")
    (dst / "pkg").mkdir(parents=True)
    (dst / "pkg" / "same.py").write_text("same")
    (dst / "pkg" / "edit.py").write_text("old")
    os.utime(dst / "pkg" / "same.py", ns=(1, 1))
    subprocess.run(["bash", "-c", f'{_provision_function("sync_tree")}\nsync_tree "{src}" "{dst}"'], check=True)
    assert os.stat(dst / "pkg" / "same.py").st_mtime_ns == 1 and (dst / "pkg" / "edit.py").read_text() == "new" and not (dst / "pkg" / "__pycache__").exists()


def test_provision_has_no_unconditional_config_writes_left():
    text = open(os.path.join(os.path.dirname(__file__), "..", "..", "boot", "provision.sh")).read()
    import re
    unconditional = [line for line in text.splitlines() if re.match(r"\s*cat > ['\"/]", line) and "pve-no-subscription" not in line]
    assert unconditional == []                                                       # every config file goes through put()


def test_no_code_path_copies_a_whole_tree_onto_an_existing_one():
    """A whole-tree copy into an existing folder rewrites identical files and is prohibited (operator, 2026-10-19). These paths write onto drives or restore onto existing data."""
    root = os.path.join(os.path.dirname(__file__), "..", "..", "baseline")
    for rel in ("lib/installed_drive_update.py", "lib/handoff.py", "bin/baseline-independent-drive-install", "lib/rebuild_drive.py", "lib/mirror.py", "lib/data_history.py"):
        assert "copytree" not in open(os.path.join(root, rel)).read(), rel


def test_copy_changed_keeps_links_and_never_touches_matching_files(tmp_path):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir()
    (src / "f").write_text("x")
    (src / "ln").symlink_to("f")
    first = wo.copy_changed(src, dst, symlinks=True)
    assert first == {"copied": 2, "unchanged": 0} and os.readlink(dst / "ln") == "f"
    os.utime(dst / "f", ns=(1, 1))
    assert wo.copy_changed(src, dst, symlinks=True) == {"copied": 0, "unchanged": 2} and os.stat(dst / "f").st_mtime_ns == 1
