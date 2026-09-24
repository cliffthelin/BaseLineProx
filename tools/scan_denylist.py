#!/usr/bin/env python3
"""Generic external-identity denylist scanner - a dev/CI tool, never
deployed to a host, never imported by anything under baseline/lib.

Prohibited real-world identifiers (names, hostnames, serials -
whatever must never appear in this repository or its retained
artifacts) are supplied ONLY through a protected file descriptor, one
term per line, never via argv, an environment variable, or a committed
file - the exact same discipline this project already applies to the
inventory comparison key (see baseline/lib/inventory/keysource.py).
This script contains no real identifier itself, and a match is never
printed: on a hit, it reports only the affected path (or commit) and a
generic category, never the matched text or any surrounding context -
the entire point is to prove nothing prohibited slipped in without
printing the very thing that must not be printed.

Resource safety (added after this project's own dogfooding OOM-killed
a naive first version against a 7GB leftover disposable artifact
directory): every read is chunked and budgeted, per-file and
overall, and the real scan runs inside an isolated worker subprocess
under a memory ceiling (see run_scan_isolated) so a worker that
somehow still exceeds its budget can only take itself down - reported
back as a clean `scan_incomplete: resource_limit_exceeded` result -
never the calling process. Every operational log event (a read error,
an oversized-file skip, a budget-exhausted skip) goes through
bounded_log.BoundedEventLog: bounded total records regardless of how
many times the same condition recurs, never one log line per
occurrence - see that module's docstring for the general principle.

Two independent, separately-invoked scans:

  scan-tree    - every git-tracked file in the working tree (source,
                 tests, fixtures, example manifests, docs) plus any
                 additional "retained artifact" directories passed via
                 --extra-dir (e.g. evidence kept under experiments/).

  scan-history - git log across all refs, diffs included, streamed
                 (never the whole log held in memory at once). A
                 history hit is reported (commit id + generic category
                 only) for a separate human remediation decision - this
                 script NEVER rewrites history, never runs `git
                 filter-branch`/`git filter-repo`, and never deletes or
                 amends anything.

Both modes exit non-zero on any finding OR on scan_incomplete, so a
CI/pre-P0 gate can treat either as a hard stop.

Repository/remote ownership metadata - this project's own GitHub
account name as it appears in a remote URL, LICENSE, or README
attribution - is out of scope for the repository-content rule: it is
already public git-hosting metadata, not a secret this project is
trying to keep out of its own tracked content. Excluded by an explicit
path list (OWNERSHIP_METADATA_FILES), never by content - so that
exclusion can never be (ab)used to hide anything else.
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bounded_log import BoundedEventLog  # noqa: E402

OWNERSHIP_METADATA_FILES = {"README.md", "LICENSE"}

# Bounded, never unbounded - matching this codebase's established
# discipline elsewhere (inventory Runner.walk_bounded, max_output_bytes).
CHUNK_BYTES = 4 * 1024 * 1024
MAX_SCAN_BYTES_PER_FILE = 64 * 1024 * 1024
OVERALL_SCAN_BUDGET_BYTES = 2 * 1024 * 1024 * 1024  # across the whole scan-tree run
HISTORY_LINE_BUDGET = 2_000_000  # lines of `git log -p` output, streamed
_OVERLAP_BYTES = 256

DEFAULT_WORKER_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
DEFAULT_WORKER_TIMEOUT_S = 300
MAX_WORKER_RESULT_BYTES = 8 * 1024 * 1024


def read_denylist(fd: int) -> list[str]:
    with os.fdopen(fd, "r") as f:
        return [line.strip() for line in f if line.strip()]


def _tracked_files(repo_root: str) -> list[str]:
    proc = subprocess.run(["git", "-C", repo_root, "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in proc.stdout.splitlines() if line]


def _category_for(rel_path: str) -> str:
    if rel_path.startswith("tests/"):
        return "tests"
    if rel_path.startswith("docs/"):
        return "docs"
    if rel_path.startswith("experiments/"):
        return "retained_artifact"
    if rel_path.endswith((".json",)):
        return "example_manifest_or_fixture"
    return "source"


def _finalize_result(result):
    """Attaches the one authoritative final_status field every result
    (scan_tree, scan_history, run_scan_isolated, run_full_scan's
    per-scope results) carries, computed the same way everywhere:
    findings win over incomplete, incomplete always wins over clean -
    a scan that could not fully complete is NEVER reported as clean,
    regardless of whether it happened to find nothing before running
    out of budget."""
    if result.get("findings"):
        result["final_status"] = "findings"
    elif result.get("scan_incomplete"):
        result["final_status"] = "incomplete"
    else:
        result["final_status"] = "clean"
    result.setdefault("peak_rss_kb", None)
    return result


def _file_physical_stats(full_path):
    """(logical_bytes, allocated_bytes, is_sparse) from a single
    os.stat() - st_blocks is in 512-byte units per POSIX, independent
    of the filesystem's actual block size, so this is portable. Returns
    (None, None, False) if the file can't be stat'd (caller treats that
    as excluded, not silently zero)."""
    try:
        st = os.stat(full_path)
    except OSError:
        return None, None, False
    logical = st.st_size
    allocated = getattr(st, "st_blocks", None)
    allocated_bytes = allocated * 512 if allocated is not None else logical
    # A small fixed slack accounts for filesystem metadata/rounding on
    # tiny files - only a real, multi-block gap counts as "sparse".
    is_sparse = logical > 0 and allocated_bytes < logical - 4096
    return logical, allocated_bytes, is_sparse


def _file_contains_any_term(full_path, denylist, log, max_bytes=MAX_SCAN_BYTES_PER_FILE):
    """Chunked, bounded, constant-memory read - never `f.read()` on the
    whole file. Returns (matched: bool, bytes_scanned: int, capped:
    bool) - capped is True iff the budget was exhausted before EOF, the
    signal the caller uses to classify the file as "incomplete" rather
    than "fully scanned". Any read error or an oversized file is a
    bounded, deduplicated log event, never a per-file log line and
    never a raised exception."""
    longest_term = max((len(t) for t in denylist if t), default=0)
    overlap = max(_OVERLAP_BYTES, longest_term - 1)
    try:
        with open(full_path, "rb") as f:
            carry = b""
            scanned = 0
            while scanned < max_bytes:
                chunk = f.read(CHUNK_BYTES)
                if not chunk:
                    break
                scanned += len(chunk)
                window = carry + chunk
                text = window.decode("utf-8", errors="ignore")
                for term in denylist:
                    if term and term in text:
                        return True, scanned, False
                carry = window[-overlap:] if overlap else b""
            else:
                # Loop exhausted the budget without exhausting the file.
                log.record("file_scan_capped", detail={"cap_bytes": max_bytes})
                return False, scanned, True
    except (OSError, IsADirectoryError) as exc:
        log.record(f"file_read_error:{type(exc).__name__}")
        return False, 0, False
    return False, scanned, False


def scan_tree(repo_root, denylist, extra_dirs=(), overall_budget_bytes=OVERALL_SCAN_BUDGET_BYTES, clock=time.time):
    log = BoundedEventLog(clock=clock)
    findings = []
    candidates = [(p, os.path.join(repo_root, p)) for p in _tracked_files(repo_root)]
    for extra in extra_dirs:
        for root, _dirs, names in os.walk(extra):
            for name in names:
                full = os.path.join(root, name)
                candidates.append((os.path.relpath(full, repo_root), full))

    total_bytes = 0
    logical_bytes_total = 0
    allocated_bytes_total = 0
    files_fully_scanned = 0
    files_incomplete = 0
    files_excluded = 0
    sparse_files_encountered = 0
    scan_incomplete = False
    for rel_path, full_path in candidates:
        if rel_path in OWNERSHIP_METADATA_FILES:
            files_excluded += 1
            continue
        if total_bytes >= overall_budget_bytes:
            log.record("overall_budget_exhausted_skip", detail={"path_category": _category_for(rel_path)})
            scan_incomplete = True
            files_excluded += 1
            continue

        logical, allocated, is_sparse = _file_physical_stats(full_path)
        if logical is None:
            files_excluded += 1  # unstat-able (e.g. a race, a broken symlink) - not silently "fully scanned"
            continue
        logical_bytes_total += logical
        allocated_bytes_total += allocated
        if is_sparse:
            sparse_files_encountered += 1

        remaining = overall_budget_bytes - total_bytes
        matched, scanned, capped = _file_contains_any_term(full_path, denylist, log,
                                                             max_bytes=min(MAX_SCAN_BYTES_PER_FILE, remaining))
        total_bytes += scanned
        if capped:
            files_incomplete += 1
            scan_incomplete = True
        else:
            files_fully_scanned += 1
        if matched:
            findings.append({"path": rel_path, "category": _category_for(rel_path)})

    if files_incomplete and files_excluded and log.count("overall_budget_exhausted_skip"):
        reason = "per_file_cap_and_overall_budget_exhausted"
    elif log.count("overall_budget_exhausted_skip"):
        reason = "overall_budget_exhausted"
    elif files_incomplete:
        reason = "per_file_cap_exceeded"
    else:
        reason = None

    return _finalize_result({
        "findings": findings,
        "scan_incomplete": scan_incomplete,
        "reason": reason,
        "stats": {
            "candidates_total": len(candidates),
            "logical_bytes_present": logical_bytes_total,
            "allocated_bytes": allocated_bytes_total,
            "bytes_actually_read": total_bytes,
            "files_fully_scanned": files_fully_scanned,
            "files_excluded": files_excluded,
            "files_incomplete": files_incomplete,
            "sparse_files_encountered": sparse_files_encountered,
        },
        "log_summary": log.finalize(),
    })


def scan_history(repo_root, denylist, line_budget=HISTORY_LINE_BUDGET, clock=time.time):
    """Read-only: `git log -p` across every ref, STREAMED line by line
    (never the whole log held in memory at once) with a hard line
    budget. Never mutates anything - no filter-branch, no filter-repo,
    no amend, no rebase. A finding here is a stop-and-report signal for
    a separate remediation decision, not something this function acts
    on."""
    log = BoundedEventLog(clock=clock)
    findings = []
    seen_commits = set()
    current_commit = None
    lines_read = 0
    scan_incomplete = False

    proc = subprocess.Popen(["git", "-C", repo_root, "log", "--all", "-p", "--no-color"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="ignore")
    try:
        for line in proc.stdout:
            lines_read += 1
            if lines_read > line_budget:
                log.record("history_line_budget_exhausted")
                scan_incomplete = True
                break
            if line.startswith("commit "):
                parts = line.split()
                current_commit = parts[1] if len(parts) > 1 else None
                continue
            for term in denylist:
                if term and current_commit and term in line:
                    if current_commit not in seen_commits:
                        seen_commits.add(current_commit)
                        findings.append({"commit": current_commit, "category": "history"})
                    break
    finally:
        proc.stdout.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    return _finalize_result({
        "findings": findings,
        "scan_incomplete": scan_incomplete,
        "reason": "history_line_budget_exhausted" if scan_incomplete else None,
        "stats": {"lines_read": lines_read, "commits_with_findings": len(findings)},
        "log_summary": log.finalize(),
    })


# ---------------------------------------------------------------------------
# Isolated worker: the real scan runs in a subprocess under a memory
# ceiling, so an unexpected resource blowup can only take the worker
# down - reported back as scan_incomplete, never propagated to (let
# alone crashing) the calling process. Communication is bounded on
# both sides: the denylist travels via one already-open fd (never
# argv/env), and the result travels back as ONE bounded JSON blob
# (capped at MAX_WORKER_RESULT_BYTES) over a dedicated pipe - never an
# unbounded captured stdout/stderr stream.
# ---------------------------------------------------------------------------

def _limit_memory(limit_bytes):
    def _setter():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        except (ValueError, OSError, ImportError):
            pass  # best-effort - not supported on every platform
    return _setter


def run_scan_isolated(mode, denylist, repo_root, extra_dirs=(),
                       memory_limit_bytes=DEFAULT_WORKER_MEMORY_LIMIT_BYTES,
                       timeout_s=DEFAULT_WORKER_TIMEOUT_S):
    """Spawns `python3 scan_denylist.py --worker <mode> ...` under an
    address-space limit (where the platform supports RLIMIT_AS) and
    reads back one bounded JSON result. On a worker crash, OOM-kill, or
    timeout, returns a clean scan_incomplete result instead of raising
    - the caller (and whatever process called it) survives regardless
    of what happened inside the worker."""
    denylist_r, denylist_w = os.pipe()
    result_r, result_w = os.pipe()
    os.set_inheritable(denylist_r, True)
    os.set_inheritable(result_w, True)

    with os.fdopen(denylist_w, "w") as f:
        f.write("\n".join(denylist) + "\n")

    argv = [sys.executable, os.path.abspath(__file__), "--worker", mode,
            "--denylist-fd", str(denylist_r), "--repo-root", repo_root,
            "--result-fd", str(result_w)]
    for d in extra_dirs:
        argv += ["--extra-dir", d]

    proc = subprocess.Popen(argv, pass_fds=(denylist_r, result_w),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             preexec_fn=_limit_memory(memory_limit_bytes) if hasattr(os, "fork") else None)
    os.close(denylist_r)
    os.close(result_w)

    chunks = []
    total = 0
    with os.fdopen(result_r, "rb") as f:
        while total < MAX_WORKER_RESULT_BYTES:
            chunk = f.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)

    try:
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return _finalize_result({"findings": [], "scan_incomplete": True, "reason": "worker_timeout",
                                  "stats": {}, "log_summary": []})

    raw = b"".join(chunks)
    if not raw:
        return _finalize_result({
            "findings": [], "scan_incomplete": True,
            "reason": "resource_limit_exceeded" if returncode != 0 else "worker_produced_no_result",
            "returncode": returncode, "stats": {}, "log_summary": []})
    try:
        result = json.loads(raw.decode("utf-8", errors="ignore"))
        result.setdefault("final_status", None)
        return result if result["final_status"] else _finalize_result(result)
    except json.JSONDecodeError:
        return _finalize_result({"findings": [], "scan_incomplete": True, "reason": "worker_result_unparseable",
                                  "stats": {}, "log_summary": []})


def _peak_rss_kb():
    """Peak resident set size of THIS process so far, in KB (Linux:
    ru_maxrss is already KB; this module only ever runs the worker path
    on Linux in practice, so no cross-platform unit conversion is
    attempted - documented rather than silently wrong on another OS)."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError):
        return None


