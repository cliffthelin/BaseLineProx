# DR200: Verify the selected AppData volume before runtime use

Date: 2026-10-09  
Status: accepted

## Context

AppData has real per-application plans and OverlayFS/OCI mount specifications,
but nothing confirmed that `/mnt/APPDATA_<persona>` was backed by its dedicated
filesystem. A normal directory on the substrate could therefore look like a
valid target to future apply code.

## Decision

`appdata.verify_appdata_mount(runner, persona)` is the read-only prerequisite
for runtime use. It accepts only a configured persona, resolves that persona's
filesystem label with `blkid`, checks the exact mountpoint and ext4 filesystem
with `findmnt`, and resolves both device paths before comparing their identity.
Missing volumes, absent mounts, other filesystems, source mismatches, and probe
errors raise `AppDataRuntimeError`; no directory fallback is allowed. It does
not mount, format, change ownership, or launch applications.

## Evidence

The new wrong-volume test failed before implementation because the verification
function did not exist. The focused `tests/unit/test_appdata.py` suite passes
with 77 tests using scripted command results; this is synthetic command
evidence, not physical-mount or application-isolation verification. No drive
was mounted or modified.

## Remaining work

REAL-008/queue74 remains open: apply overlays and per-app identities, sandbox
launch and sharing, reset/migration/recovery, and guest/physical verification.
This function is a required guard for that work, not a claim that AppData is
already enforced at runtime. No earlier decision record is superseded.
