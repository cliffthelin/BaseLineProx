import shutil

from inventory.runner import RealRunner


def test_which_missing_binary_returns_none():
    assert RealRunner().which("definitely-not-a-real-binary-xyz") is None


def test_run_missing_binary_is_unavailable_not_an_exception():
    result = RealRunner().run(["definitely-not-a-real-binary-xyz"])
    assert result.ok is False
    assert result.unavailable is True


def test_run_timeout_is_recorded_not_raised():
    result = RealRunner().run(["sleep", "5"], timeout=0.2)
    assert result.ok is False
    assert result.timed_out is True


def test_run_output_is_capped_and_flagged_truncated():
    result = RealRunner().run(["python3", "-c", "print('x' * 1000)"], max_output_bytes=10)
    assert result.output_truncated is True
    assert len(result.stdout.encode()) <= 10


def test_read_text_missing_file_is_unavailable():
    result = RealRunner().read_text("/definitely/not/a/real/path.txt")
    assert result.ok is False
    assert result.unavailable is True


def test_walk_bounded_respects_max_entries(tmp_path):
    for i in range(20):
        (tmp_path / f"file{i}").write_text("x")
    result = RealRunner().walk_bounded(str(tmp_path), max_depth=2, max_entries=5)
    assert result.output_truncated is True
    assert len(result.stdout.splitlines()) == 5


def test_walk_bounded_respects_max_depth(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "too-deep.txt").write_text("x")
    (tmp_path / "a" / "shallow.txt").write_text("x")
    result = RealRunner().walk_bounded(str(tmp_path), max_depth=1, max_entries=100)
    assert "too-deep.txt" not in result.stdout


def test_which_uses_shutil_which_not_a_shell(monkeypatch):
    calls = []
    original = shutil.which

    def spy(name):
        calls.append(name)
        return original(name)

    monkeypatch.setattr(shutil, "which", spy)
    RealRunner().which("python3")
    assert "python3" in calls
