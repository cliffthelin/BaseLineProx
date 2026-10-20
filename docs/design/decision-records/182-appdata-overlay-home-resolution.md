# DR182: Resolve per-user AppData overlay targets

Date: 2026-10-09

## Decision

`OverlayMount.mount_argv()` accepts the actual target persona home directory
for `~/...` data targets. It joins that path into the lowerdir and mountpoint,
and rejects an absent or noncanonical home plus OverlayFS option delimiters.
Absolute system data paths remain directly executable without a user home.

## Reason

The old planner generated commands containing a literal `~/.config/...`
mountpoint and lowerdir. `mount` does not perform shell expansion, so that
command could not mount the Chromium data path described by the plan.

## Verification and limits

Test-first regressions failed before implementation because
`mount_argv()` did not accept a target home and emitted tilde paths. The final
focused combined suite passed: 248 tests across AppData planning, hardware
inventory, backup/restore, and related web/runtime error handling. Tests use
synthetic runners. No overlay was mounted; AppData runtime provisioning,
storage identity verification, app sandbox enforcement, and persistence
acceptance remain open under REAL-008/queue74.
