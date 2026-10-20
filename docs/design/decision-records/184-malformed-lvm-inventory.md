# DR184: Malformed LVM inventory cannot authorize volume creation

Date: 2026-10-09

## Context

`parse_logical_volumes` and `parse_logical_volume_sizes` silently ignored
malformed rows. In `ensure_volume`, a malformed but successful `lvs` response
could therefore look like an empty volume group and proceed to `lvcreate` and
`mkfs`. The size parser could also present an incomplete inventory as complete.

## Decision

An empty successful listing remains a valid empty result. Every nonblank LVM
row must have exactly the expected fields, sizes must be nonnegative integers,
and duplicate identities are rejected. `ensure_volume` returns a failure before
any create/format command if its listing is malformed. Existing-install
detection includes the parse error, while telemetry raises an inventory error
so the web surface can show the failure.

## Verification and limits

207 focused tests passed with synthetic runners across drive installation,
volume telemetry, and Drive Administration. Regression tests prove malformed
listing rows cannot reach `lvcreate`/`mkfs`. No physical drive was modified or
verified. The live host's LVM query remains limited by its no-new-privileges
sandbox condition documented in DR183.

## Follow-up

This is one REAL-006 repair. Other storage consumers and runtime verification
remain open in `docs/design/runtime-reality-tasks.md`.
