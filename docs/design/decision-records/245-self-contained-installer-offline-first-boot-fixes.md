# DR245: Self-contained installer - offline first boot, reboot loop, and the fixes the rehearsal exposed

Date: 2026-10-10

Number provisional: two agents write decision records in this tree concurrently (DR244 landed while this work
was in progress). Renumber at merge if 245 is taken.

Branch `claude/whats-left-fixes`, worktree `/run/media/cane/CACHE/claude-whats-left`, based on shared-tree HEAD
`f5fede6` plus snapshot `0c9a679` of that tree's uncommitted work at 02:49 (not authored here).

## Context

The 2026-10-10 offline rehearsal of the self-contained installer (Proxmox + Baseline source + offline package
repository on one ISO, installed onto a blank sparse disk with no network) reached the first-boot CONFIRM screen
but never the kiosk, and exposed several defects. This record covers the fixes for its "what's left" list.

## Decisions

### 1. First boot may commit offline from the drive's own verified repository (`957b1ca`)

`firstboot_statemachine`: from `network_repair_failed`, if the drive carries its own package repository -
registered with apt AND re-verified against its manifest at that moment - the diagnostic tools are installed from
that repository only (apt given one source list, `SourceParts=-`, so no network source is consulted), then verified
and committed. The network failure is not overwritten: `network_repair_failed` stays in the journal,
`network_repaired` is never written on this path (its evidence invariant is untouched), and `committed` records
`network_verified=False`, `package_source="offline"`. Without a verified repository the old refusal is unchanged.
Consent is not widened: this runs only after CONFIRM, whose screen names the offline source when one is present.

### 2. The first-boot installer never reboots from inside Proxmox's first-boot unit (`b9b198a`)

Read from `proxmox-first-boot_9.2.5` on the ISO: the unit is `Type=oneshot` and removes its
`pending-first-boot-setup` flag in `ExecStartPost`, which runs only after the hook returns. An inline
`systemctl reboot` killed the unit first, so the hook re-ran every boot. Now: an already-complete install returns
successfully and does nothing; otherwise the reboot is queued with `systemd-run --no-block
--property=After=<invoking unit>` (unit read from `/proc/self/cgroup`). Verified against real systemd (user
instance) with the same oneshot + ExecStartPost shape: hook returns -> ExecStartPost -> queued reboot.

### 3a. Scripts inbox follows the active persona (`51a94e3`)

Gate and unit used the singular pre-persona `/mnt/USER`, which no persona install has, so the gate refused every
boot and `Restart=on-failure` looped. Both now resolve the active persona's `USER_<PERSONA>` through one function.

### 3c. Proposal and repair agree on what a missing lifeline fact means (`f6f4403`)

`network.check_lifeline` stops at the first failing fact. Discovery read a missing fact as not-OK; both repair
guards read it as healthy, so a NIC with no carrier was "already_healthy". One helper,
`repair.lifeline_reports_healthy`, now requires both facts present and exactly True; a genuine `already_healthy`
refusal is re-verified by first boot and recorded as `network_repaired` only on that fresh evidence.

### 4. Run script: no default target; work folder off the repo (`4b1d513`)

Two drives, two agents (Claude PC601 `FD01N6557110C271B`, Codex PC401 `MD89N41071210AP4E`). The script
hardcoded PC401 as the only target. Now `--target` is required for any stage touching a real drive (an exact
`--confirm-wipe` serial implies it), the other drive is protected for that run, and the work folder is
`/run/media/cane/CACHE/baseline-build/allscript-<target>` on ext4 instead of `<repo>/.runtime-proof173` on NTFS.

### 5. Recovery image under a kernel-enforced write budget (`8bdd378`)

Budget = real free space minus the destination's 3% reserve, enforced with `prlimit --fsize`; implemented to the
existing (previously failing) test specification. The compressed image is no longer charged its raw size.

### Also fixed along the way

- `32583d9`: 20 `baseline/bin` entry points committed `100644` (13 already at `f5fede6`), invisible on NTFS where
  every file reads as 777; an ISO built from a POSIX checkout would have shipped non-executable systemd entry
  points. Guard test added.
- conftest hardware guard: `prlimit` added to its wrapper list (`prlimit qemu-img ...` slipped past it).
- 4 assertions in `test_firstboot_statemachine` that could never fail (argv starts with `env`) strengthened.

## Not done here

- 3b (`inxi` parse failure under QEMU): no captured output existed; deferred to the re-run rehearsal.
- 6: the OS-selection and apps-with-overlays stage is not built.
- Two whole-drive recovery images cannot both fit on `/mnt/10TB` (819.5 GB free).
- The 35 remaining unit-test failures predate this work (mostly in-progress `drive_installer` mount-table probing).
