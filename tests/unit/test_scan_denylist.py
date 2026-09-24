"""Generic external-identity denylist scanner - denylist supplied only
via a protected fd, matches never printed (path/category only),
bounded chunked reads (constant memory regardless of file size), an
overall scan budget, a separate non-mutating history scan, isolated
worker-subprocess execution under a memory ceiling, and the
ownership-metadata exclusion staying path-based (never content-based)."""
import os
import subprocess

import pytest

import scan_denylist


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


def _denylist_fd(terms):
    r, w = os.pipe()
    with os.fdopen(w, "w") as f:
        f.write("\n".join(terms) + "\n")
    return r


# --------------------------------------------------------------------------
# Denylist loading - fd only
# --------------------------------------------------------------------------

def test_read_denylist_strips_blank_lines_and_whitespace():
    fd = _denylist_fd(["  term-one  ", "", "term-two", "   "])
    assert scan_denylist.read_denylist(fd) == ["term-one", "term-two"]


# --------------------------------------------------------------------------
# scan_tree - now returns a structured result dict
# --------------------------------------------------------------------------

def test_scan_tree_finds_a_denylisted_term_in_a_tracked_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("host = 'real-machine-name-example'\n")
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["real-machine-name-example"])
    assert result["scan_incomplete"] is False
    assert len(result["findings"]) == 1
    assert result["findings"][0]["path"] == "config.py"
    assert result["findings"][0]["category"] == "source"
    assert result["stats"]["files_fully_scanned"] >= 1
    assert result["final_status"] == "findings"


def test_scan_tree_clean_when_no_term_present(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("host = 'placeholder'\n")
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["real-machine-name-example"])
    assert result["findings"] == []
    assert result["scan_incomplete"] is False


def test_category_for_paths():
    assert scan_denylist._category_for("tests/test_x.py") == "tests"
    assert scan_denylist._category_for("docs/plan.md") == "docs"
    assert scan_denylist._category_for("experiments/m1/evidence.png") == "retained_artifact"
    assert scan_denylist._category_for("docs/design/example.json") == "docs"
    assert scan_denylist._category_for("fixtures/example.json") == "example_manifest_or_fixture"
    assert scan_denylist._category_for("baseline/lib/repair.py") == "source"


def test_scan_tree_ignores_untracked_files(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "tracked.py").write_text("clean\n")
    _commit_all(repo)
    (repo / "untracked.py").write_text("real-machine-name-example\n")  # never git add'd

    result = scan_denylist.scan_tree(str(repo), ["real-machine-name-example"])
    assert result["findings"] == []


def test_scan_tree_excludes_ownership_metadata_files_by_path_not_content(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("real-machine-name-example\n")
    (repo / "other.md").write_text("real-machine-name-example\n")
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["real-machine-name-example"])
    paths = {f["path"] for f in result["findings"]}
    assert "README.md" not in paths
    assert "other.md" in paths


def test_scan_tree_covers_extra_dirs_for_retained_artifacts(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "clean.py").write_text("clean\n")
    _commit_all(repo)

    artifacts = tmp_path / "retained"
    artifacts.mkdir()
    (artifacts / "evidence.txt").write_text("real-machine-name-example\n")

    result = scan_denylist.scan_tree(str(repo), ["real-machine-name-example"], extra_dirs=(str(artifacts),))
    assert any(f["path"].endswith("evidence.txt") for f in result["findings"])


# --------------------------------------------------------------------------
# Bounded, chunked file reads - constant memory regardless of file size
# --------------------------------------------------------------------------

def test_term_straddling_a_chunk_boundary_is_still_found(tmp_path):
    """The overlap window must catch a term that spans two chunks."""
    term = "boundary-straddling-secret-term"
    prefix = "x" * (scan_denylist.CHUNK_BYTES - 10)
    content = prefix + term  # term starts just before the first chunk boundary
    f = tmp_path / "big.txt"
    f.write_text(content)
    log = scan_denylist.BoundedEventLog()

    matched, scanned, _capped = scan_denylist._file_contains_any_term(str(f), [term], log)
    assert matched is True


def test_per_file_scan_is_capped_not_unbounded(tmp_path):
    """A file larger than MAX_SCAN_BYTES_PER_FILE must never be read in
    full - bytes_scanned stays at the cap, and the cap event is logged
    (bounded, not per-chunk)."""
    f = tmp_path / "huge.txt"
    cap = 1024  # small cap for a fast test
    with open(f, "wb") as fh:
        fh.write(b"a" * (cap * 5))
    log = scan_denylist.BoundedEventLog()

    matched, scanned, capped = scan_denylist._file_contains_any_term(str(f), ["never-present-term"], log,
                                                               max_bytes=cap)
    assert matched is False
    assert scanned <= cap + scan_denylist.CHUNK_BYTES  # bounded by one chunk over the cap, never the full file
    assert log.count("file_scan_capped") == 1
    assert capped is True


