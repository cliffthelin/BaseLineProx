# Physical validation plan: Phase P0 (read-only preservation) and Phase P1 (disposable-drive install)

Status: **planning only**. Nothing in this document has been run against any physical host. No physical drive has been touched, mounted, written to, or installed to. This document is the reviewed procedure to run later, plus the exact commands it will use, not a record of anything already executed.

## Why P0 must happen before P1

The current working BaselineOS drive is the only known-working reference this project has. Its original predecessor already failed once (`backups/failure_log_attempt2.txt` - thousands of I/O errors). Before any new drive is installed, imaged, or compared against, the current drive's actual state - not memory of what was installed, not assumptions from `provision.sh`'s deploy list - must be captured, off that drive, in a form that can be reviewed and diffed later. This is exactly what [decision-records/27](decision-records/27-milestone-1.1-provisioning-closeout.md) closed out in QEMU: the disposable-image proof is now solid, but no QEMU pass can substitute for knowing what the *specific, currently-relied-upon* physical drive actually has on it.

---

## 1. Reviewed P0 collection procedure

P0 uses the just-ported [current-drive inventory collector](current-drive-inventory-plan.md) (`baseline/lib/inventory/`, `baseline/bin/baseline-drive-inventory`), reviewed and adapted from `cliffthelin/baseline`'s `inventory/current-drive-manifest` branch into canonical `BaseLineProx` (see decision commits `f55ed13`, `c688b57`). It is read-only by construction: every collector degrades to a reported failure rather than raising or retrying with elevated privilege, the only write in the entire tool is the one explicitly-named output manifest file, and `pathsafety.py` refuses to write into the repository/deployment root, `/etc`, `/var/lib/baseline`, or `/etc/pve` regardless of what path is requested.

Procedure, matching the numbered steps already given, each mapped to what the tool actually does:

1. **Environment probe.** Run `boot/baseline-repair-env-probe.sh` (already exists, already used elsewhere in this project for the same non-mutating purpose) to confirm the host's actual state - Proxmox version, network stack in use, standalone-vs-clustered - before trusting anything downstream. Read-only.
2. **Current-drive inventory collector.** `baseline-drive-inventory collect --source current-drive ...` (exact command in section 2). This single run performs steps 3-10 below as one atomic collection pass - they are not separate commands, they are what one `collect` invocation does internally, one collector module per concern.
3. **Package versions and manually-installed packages** - `collectors/system.py::collect_packages()`: `dpkg-query` for every installed package + version, `apt-mark showhold`, and (batched, one call, never per-package) Conffiles metadata for drift evidence.
4. **The five diagnostic tools** - `collectors/tools.py`, data-driven off `tools_manifest.json`: presence (`which`) and version string for `lm-sensors`, `nvme-cli`, `smartmontools`, `iperf3`, `ethtool`. Never starts, enables, or queries a live listener - version-query commands only.
5. **Enabled/disabled services and timers** - `collectors/system.py::collect_systemd_units()` (enabled units + `systemd-delta`) and `collectors/scheduling.py` (cron, `systemctl list-timers --all`). Also, per the port's addition, explicit status for all three Baseline units (`baseline.service`, `baseline-additive-dhcp-reapply.service`, `baseline-firstboot.service`), not just one.
6. **Allowlisted `/etc/pve` configuration** - `collectors/proxmox.py`: named-path reads only (`storage.cfg`, `datacenter.cfg`, per-node `qemu-server`/`lxc` `.conf` files, firewall rules), each field-allowlisted; `priv/` is never listed, read, or even existence-checked (enforced, not just avoided - see `test_never_lists_or_reads_priv_directory`). `pvesubscription get` is never invoked, by design, not deferred.
7. **Network topology and interfaces source-closure** - `collectors/network.py`: `/etc/network/interfaces` read and redacted (address/gateway/DNS values blanked, structure preserved), DNS resolver availability. `collectors/storage.py` covers mounts/block-device topology (`findmnt`, `lsblk`) as a related but separate concern.
8. **Boot configuration, kernel command line, firmware mode** - `collectors/storage.py::collect_boot()` (grub default, redacted `/proc/cmdline`, `proxmox-boot-tool status`, EFI entry count only) and `collectors/system.py::collect_firmware_drivers()` (`lsmod`, `lspci -nnk`, allowlisted `dmidecode` fields).
9. **Baseline files, unit files, and configuration hashes** - `collectors/baseline_config.py`: `/etc/baseline/*.json` (key names only), a bounded `/var/lib/baseline` walk, and - the port's addition - `/opt/baseline/bin/*` and `/opt/baseline/lib/*.py` enumerated and `sha256sum`'d (filenames + hashes only, never content, since hashing Baseline's own known source is exactly the drift evidence this step needs).
10. **Storage, repositories, scheduled tasks, relevant sysctls** - `collectors/storage.py` (mounts/block devices), `collectors/system.py::collect_apt()` (repositories - see the known Deb822 gap in section 6 below), `collectors/scheduling.py` (already covered in step 5), `collectors/security.py::collect_sysctl()` (fail-closed: only a small reviewed allowlist ever gets a live-queried value; every other key found in config files is recorded by name only, never queried).
11. **Export the manifest somewhere other than the drive being examined.** The `collect` command's `--out` still writes to a local path first (it has to - that's how a file is created); this step is the mandatory *next* action, not something the tool does automatically: copy the written manifest off the current drive - to attached external media (USB) or directly into this project conversation as an attachment - before it is considered preserved. Do not leave the only copy on the drive whose future is in question.
12. **Hash and preserve the manifest as the "current known-working drive" baseline.** `sha256sum` the exported manifest immediately after step 11, on the *receiving* side (not the source drive), and record that hash alongside the file. This hash is the tamper-evidence anchor for every future comparison against it.

