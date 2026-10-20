# DR183: Volume inventory distinguishes failure from an empty plan

Date: 2026-10-09

## Decision

LVM list/size probes now require a successful command and textual stdout.
`collect_volume_details()` raises `VolumeObservationError` when those
observations fail. Volume usage reads the real `findmnt` JSON tree to establish
which planned mountpoints are mounted; genuinely unmounted volumes are omitted
from usage, while `df` failure or malformed output on a confirmed mount raises
an observation error. Drive Administration displays the error instead of
returning an empty volume plan.

## Verification and limits

Test-first regressions exposed missing error types and the old empty-list
fallback. The final focused Drive Installer, telemetry, and web suites passed:
163 passed. A read-only live `findmnt`/`df` run found zero mounted Baseline
volumes. The LVM read-only probe returned the sandbox's explicit `no new
privileges` error, which now appears as an inventory failure; no elevated
command, device mutation, or Proxmox target verification occurred.