def _run_worker(args) -> int:
    """Runs inside the isolated worker subprocess: performs the real
    scan and writes exactly one JSON result blob to --result-fd, then
    exits. Never prints matched text - the result blob itself never
    carries matched values, only path/commit + category, per module
    docstring."""
    denylist = read_denylist(args.denylist_fd)
    if args.worker == "scan-tree":
        result = scan_tree(args.repo_root, denylist, tuple(args.extra_dir))
    else:
        result = scan_history(args.repo_root, denylist)
    result["peak_rss_kb"] = _peak_rss_kb()  # scan_tree/scan_history already set final_status
    payload = json.dumps(result).encode("utf-8")[:MAX_WORKER_RESULT_BYTES]
    with os.fdopen(args.result_fd, "wb") as f:
        f.write(payload)
    return 1 if (result["findings"] or result["scan_incomplete"]) else 0


# ---------------------------------------------------------------------------
# The real pre-P0 check: three independently-scoped, independently
# isolated scans in one report. A scope that could not be fully
# scanned is NEVER reported as clean - see _finalize_result.
# ---------------------------------------------------------------------------

SCOPE_NOT_IN_SCOPE = "not_in_scope"


def _not_in_scope_result(reason):
    return {"findings": [], "scan_incomplete": False, "reason": reason,
            "stats": {}, "log_summary": [], "final_status": SCOPE_NOT_IN_SCOPE, "peak_rss_kb": None}


