# DR141: Review and repair regressions in production-operation audit

Date: 2026-10-04. Review of `a396010` and its integration at `f5fede6`.
Code changes and tests in this increment are local and uncommitted. Validation
used fake runners and local subprocess boundaries only; no physical device was
queried or changed, and no real Proxmox operation was performed.

## Findings

1. `physical_device_safety.get_boot_device_serial()` followed only one
   `lsblk PKNAME` edge. A root LV such as Proxmox `/dev/mapper/pve-root` may
   require walking more than one parent before reaching a whole disk. The
   existing fake represented only a root partition directly under a disk, so
   it did not cover the layered topology already described in
   `experiments/m0-inv7/storage_ancestry.py` and DR07. The consequence is a
   fail-closed refusal of drive safety checks and installer discovery on
   unsupported layered roots, rather than unsafe formatting. The resolver now
   walks parent edges, limits traversal, and requires exactly one readable
   physical serial. Unknown, cyclic/overlong, and multi-disk results fail
   closed. It does not resolve ZFS pool membership, and its live behavior on
   the target Proxmox installation remains unverified.

2. `SystemSectionApplier` validated only fields in the settings schema, but
   `_DEFAULT_SETTINGS_SECTIONS["network"]` omitted the existing `dhcp` field.
   The earlier config pipeline and its later hostname-only behavior accept
   `dhcp: true`; therefore settings edits containing the normal default were
   rejected before reaching the apply function. The schema validator now
   accepts a boolean `dhcp` field for network settings. The pipeline continues
   to refuse `dhcp: false` before writing, and persists settings only when
   the live apply reports success.

3. Firewall, tether, handoff and iperf3 handlers removed in `a396010` had
   returned success without carrying out the represented operation. Treating
   those prior results as simulated success was correct to remove. Subsequent
   `f5fede6` reconnects real firewall, tether and iperf3 paths; handoff restore
   requires archive inputs and reports failure when they are absent. Cache
   update checking still has no publisher/version source and is explicitly
   unavailable. These items remain runtime integration work as documented in
   DR139; changing an unavailable result to failure does not implement it.

## Verification

Focused suite covering physical-device safety, settings, config apply/pipeline,
installer-plan discovery, DR137 review regressions, drive administration and
layout: **515 passed**. `git diff --check` passed. These tests establish behavior
against synthetic runners only. They do not prove the boot ancestry reported by
the actual Proxmox host or physical-drive exclusion.

## Remaining work and documentation

Physical and Proxmox verification remains open under v0.2 rows 55 and 72.
ZFS ancestry and multiple boot-disk identity need a complete supported
collector; the current resolver correctly refuses multiple serials. DR139's
status is historical and was not changed. `docs/INSTALL.md` and the v0.2 queue
were updated in place to point to this record and state the evidence limit.
