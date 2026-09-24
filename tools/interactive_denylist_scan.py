#!/usr/bin/env python3
"""Interactive, local-only entry point for the real pre-P0 external-
identity scan. Run this yourself, directly on your own terminal:

    python3 tools/interactive_denylist_scan.py

It reads exactly three denylist values one at a time from the
controlling terminal via `getpass.getpass()` - the same battle-tested
standard-library mechanism a password prompt uses. On Unix, `getpass`
opens `/dev/tty` directly (not stdin) and disables terminal echo via
`termios` for the duration of each prompt, restoring it afterward even
on Ctrl-C or an exception.

The three values are NEVER accepted or exposed through:
  - this conversation / chat (Claude never sees them - this script is
    meant to be run directly, by you, after Claude hands you the
    command)
  - command-line arguments (getpass prompts interactively; nothing
    sensitive is ever a CLI arg)
  - environment variables
  - shell history (typed at a hidden getpass prompt, not a shell
    command line - never recorded by bash/zsh history, and terminal
    echo is off so it never appears on screen either)
  - repository files (never written to any tracked path)
  - test fixtures (this module's own tests inject synthetic values via
    a function parameter - see collect_denylist_interactively's
    prompt_fn - never real ones, and never through this file)
  - ordinary temporary files (the values live only in this process's
    memory and in the anonymous pipe fd handed to each isolated worker
    subprocess by scan_denylist.run_full_scan - never written to any
    path on disk, matching scan_denylist.py's own protected-fd
    discipline throughout)
  - logs or matched-value output (only the generic
    scan_denylist.format_full_scan_report() table is ever printed -
    scope name, status, and two counts, nothing else)

If fewer than three non-empty values are entered, this aborts before
scanning anything - a short denylist is refused outright rather than
silently scanning against an incomplete list.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_denylist  # noqa: E402

REQUIRED_VALUE_COUNT = 3


def collect_denylist_interactively(prompt_fn=None):
    """prompt_fn(i) -> str is injectable so tests can supply synthetic
    values without ever touching a real terminal or /dev/tty - the
    real (default) prompt_fn is the only code path that ever reads
    from an actual hidden prompt."""
    prompt_fn = prompt_fn or (lambda i: getpass.getpass(f"Protected value {i} of {REQUIRED_VALUE_COUNT} "
                                                          f"(input hidden, not echoed): "))
    values = []
    for i in range(1, REQUIRED_VALUE_COUNT + 1):
        v = prompt_fn(i)
        if v and v.strip():
            values.append(v.strip())
    return values


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--retained-evidence-dir", action="append", default=[],
                         help="a retained-artifact directory to include in the retained_evidence scope "
                              "(repeatable); if never given, that scope is reported not_in_scope, "
                              "not silently skipped")
    parser.add_argument("--memory-limit-mb", type=int,
                         default=scan_denylist.DEFAULT_WORKER_MEMORY_LIMIT_BYTES // (1024 * 1024))
    parser.add_argument("--timeout-s", type=int, default=scan_denylist.DEFAULT_WORKER_TIMEOUT_S)
    args = parser.parse_args(argv)

    print(f"This will prompt for exactly {REQUIRED_VALUE_COUNT} protected values, one at a time.")
    print("Input is hidden (not echoed to the screen) and read directly from this terminal.")
    print("Nothing you type here is ever sent anywhere else - it stays in this process's memory")
    print("and the isolated scanner subprocess it spawns, never written to disk or printed back.\n")

    denylist = collect_denylist_interactively()
    if len(denylist) != REQUIRED_VALUE_COUNT:
        print(f"expected exactly {REQUIRED_VALUE_COUNT} non-empty values, got {len(denylist)} - "
              "aborting, nothing was scanned", file=sys.stderr)
        return 2

    print("\nRunning the scan (current_tracked, retained_evidence, git_history)...\n")
    report = scan_denylist.run_full_scan(
        denylist, args.repo_root, tuple(args.retained_evidence_dir),
        memory_limit_bytes=args.memory_limit_mb * 1024 * 1024, timeout_s=args.timeout_s,
    )
    print(scan_denylist.format_full_scan_report(report))

    if report["overall_status"] == "findings":
        print("\nSTOP: at least one scope reported a finding. Matched text was withheld by design - "
              "review the affected path(s)/commit(s) reported above for a separate remediation decision. "
              "git history is never rewritten automatically.", file=sys.stderr)
        return 1
    if report["overall_status"] == "incomplete":
        print("\nSTOP: at least one scope could not be fully scanned (scan_incomplete) - "
              "this is NOT a clean pass. Re-run with a larger --memory-limit-mb/--timeout-s, "
              "or narrow --retained-evidence-dir, then re-check before P0.", file=sys.stderr)
        return 1

    print("\nAll in-scope checks are clean. Any scope reported not_in_scope was never "
          "declared/included - confirm that was intentional before treating P0 as cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
