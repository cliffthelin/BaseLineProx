# DR136: Peer review of installer enrollment and the full main merge

Date: 2026-10-03. Outcome: changes requested for both review scopes. Findings
are reproduced against fakes only; no physical drives or QEMU targets were
accessed. No merge or push was performed.

## Revisions and review scope

Main is `0391f347ba84a2e57403e4249200d326bce7383c`; the inherited parent is
`b1a0feadf56a6ed181bc104624df80572fabe86d`; the new commit is
`df4a84a3c5ad04838de04246feb5109e71e8c8db` (19 files).
The full merge carries 230 commits, 1,168 changed files, 169,148 insertions
and 378 deletions. The parent contributes 229 commits.

`git ls-remote --heads origin main local/physical-device-safety
local/installer-enrollment-plan` confirmed the remote main and inherited branch
match the local revisions. The new branch has no remote head. This read did
not update refs. Both existing scratch folders remain excluded.

The new commit received a source review. The inherited payload received a
risk-focused review of device validation, drive actions, storage identity,
backups and deployment wiring, plus the Baseline Python suite and a payload
inventory. This is not an exhaustive line-by-line approval of 230 commits:
652 changed paths belong to vendored Guardian; its Rust/package/runtime tests
were not run. Fixing these blockers does not automatically approve the rest.

## Findings

### F1 — P1: formatting loses the confirmed drive serial

Inherited from `81e2ae5`, reproduced on the parent and the new branch.
`drive_admin.lay_out_baseline_drive` (line 1132) calls
`baseline_drive_layout.apply` without `expected_serial`. Its final validation
accepts any large non-boot block device at the earlier path, including an
unenrolled replacement. `_prepare` and HITL bind their earlier checks to a
serial, but that serial does not reach the destructive helper.

The fake runner changes `/dev/sdb`'s serial during the action's mountpoint
read, after confirmation. `wipefs`, GPT erasure and all eight `mkfs.ext4`
commands still run against the replacement fake disk. No real commands run.
Preserve the exact confirmed serial through dispatch, re-resolve/check at
mutation and reject replacements, including another managed disk. Rows 55/65/67.

### F2 — P1: unknown boot identity permits enrollment

The new enrollment action exposes an inherited fail-open check:
`physical_device_safety.validate_target_device` (line 157) excludes the boot
drive only when its serial is known. An unresolved root source/serial disables
that exclusion. A fake empty `findmnt /` result allows matching-serial
enrollment, even through the real signed test web/HITL flow. The parent device
gate independently admits the same case; the low-level flaw predates DR135.

Resolve the running system's backing disks or conclusively establish a root
with no physical backing; refuse indeterminate topology. A failed identity
read cannot prove a drive is non-boot. Row 55 / physical-device validation.

### F3 — P2: autofill guesses destructive drive choices

New in DR135, `install_plan.autofill` (lines 151–160). Three empty candidates
cause the last to be selected for Baseline and the first for Proxmox based on
listing order. Two existing Proxmox candidates plus Baseline and an empty disk
produce a Proxmox ambiguity note but select the empty disk for a new install.
Both contradict the documented promise to leave ambiguous choices unset.
Distinguish absence from ambiguity for both roles and require explicit choice
between multiple candidates. Rows 72/76. The planner executes nothing; no
physical erase is claimed here.

### F4 — P2: missing PARTUUIDs validate and compile

New in DR135, `_check_retain` (lines 246–254). If both listing and plan contain
None for all required partitions, validation returns no errors and `_mounts`
compiles `PARTUUID=None`. Reject absent/malformed partition identities and
validate name/list uniqueness before producing mounts. Rows 72/76; no mounts
were applied.

### F5 — P2: cloned PARTUUIDs do not identify the selected drive

New in DR135: retained-volume validation only compares the chosen disk. A
second enrolled disk with another serial but cloned PARTUUIDs does not
invalidate a saved plan. `PARTUUID=` mounts remain ambiguous: cloning copies
GPT GUIDs too. Require each selected PARTUUID to identify exactly one attached
partition, including collisions outside the selected disk, or compile an
identity also bound to serial. Rows 72/76. DR135's uniqueness claim needs this
qualification; its historical text remains unchanged.

## Verification

The original committed suite, before adding review tests:

```text
python3 -m pytest -q tests/unit --tb=short
6 failed, 3081 passed in 112.70s
```

The first sandboxed attempt could not open loopback sockets. The run above
used approved execution outside that sandbox with the repository's autouse
hardware guard still active. Loopback HTTP integration is real HTTP, not
physical hardware verification. The six failures are exactly the DR135
`test_guest_backup.py` failures: 32 GiB available versus about 44 GiB required.
An isolated source snapshot of the parent reproduced all six. They are
inherited, not new-commit regressions. Give those tests controlled fake free
space; do not skip them or weaken the production backup-space gate (row 60).

Six new regressions in `tests/unit/test_peer_review_main_readiness.py` all fail:
two for F3 and one each for F1/F2/F4/F5. They remain deliberately RED; this
review makes no production implementation change. Two separate parent probes
also reproduced F1 and the underlying F2. That parent targeted run produced
8 failures / 7 passes: the six backup failures plus the two safety probes.

The import deployment checker and `bash -n boot/provision.sh` pass. Committed
DR135 does not pass `git diff --check`: the new bot description has trailing
whitespace and INSTALL.md has a new blank line at EOF. This corrects DR135's
blanket whitespace-check claim. The full payload also has whitespace findings,
chiefly in vendored evidence. No newly reachable history blob exceeds 100 MiB;
the largest is the 9,539,634-byte Guardian source archive. This size inventory
is not a credential audit.

Logs, parent probes and review failures are retained in `docs/verification/136/`.
No real-drive discovery, enrollment, formatting, mounting, boot or restore was
attempted. Earlier QEMU/physical records were not re-executed or promoted into
new verification claims.

## Decision and outstanding work

Neither scope is approved for merge/push to main. Resolve F1–F5 with
RED-to-GREEN tests, make inherited backup tests deterministic, rerun required
checks and review the final complete payload. A cherry-pick of `df4a84a` alone
onto main needs dependency analysis: main lacks modules/actions it extends.

INSTALL.md now qualifies the safety/identity claims and the v0.2 queue records
the pending fixes under existing rows. DR135 and older records remain history;
DR136 supersedes their unqualified safety/uniqueness/check claims only where
identified above. The review artifacts are uncommitted; the reviewed branch
tips, local main and remote branches were not changed.
