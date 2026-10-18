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
