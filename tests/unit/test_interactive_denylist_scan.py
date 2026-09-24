"""Interactive local-only scan runner - tested exclusively with
synthetic identifiers injected via collect_denylist_interactively's
prompt_fn parameter. This test file never touches a real terminal,
/dev/tty, or getpass - the real hidden-input path is exercised only
when a human runs the script directly, which these tests deliberately
cannot and do not simulate."""
import subprocess

import interactive_denylist_scan as ids


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo


def _commit_all(repo, message="commit"):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)


# --------------------------------------------------------------------------
# collect_denylist_interactively - synthetic prompt_fn only
# --------------------------------------------------------------------------

def test_collects_exactly_three_values_via_injected_prompt():
    calls = []

    def fake_prompt(i):
        calls.append(i)
        return f"synthetic-value-{i}"

    values = ids.collect_denylist_interactively(prompt_fn=fake_prompt)
    assert values == ["synthetic-value-1", "synthetic-value-2", "synthetic-value-3"]
    assert calls == [1, 2, 3]


def test_blank_entries_are_dropped_not_kept_as_empty_strings():
    def fake_prompt(i):
        return "" if i == 2 else f"synthetic-value-{i}"

    values = ids.collect_denylist_interactively(prompt_fn=fake_prompt)
    assert values == ["synthetic-value-1", "synthetic-value-3"]
    assert len(values) != ids.REQUIRED_VALUE_COUNT  # caller (main) must refuse to scan on this


def test_whitespace_only_entry_is_treated_as_blank():
    def fake_prompt(i):
        return "   " if i == 1 else f"synthetic-value-{i}"

    values = ids.collect_denylist_interactively(prompt_fn=fake_prompt)
    assert len(values) == 2


def test_values_are_stripped_of_surrounding_whitespace():
    def fake_prompt(i):
        return f"  synthetic-value-{i}  "

    values = ids.collect_denylist_interactively(prompt_fn=fake_prompt)
    assert values == ["synthetic-value-1", "synthetic-value-2", "synthetic-value-3"]


def test_default_prompt_fn_is_getpass_not_input():
    """Confirms the real (non-test) path uses getpass.getpass - hidden,
    /dev/tty-based input - not the plain `input()` builtin, which would
    echo to the screen and could be captured by terminal scrollback/
    screen-recording tools. Verified by signature inspection, not by
    actually invoking it (which would block waiting for real input)."""
    import inspect
    source = inspect.getsource(ids.collect_denylist_interactively)
    assert "getpass.getpass" in source
    assert "input(" not in source.replace("getpass.getpass(", "")


# --------------------------------------------------------------------------
# main() - full flow with synthetic values, no real terminal involved
# --------------------------------------------------------------------------

def test_main_aborts_on_fewer_than_three_values(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("clean\n")
    _commit_all(repo)

    monkeypatch.setattr(ids, "collect_denylist_interactively", lambda: ["only-one-value"])
    rc = ids.main(["--repo-root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "aborting" in captured.err
    assert "only-one-value" not in captured.out
    assert "only-one-value" not in captured.err


def test_main_clean_scan_with_synthetic_values(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("nothing interesting here\n")
    _commit_all(repo)

    monkeypatch.setattr(ids, "collect_denylist_interactively",
                         lambda: ["synthetic-a", "synthetic-b", "synthetic-c"])
    rc = ids.main(["--repo-root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "current_tracked" in captured.out
    assert "git_history" in captured.out
    for v in ("synthetic-a", "synthetic-b", "synthetic-c"):
        assert v not in captured.out
        assert v not in captured.err


def test_main_reports_finding_and_never_prints_the_matched_synthetic_value(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("token = 'synthetic-secret-xyz'\n")
    _commit_all(repo)

    monkeypatch.setattr(ids, "collect_denylist_interactively",
                         lambda: ["synthetic-secret-xyz", "synthetic-b", "synthetic-c"])
    rc = ids.main(["--repo-root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "STOP" in captured.err
    assert "synthetic-secret-xyz" not in captured.out
    assert "synthetic-secret-xyz" not in captured.err
    # The summary table is scope/status/counts ONLY, matching the exact
    # format requested - it never lists individual finding paths (those
    # live in the full report dict for separate, deliberate inspection,
    # not printed by default).
    assert "config.py" not in captured.out
    assert "current_tracked" in captured.out
    assert "findings" in captured.out


def test_main_retained_evidence_not_in_scope_by_default(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("clean\n")
    _commit_all(repo)

    monkeypatch.setattr(ids, "collect_denylist_interactively",
                         lambda: ["synthetic-a", "synthetic-b", "synthetic-c"])
    rc = ids.main(["--repo-root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "not_in_scope" in captured.out


def test_main_retained_evidence_scoped_via_flag(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("clean\n")
    _commit_all(repo)
    artifacts = tmp_path / "retained"
    artifacts.mkdir()
    (artifacts / "evidence.txt").write_text("synthetic-evidence-secret\n")

    monkeypatch.setattr(ids, "collect_denylist_interactively",
                         lambda: ["synthetic-evidence-secret", "synthetic-b", "synthetic-c"])
    rc = ids.main(["--repo-root", str(repo), "--retained-evidence-dir", str(artifacts)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "synthetic-evidence-secret" not in captured.out
    assert "retained_evidence" in captured.out


def test_main_incomplete_scan_is_never_reported_as_success(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("x" * 10000)
    _commit_all(repo)

    monkeypatch.setattr(ids, "collect_denylist_interactively",
                         lambda: ["synthetic-a", "synthetic-b", "synthetic-c"])
    # Force an immediate worker timeout so at least one scope comes back incomplete.
    rc = ids.main(["--repo-root", str(repo), "--timeout-s", "0"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "STOP" in captured.err
    assert "incomplete" in captured.out
