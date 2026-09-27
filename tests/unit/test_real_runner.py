"""Real-filesystem tests for repair.RealRunner - confined to pytest's
tmp_path (auto-cleaned, never touches real system paths). Exists
because a real QEMU smoke test (docs/design/decision-records/59-qemu-
smoke-test-vm-scripts-and-quadlet.md) found FakeRunner.write_text_atomic
silently auto-creates missing parent directories while RealRunner's
real implementation did not - every existing test using FakeRunner
passed while the equivalent real call raised FileNotFoundError. This
file exists so that specific class of fake/real divergence has a real,
non-fake test guarding it going forward, not just a fix nobody proves."""
from pathlib import Path

import repair


def test_write_text_atomic_creates_missing_parent_directories(tmp_path):
    target = tmp_path / "nested" / "deeper" / "still" / "file.txt"
    assert not target.parent.exists()

    repair.RealRunner().write_text_atomic(str(target), "hello")

    assert target.read_text() == "hello"


def test_write_text_atomic_overwrites_existing_file_preserving_mode(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("old")
    target.chmod(0o600)

    repair.RealRunner().write_text_atomic(str(target), "new")

    assert target.read_text() == "new"
    assert (target.stat().st_mode & 0o777) == 0o600


def test_append_text_creates_missing_parent_directories(tmp_path):
    target = tmp_path / "nested" / "log.jsonl"
    repair.RealRunner().append_text(str(target), "line1\n")
    repair.RealRunner().append_text(str(target), "line2\n")
    assert target.read_text() == "line1\nline2\n"


def test_makedirs_is_idempotent(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    runner = repair.RealRunner()
    runner.makedirs(str(target))
    runner.makedirs(str(target))  # must not raise on second call
    assert target.is_dir()
