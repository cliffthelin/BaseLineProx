import json

import operator_identity as oi


def test_the_person_is_whoever_asked_for_root_never_root_itself():
    assert oi.invoking_user({"SUDO_USER": "Cane"}) == "cane"
    assert oi.invoking_user({"BASELINE_OPERATOR": "cane", "SUDO_USER": "other"}) == "cane"
    assert oi.invoking_user({"SUDO_USER": "root"}) is None and oi.invoking_user({}) is None
    assert oi.invoking_user({"SUDO_USER": "bad name"}) is None


def test_the_name_is_recorded_once_and_an_existing_one_is_kept(tmp_path):
    assert oi.record(tmp_path, "cane")["result"] == "added"
    assert oi.read(tmp_path / oi.FILE) == "cane"
    before = (tmp_path / oi.FILE).stat().st_mtime_ns
    assert oi.record(tmp_path, "someone")["result"] == "kept the drive's own"
    assert oi.read(tmp_path / oi.FILE) == "cane" and (tmp_path / oi.FILE).stat().st_mtime_ns == before


def test_nobody_to_record_is_said_not_invented(tmp_path):
    assert "not written" in oi.record(tmp_path, None)["result"] and not (tmp_path / oi.FILE).exists()


def test_a_damaged_or_root_record_reads_as_none(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / oi.FILE).write_text("nope")
    assert oi.read(tmp_path / oi.FILE) is None
    (tmp_path / oi.FILE).write_text(json.dumps({"username": "root"}))
    assert oi.read(tmp_path / oi.FILE) is None
