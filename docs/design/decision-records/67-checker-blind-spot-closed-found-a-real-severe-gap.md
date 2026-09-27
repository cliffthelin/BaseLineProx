# Decision record: closed the checker's directly-copied-lib blind spot; it immediately found a real, severe gap

Status: **implemented and tested (962/962 suite passing). Not run
against real hardware.**

## Follow-up to decision record 66

Decision record 66 documented a real, then-unfixed blind spot in
`tools/check_provision_deploys_all_imports.py`: it only walked the
transitive imports of bin scripts `provision.sh` copies, so a lib
module staged via its own direct `cp` line (no bin script ever
imports it - `vm_scripts.py`'s own case) had its dependencies invisible
to the scan regardless of whether they were staged. That record
deliberately left the blind spot open rather than fix it in the same
pass, to keep that record's own claims checked and honest rather than
mixing "found X" with "and also fixed the tool that found X" before
either was verified.

This record closes it.

## The fix

`find_missing_lib_dependencies()` now also seeds its transitive walk
from every lib module `provision.sh` copies directly (`copied_lib`),
not only from bin-script-reachable ones. RED test added first
(`test_checker_catches_a_gap_in_a_directly_copied_lib_modules_own_dependency`,
a synthetic fixture with zero bin scripts involved) - confirmed
failing against the unmodified checker before writing the fix.

## It immediately found a real, severe, previously-invisible gap

Running the strengthened checker against this actual repo did not
report clean - it found `stream_json.py` missing. Real, load-bearing,
unconditional: `harness.py` does a bare `import stream_json` and calls
`stream_json.parse_event`/`to_normalized` directly in its event-stream
handling path. `harness.py` has been staged via its own direct `cp`
line since before this session (line 44 of `provision.sh`, not
introduced by any change here) - meaning this gap predates every prior
audit pass in this repo's history, including decision record 63's,
and would have crashed `baseline.service` with `ModuleNotFoundError`
the first time it actually processed a streamed event, on every real
deployed machine to date. `stream_json.py` is now staged next to
`harness.py`, and both are added to the presence-verification loop
(`harness.py` itself was never in that loop either, a second small gap
in the same neighborhood, fixed alongside).

This is the strongest evidence yet that decision record 63's whole
premise - `provision.sh`'s copy list silently drifting from the real
import graph - was not a one-time defect but a recurring failure mode
of manual copy-list maintenance, and that strengthening the automated
check keeps finding more of it rather than exhausting it in one pass.

## What this does not do

- Does not claim the checker is now exhaustive. It still cannot see:
  imports gated behind a runtime `try/except` where the *guarded*
  name itself is never staged and the fallback path is never executed
  in any test (would silently degrade, not crash - same shape as
  decision record 66's own finding, just one level removed); a system
  package dependency (not a local `lib/*.py` module); or a module
  reachable only via `importlib`/dynamic import instead of a static
  `ast.Import` node. These remain real, stated blind spots, not solved
  here.
- Not run against real hardware.

## Verification performed

- RED confirmed first for the new test, against the unmodified checker.
- `bash -n boot/provision.sh` - clean.
- `tools/check_provision_deploys_all_imports.py` - zero gaps after the
  `stream_json.py` fix, run directly against this repo.
- Full suite: 962/962 passing (961 before this pair of changes), no
  regressions.
