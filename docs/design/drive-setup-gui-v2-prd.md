# PRD: BaselineOS Drive Setup GUI v2 — bootable install + first-boot configuration

Status: draft (revised — see §0 changelog)
Owner: Cliff Thelin
Depends on: `packaging/baseline-drive-setup/` (v1, shipped as `.deb`), `baseline/lib/handoff.py`, `baseline/bin/baseline-setup-wizard`

## 0. Revision changelog

**Diagnostic-tool collector planning added (2026-09-22)**: §5.9 covered package *installation* only — confirmed directly that no collector code exists anywhere for any of the five tools (`baseline/lib/hardware.py` collects only `inxi`), and that the ad hoc `provision.sh` deployment path used for real-hardware migrations ahead of Milestone 2 doesn't install the five packages at all. New §5.9a specifies capability detection and normalized collectors for `lm-sensors`/`nvme-cli`/`smartmontools`/`ethtool`/`iperf3`, reusing this project's existing `Runner`-injectable/`FakeRunner`-testable pattern (`repair.py`) and existing interface-discovery code (`network.list_interfaces()`), with the same AI-harness authority boundary already enforced for hardware/network (`harness.py`'s `--tools ""`) extended to cover these five, and `iperf3` kept structurally outside the passive context blob as an explicit operator-confirmed action. Milestone 2's summary updated to require this, not just the install.

**Milestone 0 closeout (2026-09-21, documentation-only reconciliation pass, no new experiments run)**: all nine Milestone 0 investigations are complete. This pass reconciles the PRD's language against the actual evidence from [milestone-0-plan.md](milestone-0-plan.md)'s ledger and the nine decision records — no claim below goes beyond what a decision record actually demonstrated, and where evidence was mixed (proven for one subsystem, synthetic-only for another) the PRD now says so rather than rounding up. Load-bearing corrections made in this pass:
- §5.1a rewritten: Investigation 8 found `flock()` is confirmed advisory (does not stop a non-cooperating process) and udisks' `OpenDevice` D-Bus path provides no exclusivity of its own — neither is an enforcement mechanism. Real kernel `O_EXCL` behavior against a whole physical device was **not reachable to test** on the research host (permission wall) and remains genuinely unresolved, deferred to Milestone 3 real-hardware validation with real root.
- §5.2 updated: Investigation 7 directly confirmed sysfs `holders`/`slaves` are empty for an active ZFS pool member even though the device is genuinely in use — `zpool status` is a mandatory, separate collection source, not a fallback. LVM and this ZFS finding are real-tool-validated; MD RAID and LUKS ancestry remain synthetic-tested only (`mdadm`/`cryptsetup` were absent from the test image) pending Milestone 1 real validation.
- §5.5/§7 updated: confirmed directly that `proxmox-auto-install-assistant` subcommands (`validate-answer`, `prepare-iso`) return exit code 0 even on failure — error detection must parse stdout text and independently verify resulting artifacts, never trust `$?`. Also confirmed directly: a failed `prepare-iso` run (unwritable output path) leaves a complete, credential-bearing temp file behind with no automatic cleanup — Baseline's own tooling must own this cleanup on every exit path.
- §5.6/§9 updated per Investigation 9: the signed setup-intent bundle mechanism, under the deployment shape where the verification key lives beside the bundle on the target filesystem, is an **integrity/corruption check, not authentication** — it does not defend against an attacker with filesystem write access to the target. An independently-provisioned verification key (e.g. baked into the first-boot TUI image at build time) is recommended for real authentication, but this was not implemented or tested — recommending the shape is not the same as validating it. Replay protection (a durable consumed-intent ledger) is proven durable against interruption and content corruption, but **cannot survive a combined rollback of both the ledger and the intent to an earlier snapshot** without an independent monotonic trust anchor, which does not exist in the current design.
- §5.7 updated: the fresh-OVMF-NVRAM boot result (Investigation 4) proves portability across fresh OVMF firmware state specifically — QEMU's own UEFI implementation — not universal compatibility with every physical machine's UEFI firmware, which can differ from OVMF in boot-manager and boot-order-persistence behavior.
- §5.7 also adds a mandatory requirement found as a real defect in Investigation 4: installer media left first in boot order after a successful install allowed the installer's own reboot to silently re-enter itself against an already-installed, data-bearing disk (confirmed directly, not hypothesized) — the boot pipeline must ensure the installed disk becomes first-priority immediately after a successful install completes, with installer media treated as one-time-only.
- §5.5/§5.12 note added: the IPv6-only `from-dhcp` network result observed throughout Milestone 0's QEMU testing (Investigations 3/5/6) is scoped explicitly to this project's own QEMU/SLIRP/installer test environment — it is not a claim about how real Proxmox installs behave on real hardware/networks, and must be re-verified against a real target before Milestone 2/3 code depends on it.
- See [milestone-0-plan.md](milestone-0-plan.md)'s new "Milestone ledger" section for the per-investigation proven/partial/rejected/deferred status this pass is based on.

**Milestone 0 update (Investigation 5, post-revision-2)**: §5.8 rewritten. The original chroot-vs-`systemd-nspawn` offline-containment question is closed as `defer-to-first-boot`, verified directly against a disposable overlay of the real installed image (Investigation 3/4's pipeline) — no offline package installation, no containment mechanism, exists anywhere in this design. Packages install once, during the destination-hardware first-boot stage, against a real running systemd. See `decision-records/05-offline-staging-containment.md`.

**Revision 2** (this one) closes a second review pass. Architecture and milestone direction are approved; the remaining problems were narrower but load-bearing:

- The PRD assumed a first-boot systemd unit could make consequential network/firewall/tether/restore decisions unattended, then separately required the user confirm the detected subnet — those two statements can't both be true once the Ubuntu-hosted GUI is gone and the drive is booting on its own. §5.6 now specifies a real destination-hardware first-boot TUI on Baseline's own tty1 that does the confirming, with a defined handoff contract from the installer GUI.
- "Independently proven disposable" and "genuinely blank" overstated what signature inspection can show. Renamed throughout to technical-eligibility language with explicit states (§5.3, §6) and a separate, unmerged concept of user attestation.
- `flock` was asserted as exclusive-access protection; it's advisory only. §5.1a now marks the locking mechanism **unresolved, to be proven at Milestone 0**, and requires `by-id`/serial/WWN identity — `by-path` alone is no longer sufficient.
- Backend selection previously lived behind one runtime-configurable abstraction. §5.4 now requires the physical-device capability be **structurally absent** from the Milestone 0–2 helper binary and polkit action, not gated by a flag or a milestone check at runtime.
- "Partial-apply impossible by construction" for handoff restore was incorrect — validation-before-apply doesn't protect against power loss, filesystem failure, or a later category failing after an earlier one committed. §5.12 now specifies a transactional model with a durable journal and an explicit `partial_state_requires_attention` outcome.
- Added: chroot/offline-install containment requirements (§5.8), firewall application as a transactional, rollback-timer-protected action with a full standalone-host traffic account (§5.9), and treatment of the prepared answer-file ISO as sensitive material with its own Milestone 0 questions (§7.1).
- Assorted corrections: sysfs `holders`/`slaves` vs. relying solely on `lsblk`'s `HOLDERS` column; USB-disconnect-mid-write is "indeterminate + bounded termination," not "aborts"; automount interference needs active mitigation, not an assumption that a holder check prevents it; firewall unit tests must exercise the actual generated config format; host-key restoration validates private key, public key, *and* directory permissions.

**Revision 1** replaced the first draft's unbacked guarantees (device-name confirmation, "untouched on failure", chroot-validated networking, LAN-connect-proves-global-inaccessibility) with mechanism-honest language and introduced the milestone sequence. See git history for that diff if needed; this document supersedes it.

## 1. Problem

v1 of `baseline-drive-setup` (the `.deb`, shipped this session) solved *authorization* — a GTK4 app that picks a drive and runs a privileged helper through `pkexec`, no custom sudo, no scary install commands. It does **not** solve *installation*: `qemu-install` boots the raw Proxmox ISO with `-nographic -serial mon:stdio`, which the graphical Proxmox installer cannot drive, so nothing actually completes. Everything past drive selection — a bootable Proxmox install, the five diagnostic tools, LAN-scoped Proxmox web UI, SSH/tether preconfiguration, and handoff-packet restore — is either missing or lives in a disconnected CLI tool (`baseline-setup-wizard`) the GUI never invokes.

This PRD defines a production-quality installer **framework** whose destructive backend is structurally limited to image files through Milestone 2, and whose consequential real-world decisions (network, firewall, tether, secret restoration) are always confirmed by a human at the console that can actually see the real hardware — never inferred by unattended code running somewhere the human isn't looking.

## 2. Governing architectural principle

> "As much of the setup process as we can should be made available while a full OS is in place, not automating CLI scripts between TUI pages." — user, 2026-09-20

"A full OS is in place" now has a precise meaning in this document: **the target's own first boot on destination hardware**, with Baseline's existing tty1-ownership model (established earlier in this project) presenting a real, human-facing TUI — not a systemd unit making silent choices, and not the Ubuntu-hosted installer GUI, which no longer exists once the drive is booted on its own.

## 3. Goals / Non-goals

**Goals**
- A user with a technically-eligible image, virtual disk, or (at Milestone 3) whole physical drive can go from "GUI open" to "drive boots Proxmox, configured" with no manual TUI navigation *of the Proxmox installer*, while still explicitly confirming every consequential, hardware-dependent decision at the point where real facts exist.
- Every privileged action stays behind `pkexec` + a polkit action scoped to exactly what that milestone permits; "show me the script" is a redacted execution plan / config diff, never a secret-bearing command.
- Every step that can destroy data requires a stable-identity confirmation the helper independently re-verifies immediately before the write, plus an explicit user attestation — never a technical signature check alone, and never a bare device path.
- Local-network-only Proxmox web UI access is the default, applied as a rollback-protected transaction, with claims worded to match exactly what was tested.

**Non-goals (this PRD)**
- No support for installing alongside an existing OS on the same disk, preserving partitions, shrinking filesystems, dual-boot, installing into free space, or reusing an existing EFI partition — Milestone 4, deferred, needs its own risk model.
- No remote/headless operation over SSH — local GUI for Phase 1/offline staging; local TUI on the target itself for first boot.
- No cross-major-version Proxmox handoff restore, and no automatic restoration of private key material regardless of version match (§5.12).
- No physical-device support of any kind before Milestone 3 — see §5.4 for what "structurally absent" requires.

## 4. Destructive-target policy

Destructive installation is permitted only against:

1. Sparse/raw image files created by this tool in its own controlled workspace.
2. Virtual disks (QEMU-backed), same mechanism as (1).
3. At Milestone 3 only: a whole physical drive that has passed every technical-eligibility check in §6 **and** received explicit user attestation — the tool proves technical facts about the drive, never the user's intent toward its contents; that judgment stays with the user, stated plainly, not implied by a "disposable" label.

Nothing in this tool preserves existing partitions or installs beside existing data in this version.

## 5. Functional requirements

### 5.1 Drive selection and stable identity

`/dev/sdX` paths are not authorization-grade — unstable across reconnection, reboot, enumeration order. The GUI and helper key off:

- `/dev/disk/by-id/...`, preferring a WWN or serial-derived identifier
- Manufacturer, model, capacity
- Serial/WWN itself, not just the `by-id` symlink name
- Connection type (USB/SATA/NVMe)
- Existing partition-table/filesystem signature state (§5.3)
- Mounted/in-use status, including sysfs-derived `holders`/`slaves` relationships (§5.1a)

**`by-path` alone is not identity** — it names a connection point, and a different physical drive inserted into the same port would resolve to the same `by-path` entry. A physical drive with no serial, WWN, or other content-independent unique identifier is **ineligible for destructive installation**, full stop — it does not fall back to path-based authorization.

The GUI's confirmation dialog reads back a human-readable identity string, e.g.:

> **ERASE Samsung T7 1TB ending 4C21**

The helper independently rediscovers the device by its stable identity and re-checks capacity, serial/WWN, and storage-graph position immediately before the destructive operation — it does not trust the GUI's earlier snapshot. A mismatch at this point refuses and requires full reselection.

### 5.1a Exclusive access — researched at Milestone 0 (Investigation 8), still unresolved, deferred to Milestone 3

`flock` is advisory — this is now directly confirmed, not merely asserted: a second, non-cooperating file descriptor's plain read/write succeeded against a `flock`-held loop device without ever calling `flock` itself. udisks' `Block.OpenDevice` D-Bus method, the standard unprivileged path to a device FD on this class of system, was also confirmed to provide **no exclusivity of its own** — a second concurrent `OpenDevice` call against the same device succeeded while the first FD was still open. Neither mechanism is an enforcement boundary; both are, at best, cooperative signals.

**What Investigation 8 could not test**: genuine kernel-level `O_EXCL` enforcement against a whole physical block device — the mechanism most likely to actually work, since Linux's block layer treats `O_EXCL` specially there (unlike on a regular file, where it only affects creation) — was never reachable in testing, because the research host had no path to open a `root:disk`-owned device node directly. **This PRD does not claim `O_EXCL` works, and does not claim it doesn't — it is genuinely untested**, and must be proven with real root (via `pkexec`) against real hardware before Milestone 3 depends on it.

A real, useful, unprompted finding: this system's automounter mounted a recognized filesystem on a loop device on its own initiative, with no explicit mount command issued — confirming automount is a live, default-on threat this mechanism must actively defend against, not a theoretical one. Whichever combination Milestone 3 lands on, still evaluating:

- Repeated (not one-shot) mount/swap/holder re-checks across the operation's duration, using sysfs `/sys/block/<dev>/holders/` and `/sys/block/<dev>/slaves/` directly — not solely `lsblk`'s `HOLDERS` column, which is a convenience view over the same data and may not reflect every relationship type.
- Host automount inhibition for the duration of the operation (e.g. a `udisks2` inhibit lock or equivalent), with restoration afterward.
- An exclusive block-device open where the kernel/tooling supports it (`O_EXCL`, or `BLKROSET`-style guards as applicable) — **the correct FD-passing mechanism for handing an already-open descriptor to QEMU without reopening by path is `-add-fd`+`-blockdev driver=host_device,filename=/dev/fdset/N`, confirmed working**; the more obvious-looking `-drive file=/dev/fd/N` is actually a path-based reopen through `/proc/self/fd` and fails under privilege separation — confirmed directly, not assumed.
- Continuous device-presence and identity monitoring for the duration of the write, aborting immediately if a new holder, mount, or identity change appears — **not directly tested at Milestone 0** (the planned contention and disconnect-detection tests were stopped before completion; see [decision-records/08-exclusive-access.md](decision-records/08-exclusive-access.md)).

Whichever combination is chosen, cleanup and automount-inhibition restoration must happen on every exit path (success, failure, cancellation, crash). **This remains a genuinely open question, not a placeholder** — Milestone 0's contribution is real, evidence-backed elimination of two mechanisms (`flock`, `OpenDevice`) as insufficient on their own, plus a proven FD-passing pattern for whatever mechanism Milestone 3 does end up using; it is not a solved design. See [decision-records/08-exclusive-access.md](decision-records/08-exclusive-access.md) for full evidence and the specific real-hardware validation Milestone 3 must still perform.

### 5.2 Storage-ancestry exclusion

Excluding only `findmnt -no SOURCE /` is unsafe — that can resolve to an LVM LV, a dm-crypt mapping, a RAID member, or a ZFS dataset, not the physical disk underneath. The helper resolves the **full live-system storage graph** using sysfs ancestry (`holders`/`slaves`, walked recursively — not assumed to be fully exposed via any single `lsblk` column) plus `pvs`/`vgs`, `dmsetup deps`, `mdadm --detail`, and `zpool status`, and excludes every physical ancestor backing:

- `/`, `/boot`, `/boot/efi`
- swap
- any other mounted filesystem
- LVM physical volumes
- dm-crypt mappings
- MD RAID members
- ZFS pool members
- active loop-backed storage
- any device with holders or open dependent mappings

**If the relationship cannot be resolved with confidence, the drive is unavailable for selection — not flagged with a warning.**

**Milestone 0 (Investigation 7) confirms this design directly, with one real gap flagged rather than assumed away**: real loop-backed LVM validation matched the synthetic resolution model exactly at the sysfs level. Real ZFS validation directly proved the reason `zpool status` must be a separate, mandatory source: with `loop0` confirmed by `zpool status` to be an active pool member, `/sys/class/block/loop0/holders/` and `.../slaves/` were **both empty** — ZFS vdev membership is genuinely invisible to sysfs, not merely undocumented. **MD RAID and LUKS-on-LVM ancestry remain synthetic-tested only** — `mdadm`/`cryptsetup` were absent from the test image used — the resolution logic passed all synthetic fixtures for both, but has no real-tool-output cross-check yet; this should close out at Milestone 1, not be assumed proven by analogy to the validated LVM case. See [decision-records/07-storage-ancestry.md](decision-records/07-storage-ancestry.md).

### 5.3 Technical eligibility states (replaces "blank"/"disposable")

Software can prove technical facts. It cannot prove the user doesn't care about a drive's contents, and it cannot prove a drive is truly free of recoverable data merely because no known signature is present — a wiped signature can still leave recoverable data behind, and `wipefs`/`blkid` only detect signatures they recognize. The tool therefore classifies every candidate device into exactly one state, computed read-only via `lsblk`, `blkid`, `wipefs --no-act`, partition-table parsing, and the §5.2 ancestry tooling — **never** by mounting a filesystem to inspect its files:

| State | Meaning |
|---|---|
| `no_detected_signatures` | No recognized partition table, filesystem, RAID marker, LVM metadata, or encryption header found. **Not** a claim that the drive is blank or that no data is recoverable — only that nothing recognized was found. |
| `recognized_existing_data` | A recognized signature of some kind is present. |
| `ambiguous_or_unreadable` | Read errors, partial/corrupt signatures, or anything the tooling can't classify confidently. |
| `active_or_ineligible` | Mounted, part of an excluded ancestry graph (§5.2), held by another process, or lacking a stable identity (§5.1). Never selectable regardless of signature state. |

`ambiguous_or_unreadable` and `active_or_ineligible` are never selectable for destructive installation. `no_detected_signatures` and `recognized_existing_data` are both selectable **only** after the user attestation in §6 — the tool does not treat "no signatures found" as requiring a weaker confirmation than "has data." Both require the same erase-phrase confirmation; the eligibility state is shown to the user as information, not used to relax the confirmation requirement.

### 5.4 Backend structure — physical devices structurally absent before Milestone 3

Through Milestone 2, the shipped privileged helper binary and its polkit action **do not have a code path capable of expressing a block-device target at all**:

- The helper's destructive subcommands accept only a path that must resolve, after canonicalization, to a regular file inside a workspace directory the helper itself controls (created by the helper, not user-suppliable) — never a path the caller chose freely, and never anything that `stat` reports as a block device.
- Any argument that resolves to a block device is rejected by type-check before any other validation runs.
- The polkit `.policy` file shipped through Milestone 2 authorizes only the image-backed action ID; no `os.baseline.drive-setup.*physical*` action exists in the shipped package.
- No `--physical`, `--device`, or equivalent dormant flag exists in the helper's argument parser, even disabled or unwired.
- Milestone 0–2 tests include an explicit **surface test**: enumerate the helper's accepted subcommands and argument shapes and assert none of them can be made to accept a block-device path, by construction (a static assertion over the argument schema, not just a runtime behavioral test).

At Milestone 3, physical-drive support is added as a **separately reviewed** new helper capability and a new, separately scoped polkit action — a genuine new security boundary, reviewed on its own, not an existing flag or milestone check flipped on.

### 5.5 Unattended install (Phase 1, image/virtual-disk backend only through Milestone 2)

- GUI form collects only what the Proxmox installer answer file needs: hostname, initial root password (see §7.1 for why this is treated as sensitive material through the whole pipeline), timezone, keyboard layout, network = DHCP. Static IP, firewall, SSH, and tether are first-boot concerns (§5.6).
- Helper subcommand `automated-install` generates a TOML answer file via `proxmox-auto-install-assistant prepare-iso`, producing a self-contained unattended ISO, then boots it under QEMU against the image/virtual-disk backend with a real display (`-vnc` or `-display gtk`), not `-nographic`.
- **Never trust the assistant's exit code.** Confirmed directly (Investigation 2/3, both `validate-answer` and `prepare-iso`): every failure mode tested, including deliberately invalid answer files and induced I/O failures, returned exit code 0 — the tool only reports failure via stdout text (`Error:` prefix). Baseline's own wrapper around every subcommand must parse output text and independently verify the resulting artifact (file exists, is the right type, is within expected size bounds, contains no forbidden strings) rather than branching on `$?`.
- **Note on the observed `from-dhcp` network result**: throughout Milestone 0's QEMU-based testing, `network.source = "from-dhcp"` consistently produced an IPv6-only lease from QEMU's SLIRP networking, never IPv4 — this is scoped explicitly to this project's own QEMU/SLIRP/installer test environment (Investigations 3/5/6), not a claim about real Proxmox installs on real hardware/networks, and must be re-verified against a real target before any Milestone 2/3 code depends on IPv4 availability during first boot.
- **Failure contract:** once the installer begins, it may erase or partially rewrite the target before failing. The tool states:

  > "The previous attempt may have modified this target. It is not known to be in its original state."

  A retry rediscovers and revalidates the same stable device identity from scratch, displays the "may have been modified" notice, and requires fresh destructive-authorization confirmation. **Retry never begins automatically.**
- Firmware mode (UEFI vs. legacy BIOS) is an explicit, recorded choice — see §5.7.

### 5.6 First-boot configuration — offline staging + destination-hardware TUI

This is the section the prior revision got structurally wrong: it described a first-boot systemd unit configuring network/firewall/tether/restore decisions automatically, while separately requiring the user confirm the detected subnet. Once the Ubuntu-hosted GUI is gone — which it is, the instant the new drive boots on its own — there is no GUI left to ask that question. The confirmation has to happen somewhere real, and the only place that exists is the target's own console.

**Offline staging** (no chroot, no package installation — see §5.8; this stage only copies files):
- Copy Baseline.
- Stage the handoff packet's non-secret categories into a quarantine location (not yet applied — see §5.12).
- Seed authorized public keys into a staged location.
- Install and enable a Baseline **first-boot state machine** unit, and a **signed setup-intent bundle** produced by the installer GUI containing: the operator's Phase-1 form choices, which handoff categories were selected for staging, whether SSH/tether preconfiguration was requested and with what values, and nothing secret in plaintext beyond what's unavoidable (staged handoff secrets stay encrypted at rest until the destination TUI supplies the passphrase).
  - **What "signed" is allowed to mean here (Milestone 0, Investigation 9)**: under the deployment shape where the verification key is stored beside the bundle on the target filesystem — the shape this design currently describes — the signature is an **integrity/corruption check**: it detects accidental corruption or mismatch between what the operator chose and what got staged. **It is not authentication and does not defend against an attacker with write access to the target filesystem**, who could replace both the bundle and the key together. Real authentication requires the verification key to come from a channel independent of the bundle's own filesystem (e.g. baked into the first-boot TUI's own image at build time) — this is the recommended direction for Milestone 1+, but it has not been implemented or validated, and recommending the shape is not a claim that it works.
  - The bundle's replay protection (a durable, existence-based consumed-intent ledger) is proven to survive an interrupted write and to fail closed against a corrupted ledger entry, but **cannot survive a combined rollback of both the ledger and the intent to an earlier filesystem snapshot** without an independent monotonic trust anchor (e.g. a hash-chained ledger, a hardware counter, or an out-of-band record) — none of which exists in the current design. This is a real, stated gap, not a hypothetical one. See [decision-records/09-setup-intent-trust-model.md](decision-records/09-setup-intent-trust-model.md), including its addendum.
- **The five diagnostic tools are explicitly not installed at this stage** — see §5.8.

**Destination-hardware first boot** (the target itself; a QEMU boot of this stage is a proof exercise for Milestones 1–2, explicitly not claimed equivalent to real hardware):
- Baseline's first-boot state machine owns tty1, exactly as Baseline already owns tty1 in normal operation. **tty2 remains available throughout** — this is not a mode that locks the operator out of anything.
- The unit may perform **fact discovery** automatically and silently: real NIC names, link state, DHCP lease/subnet, USB device presence, present storage. Discovery has no side effects and requires no confirmation.
- Every **consequential** decision — applying network configuration, applying the firewall policy, applying tether configuration, applying any handoff-restore category, especially anything from the private-key tier in §5.12 — is presented on tty1 as a real, human-facing TUI screen showing the discovered facts and the proposed action, and requires explicit local confirmation or correction before it is applied. This mirrors the setup-intent bundle from offline staging: the bundle proposes, the TUI confirms.
- Each consequential action, once confirmed, is applied through the bounded, rollback-protected mechanisms specified elsewhere in this document (§5.9 for firewall, §5.12 for handoff) — the TUI is the confirmation surface, not a new application mechanism.
- After the full sequence completes (or the operator explicitly defers a step), Baseline records **first-boot completion** in a durable marker. The state machine does not re-run automatically on subsequent boots; a deferred or re-run pass requires an explicit operator action from within Baseline's normal running state, not an automatic re-trigger.

**Post-boot verification** (back on the GUI-running machine, or reported by the completed first-boot state machine): confirm the five tools installed and idle, confirm applied network config, confirm firewall state matches what was confirmed on tty1, confirm Baseline is running, confirm tty1/tty2 behavior, confirm storage/recovery paths intact.

The GUI never claims LAN access or tethering "works" on the strength of a QEMU session or chroot alone — those claims are only made after the destination-hardware TUI stage reports a *confirmed and verified* result.

### 5.7 Bootability verification

Two independent checks:

1. **Static verification** — partition table matches expectation, root filesystem/LV present, Proxmox packages installed, ESP or BIOS-boot structures present, bootloader files present, `fstab` valid, Baseline first-boot unit and setup-intent bundle staged.
2. **Actual QEMU boot test** — boot from the installed target, require a deterministic success marker via serial or guest-agent output, shut down cleanly.

Firmware mode is tracked explicitly: an install under virtual UEFI may write only to virtual NVRAM, which doesn't exist on destination hardware. The disk needs a portable/fallback EFI boot path (`/EFI/BOOT/BOOTX64.EFI` or equivalent) validated as part of static verification, not assumed.

**Passing the QEMU boot test proves the disk is structurally bootable. It does not prove destination hardware will boot it.** That claim is only made after §5.6's destination-hardware first boot completes and is confirmed.

**Milestone 0 (Investigation 4) confirmed this precisely, with the scope stated exactly as tested**: a disk installed under legacy BIOS booted successfully both by rebooting into itself and by fresh-UEFI-NVRAM boot (a blank `OVMF_VARS` copy, never touched by the installer, reached a working login prompt in under 10 seconds with no manual EFI boot-manager intervention). **This proves portability across fresh OVMF firmware state — QEMU's own UEFI implementation — not universal compatibility with every physical machine's UEFI firmware**, which can differ from OVMF and from each other in boot-manager behavior and boot-order persistence. A real physical-hardware UEFI boot test remains required before Milestone 3 claims destination-hardware boot compatibility.

**Mandatory: installer media must be one-time boot media.** Investigation 4 found, as a real defect rather than a hypothetical: a successful install's own reboot silently re-entered the same automated installer against the now-installed, data-bearing disk, because the installer media (the virtual CD-ROM) couldn't be ejected and remained first in boot priority. Given the installer's answer file directly controls which disk gets erased (§7.1/Investigation 2), an unplanned reboot under that condition is a real destructive-reinstall risk, not a cosmetic loop. Fixed and confirmed directly: boot order must prefer installer media exactly once, then the installed disk on every subsequent boot (QEMU: `-boot order=c,once=d`) — this is a hard requirement for Milestone 1's real pipeline, not a convention, and the equivalent guarantee (installed disk becomes boot-first immediately after a successful install) must hold for whatever real-hardware boot-order mechanism Milestone 3 uses too.

### 5.8 Package installation — deferred to first boot, not staged offline

**Decision (Milestone 0, Investigation 5): package installation is never done offline.** No chroot, no `systemd-nspawn`, no offline containment mechanism of any kind exists in this design. Offline staging (§5.6) copies files only — Baseline itself, the setup-intent bundle, the first-boot unit, staged (unapplied) handoff/key material. Every package Baseline needs, including the five diagnostic tools (§5.9), installs during the destination-hardware first-boot stage (§5.6), via a normal `apt-get install` against the real, running target OS with a real systemd — the same environment and mechanism any normal Debian/Proxmox system uses for its own package management, with no synthetic sandbox standing between the package and the service manager it expects.

**Why, with evidence**: the original plan required choosing between chroot+`policy-rc.d` and `systemd-nspawn` for offline containment, with the safety property resting on "maintainer scripts can't start services because there's no reachable systemd." Investigation 5 found that reasoning insufficient on its own — a maintainer script can invoke binaries directly, manipulate devices, or depend on mounted host interfaces in ways "systemd isn't PID 1" doesn't cover — and, separately, found that verifying either containment approach on a real development host requires real root, which this project's own architecture deliberately doesn't grant to interactive tooling. Rather than requesting sudo credentials or building a privileged mounting helper to force the comparison, the gap was read as the actual answer: if package installation is going to happen where a real systemd is genuinely running anyway, do it there, once, in the environment the packages already expect — not twice, once fake and once real. This was verified directly, not assumed: the five packages were installed against a disposable overlay of the actual installed image, with listening sockets captured before and after (identical), `iperf3` confirmed `disabled`/`inactive` both immediately after install and again after a full reboot, `dpkg --audit` clean, and no `sensors-detect` or SMART self-test triggered. Full evidence in `docs/design/decision-records/05-offline-staging-containment.md`.

**What this changes structurally**:
- No `policy-rc.d`, no bind-mounted `/proc`/`/sys`/`/dev`, no chroot/nspawn code path exists anywhere in the shipped tool.
- The setup-intent bundle (§5.6) carries the package *selection*, not installed packages — the destination-hardware first-boot stage performs the actual install as one of its confirmed, consequential actions.
- The distinction the prior revision required ("package installed offline" vs. "capability verified on destination hardware") is now moot — there is only one installation event, and it already happens on destination hardware, so there is only one claim to make: installed and verified, together.
- Package-database consistency (`dpkg --audit`) and the `iperf3`-listener check both happen at the same point, post-install on destination hardware, not split across an offline stage and a later verification stage.

### 5.9 Five diagnostic tools

Fixed set, no per-tool opt-out: `lm-sensors`, `nvme-cli`, `smartmontools`, `iperf3`, `ethtool`. Installed noninteractively (`DEBIAN_FRONTEND=noninteractive`) during the destination-hardware first-boot stage (§5.6), not offline (§5.8). No `sensors-detect`, no triggered SMART self-tests — confirmed directly in Investigation 5 (no `sensors3.conf` regenerated, no self-test log entries). `iperf3`'s listener/enabled state is verified once, post-install, on destination hardware — confirmed `disabled`/`inactive` in testing, both immediately after install and after a full reboot. `smartmontools` may already be present as part of Proxmox's own base install (confirmed in testing) — the install step must tolerate that (already-installed is not a failure) rather than assuming a clean slate.

**This section covers installation only.** §5.9a specifies what Baseline actually does with these tools once installed — nothing in the codebase reads their output yet (confirmed 2026-09-22: `baseline/lib/hardware.py` collects only `inxi`; no `sensors`/`nvme`/`smartctl`/`ethtool`/`iperf3` collector exists anywhere, and `provision.sh`'s ad hoc deployment path — used for real-hardware migrations before Milestone 2's first-boot TUI exists — does not install these five packages at all).

### 5.9a Diagnostic tool collectors — capability detection and normalized output

**Governing constraint, unchanged from §2's architectural principle**: the AI harness (`harness.py`) receives zero tool-calling capability (`--tools ""`) and only ever sees a context blob that Baseline's own deterministic code assembled. Adding these five collectors must not create any path — direct or indirect — for the harness to invoke `sensors`, `nvme`, `smartctl`, `ethtool`, or `iperf3` itself. Every collector below is Baseline-side code; the harness only ever reads their already-normalized output, exactly as it does today for `hardware.collect()`/`network.check_lifeline()`.

**Shared shape, reusing this project's established patterns** — not a new architecture:
- Each collector goes through the same `Runner`-injectable subprocess boundary `repair.py` already established (`RealRunner`/`FakeRunner`), so every collector is unit-testable with no real hardware, no real binary, and no root — consistent with this project's whole testing discipline.
- Each collector returns a structured result with an explicit `available: bool` and, when `false`, a `reason` (tool missing, no compatible hardware, permission denied, empty/malformed output) — never raises, never blocks the caller. A missing tool or absent sensor/drive/interface is a normal, expected outcome, not an error condition Baseline surfaces as a failure. `hardware.full_inventory()`'s existing per-item tolerance (an item with no usable fields is simply skipped) is the model to follow.
- Capability *detection* (is the tool present, is compatible hardware present) is always a separate, cheap first step from capability *use* (running the actual query) — matching the functional milestones below, which each name a discovery step before any device-specific query.

**Per-tool collector, in the module now proposed as `baseline/lib/diagnostics.py`** (new; extends the existing `hardware.py`/`network.py` collector family rather than growing either of those files past their current scope):

1. **`lm-sensors`** — `sensors -j` (JSON output; no interactive prompts, no `sensors-detect` ever invoked by Baseline). Normalize to `{available, chips: [{chip, features: [{label, value, unit}]}]}`. `available: false` when the binary is absent or returns empty/no-chips output (a real, common case on VMs and some hardware) — not an error.

2. **`nvme-cli`** — two-stage, matching the milestone exactly: `nvme list -o json` discovers devices first; only paths that command actually returned are ever queried. For each discovered device, `nvme smart-log <path> -o json` (read-only). Normalize to `{available, devices: [{path, model, firmware, health: {temperature, percentage_used, media_errors, ...}}]}`. Zero discovered devices is `available: true, devices: []`, not an error — a host with no NVMe drives is a normal case.

3. **`smartmontools`** — `smartctl --scan-open -j` discovers supported devices first, before any device-specific query (the milestone's explicit ordering). For each, `smartctl -a -j <device>` (read-only: health, temperature, power-on hours, attribute table). **Self-tests (`-t short`/`-t long`) are never invoked by this collector or by any automatic path** — they are a distinct, separate operator-initiated action (own confirmation step, own function, not reachable from the passive collector), matching the milestone's "self-tests require explicit operator initiation" exactly.

4. **`ethtool`** — never assumes an interface name. Reuses `network.list_interfaces()` / `network._physical_nics()` (already existing, already the project's canonical interface-discovery source — not reimplemented) to get the candidate list, then runs `ethtool <iface>` per discovered physical interface (link speed, duplex, auto-negotiation — read-only query only; `ethtool -s` or any settings-changing flag is structurally never exposed here). Normalize to `{available, interfaces: [{name, link_detected, speed, duplex, autoneg}]}`.

5. **`iperf3`** — structurally different from the other four: an *active* network test with real side effects (opens a listening socket, generates test traffic against an explicitly chosen peer), not a passive read. It is **not** part of the passive context blob `_context_blob()` assembles, and is never triggered automatically by any collector, first-boot step, or harness turn. It is a distinct, explicitly operator-confirmed action — both endpoints (which side is server, which is client, and the peer address) chosen by the operator, gated the same way §5.10's firewall apply and `repair.py`'s network changes are gated (explicit confirmation before the action, not inferred from context). Matches the milestone's "operator-authorized client/server test using explicitly selected endpoints" precisely — Baseline never guesses a peer or self-initiates a listener.

**Failure/absence is not a degraded mode to special-case** — a fresh VM with no NVMe drive, no hardware sensors, and a single virtio NIC is the *common* case in this project's own QEMU-based testing, and every collector above must produce a clean, complete, `available: false`-where-appropriate result against exactly that environment, not just against fully-populated real hardware. Unit tests (`FakeRunner`-scripted, per the pattern in `tests/unit/`) must cover both the populated and the absent/missing-tool case for each collector.

**Sequencing**: this belongs to Milestone 2 (destination-hardware first-boot TUI), after §5.9's package install and after target-bound network verification succeeds (§9's existing re-ordering note) — not Milestone 1, and not the ad hoc `provision.sh` path used for real-hardware migrations before Milestone 2 exists in code.

### 5.10 Proxmox web UI firewall — transactional, rollback-protected

A malformed firewall policy can cut off the very access being used to verify it. Firewall application follows the same shape as a network-config change, not a fire-and-forget rule push:

1. Preserve the current rule set (so it can be restored verbatim).
2. Validate the proposed IPv4 and IPv6 policy against the schema of the **detected, installed Proxmox version's actual firewall engine** — not a hardcoded assumption about which engine/version is present.
3. Show the complete proposed policy on tty1, as part of the §5.6 destination-hardware confirmation step — every rule, every interface, both address families, not just the allowed-subnet line.
4. Arm an independent rollback timer before applying.
5. Apply.
6. Verify allowed LAN access to :8006 **and** every locally-required service (see traffic account below).
7. Cancel the rollback timer only on verified success.
8. If verification fails or the timer expires first, restore the preserved rule set automatically.

**Traffic account** — the policy is built to keep the host actually functional as a standalone Proxmox node, not just to open :8006:
- DHCP client traffic
- DNS
- IPv6 neighbor discovery and router advertisements
- ICMP/ICMPv6 required for correct IPv6 operation
- Loopback
- Established/related traffic
- SSH, if enabled
- Baseline's own local communication needs
- Only the Proxmox services actually required for **standalone** operation

**Cluster traffic is not pre-opened "for the future."** This installer targets a standalone host; enabling cluster membership is a later, separate policy transition with its own review, not bundled into initial setup.

What the tool claims after this process, worded precisely: **"allowed from the confirmed subnet, denied by host policy elsewhere."** Not "globally unreachable" — no external-vantage-point probe exists in this design to back that stronger claim.

### 5.11 SSH preconfiguration

Unchanged in substance from prior revision: independent of handoff restore; GUI offers public-key import and a password-auth toggle (default disabled once a key is present); if handoff public keys are also selected, handoff keys apply first, GUI-entered keys append, never silently overwrite. SSH host/user private keys are handled under §5.12's tiered model, not here. Application of this configuration happens at the destination-hardware TUI stage (§5.6) like every other consequential action.

### 5.12 Tether preconfiguration

Unchanged in substance: offline staging records intent only (interface alias if known from a handoff packet, preferred-vs-fallback choice); the real interface only exists once the real USB device is present on the real machine, so application and validation happen at the destination-hardware TUI stage. Implementation target (systemd-networkd vs. `/etc/network/interfaces.d/`) must be confirmed against what `boot/provision.sh` actually assumes elsewhere in this repo before implementation.

### 5.13 Handoff packet restore — tiered trust, transactional application

Trust tiers unchanged from prior revision:

| Category | Default |
|---|---|
| Baseline configuration | Selectable, on by default |
| Baseline non-secret state | Selectable, on by default |
| Authorized public keys | Selectable, on by default |
| SSH host private keys | **Off** — exceptional-continuity case, second explicit warning |
| Root/user private keys | **Off** — strongly discouraged, second explicit warning |
| Machine identity (`/etc/machine-id`, hostname) | **Never restored automatically** |

Duplicate-host-identity risk from restoring shared host keys is stated explicitly in the second warning.

**Application model corrected.** "Validate all before applying any" prevents validation-time partial changes; it does **not** protect against power loss, filesystem failure, a permission-setting failure, or a later category failing after an earlier one already committed. Restoration is therefore a transaction with a durable journal, not a claim of atomicity across unrelated filesystems and services:

1. Validate all inputs (integrity, schema version, Proxmox-major-version, path-traversal/symlink checks, size/decompression-bomb limits).
2. Back up every destination path that may change.
3. Stage replacement files on the destination filesystem (same filesystem as the eventual target, so the next step can be atomic).
4. Apply each category through atomic rename where the filesystem supports it.
5. Record each completed transition in a durable, on-disk journal as it completes — not only at the end.
6. If a later category fails, roll back every already-completed transition using the journal, in reverse order.
7. Independently verify the post-rollback (or post-success) state matches what was intended — file contents, ownership, and mode, not just presence.
8. If complete rollback cannot be proven (e.g. a backup itself failed to restore), report **`partial_state_requires_attention`** and stop — never silently present a mixed state as either "succeeded" or "cleanly failed."

Additional integrity requirements: authenticated packet integrity (AEAD or a signed manifest hash, not just "decrypts"); schema-version compatibility independent of the Proxmox-major-version check; size/extraction limits; path-traversal and symlink protection on every extracted entry before it touches the filesystem; exact ownership/mode validation on restored files. For SSH host-key restoration specifically, validate the **private key, the matching public key, and the containing directory's permissions** as three separate checks — not `600 root:root` on the private key file alone.

Application of selected categories happens at the destination-hardware TUI stage for anything from the private-key tier (per §5.6); non-secret categories may apply during offline staging since they carry no equivalent real-hardware dependency, but still go through the same journaled/transactional mechanism above.

### 5.14 Prepared ISO — treated as sensitive material

See §7.1.

### 5.15 "Show me the script" (extends v1)

Covers every action from Phase 1 through the destination-hardware TUI stage. Output is a redacted execution plan / configuration diff, never a secret-bearing command line, per §7.

## 6. Technical-eligibility gate (Milestone 3 physical-drive gate)

Renamed from "disposability proof" — the tool proves technical facts, not the user's intent toward the drive's contents. A physical drive becomes eligible for destructive installation only once, in sequence:

1. Stable identity resolved with a real serial/WWN (§5.1) — no serial/WWN, no eligibility, regardless of other checks.
2. Technical eligibility state computed (§5.3): must be `no_detected_signatures` or `recognized_existing_data`; `ambiguous_or_unreadable` and `active_or_ineligible` are never eligible.
3. Full storage-ancestry exclusion passes (§5.2) with no ambiguity.
4. Exclusive-access mechanism from §5.1a engaged and continuously re-verified.
5. **Explicit user attestation**, worded to state what it actually is — the user's own judgment that this drive's contents may be destroyed, not a system-generated "disposable" verdict. Erase-phrase confirmation naming the stable identity, e.g. "ERASE Samsung T7 1TB ending 4C21."
6. Helper re-discovers and re-validates identity/capacity/ancestry one last time inside the privileged context, immediately before the write begins.

Any failure at any step aborts with no partial action. A device that reaches step 6 and is then interrupted (USB disconnect, power loss, crash) is reported as **indeterminate**, not "aborted cleanly" — see §8.5.

## 7. Security requirements

- No hardcoded secrets. Passwords/passphrases never placed on any command line (visible via process listings). They cross the `pkexec` boundary via stdin or an inherited file descriptor, or a root-only `tmpfs` file at `0600`, created immediately before use and unlinked on every exit path (success/failure/signal/cancel), only if the answer-file mechanism requires a path (§7.1 — confirm this against the actual schema, don't assume).
- All GUI/TUI inputs validated against an explicit allow-list before interpolation into any shell command or config file.
- Helper subcommands take fixed, schema-validated argument shapes — never a free-form string executed as-is (§5.4's surface test extends this to a static guarantee, not just a runtime check).
- Firewall rule generation is unit-tested against the **actual generated configuration format** for the detected Proxmox firewall engine — not merely asserted to lack the string `0.0.0.0/0`, which would pass a rule that's broken in some other way.
- Handoff failures fail closed per §5.13's transactional model, including the explicit `partial_state_requires_attention` outcome when full recovery can't be proven.
- Error messages / "show details" panels never leak passphrase or password values, including in stack traces and crash output.

### 7.1 The prepared answer-file ISO is itself sensitive

Even if the temporary answer-file/secret-delivery mechanism above is handled correctly, the **prepared unattended-install ISO** that `proxmox-auto-install-assistant prepare-iso` produces may embed the answer file, and therefore potentially embed password material, inside the ISO itself. **All five questions below are now resolved, with direct evidence, by Milestone 0 Investigation 2** (see [decision-records/02-answer-file-secrets.md](decision-records/02-answer-file-secrets.md)):

- ~~Does the answer-file schema accept a pre-hashed password, or does it require plaintext?~~ **Resolved**: `root-password-hashed` is a real, accepted, mutually-exclusive alternative to plaintext `root-password`, confirmed via `validate-answer`. The tool performs **no format validation** on the hash — MD5, bcrypt-shaped, and arbitrary non-hash strings all pass equally — so Baseline's own hash generator is the sole guarantor of hash quality.
- ~~What exactly ends up embedded in the prepared ISO?~~ **Resolved**: in `--fetch-from iso` mode, the full answer file including the password hash is embedded in fully recoverable plaintext, confirmed by both `inspect-iso` and a raw byte search. **`--fetch-from http` mode embeds no answer content at all** — confirmed by raw byte search finding zero matches — and is the accepted design direction (§5.6/Investigation 3), with the caveat that `--answer-auth-token`, if used, is itself embedded recoverably in the ISO regardless of fetch mode; Baseline's design does not use that token for anything security-relevant.
- ~~Does the prepared ISO constitute reusable authentication material if someone else obtains it?~~ **Resolved, yes for `--fetch-from iso` mode**: anyone who obtains such a prepared ISO has the root password hash, full stop, demonstrated directly. This is direct, concrete confirmation of this section's original concern, and is the reason `--fetch-from http` (with a Baseline-owned, single-use, TTL-bounded, hardware-fact-checked answer server) is the accepted design, not embedded-ISO mode.
- ~~Where is the prepared ISO stored, for how long, and is it safe to reuse across multiple installs?~~ **Resolved, not safe to reuse**: confirmed directly — a prepared ISO whose embedded answer-server URL pointed at an already-exited server produced `Connection refused`; more generally, a fixed one-time credential means a prepared ISO must be treated as single-use and deleted after its one intended install.
- ~~What is the cleanup behavior after a crash or reboot mid-process?~~ **Resolved, and this is real, not hypothetical**: a `prepare-iso` run that fails partway through (tested directly via an unwritable output path) leaves a complete, credential-bearing, ISO-sized `.tmp` file in the staging directory with **no automatic cleanup by the tool itself** — confirmed via direct byte search finding the password-hash canary in the leftover file. Milestone 1's tooling must own this cleanup itself on every exit path (a defensive wrapper around `prepare-iso` that never trusts its exit code — see §5.5 — and force-removes and re-verifies emptiness of the staging directory was built and tested in Investigation 3, confirmed to remove exactly this kind of leftover file).

If plaintext embedding turns out to be unavoidable given the tool's actual schema, the design uses a **generated one-time credential**, not the user's real intended password, and **requires rotation on first boot** before the destination-hardware TUI stage is considered complete — confirmed structurally enforceable, not race-prone: the answer file's `[first-boot] ordering = "before-network"` setting runs the rotation script before any network device is configured at all, so there is no possible window for remote authentication to race the rotation. Deleting the ISO from SSD storage afterward is described as *deletion*, not *secure erasure* — SSD wear-leveling means the underlying flash cells aren't reliably overwritten by a simple unlink, and this document does not claim otherwise.

## 8. Testing strategy (TDD)

Per the project's testing rules: 80% minimum coverage, unit + integration + e2e, red-green-refactor, AAA structure.

### 8.1 Unit tests (Python, `pytest`, `FakeRunner` pattern from `tests/unit/inventory_tests/`)

`tests/unit/drive_setup_tests/`:
- `test_answer_file.py` — TOML structure from a form dict; rejects invalid hostname/password before the validator exists.
- `test_firewall_rule.py` — generated rule set exercised against the **actual target config format**, not string-absence checks alone; never emits `0.0.0.0/0`/`::/0`; covers IPv4+IPv6, multiple interfaces, established/related, loopback, DHCP/DNS/ICMPv6-ND passthrough; malformed/oversized subnet input raises; cluster-traffic rules are never present by default.
- `test_storage_ancestry.py` — root-on-plain-partition, root-on-LVM, root-on-LUKS-on-LVM, root-on-MD-RAID, root-on-ZFS-pool-member all resolve to full ancestor exclusion via sysfs `holders`/`slaves` walking (not just an `lsblk` column mock); unresolvable relationship excludes rather than warns.
- `test_eligibility_states.py` — every recognized signature type maps to `recognized_existing_data`; zero-signature/zero-partition/zero-holder/zero-mount maps to `no_detected_signatures` (and the test asserts this state is never rendered to the user as "blank" or "safe"); read errors/partial signatures map to `ambiguous_or_unreadable`; mounted/held/no-stable-identity maps to `active_or_ineligible` regardless of signature state.
- `test_stable_identity.py` — same model+capacity but different serial is rejected; a device with no serial/WWN is rejected regardless of `by-path` resolution; a `by-id` path resolving to a different device than at selection time is rejected.
- `test_backend_surface.py` — enumerates the helper's full argument schema and asserts, statically, that no accepted shape can resolve to a block-device path pre-Milestone-3 (the structural-absence guarantee from §5.4).
- `test_handoff_transaction.py` — against `FakeRunner`/temp dir: wrong passphrase raises; manifest/schema mismatch raises; path-traversal/symlink entries rejected before touching the filesystem; decompression-bomb-sized archive rejected; a simulated failure in category 2 of 3 triggers rollback of category 1 via the journal, and post-rollback state is independently re-verified; a simulated rollback failure produces `partial_state_requires_attention`, not a false "success" or "clean failure."
- `test_ssh_key_ordering.py` — merged `authorized_keys` preserves handoff keys first, appends new ones, no duplicates.
- `test_ssh_host_key_restore.py` — validates private key, matching public key, and directory permissions as three independent checks.
- `test_secret_handling.py` — no code path places a password/passphrase into a subprocess `argv` list; tmpfs secret file unlinked on every exit path including simulated exception/signal; prepared-ISO content is inspected in a fixture to confirm no unexpected plaintext credential ends up embedded beyond what §7.1's findings say is unavoidable.
- `test_setup_intent_handoff.py` — the signed bundle the installer GUI produces for the destination-hardware TUI round-trips correctly and is rejected if tampered, malformed, expired, target-mismatched, replayed, or of an unrecognized schema (per §5.6's integrity/authentication distinction — see decision record 09's prototype in `experiments/m0-inv9/` as the reference implementation shape).

Example (AAA):
```python
def test_eligibility_no_signatures_is_not_labeled_blank():
    # Arrange
    device = FakeBlockDevice(partition_table=None, filesystems=[], raid_members=[])

    # Act
    state = classify_eligibility(device)

    # Assert
    assert state == EligibilityState.NO_DETECTED_SIGNATURES
    assert "blank" not in render_eligibility_label(state).lower()
    assert "safe" not in render_eligibility_label(state).lower()

def test_handoff_partial_failure_reports_requires_attention():
    # Arrange
    journal = FakeJournal()
    categories = [ok_category("baseline-config"), ok_category("public-keys"),
                  failing_category("ssh-host-keys")]

    # Act
    result = apply_handoff_transaction(categories, journal)

    # Assert
    assert result.outcome in (Outcome.SUCCESS, Outcome.PARTIAL_STATE_REQUIRES_ATTENTION)
    if result.outcome is Outcome.PARTIAL_STATE_REQUIRES_ATTENTION:
        assert journal.rollback_attempted_for(["baseline-config", "public-keys"])
```

### 8.2 Unit tests (bash helper, `bats`)
- Stable-identity re-discovery rejects a mismatched serial/capacity immediately before the destructive call.
- Every subcommand rejects a missing/malformed positional arg with no partial side effect before validation completes.
- Block-device-shaped argument is rejected by type-check before any other logic runs (pre-Milestone-3 build).
- Exclusive-access acquisition failure (per whatever §5.1a's Milestone-0 research settles on) aborts cleanly and restores any automount inhibition.

### 8.3 Integration tests
- Full Phase 1 against a throwaway sparse image: answer-file generation → unattended install → static verification → QEMU boot test.
- Offline staging against the resulting image: Baseline, first-boot unit, and setup-intent bundle copied — no package installation attempted at this stage (§5.8).
- Destination-hardware TUI stage, run inside a QEMU VM as a proof exercise (explicitly not claimed equivalent to real hardware): tty1 presents discovered facts and proposed actions, confirmation gate blocks application until acknowledged, tty2 remains responsive throughout, firewall apply/verify/rollback-timer sequence exercised in both the success and induced-failure directions.
- Interrupted-run recovery: kill mid-install, mid-staging, mid-first-boot, and mid-handoff-transaction; assert each resumes only via fresh, explicit authorization, and that a mid-handoff-transaction kill produces either a verified rollback or `partial_state_requires_attention` — never a silent success.

### 8.4 E2E (GUI + TUI)
- Installer GUI: controller/model layer tested directly via `pytest`, plus one `Xvfb` smoke test confirming "Authorize & Build" enables only after the exact erase-phrase naming the stable identity is typed.
- Destination TUI: since this runs on Baseline's existing tty1 infrastructure, extend whatever test harness already covers Baseline's Textual TUI (per `07eda93`/`610fff2` in this repo's history) rather than building a separate one — confirm this reuse is feasible during Milestone 0 rather than assuming it.

### 8.5 Additional cases from review
- Device path changes between GUI selection and authorization — caught by stable-identity re-discovery.
- Same model/capacity, different serial — rejected.
- **USB disconnect after the first destructive write begins**: not describable as "aborts." Specify bounded-time process termination (the destructive worker is killed with a timeout if it doesn't exit on its own) and the target is reported **indeterminate**, matching §5.5's failure contract — never silently treated as cleanly stopped.
- Automount interference: exercised as an active-mitigation test, not assumed prevented by a holder check alone — a test that spins up a fake automount event mid-operation and asserts the operation detects and aborts, given whatever mechanism §5.1a's research settles on.
- Cancellation before vs. after the first destructive write — both leave the tool in the "may have been modified"/indeterminate state.
- QEMU crash after partitioning begins — same indeterminate-state contract.
- UEFI install with no portable fallback EFI entry — caught by static verification.
- Multiple active LAN interfaces — firewall rule covers all of them.
- Firewall rollback timer: induced verification failure triggers automatic restore of the preserved rule set within the timer window.

### 8.6 Coverage target
80% minimum across `baseline/lib/handoff.py`, the new storage-ancestry/eligibility/stable-identity/answer-file/firewall-rule/ssh-merge/transaction-journal modules, the destination-TUI controller layer, and the bash helper's validation logic. GUI/TUI widget wiring is exempted from the numeric target (thin by design), covered instead by the smoke tests in §8.4, which supplement but do not replace the model-layer tests.

## 9. Recommended implementation sequence

```mermaid
flowchart TD
    A["Milestone 0: Safety and feasibility spike"] --> B["Milestone 1: Sparse-image installer"]
    B --> C["QEMU boot verification"]
    C --> D["Offline staging"]
    D --> E["Milestone 2: Destination-TUI first-boot agent"]
    E --> F["Milestone 3: Disposable physical drive"]
    F --> G["Milestone 4: Advanced disk preservation (deferred, separate PRD)"]
```

### Milestone 0 — Safety and feasibility spike — **complete, see [milestone-0-plan.md](milestone-0-plan.md)'s ledger**
No physical block-device writes of any kind; no physical-device code path exists to write with (§5.4). All nine investigations closed:
- ~~The exact `proxmox-auto-install-assistant` answer-file format, and specifically whether it accepts a password hash or requires a plaintext path (§7.1).~~ **Resolved** — see [decision-records/02-answer-file-secrets.md](decision-records/02-answer-file-secrets.md).
- ~~What the prepared ISO actually embeds, and the full set of §7.1's questions.~~ **Resolved** — see §7.1 above and decision record 02.
- ~~Secure secret delivery mechanism works end-to-end, including cleanup on every exit path.~~ **Resolved** — see [decision-records/03-sparse-image-install.md](decision-records/03-sparse-image-install.md): defensive wrapper + ephemeral single-use TTL-bounded, hardware-fact-checked answer server, exercised against a real installer client through to a real confirmed install.
- ~~ISO signature/checksum verification.~~ **Resolved** — see decision record 01/02: full GPG-signed `Release` → hash-pinned `Packages` → hash-pinned `.deb` chain, and a GPG-signed `SHA256SUMS.asc` covering the ISO itself.
- ~~Whether `proxmox-auto-install-assistant` runs on this Ubuntu 26.04 development host at all.~~ **Resolved** — see [decision-records/01-assistant-iso-feasibility.md](decision-records/01-assistant-iso-feasibility.md): runs directly, no chroot/nspawn needed.
- ~~QEMU firmware/boot-mode behavior (UEFI NVRAM vs. portable fallback path).~~ **Resolved, scoped** — see [decision-records/04-fresh-nvram-boot.md](decision-records/04-fresh-nvram-boot.md) and §5.7 above: proven across fresh OVMF state, not claimed for arbitrary physical UEFI firmware.
- ~~Complete storage-ancestry detection logic against real LVM/LUKS/RAID/ZFS test fixtures, via sysfs `holders`/`slaves`.~~ **Partially resolved** — see [decision-records/07-storage-ancestry.md](decision-records/07-storage-ancestry.md) and §5.2 above: LVM and ZFS real-validated; MD RAID/LUKS synthetic-only, real validation deferred to Milestone 1.
- ~~The exclusive-access design from §5.1a — this is a required output of Milestone 0, not an assumption carried into it.~~ **Researched, still unresolved** — see [decision-records/08-exclusive-access.md](decision-records/08-exclusive-access.md) and §5.1a above: `flock` and udisks `OpenDevice` confirmed insufficient; real `O_EXCL` enforcement untested; deferred to Milestone 3 real-hardware validation, not solved here.
- ~~The offline-install containment approach from §5.8 (chroot+policy-rc.d vs. systemd-nspawn vs. defer-to-first-boot).~~ **Resolved** — see [decision-records/05-offline-staging-containment.md](decision-records/05-offline-staging-containment.md): `defer-to-first-boot` accepted, verified directly against a disposable overlay of the real installed image; no offline containment mechanism exists in this design.
- ~~Whether Baseline's existing tty1/Textual TUI infrastructure can be reused for the destination-hardware first-boot TUI (§5.6, §8.4), or whether it needs a dedicated first-boot mode.~~ **Resolved** — see [decision-records/06-first-boot-state-machine.md](decision-records/06-first-boot-state-machine.md): a first-boot unit mirroring `boot/baseline.service`'s tty1-ownership pattern (`Conflicts=getty@tty1.service`, `TTYPath=/dev/tty1`) was built and proven to take tty1 correctly, including after a real corrected-and-reverified fix to an authorization-boundary defect found during this investigation.
- ~~Cancellation semantics at every stage.~~ **Partially resolved** — decision record 06 proves interrupted-run recovery (crash mid-transition resumes correctly via a durable journal); broader cancellation semantics at every other stage were not separately exercised and remain Milestone 1 work.
- ~~Prepared-ISO cleanup — confirm nothing with embedded secret material survives a crash.~~ **Resolved, and the answer is "not by the raw tool, requires Baseline's own wrapper"** — see §7.1 above and decision records 02/03.
- **New at closeout, Investigation 9**: setup-intent trust model — see [decision-records/09-setup-intent-trust-model.md](decision-records/09-setup-intent-trust-model.md) and §5.6 above: verification/policy logic proven synthetically (16/16 tests); real key provisioning and the replay-rollback gap (no independent monotonic anchor) are explicitly unresolved, carried into Milestone 1+.

### Milestone 1 — Virtual disk installation
Sparse image files only. Prove: ISO preparation, automated installation, the indeterminate-on-failure contract, static filesystem verification, actual QEMU boot test, first-boot unit + setup-intent bundle staging (file copy only, no package installation — §5.8), logs and redaction.

### Milestone 2 — Destination-hardware first-boot TUI
Run on an actual booted Proxmox VM as a proof exercise for the real thing. Prove: tty1 TUI presents discovered facts and requires confirmation for every consequential action (§5.6), tty2 stays available throughout, firewall transactional apply/verify/rollback-timer (§5.10), SSH/tether application at the confirmation stage, handoff transactional restore including induced-failure rollback and `partial_state_requires_attention` (§5.13), idempotent reruns, first-boot-completion marker preventing automatic re-trigger, five diagnostic tools installed (§5.9) **and** their collectors implemented and exercised (§5.9a) — capability detection, normalized output, graceful degradation on missing tool/hardware, and `iperf3` reachable only as an explicit operator-confirmed action, never from the passive context blob.

### Milestone 3 — Whole disposable physical drive
Only after 0–2 pass, and only by adding the separately-reviewed physical-device helper capability and polkit action from §5.4. Require: stable identity with real serial/WWN, full technical-eligibility gate (§6), the proven exclusive-access mechanism from §5.1a, explicit user attestation (not a system-generated "disposable" verdict), no automatic retries, and a real first-boot-on-destination-hardware pass before the tool declares the overall process complete.

### Milestone 4 — Non-disposable or shared drive
Explicitly deferred. Needs its own risk model and likely a separate installer mode.

## 10. Acceptance criteria

- No code path can express a block-device target before Milestone 3; enforced structurally (§5.4, §8.1's `test_backend_surface.py`), not by convention or a runtime flag.
- A user targeting the currently-running OS's storage — at any depth of LVM/LUKS/RAID/ZFS — cannot select it.
- Every destructive action requires: real serial/WWN identity, a technical-eligibility state that isn't `ambiguous_or_unreadable`/`active_or_ineligible`, the proven exclusive-access mechanism engaged, and an explicit user attestation typed as an erase phrase naming the stable identity.
- No tool output ever labels a drive "blank," "safe," or "disposable" as a system-generated verdict — only the technical states from §5.3, with attestation kept visibly separate as the user's own judgment.
- A failed or interrupted destructive operation is always reported as indeterminate, never as cleanly aborted, and never retries without fresh explicit authorization.
- Every consequential real-world decision (network, firewall, tether, handoff restore) is confirmed on the destination-hardware TUI before being applied — none of them are ever applied by unattended first-boot code without that confirmation.
- Firewall application is transactional: preserved ruleset, rollback timer armed before apply, automatic restore on verification failure.
- Handoff restoration is transactional with a durable journal; a partial failure is reported as `partial_state_requires_attention`, never silently merged into success or failure.
- SSH host keys and private keys are never restored without an explicit, separately-worded second confirmation.
- No secret value ever appears in a command-line argument, environment dump, log, or crash report; the prepared ISO's secret content is accounted for per §7.1.
- Every privileged action is inspectable via "show me the script" before it runs.
- All new logic in §8.1–8.3 has tests written first and passing, at ≥80% coverage on the modules listed in §8.6.

## 11. Open risks / explicit unknowns — Milestone 0 status (closed out 2026-09-21)

- ~~Whether `proxmox-auto-install-assistant` is obtainable/runnable on this Ubuntu 26.04 desktop without Docker.~~ **Resolved** — see [decision-records/01-assistant-iso-feasibility.md](decision-records/01-assistant-iso-feasibility.md): confirmed host is Ubuntu 26.04.1 LTS; the official `.deb` runs directly against the host's own libraries once extracted, no isolated Debian chroot/nspawn needed.
- **Still open, not investigated at Milestone 0**: whether Proxmox base install omits NetworkManager (assumed for §5.12) — no Milestone 0 investigation targeted this question; confirm against a real installed system before Milestone 2 code depends on the assumption.
- ~~The actual answer-file schema's handling of the root password, and what ends up embedded in the prepared ISO (§7.1).~~ **Fully resolved** — see [decision-records/02-answer-file-secrets.md](decision-records/02-answer-file-secrets.md) and §7.1 above: `root-password-hashed` is real and functional but unvalidated by the tool; `--fetch-from http` embeds no answer content (accepted design); a failed `prepare-iso` leaves a credential-bearing temp file with no automatic cleanup (confirmed, not hypothetical); `before-network` first-boot ordering gives a structural, non-race-prone guarantee for forced credential rotation.
- ~~The exclusive-access design (§5.1a) — genuinely unresolved, not a placeholder.~~ **Researched at Milestone 0, remains genuinely unresolved** — see [decision-records/08-exclusive-access.md](decision-records/08-exclusive-access.md) and §5.1a above. `flock` and udisks `OpenDevice` are confirmed insufficient on their own; real `O_EXCL` enforcement against a physical device was not reachable to test in this environment and stays an open question for Milestone 3, not something this PRD claims is solved.
- ~~The offline-install containment approach (§5.8).~~ **Resolved** — see [decision-records/05-offline-staging-containment.md](decision-records/05-offline-staging-containment.md): `defer-to-first-boot` accepted, verified directly.
- ~~Whether Baseline's existing tty1 TUI infrastructure can host the destination-hardware first-boot flow directly, or needs its own mode.~~ **Resolved** — see [decision-records/06-first-boot-state-machine.md](decision-records/06-first-boot-state-machine.md): direct reuse of the existing tty1-ownership pattern, proven working (after a real authorization-boundary defect was found and corrected in the same investigation).
- **New at closeout**: the setup-intent trust model's actual guarantee (§5.6/[decision-records/09-setup-intent-trust-model.md](decision-records/09-setup-intent-trust-model.md)) — under the current colocated-key deployment shape it is integrity/corruption detection, not authentication; real key provisioning and rollback-resistant replay protection (no independent monotonic anchor exists yet) remain open, carried into Milestone 1+.
- Re-confirm with the user, explicitly, before any Milestone 3 work begins against a real device — the mechanism (pkexec + a separately reviewed helper capability) doesn't change from v1, but the moment itself should be a deliberate go/no-go, not an assumption carried forward from this PRD's approval. **Still applies, unchanged by Milestone 0's closeout** — Milestone 0 explicitly did not touch a physical device at any point across all nine investigations.