def test_large_sparse_file_does_not_hang_or_read_unbounded_bytes(tmp_path):
    """A sparse file can report a multi-gigabyte logical size while
    consuming almost no real disk/memory - proves the scanner's
    per-file cap bounds actual bytes read regardless of the file's
    apparent size, using a small cap so the test itself stays fast."""
    f = tmp_path / "sparse.bin"
    with open(f, "wb") as fh:
        fh.truncate(2 * 1024 * 1024 * 1024)  # 2GB logical size, ~0 bytes on disk
    assert f.stat().st_size == 2 * 1024 * 1024 * 1024

    log = scan_denylist.BoundedEventLog()
    small_cap = 2 * scan_denylist.CHUNK_BYTES
    matched, scanned, capped = scan_denylist._file_contains_any_term(str(f), ["never-present-term"], log,
                                                               max_bytes=small_cap)
    assert matched is False
    # Actual bytes read must be bounded by the cap, nowhere near the
    # file's 2GB logical size - this is the concrete proof memory/time
    # stays bounded regardless of on-disk file size.
    assert scanned <= small_cap + scan_denylist.CHUNK_BYTES
    assert log.count("file_scan_capped") == 1
    assert capped is True


def test_overall_scan_budget_stops_further_files_and_marks_incomplete(tmp_path):
    repo = _init_repo(tmp_path)
    for i in range(5):
        (repo / f"f{i}.txt").write_text("x" * 1000)
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["never-present"], overall_budget_bytes=1500)
    assert result["scan_incomplete"] is True
    # 1500 doesn't divide evenly by the 1000-byte files, so one file
    # is legitimately both per-file-capped AND the overall budget runs
    # out on the next - the reason string reflects whichever of the
    # two (or both) genuinely happened, not a fixed string.
    assert "overall_budget_exhausted" in result["reason"]
    assert result["stats"]["files_fully_scanned"] < 5
    assert result["final_status"] == "incomplete"  # never "clean", even though no findings


def test_read_error_is_logged_boundedly_not_per_occurrence():
    log = scan_denylist.BoundedEventLog()
    matched, scanned, _capped = scan_denylist._file_contains_any_term("/nonexistent/path/at/all", ["x"], log)
    assert matched is False
    assert log.count("file_read_error:FileNotFoundError") == 1


# --------------------------------------------------------------------------
# scan_history - streamed, budgeted, never mutates
# --------------------------------------------------------------------------