def run_full_scan(denylist, repo_root, retained_evidence_dirs=(),
                   memory_limit_bytes=DEFAULT_WORKER_MEMORY_LIMIT_BYTES, timeout_s=DEFAULT_WORKER_TIMEOUT_S):
    """current_tracked (git-tracked files only), retained_evidence (only
    if at least one directory is explicitly declared in scope - never
    assumed), and git_history - each run in its own isolated worker
    under its own memory ceiling, so one scope's resource use can never
    affect another's, or the caller."""
    current_tracked = run_scan_isolated("scan-tree", denylist, repo_root, extra_dirs=(),
                                         memory_limit_bytes=memory_limit_bytes, timeout_s=timeout_s)

    if retained_evidence_dirs:
        retained_evidence = run_scan_isolated("scan-tree", denylist, repo_root, extra_dirs=retained_evidence_dirs,
                                               memory_limit_bytes=memory_limit_bytes, timeout_s=timeout_s)
    else:
        retained_evidence = _not_in_scope_result("no retained-evidence directory was declared in scope")

    git_history = run_scan_isolated("scan-history", denylist, repo_root,
                                     memory_limit_bytes=memory_limit_bytes, timeout_s=timeout_s)

    scopes = {"current_tracked": current_tracked, "retained_evidence": retained_evidence,
              "git_history": git_history}

    rows = []
    for name, result in scopes.items():
        incomplete_count = result["stats"].get("files_incomplete")
        if incomplete_count is None:
            incomplete_count = 1 if result.get("scan_incomplete") else 0
        rows.append({
            "scope": name,
            "status": result["final_status"],
            "findings": len(result["findings"]),
            "incomplete": incomplete_count,
        })

    statuses = {r["status"] for r in rows}
    if "findings" in statuses:
        overall_status = "findings"
    elif "incomplete" in statuses:
        overall_status = "incomplete"
    else:
        overall_status = "clean"  # not_in_scope alone (no findings/incomplete anywhere) is still an overall clean pass

    return {"rows": rows, "overall_status": overall_status, "scopes": scopes}


