# DR143: Reject malformed observations and document the two drive roles

Date: 2026-10-04. Continues DR142 and the operator's request to turn fake
production results into explicit errors and repair tasks. Changes remain local
and uncommitted. No physical writes, mounts, credential handling, or Proxmox
runtime operations were performed.

## Runtime changes and verification

Malformed VM IDs previously could become an invented ID 0. Metrics now reject
missing, boolean, zero or invalid IDs and invalid, negative or nonfinite
measurements with REAL-001 errors; absent measurements remain unknown.

Existing smartd configuration previously could be interpreted as disabled when
the parser did not understand it. Readback now rejects per-device, mixed,
multiple DEVICESCAN, incomplete, duplicate or unknown directives with REAL-002.
Partial updates preserve the original file when readback fails, report the
error, and can continue independent configuration work. Broader smartd support
and live runtime verification remain open in the task register.

Twelve new regression cases were confirmed RED before production changes
(12 failed, 19 deselected). The focused suite then passed: 211 tests in 0.52s.
These are synthetic/unit boundary checks, not physical Proxmox verification.
The production import checker, boot/provision.sh syntax and whitespace checks
passed. DR142's 3241-test full-suite result predates these changes; it is not a
new full-suite claim for this increment.

## Read-only physical observations

Recorded command outputs are in docs/verification/143/physical-metadata.json.
Kernel device names below identify observations only; durable identity is the
drive serial, re-resolved before any future action.

PC601 serial <PC601 drive serial> currently resolves to /dev/sdc. Its third
partition is a 475.9 GiB LVM physical volume containing visible Proxmox logical
volumes: pve-root 5 GiB, pve-swap 2 GiB and pve-data 28 GiB thin storage, with
1 GiB thin metadata. The root filesystem was already mounted read-write by the
environment; df reported 87% used and 626 MiB available. This inspection did
not enumerate inactive guest volumes or establish remaining VG capacity.

PC401 serial <PC401 drive serial> currently resolves to /dev/sdd. It instead has
six ext4 partitions: BASELINE, INSTALLER_CACHE, SESSION_TEMP, SUBSTRATE,
USER_ADMIN and USER_PERSONAL. It has no observed Proxmox EFI/root layout.
The running development root is /dev/nvme0n1p2, not either inspected target.

These are different existing roles. Copying the PC401 layout onto the PC601
would replace its Proxmox boot/storage layout. An interchangeable layout would
require an intentional migration; byte cloning also duplicates disk,
filesystem and LVM identities, conflicting with existing identity guards.
No clone or migration was requested or attempted. Metadata inspection does
not prove that the installed Proxmox boots or that guest recovery works.

## Current status and remaining work

INSTALL.md, the layer overview, task register, queue and handoff were updated
with current observations. The layer overview's stale statement that the
backup destination selector was unbuilt was corrected; complete guest recovery
remains open under REAL-011. Historical decision records remain append-only.
REAL-001/002 still require live verification and broader supported inputs;
the other DR142 tasks remain open. Existing queue rows 55, 72 and 76 continue
to govern runtime proof and installer work. This is an incremental audit,
not approval to merge either branch or a whole-project readiness claim.
