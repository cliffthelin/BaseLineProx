# Decision record: Storage graph

Date: 2026-09-21
Investigator: Claude Code
Status: complete — read-only throughout, synthetic unit tests plus real loop-backed LVM and ZFS validation

## Scope discipline

This investigation is explicitly read-only and confined to synthetic/loop-backed fixtures — no exclusive-access research, no physical-device work (that's Investigation 8, not attempted here). This host has no root (same constraint as Investigation 5), confirmed again directly: `losetup -f --show` fails with `Permission denied` even inside an unprivileged user namespace with `--map-root-user` (loop devices are a real host kernel resource; UID mapping inside a namespace doesn't grant access to them). Real loop/LVM/ZFS fixture work was therefore done the same way Investigation 5 did its real package-install validation: inside a disposable QEMU guest, which has genuine root, rather than by requesting host sudo or building a privileged host-side helper.

## What was built

`experiments/m0-inv7/storage_ancestry.py` — a read-only resolution module. `resolve_physical_ancestors(target, sysfs, lvm=None, md=None, zfs=None)` walks a sysfs holders/slaves snapshot recursively, cross-checking LVM and MD sources against sysfs for contradictions, and consulting a separate ZFS snapshot (`zpool`-derived) for any device that's a zvol/dataset rather than an ordinary dm/md block device. Nothing in the module runs a subprocess, opens a device, or mounts anything — it operates purely on already-collected data structures. `classify_signature(...)` implements the PRD's four-state classification, deliberately never returning "blank" or "safe."

## Synthetic unit tests — 12/12 passed, no privilege required

`experiments/m0-inv7/test_storage_ancestry.py` covers every fixture shape the PRD's §8.1 lists, plus two contradiction cases:

