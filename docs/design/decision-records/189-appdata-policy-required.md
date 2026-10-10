# DR189: Require explicit AppData policy for every catalog object

Date: 2026-10-09  
Status: accepted

## Context

`appdata.installable_apps()` used `DATA_TARGETS.get(entry_id, ())`. A package
missing from the mapping was therefore rendered like a package explicitly
declared to be stateless. OCI entries had the equivalent gap through
`CONTAINER_BINDS.get()`. A catalog expansion could silently omit required
persistent storage while the planner continued to look complete.

## Decision

Every package entry must have a `DATA_TARGETS` key, and every OCI image entry
must have a `CONTAINER_BINDS` key. A declared empty tuple means the catalog
owner has confirmed that the object needs no per-app data target/bind. Missing
keys raise `DataTargetPolicyError`; they never produce an empty plan.

## Evidence

The regression test injects a synthetic catalog package without a policy and
checks that planning raises. All 74 AppData tests and 3 direct isolation-page
renderer tests passed. Current catalog planning also succeeded through those
tests. The remaining web route tests could not open local sockets in this
restricted run. Verification uses local code and synthetic catalog data; no
mounts or physical storage were changed.

## Remaining work

This closes only the unknown-versus-explicitly-stateless catalog fallback.
Current target declarations still require per-application runtime review, and
the AppData plans are not mounted or enforced at launch. Queue74/REAL-008 stays
open for selected mounted AppData, per-app identity, isolation, sharing,
migration, reset, recovery, and guest verification.
