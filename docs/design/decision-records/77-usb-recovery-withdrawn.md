# Decision record: USB challenge-response recovery withdrawn, archived verbatim

Status: **removed from the active codebase. Archived, not deleted.
Full suite green (1122/1122) after removal.**

## Direct instruction

"We decided not to do the usb recovery option if you were thinking
that was blocking the recovery mode." A withdrawal of the feature
itself, not a reprioritization - confirmed directly when asked what
should happen to the already-built code: "Back the code up for later
reference and then remove it."

## Clarifying what was and wasn't actually blocked

Checked directly before acting: the work queue's own item 26
(recovery mode itself) was never actually blocked on item 24 (the USB
mechanism) - its real blockers were item 25 (an active-persona concept
to switch into) and an undecided UI surface. Recovery mode proceeds on
`recovery_tiers.py`/`admin_elevation.py` credential-tier logic alone,
built and tested in decision record 76, unaffected by this removal.

## What was removed

`baseline/lib/recovery_trust.py` and `tests/unit/test_recovery_trust.py`
(decision record 76's real Ed25519 challenge-response mechanism, its
17 unit tests, and the real end-to-end `openssl` smoke test). Checked
before removing: never wired into `provision.sh`, and `grep` across
the repo found no other real dependents - removing it has zero ripple
effect on anything else built this session.

## Where it went

Copied verbatim to `docs/design/archive/recovery_trust-usb-challenge-response/`
(the two source files plus a `README.md` explaining what it was, why
it was withdrawn, and how to bring it back if wanted later) before
deleting the originals - not relying on git history alone for "later
reference," per the direct instruction to back it up first.

## A repeat instance of the same real bug, caught the same way

Removing the files broke `test_no_persistence_typo.py` a second time
in this session - not because of the removal itself, but because
decision record 76's own prose quoted the misspelling literally while
describing the *first* time this same typo-guard test caught the same
class of mistake (in decision record 74). Reworded to describe the
misspelling without literally typing it, re-verified the archived
`README.md` didn't repeat it either, then re-ran the full suite.

## Verification performed

- `grep` across the whole repo confirmed no remaining references to
  `recovery_trust` before deletion.
- `tools/check_provision_deploys_all_imports.py` - zero gaps
  (unaffected, since the module was never staged).
- Full suite: 1122/1122 passing (1139 - 17 removed tests), no
  regressions.