def format_full_scan_report(report):
    lines = [f"{'scope':<22}{'status':<14}{'findings':>10}{'incomplete':>12}"]
    for row in report["rows"]:
        lines.append(f"{row['scope']:<22}{row['status']:<14}{row['findings']:>10}{row['incomplete']:>12}")
    lines.append(f"\noverall_status: {report['overall_status']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["scan-tree", "scan-history"], nargs="?")
    parser.add_argument("--worker", choices=["scan-tree", "scan-history"], default=None,
                         help=argparse.SUPPRESS)  # internal: run in-process as the isolated worker
    parser.add_argument("--denylist-fd", type=int, required=True,
                         help="an already-open file descriptor to read denylist terms from, one per line - "
                              "never pass terms via argv or an environment variable")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--extra-dir", action="append", default=[],
                         help="additional directory of retained artifacts to scan (scan-tree only)")
    parser.add_argument("--result-fd", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--memory-limit-mb", type=int, default=DEFAULT_WORKER_MEMORY_LIMIT_BYTES // (1024 * 1024))
    parser.add_argument("--timeout-s", type=int, default=DEFAULT_WORKER_TIMEOUT_S)
    parser.add_argument("--no-isolation", action="store_true",
                         help="run the scan directly in this process instead of an isolated worker "
                              "(for environments where subprocess isolation isn't available)")
    args = parser.parse_args(argv)

    if args.worker:
        return _run_worker(args)

    if args.mode is None:
        parser.error("mode is required")

    denylist = read_denylist(args.denylist_fd)
    if not denylist:
        print("no denylist terms provided on the fd - nothing to check", file=sys.stderr)
        return 0

    if args.no_isolation:
        result = scan_tree(args.repo_root, denylist, tuple(args.extra_dir)) if args.mode == "scan-tree" \
            else scan_history(args.repo_root, denylist)
    else:
        result = run_scan_isolated(args.mode, denylist, args.repo_root, tuple(args.extra_dir),
                                    memory_limit_bytes=args.memory_limit_mb * 1024 * 1024,
                                    timeout_s=args.timeout_s)

    if result["scan_incomplete"]:
        print(f"SCAN INCOMPLETE: {result.get('reason')} - treat as a hard stop, not a clean pass", file=sys.stderr)
        for summary in result["log_summary"]:
            print(f"  {summary}", file=sys.stderr)
        return 1

    if result["findings"]:
        print(f"DENYLIST SCAN FAILED: {len(result['findings'])} finding(s) - matched text withheld")
        for f in result["findings"]:
            print(f"  {f}")
        if args.mode == "scan-history":
            print("History finding(s) require a separate remediation decision - "
                  "this tool does not rewrite history.", file=sys.stderr)
        return 1

    print(f"denylist {args.mode}: clean ({len(denylist)} term(s) checked, {result['stats']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