**This phase performs no install, repair, reconfiguration, or restart of anything**, by construction: `collect` never calls anything but read-only commands and filesystem reads (confirmed by the 74 carried-over + 3 new tests asserting exactly this against a fake runner that records every call attempted), and its one write target is validated three separate times (`validate_output_path()`, then `atomic_write()`'s own independent re-check, then the four forbidden-root exclusions) before anything touches disk.

## 2. Exact read-only commands

Run as the operator, on the current drive, once physical/console access is available. None of these have been run yet.

```bash
# Step 1: environment probe (already-existing, already-used tool)
bash /opt/baseline/lib/../../boot/baseline-repair-env-probe.sh
# (or wherever it's staged on that host - it is not deployed by
# provision.sh today; copy it over first if it isn't already present)

# Steps 2-10: one inventory collection pass
/opt/baseline/bin/baseline-drive-inventory collect \
    --source current-drive \
    --host-label baseline-current \
    --node <proxmox-node-name> \
    --out /root/baseline-current-drive-manifest.json

# Immediately after: read-only self-check (schema validity, output
# permissions, forbidden field names, raw-secret-shaped value scan) -
# this never writes anything, including to the manifest it's checking
/opt/baseline/bin/baseline-drive-inventory validate \
    --manifest /root/baseline-current-drive-manifest.json
```

`--node` should be passed once per Proxmox node name the host actually reports (single-node systems: once). If unsure of the exact node name beforehand, `hostname` or `pvecm status`'s own output names it - read those first, non-destructively, rather than guessing.

**Step 11 (export off the drive)** - no single fixed command, since it depends on what media is available at the time; the historical design doc's own guidance (its added "file-handoff" step) applies directly: prefer attaching the manifest and its `validate` report to this project conversation directly (no third-party service, no new software on the drive being preserved); if a USB copy is wanted instead, `cp /root/baseline-current-drive-manifest.json /media/<usb-mount>/` after mounting read-write media that isn't the drive under inventory.

**Step 12 (hash, on the receiving side, after export):**

```bash
sha256sum baseline-current-drive-manifest.json > baseline-current-drive-manifest.json.sha256
```

No `sudo`, `pkexec`, `polkit`, `mount`, package install, service change, or block-device write appears anywhere in this list, matching the standing constraint for this phase.

## 3. Intended external output location requirements

- **Never on the drive being examined**, once step 11 completes - the whole point of preservation is surviving that specific drive's eventual failure or replacement, so a copy that only exists on it proves nothing.
- **Never inside `/opt/baseline`, `/etc`, `/var/lib/baseline`, or `/etc/pve`** even transiently beyond the tool's own initial write - `pathsafety.py` already refuses this at the tool level; the operator-chosen `--out` path (e.g. `/root/...`) is outside all four by construction, but should not be moved into any of them afterward either.
- **Attached to this project conversation, or copied to separate, already-trusted media** (USB, a second machine via `scp`) - not a new cloud service, not new credentials added to the audited host, matching the historical design doc's own reviewed guidance on this exact question.
- **World-unreadable at rest**: `atomic_write()` already `chmod 0600`s the manifest at the moment of writing; whatever holds the exported copy afterward (USB filesystem permissions, the receiving machine's directory) should preserve that, not loosen it.
- **Paired with its `validate` report and its `sha256sum`** wherever it ends up - the manifest alone, without the hash anchor or the validator's pass/fail-and-degraded-categories summary, is harder to trust later.
- **Retained indefinitely as the reference baseline**, not treated as disposable test output - unlike every QEMU experiment workspace this project has produced and deleted, this file's entire purpose is to outlive the drive it describes.

## 4. Current-drive versus new-build comparison procedure

**Honest scope note, carried over from the ported branch's own design doc and confirmed during the port review: no comparison/classification code exists yet.** `inventory/current-drive-manifest` implements collection only; `diff.py` was named as future work in its own design doc and was never built, on that branch or this one. This section is therefore the *procedure* to follow - today, manually, until a dedicated diff tool is built as a small, separate follow-on - not a description of an existing automated step.

Until that tool exists, the comparison procedure is:

1. Produce two manifests with the same collector, one per host: `--source current-drive` for the preserved reference (section 1-2 above), `--source disposable-vm` for a fresh QEMU or physical build (the CLI already accepts and records this distinction - `manifest["source"]` - specifically so two manifests are never accidentally compared as if they were the same kind of thing).
2. Run `baseline-drive-inventory validate` against each independently first - a manifest that fails its own validity/permission/secret-shape checks should not be trusted as an input to any comparison.
3. Compare category-by-category (a manual `diff` of the two JSON files' `categories` object is sufficient today given `schema.to_json()`'s sorted-key, deterministic serialization - the two files are byte-comparable line by line where nothing changed):
   - `packages`: new-build package set vs. current-drive's, and vice versa (present-only-on-one-side in either direction).
   - `tools`: does the new build have all five diagnostic tools at parity.
   - `baseline_config.deployed_file_sha256`: any Baseline source file whose hash differs between drives is either a legitimate version change (this repo moved forward) or a real drift signal - context, not the manifest alone, decides which.
   - `network`/`boot`: expected to differ (see below) - review for plausibility, not equality.
   - `proxmox`: `storage.cfg`/`datacenter.cfg` differences, VM/CT config presence.
   - `scheduling`, `security`: cron/timer/sysctl differences.
4. **Differences produce suggestions for human review, never automatic restoration.** This is not a policy choice this procedure is inventing - it is the only posture consistent with everything this project has already established: [drive-setup-gui-v2-prd.md](drive-setup-gui-v2-prd.md) already documents that `machine-id` must never be auto-restored, and the same reasoning generalizes - a manifest diff is *evidence a human should look at*, never a trigger for code to act on unattended. A future `diff.py` should emit a labeled list (e.g. `missing_on_new`, `present_only_on_new`, `hash_changed`, `config_drift`) for a person to read, not a patch to apply.
5. **Never copy machine-specific network, boot, or Proxmox identity settings blindly.** `network.interfaces_text` (redacted address/gateway/DNS), `boot.kernel_cmdline`, and `proxmox`'s node names/UUIDs are expected to legitimately differ between the old physical drive and a new physical drive or VM - different NIC, different disk topology, a fresh `/etc/pve` cluster identity. These categories exist in the comparison for *awareness*, not as fields to reconcile toward equality.

## 5. Physical Phase P1 validation plan

**Not started. Nothing below has been run.** P1 only begins after P0's manifest is exported, hashed, and preserved per sections 1-3.

1. **Identify the disposable target by serial/WWN and capacity, not `/dev/sdX`.** A device path is reassigned across reboots and enumeration order; it must never be the thing that decides which physical device gets written to. The commands to run (read-only, later, not executed in this pass):
   ```bash
   lsblk -o NAME,SIZE,MODEL,SERIAL,WWN,TRAN
   udevadm info --query=property --name=/dev/sdX | grep -E 'ID_SERIAL|ID_WWN|ID_MODEL'
   smartctl -i /dev/sdX   # capacity, model, serial cross-check
   ```
   The user has identified `/dev/sdk` as the currently-attached, already-formatted candidate (a second, separate 512GB drive of the same make/model already used in QEMU-equivalent testing) - but per this phase's own rule, its device path is a starting pointer for *where to look*, not the identity confirmation itself. Before any write, the serial/WWN/capacity read above must be run and recorded, and must be re-confirmed immediately before the install step (device paths can and do shift between an identification pass and a later action, especially across a reboot or a hot-plug event).
2. **Keep the current working drive untouched and, preferably, physically disconnected** during every step below - not merely "not the target," but out of the machine, so a path-confusion mistake elsewhere cannot reach it at all.
3. **Confirm target identity a second time, immediately before the install step**, not just once at the start of the session.
4. **Install the new build** - the already-proven `prepare-iso --fetch-from iso` automated path (or the interactive Terminal-UI path, if preferred for this specific target), same as every QEMU pass in decision records 26/27, now against the confirmed physical device.
5. **Exercise the local authorization workflow** - the same tty1 CONFIRM gate, target-bound network verification, and package install/verify/commit sequence already proven in QEMU, now for real: real tty1, real keyboard, no HMP scripting standing in for a human.
6. **Validate physical NIC/network behavior** - real link negotiation, real driver binding, the things QEMU's `virtio-net`/SLIRP cannot exercise (`ethtool` link/speed/duplex against the real NIC, ping/DNS/HTTPS through it for real).
7. **Run real sensor, NVMe, SMART, and ethtool collectors** - `diagnostics.py`'s existing collectors, this time against real hardware instead of a VM (where `lm-sensors` correctly reports no chips, per decision record 27's own honest finding) - the first time any of these produce genuine, non-empty readings in this project.
8. **Verify `iperf3` remains inactive** - `systemctl is-enabled`/`is-active` + `ss -tln` for `:5201`, matching the same check already proven in QEMU.
9. **Reboot twice** - matching the QEMU proofs' own discipline: once to confirm normal persistence and non-repetition, a second time (or an interruption test, if warranted physically) to re-confirm.
10. **Generate the new-drive inventory** - `baseline-drive-inventory collect --source disposable-vm --out ...` (or a more accurate `--host-label` for a physical-but-disposable target) against the freshly built drive.
11. **Compare it with the preserved current-drive manifest** per section 4 above, and produce the suggestions-for-review list - not an automatic restoration - for a human (the user) to act on.

Explicitly out of scope for P1 and not started in this pass: GUI/browser sandbox work, the Proxmox capability adapter, Harvester evaluation, and touching the actual production/current drive in any way.
