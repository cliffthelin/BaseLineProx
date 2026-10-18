# DR300: Installer-lane serial locks preserve drive ownership

**Status:** accepted from the operator's direct instruction, 2026-10-11  
**Scope:** the data-protection guard for physical drive actions  
**Codex target:** PC401, serial `<PC401 drive serial>`  
**Claude target:** PC601, serial `<PC601 drive serial>`

## Context

Decision record 66 established the populated-drive guard after an earlier
uncontrolled target selection nearly endangered a drive holding real data. The
operator later assigned PC401 to Codex and PC601 to Claude, authorized
serial-bound drive control in each lane, and clarified that read-only
inspection of other drives remains allowed. Each checkout has its own pinned
`baseline/INSTALLER_UUID`; a single global serial lock would cross the lanes and
either risk the other drive or block the other installer.

## Decision

Map each known installer UUID to its one authorized serial in
`drive_guard.py`. The active lane is loaded from its pinned
`baseline/INSTALLER_UUID`, copied beside the installed module at
`/opt/baseline/INSTALLER_UUID`. The exception applies only after `lsblk`
successfully reads the device state and a second read returns exactly one
matching serial line. The other lane's serial is refused before an empty-disk
or installer-generated-UUID allowance. An unreadable drive, failed serial
probe, empty or ambiguous serial output, case-changed or partial serial, and
every other populated serial remain protected by the existing rule. These
locks are source policy, not call parameters. All destructive entry points
retain `physical_device_safety` validation before writes.

This exception authorizes drive-control operations against PC401; it does not
claim that PC401 has booted successfully or that its GUI, network, firewall,
internet access, or workloads are working.

## Verification

`tests/unit/test_drive_guard.py`: 48 passed. Full unit suite: 3,937 passed,
9 subtests passed. These are unit tests using injected command runners; no
physical drive was written or formatted by this change. A read-only call
through the production guard on the current Claude checkout permitted PC601
and refused PC401. The same mapping test confirms that Codex's pinned UUID
selects PC401. The current running QEMU belongs to the PC601 lane and was not
touched.

## Consequences and open work

The 2026-10-01 rule remains the default for all other drives. Physical PC401
boot/runtime acceptance remains open under work-queue items 72, 75, 76 and 78;
the previously recorded bridge/network and service failures are not resolved
by this guard change. This record supersedes the absolute “no override” wording
for the two explicitly assigned installer lanes; all other historical records
remain unchanged.
