# Decision record: vm_provision.py/pct_provision.py staged - a silent-degradation gap, not a crash

Status: **implemented and tested (961/961 suite passing). Not run
against real hardware.**

## What was found

Immediately after decision record 65's staging fix, checking whether
`vm_scripts.py` (already staged, "operator-invoked-only" per decision
records 57/58 in that sequence) had any of its own dependencies
missed the same way. `vm_scripts.py`'s adoption-bridge functions
(`start`/`stop`/`destroy`) import `pct_provision.py` and
`vm_provision.py` - but through a `try/except ImportError` guard that
falls back to a stub `CommandResult`, not a bare import. Neither
module was ever added to `provision.sh`.

This is a different failure shape than decision record 63's or 65's
gaps: those crashed outright (`ModuleNotFoundError` before the caller
ever ran). This one is quieter and arguably worse to have shipped
unnoticed - the adoption bridge would have silently returned a stub
result on any real deployed machine, with no exception and no obvious
signal that the real `qm`/`pct` commands never ran at all.

## The fix

Both modules staged and added to the present-file verification loop,
right alongside `vm_scripts.py`/`quadlet.py` - same operator-invoked,
no-systemd-unit treatment, since neither has a CLI entry point of its
own (confirmed: no `main()`/`__main__` in either file) and both are
already real, tested code (`test_vm_provision.py`,
`test_pct_provision.py`, 50 tests passing before this change).

## What this does not do

- **Correction, checked directly rather than assumed**: this gap was
  found by manual inspection of `vm_scripts.py`'s own imports, not by
  `tools/check_provision_deploys_all_imports.py`. Verified explicitly:
  the checker's transitive closure starts only from bin scripts
  `provision.sh` copies, and no staged bin script imports
  `vm_scripts.py` - it is staged only via its own direct `cp` line
  (same as `quadlet.py`). So `vm_scripts.py`'s own imports are outside
  the checker's reach regardless of the `try/except` guard, and the
  checker reports "OK" whether or not `vm_provision.py`/`pct_provision.py`
  are staged. The checker's real, documented scope (decision record
  63) is "is `provision.sh`'s bin-script copy list internally
  consistent with the real import graph" - it was never a check for
  "does every directly-`cp`'d lib module's own dependency tree get
  staged," and this record does not extend it to cover that; a
  directly-`cp`'d lib module with unstaged dependencies of its own
  remains a real, undetected blind spot for this tool.
- Not run against real hardware.

## Verification performed

- `bash -n boot/provision.sh` - clean.
- `tools/check_provision_deploys_all_imports.py` - zero gaps.
- Full suite: 961/961 passing, no regressions.
