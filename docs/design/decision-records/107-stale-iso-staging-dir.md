# Decision record: a prior failed attempt's own leftover staging directory broke every subsequent retry

Status: **real bug found live, fixed, and covered by a new regression
test. The real leftover directory on disk still exists but no longer
needs manual cleanup - the fix removes it automatically on the next
real attempt.**

## What happened

A real `build_self_installer` retry (after the xorriso fix, decision
record 106) failed with:

```
✗ FileExistsError: [Errno 17] File exists:
  '/var/tmp/baseline-self-installer/iso-build/staging/boot'
```

## Root cause

`build_self_installer`'s workspace (`/var/tmp/baseline-self-installer`)
is a fixed path, deliberately reused across real attempts - this is
correct and intentional for `workspace/acquire/`'s own cached assistant
binary (avoiding a real network re-fetch on every retry, flagged and
confirmed working in an earlier record this session). But
`stage_baseline_source`'s own `iso-build/staging/boot` and
`iso-build/staging/baseline` directories were *also* left behind by
the earlier failed attempt (decision record 106's own xorriso
failure), and Python's `shutil.copytree` refuses to write into an
already-existing destination directory - a real, previously-unflagged
gap: the workspace-reuse design was correct for the acquire cache, but
nothing ever cleaned the staging subtree between retries.

## Fix

`stage_baseline_source` now removes any pre-existing `staging_dir`
first (new `IsoBuilderRunner.remove_tree`, real `shutil.rmtree` in the
real implementation) before recreating it and copying fresh. Every
real retry now copies this repo's *current* content, never stale
leftovers from whatever the repo looked like during an earlier failed
attempt - and the exact reported crash can't recur.

## Files changed

- `baseline/lib/iso_builder.py` - `IsoBuilderRunner.remove_tree`
  (abstract) + `RealIsoBuilderRunner.remove_tree` (real
  `shutil.rmtree`); `stage_baseline_source` calls it before
  `makedirs`/`copytree`.
- `tests/unit/test_iso_builder.py` - `FakeIsoBuilderRunner.remove_tree`
  added; new test proves a pre-existing `staging/boot` directory is
  removed before the fresh copy happens.

## Verification performed

- Full suite: 1533/1533 (was 1532 before this record's 1 new test).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- Confirmed the real, still-present stale directory
  (`/var/tmp/baseline-self-installer/iso-build/staging/{boot,baseline}`,
  left over from the earlier failed attempt) exists on disk right now -
  the fix will remove and recreate it automatically on the operator's
  next real retry, no manual cleanup needed.