| Scenario | Result |
|---|---|
| root-on-plain-partition | resolves to the physical disk |
| root-on-LVM | resolves through LV → PV → physical disk |
| root-on-LUKS-on-LVM | resolves through decrypt → LV → PV → physical disk |
| root-on-MD-RAID | resolves to both physical members |
| root-on-ZFS-pool-member | resolves via zpool membership, not sysfs (sysfs deliberately left empty for the zvol's ancestors in this fixture, matching real behavior confirmed below) |
| Unknown device referenced by another device's slaves list | `active_or_ineligible` |
| Contradictory sysfs-vs-LVM sources (sysfs says one PV, `vgs` reports a different one) | `active_or_ineligible` |
| Contradictory MD membership (sysfs reports two slaves, `mdadm` reports one) | `active_or_ineligible` |
| Signature classification | never labels absence-of-signature as "blank" or "safe"; any recognized *or* unrecognized-but-present signature classifies as `recognized_existing_data` |

One real bug was caught and fixed by the tests themselves during development: the first ZFS fixture attempt left `sysfs.devices` completely empty, on the assumption that "ZFS doesn't populate sysfs" applied to the physical disks too — it doesn't; only the *pool-to-vdev relationship* is invisible to sysfs, the underlying block devices are still ordinary leaf entries. The fixture was corrected to reflect this, not the resolution code, which was correct as written.

## Real loop-backed validation, inside a disposable QEMU guest

A fresh disposable image was generated via the same proven pipeline (`run_final.sh`), with a one-time credential retained only for this session and purged afterward — confirmed absent from disk via a repository-wide search, matching the discipline established after Investigation 6's correction. All fixture work happened as real root inside this guest, using loop devices backed by regular files under `/root/`, never touching the guest's own installed disk (`/dev/vda*`).

### LVM — real tool output matches the synthetic model exactly

```
$ pvcreate /dev/loop0 && vgcreate inv7vg /dev/loop0 && lvcreate -L 100M -n inv7lv inv7vg
$ lsblk -f
loop0    LVM2_member LVM2 001
└─inv7vg-inv7lv
$ pvs -o pv_name,vg_name
  /dev/loop0 inv7vg
$ vgs -o vg_name,pv_count
  inv7vg   1
```
Resolved device-mapper node: `/dev/dm-5`. Direct sysfs inspection:
```
$ ls /sys/class/block/dm-5/slaves/
loop0
$ ls /sys/class/block/loop0/holders/
dm-5
$ ls /sys/class/block/loop0/slaves/
(empty)
```
This is an exact real-world match for the synthetic LVM fixture's shape (`LV.slaves = [PV]`, `PV.holders = [LV]`, `PV.slaves = []`) — the module's sysfs-walking logic was validated against genuine kernel-reported relationships, not just an assumed format.

### MD RAID — not validated against real tool output; flagged, not glossed over

`mdadm` is **not installed** on this base Proxmox image (`mdadm: command not found`). Fixing this would have required repeating the manual IPv4 workaround from Investigations 5/6 (the installer's `from-dhcp` IPv6-only result, per that decision record, reproduced again in this session's own setup) plus an `apt-get install`, for a secondary fixture — not done, given the primary LVM/ZFS validations already confirm the underlying sysfs mechanism works as modeled, and MD RAID uses that exact same kernel holders/slaves mechanism (just under `/dev/md*` naming) rather than a different one. **MD RAID resolution is therefore synthetic-tested only in this investigation** — the 12/12 unit test result stands, but has no real-tool-output cross-check backing it the way LVM and ZFS now do. This should be closed out in Milestone 1 alongside real privilege, not assumed proven by analogy alone.

### ZFS — real, direct confirmation of the PRD's core claim

```
$ zpool create inv7pool mirror /dev/loop0 /dev/loop1
$ zpool status inv7pool
  pool: inv7pool
 state: ONLINE
config:
        NAME          STATE     READ WRITE CKSUM
        inv7pool      ONLINE       0     0     0
          mirror-0    ONLINE       0     0     0
            loop0     ONLINE       0     0     0
            loop1     ONLINE       0     0     0
errors: No known data errors
```
Then, the critical check — with `loop0` confirmed by `zpool status` to be an active pool member:
```
$ ls /sys/class/block/loop0/holders/ ; echo EXIT=$?
(empty output)
EXIT=0
$ ls /sys/class/block/loop0/slaves/ ; echo EXIT=$?
(empty output)
EXIT=0
```
**Both directories exist and are empty.** This is direct, empirical proof — not an assumption carried from documentation — that ZFS vdev membership is genuinely invisible to sysfs holders/slaves, exactly as `storage_ancestry.py`'s design assumes and exactly why the PRD requires `zpool status` as a mandatory, separate collection source rather than treating sysfs as sufficient for every backend.

### Cleanup

`zpool destroy`, `lvremove`/`vgremove`/`pvremove`, `losetup -d` for every loop device created, and deletion of every backing image file — confirmed via `losetup -a` returning empty before the guest was shut down. Nothing was left behind inside the disposable guest, which was itself discarded (image and prepared ISO deleted, credential purged) after this investigation.

## What Milestone 1 must still verify with real privilege

- **MD RAID against real `mdadm` output** — not done here, flagged above.
- **LUKS/dm-crypt against real `cryptsetup` output** — `cryptsetup` was also absent from this base image; the LUKS-on-LVM scenario is synthetic-tested only, same caveat as MD.
- **Contradiction detection against real, deliberately-corrupted fixtures** — this investigation's contradiction tests are synthetic (hand-constructed mismatched data); a real test would need to actually desync `pvs` output from sysfs state on a live system, which is a more involved setup than this investigation's time budget covered.
- Whichever of `losetup`/LVM/MD/ZFS collection commands Milestone 1's real helper runs will need real root (via `pkexec`) — this investigation confirms the *resolution logic* is sound, not that the *collection* step (subprocess invocation, output parsing robustness against locale/version differences, etc.) is production-ready.

## Security implications

- The "unknown or contradictory → `active_or_ineligible`" requirement is now a directly tested property (two dedicated contradiction fixtures), not just a stated intent — a future implementation that silently trusts one source over another when they disagree would fail these tests immediately.
- The ZFS finding is the most safety-relevant result of this investigation: any future implementation that relies on sysfs alone (reasonable-looking, since it works perfectly for LVM/LUKS/MD) would silently fail to exclude a live ZFS pool member from destructive eligibility, since sysfs would report it as an ordinary, holder-free leaf device. This investigation provides direct evidence for why that shortcut is unsafe, not just a documented warning.

## Tests added

`experiments/m0-inv7/test_storage_ancestry.py` — 12 scenarios, all synthetic, no privilege required, runnable in any environment. This is the actual candidate for Milestone 1's `tests/unit/drive_setup_tests/test_storage_ancestry.py` once the module is ported into `baseline/lib/`, per the PRD's own test plan (§8.1).

## Whether Investigation 8 is unblocked

Yes — but per explicit instruction, Investigation 8 (exclusive physical-device access) does not begin until authorized separately, and remains loop-device-only per the milestone plan's own hard constraint (no real physical drive, even in Investigation 8).
