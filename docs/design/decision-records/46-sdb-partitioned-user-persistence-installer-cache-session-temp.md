# Decision record: `/dev/sdb` physically repartitioned into USER_PERSISTENCE / INSTALLER_CACHE / SESSION_TEMP

> **Drive letters in this record are as of when it was written and are not stable.**
> Identify drives by serial, never by `/dev/sdX`. As of 2026-09-30:
> serial `FD01N6557110C271B` (PC601, Proxmox install, `pve` VG) is `/dev/sdc`, and serial
> `MD89N41071210AP4E` (PC401, the Baseline drive) is `/dev/sdd`. Read the current mapping with
> `ls -l /dev/disk/by-id/ | grep -E 'FD01N6557110C271B|MD89N41071210AP4E'` (v0.2 rows 27-29).


Status: **done, for real, on real hardware.** This is the first
action in this session that modified a real physical drive directly.

## What happened

Corrected an earlier wrong claim in this same session ("no real
hardware access") - the two known real drives (`/dev/sdd`,
`/dev/sdb`, serials confirmed matching Track A1/A2 exactly) are
physically attached to this same machine this session runs on. Device
group permissions (`disk` group, `rw-rw----`) already grant direct
read/write access with no sudo needed for anything that operates on
the device file itself.

Asked to make BASELINE/USER_PERSISTENCE/INSTALLER_CACHE partitions,
resolved against a real constraint: Proxmox's own installer expects
to own an entire raw disk itself (builds its own GPT/EFI/boot/LVM
layout), so it can't coexist as one partition alongside sibling data
partitions on the same disk. The mapping used: `/dev/sdd` stays
BASELINE as a whole disk (Proxmox's own install, untouched by this
record - see the follow-up record for that half), and `/dev/sdb`
(confirmed disposable, explicitly not high-stakes per direct
instruction) was repartitioned into the three finer-grained divisions
the TestPersistence PRD's class-0 addition (decision record earlier
this session) already called for, plus `SESSION_TEMP` as a fourth,
explicitly a staging/quarantine area for anything not yet triaged
into either of the other two.

## Exact real commands run, in order

1. `physical_device_safety.validate_target_device("/dev/sdb",
   expected_serial="MD89N41071210AP4E", min_size_bytes=500_000_000_000,
   max_size_bytes=520_000_000_000)` - real validation via this
   project's own code, not a raw command - confirmed serial, size
   (512,110,190,592 bytes), and that it doesn't match this machine's
   own boot device.
2. `wipefs -a /dev/sdb` - found and erased one stale `LVM2_member`
   signature (`4c 56 4d 32 20 30 30 31` at offset `0x218`) - real,
   direct evidence that Track A2's own prior wipe either didn't fully
   happen or was reintroduced since; now genuinely clean.
3. `sgdisk -Z /dev/sdb` - fresh GPT.
4. Three partitions created via `sgdisk -n <num>:0:<size> -c
   <num>:<name> -t <num>:8300 /dev/sdb`:
   - `USER_PERSISTENCE` - 350 GiB (sectors 2048-734005247)
   - `INSTALLER_CACHE` - 100 GiB (sectors 734005248-943720447)
   - `SESSION_TEMP` - 26.9 GiB, all remaining space (sectors
     943720448-1000215182)
5. `partprobe /dev/sdb` (kernel re-read of the new table).
6. `mkfs.ext4 -F -L <name> /dev/sdb<N>` for each of the three,
   matching the GPT partition name (`-c`) with the ext4 filesystem
   label (`-L`) so both layers agree.

## Real result, confirmed via `blkid`

```
/dev/sdb1: LABEL="USER_PERSISTENCE" UUID="06da513d-eeb9-4ab1-b295-9b2d17e27c03" TYPE="ext4" PARTLABEL="USER_PERSISTENCE"
/dev/sdb2: LABEL="INSTALLER_CACHE"  UUID="4ffc20d9-ce1d-46fe-9673-06f89139541d" TYPE="ext4" PARTLABEL="INSTALLER_CACHE"
/dev/sdb3: LABEL="SESSION_TEMP"     UUID="477479ae-e39b-4acb-adba-4d88d6370eba" TYPE="ext4" PARTLABEL="SESSION_TEMP"
```

## Why ext4, why these sizes - not yet a final production decision

ext4 was chosen because it's simple, well-understood, and this is a
first real structural pass, not a schema commitment - the
TestPersistence PRD (§6) already explicitly defers final filesystem
choice past its own scope, and this record doesn't override that.
Sizes (350/100/27 GiB) were a judgment call favoring
`USER_PERSISTENCE` as the majority share, matching §9a's "daily-driver
reconstitution" requirement that this is where the bulk of real state
lives - not measured against any actual workload yet, since none
exists on real hardware to measure against.

## What this deliberately does not do

- Does not touch `/dev/sdd` (BASELINE) at all - see the follow-up
  record for that half of this session's work.
- Does not populate any of the three new partitions with real content
  yet - `USER_PERSISTENCE` and `INSTALLER_CACHE` are empty filesystems,
  not yet wired to anything. `SESSION_TEMP` has no code pointed at it
  yet either - it exists as a real, usable staging location the moment
  something needs one.
- Does not encrypt anything (LUKS2, per the PRD's own synthetic-only
  scope) - this is real hardware, plain ext4, no encryption layer
  applied in this pass.
- Does not update `vm_provision.py`/`persistence_pool.py`'s own
  `DEFAULT_PERSISTENCE_STORAGE`/`DEFAULT_VG_NAME` constants, which
  still describe the older two-drive, LVM-thin-pool design
  (`baseline-persist` on the whole of `sdb`) - that design is now
  superseded by this record's finer-grained partition layout on the
  same drive. Reconciling those constants with this new layout is
  real follow-up work, not done here.

## Verification performed

- `physical_device_safety.validate_target_device` run for real before
  any destructive command - confirmed serial/size/non-boot-device.
- `blkid` confirms all three partitions' filesystem type, label, and
  UUID directly, not inferred from the commands' own exit codes.
- `lsblk` cross-confirms the same partition sizes and labels
  independently.