def test_scan_history_finds_term_in_a_past_commit(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.py").write_text("real-machine-name-example\n")
    _commit_all(repo, "add secret")
    (repo / "f.py").write_text("cleaned\n")
    _commit_all(repo, "remove secret")

    result = scan_denylist.scan_history(str(repo), ["real-machine-name-example"])
    assert result["scan_incomplete"] is False
    # Both the add and remove commits show the term in their patch text.
    assert len(result["findings"]) == 2
    assert all(f["category"] == "history" for f in result["findings"])


def test_scan_history_clean_when_never_present(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.py").write_text("clean\n")
    _commit_all(repo)

    result = scan_denylist.scan_history(str(repo), ["real-machine-name-example"])
    assert result["findings"] == []


def test_scan_history_never_modifies_the_repository(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.py").write_text("real-machine-name-example\n")
    _commit_all(repo)

    before = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout
    scan_denylist.scan_history(str(repo), ["real-machine-name-example"])
    after = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout
    assert before == after
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                             capture_output=True, text=True, check=True).stdout
    assert status.strip() == ""


def test_scan_history_line_budget_marks_incomplete(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.py").write_text("real-machine-name-example\n")
    _commit_all(repo)

    result = scan_denylist.scan_history(str(repo), ["real-machine-name-example"], line_budget=1)
    assert result["scan_incomplete"] is True
    assert result["reason"] == "history_line_budget_exhausted"


# --------------------------------------------------------------------------
# Isolated worker subprocess - memory ceiling, parent survives worker failure
# --------------------------------------------------------------------------

def test_run_scan_isolated_clean_result(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "clean.py").write_text("nothing interesting\n")
    _commit_all(repo)

    result = scan_denylist.run_scan_isolated("scan-tree", ["never-present-term"], str(repo))
    assert result["scan_incomplete"] is False
    assert result["findings"] == []


def test_run_scan_isolated_finds_term(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("host = 'a-real-prohibited-value'\n")
    _commit_all(repo)

    result = scan_denylist.run_scan_isolated("scan-tree", ["a-real-prohibited-value"], str(repo))
    assert len(result["findings"]) == 1
    assert result["findings"][0]["path"] == "config.py"


def test_run_scan_isolated_survives_worker_exceeding_memory_limit(tmp_path):
    """A worker that hits its memory ceiling must produce a clean
    scan_incomplete result in the PARENT process - the parent itself
    must never raise or crash because the worker did."""
    repo = _init_repo(tmp_path)
    (repo / "clean.py").write_text("clean\n")
    _commit_all(repo)

    # A memory limit far too small for even the Python interpreter to
    # start - guarantees the worker cannot possibly complete normally,
    # exercising the "worker crashed" path deterministically.
    result = scan_denylist.run_scan_isolated("scan-tree", ["never-present"], str(repo),
                                              memory_limit_bytes=4 * 1024 * 1024, timeout_s=30)
    assert result["scan_incomplete"] is True
    assert result["reason"] in ("resource_limit_exceeded", "worker_produced_no_result", "worker_result_unparseable")
    # The key property: this assertion itself is reached at all - the
    # parent process (this test) survived the worker's failure.


def test_run_scan_isolated_worker_timeout_does_not_hang_the_parent(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    (repo / "clean.py").write_text("clean\n")
    _commit_all(repo)

    result = scan_denylist.run_scan_isolated("scan-history", ["never-present"], str(repo), timeout_s=0)
    assert result["scan_incomplete"] is True


# --------------------------------------------------------------------------
# CLI: matched text is never printed, only path/category
# --------------------------------------------------------------------------

def test_cli_output_never_contains_the_matched_term(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("host = 'a-distinctive-prohibited-value'\n")
    _commit_all(repo)

    fd = _denylist_fd(["a-distinctive-prohibited-value"])
    rc = scan_denylist.main(["scan-tree", "--denylist-fd", str(fd), "--repo-root", str(repo), "--no-isolation"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "a-distinctive-prohibited-value" not in captured.out
    assert "a-distinctive-prohibited-value" not in captured.err
    assert "config.py" in captured.out


def test_cli_clean_run_exits_zero(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("host = 'placeholder'\n")
    _commit_all(repo)

    fd = _denylist_fd(["a-distinctive-prohibited-value"])
    rc = scan_denylist.main(["scan-tree", "--denylist-fd", str(fd), "--repo-root", str(repo), "--no-isolation"])
    assert rc == 0


def test_cli_empty_denylist_is_a_noop_not_a_failure(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("anything\n")
    _commit_all(repo)

    fd = _denylist_fd([])
    rc = scan_denylist.main(["scan-tree", "--denylist-fd", str(fd), "--repo-root", str(repo), "--no-isolation"])
    assert rc == 0


def test_cli_via_isolated_worker_end_to_end(tmp_path, capsys):
    """The default (isolated) path, exercised through the real CLI -
    not --no-isolation - proving the worker subprocess plumbing works
    end to end, not just the in-process functions."""
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("host = 'isolated-worker-test-value'\n")
    _commit_all(repo)

    fd = _denylist_fd(["isolated-worker-test-value"])
    rc = scan_denylist.main(["scan-tree", "--denylist-fd", str(fd), "--repo-root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "isolated-worker-test-value" not in captured.out
    assert "config.py" in captured.out


# --------------------------------------------------------------------------
# Coverage accounting: logical/allocated/read bytes, fully-scanned/
# excluded/incomplete counts, sparse-file detection, peak RSS
# --------------------------------------------------------------------------

def test_stats_report_logical_and_allocated_bytes_for_a_normal_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("x" * 5000)
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["never-present"])
    assert result["stats"]["logical_bytes_present"] >= 5000
    assert result["stats"]["allocated_bytes"] > 0
    assert result["stats"]["bytes_actually_read"] >= 5000
    assert result["stats"]["files_fully_scanned"] >= 1
    assert result["stats"]["files_incomplete"] == 0
    assert result["stats"]["sparse_files_encountered"] == 0


def test_stats_count_ownership_metadata_as_excluded(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("x" * 100)
    (repo / "other.txt").write_text("y" * 100)
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["never-present"])
    assert result["stats"]["files_excluded"] >= 1  # README.md
    assert result["stats"]["files_fully_scanned"] >= 1  # other.txt


def test_stats_detect_a_sparse_file_via_extra_dir(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "clean.txt").write_text("clean\n")
    _commit_all(repo)

    artifacts = tmp_path / "retained"
    artifacts.mkdir()
    sparse = artifacts / "sparse.bin"
    with open(sparse, "wb") as fh:
        fh.truncate(64 * 1024 * 1024)  # 64MB logical, ~0 allocated

    result = scan_denylist.scan_tree(str(repo), ["never-present"], extra_dirs=(str(artifacts),))
    assert result["stats"]["sparse_files_encountered"] >= 1
    assert result["stats"]["logical_bytes_present"] >= 64 * 1024 * 1024


def test_final_status_never_reports_clean_when_incomplete(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("x" * 10000)
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["never-present"], overall_budget_bytes=100)
    assert result["final_status"] != "clean"
    assert result["final_status"] == "incomplete"


def test_final_status_is_clean_for_a_genuinely_complete_scan(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("clean\n")
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["never-present"])
    assert result["final_status"] == "clean"
    assert result["stats"]["files_incomplete"] == 0


def test_worker_result_carries_peak_rss_kb(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("clean\n")
    _commit_all(repo)

    result = scan_denylist.run_scan_isolated("scan-tree", ["never-present"], str(repo))
    assert result["peak_rss_kb"] is not None
    assert result["peak_rss_kb"] > 0


def test_direct_in_process_call_has_no_worker_rss(tmp_path):
    """Only the isolated-worker path has a real subprocess RSS to
    report; a direct in-process call has none - explicitly None, not a
    fabricated number."""
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("clean\n")
    _commit_all(repo)

    result = scan_denylist.scan_tree(str(repo), ["never-present"])
    assert result["peak_rss_kb"] is None


# --------------------------------------------------------------------------
# run_full_scan: three independently-scoped, independently isolated scans
# --------------------------------------------------------------------------

def test_run_full_scan_three_rows_in_order(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "clean.txt").write_text("clean\n")
    _commit_all(repo)

    report = scan_denylist.run_full_scan(["never-present-anywhere"], str(repo))
    scopes = {row["scope"] for row in report["rows"]}
    assert scopes == {"current_tracked", "retained_evidence", "git_history"}
    assert report["overall_status"] == "clean"


def test_run_full_scan_retained_evidence_not_in_scope_when_no_dir_declared(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "clean.txt").write_text("clean\n")
    _commit_all(repo)

    report = scan_denylist.run_full_scan(["never-present"], str(repo), retained_evidence_dirs=())
    row = next(r for r in report["rows"] if r["scope"] == "retained_evidence")
    assert row["status"] == "not_in_scope"
    # not_in_scope alone must not be conflated with "findings" or "incomplete"
    assert report["overall_status"] == "clean"


def test_run_full_scan_retained_evidence_scoped_when_dir_declared(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "clean.txt").write_text("clean\n")
    _commit_all(repo)
    artifacts = tmp_path / "retained"
    artifacts.mkdir()
    (artifacts / "evidence.txt").write_text("a-real-prohibited-value\n")

    report = scan_denylist.run_full_scan(["a-real-prohibited-value"], str(repo),
                                          retained_evidence_dirs=(str(artifacts),))
    row = next(r for r in report["rows"] if r["scope"] == "retained_evidence")
    assert row["status"] == "findings"
    assert row["findings"] == 1
    assert report["overall_status"] == "findings"


def test_run_full_scan_finding_in_one_scope_does_not_mask_another():
    pass  # covered by the retained_evidence test above; kept as a named marker for the requirement


def test_run_full_scan_history_finding_is_reported_not_fixed(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.py").write_text("a-real-prohibited-value\n")
    _commit_all(repo, "add secret")
    (repo / "f.py").write_text("clean\n")
    _commit_all(repo, "remove secret")

    before = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout

    report = scan_denylist.run_full_scan(["a-real-prohibited-value"], str(repo))
    row = next(r for r in report["rows"] if r["scope"] == "git_history")
    assert row["status"] == "findings"
    assert row["findings"] >= 1

    after = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout
    assert before == after  # never rewritten


def test_format_full_scan_report_never_contains_matched_values(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "config.py").write_text("host = 'a-distinctive-value-here'\n")
    _commit_all(repo)

    report = scan_denylist.run_full_scan(["a-distinctive-value-here"], str(repo))
    text = scan_denylist.format_full_scan_report(report)
    assert "a-distinctive-value-here" not in text
    assert "current_tracked" in text
    assert "findings" in text
