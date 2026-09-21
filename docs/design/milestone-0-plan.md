# Milestone 0 execution plan — feasibility and safety investigation

Status: **complete** — all nine investigations closed 2026-09-21. See §6 (Milestone ledger) below for per-investigation status. Milestone 1 has not started.
Parent: [drive-setup-gui-v2-prd.md](drive-setup-gui-v2-prd.md) §9, §11
Decision records: [decision-records/](decision-records/) (one file per investigation, filled in as each completes)

## 0. What this milestone is and isn't

Milestone 0 is a **feasibility and safety investigation**. It produces evidence and decisions that later milestones depend on. It does **not** implement the production installer, and nothing from it merges into the shipped `.deb` or its polkit actions until the corresponding decision record says the approach is accepted.

## 1. Hard constraints (apply to every investigation below, no exceptions)

- No writes to any physical block device.
- No physical-device argument accepted by any helper code written during this milestone, even experimentally.
- No physical-device polkit action created, even disabled.
- No modification of the current BaselineOS drive (`/dev/sdc`, `/run/media/cane/BaseLine`) or any other currently-mounted/in-use device on this machine.
- All experimentation happens in `experiments/` at the repo root (gitignored — added this revision) using temporary directories, sparse image files, and loop devices created specifically for testing and torn down afterward.
- Loop devices used in testing are created via `losetup` against files under `experiments/`, never against a real block device, and are detached at the end of each experiment run (a cleanup trap, not a manual step someone can forget).
- Incomplete or failed experiments are not merged into `packaging/` or `baseline/lib/` — they live under `experiments/` and, if a branch is used, a clearly-named `experiment/m0-*` branch, never `main`, until a decision record accepts the approach.

## 2. Decision record format

Every investigation below produces one file in `decision-records/`, filled in as work completes:

```markdown
# Decision record: <investigation name>

Date:
Investigator: Claude Code, session <id>

## Evidence collected
(what was actually run, what output/logs were captured — link to saved logs under experiments/ if large)

## Result
(what was actually learned — facts, not aspirations)

## Remaining uncertainty
(what this investigation could NOT establish, explicitly)

## Accepted / rejected approach
(which of the options considered — if any — is recommended for Milestone 1+, and why)

## Security implications
(anything this investigation surfaces that changes §5-§7 of the PRD)

## Tests added
(links to any unit/integration test files created as a byproduct)

## Next milestone unblocked?
Yes / No / Partially — and specifically what still blocks it if not fully yes.
```

Nine stub files are created now (§4) with headers only, filled in as each investigation runs.

## 3. Experiment order

Per your ordering — feasibility-and-secrets first (nothing downstream matters if the installer path doesn't exist or leaks credentials), then the narrowest possible "does an image actually boot" proof, then the surrounding safety machinery, then storage/access research (which can run fully in parallel with everything else since it never touches an installer), then the trust-model consolidation last since it depends on what the setup-intent bundle actually needs to carry once 1–7 are known:

1. **Assistant/ISO feasibility** — `proxmox-auto-install-assistant` source, version, host compatibility.
2. **Answer-file secrets** — schema, hash-vs-plaintext, what the prepared ISO embeds, argv/env/log secret-absence proof.
3. **Sparse-image installation** — first real (non-destructive) install, image-only, helper rejects any non-regular-file target.
4. **Fresh-NVRAM boot verification** — UEFI and legacy BIOS, portable EFI fallback, deterministic boot-success marker, booted in a QEMU invocation that does not reuse the installer's NVRAM state.
5. **Offline staging containment** — chroot+policy-rc.d vs. systemd-nspawn vs. defer-to-first-boot, with evidence, not preference.
6. **First-boot state machine (prototype)** — tty1/tty2 behavior, discovery-before-authorization, interrupted-run recovery, completion marker; firewall step is a fake bounded executor, not a real apply.
7. **Storage ancestry** — sysfs/lsblk/LVM/MD/ZFS relationship discovery against synthetic fixtures; contradictory or unknown results forced to `active_or_ineligible`.
8. **Exclusive-access research** — loop-device-only; competing opens, mounts, simulated automounter interference; no "solved" claim without demonstrated prevention or detection.
9. **Setup-intent trust model consolidation** — done last because it depends on what 1–7 actually established needs protecting; see §5 for the scrutiny this specifically requires.

Investigations 6 and 7 have no dependency on 1–5's outcome and could run concurrently with them if useful, but are sequenced after per your ordering since 6 (first-boot state machine) benefits from having a real bootable image from 3–4 to prototype against, and 7 (storage ancestry) is placed after to keep the record sequential and reviewable rather than because it's blocked.

## 4. Investigation briefs

### 1. Automated installer availability
- Determine the supported source and version of `proxmox-auto-install-assistant` — Proxmox's own package/repo, not a third-party mirror.
- Pin and verify the Proxmox ISO and assistant versions against Proxmox's published checksums (same rigor as the manual ISO download earlier this session — fetch the raw `.sha256`, don't trust a paraphrased checksum).
- Establish whether it runs directly on this Ubuntu 26.04 host or requires an isolated Debian environment (chroot/systemd-nspawn — no Docker, per the standing constraint that this host has no docker group membership).
- **No unreviewed community helper scripts** — if a path exists only through some third party's install script, that's a finding ("no officially-supported path found"), not a workaround to adopt silently.

### 2. Answer-file and credential behavior
- Record the exact supported schema (pull from Proxmox's own docs/source, not inferred from examples).
- Determine whether the root password may be supplied as a hash.
- Inspect a prepared ISO's actual contents (mount read-only, examine) to establish exactly what credential material it embeds.
- Prove — with a test, not an assertion — that no secret appears in `argv` (inspect `/proc/<pid>/cmdline` of the running assistant process), environment dumps, logs, or crash output.
- If plaintext embedding turns out unavoidable, the only thing prototyped here is the one-time-credential-plus-forced-first-boot-rotation path — not a "ship plaintext and hope" fallback.

### 3. Image-only installation
- Prepare an unattended ISO using the findings from #1–#2.
- Install exclusively to a sparse image file under `experiments/`.
- Record installer completion/failure signals and full logs.
- Prove the helper rejects `/dev/*` paths, symlinks resolving to block devices, device nodes (`stat` mode check), and any non-regular-file target — this is where `test_backend_surface.py` from the PRD's §8.1 gets its first real implementation, not just a design intent.

### 4. Firmware and boot portability
- Test UEFI and legacy BIOS as two separate, explicitly-labeled runs.
- Establish whether the resulting disk image contains a portable EFI fallback loader (`/EFI/BOOT/BOOTX64.EFI` or equivalent) independent of the installer's own virtual NVRAM.
- Boot the resulting image in a **fresh QEMU invocation that does not reuse the installer's NVRAM** — this is the actual test of portability; booting with the same NVRAM the installer used would hide exactly the failure mode this step exists to catch.
- Define the deterministic boot-success marker concretely (a specific serial-console string, a guest-agent ping, or equivalent) — this definition is itself a deliverable, reused by every later boot-test in the PRD.

### 5. Offline staging containment
- Compare, with evidence from actual runs: controlled chroot + bind mounts + temporary `policy-rc.d`, `systemd-nspawn`, and defer-to-first-boot.
- Verify — by attempting to trigger one — that package maintainer scripts cannot start services on the Ubuntu host under the chosen approach.
- Confirm package-database consistency after install, and that the first-boot unit stays enabled through whichever containment method is used.
- Recommend exactly one approach, with the comparison evidence in the decision record — not a menu carried forward unresolved.

### 6. First-boot state-machine prototype
- Exercised only inside a QEMU Proxmox installation (built from #3–#4's output).
- Confirm: tty1 ownership by the prototype, tty2 remains a working escape/console throughout, fact-discovery happens before any authorization prompt (never the reverse), an interrupted run recovers correctly on next boot, and a completed run sets a marker that prevents automatic re-trigger.
- **Do not apply a real firewall rule yet.** Use a fake, bounded executor standing in for "apply the firewall policy" so the state-machine transitions (propose → confirm → apply → verify → commit-or-rollback) are proven structurally before §5.10's real transactional firewall logic is built on top of them.

### 7. Storage graph
- Implement and test read-only ancestry discovery (sysfs `holders`/`slaves`, `lsblk`, `pvs`/`vgs`, `dmsetup deps`, `mdadm --detail`) against synthetic loop-backed fixtures: plain partition, LVM, LUKS-on-LVM, MD RAID — built and torn down programmatically, not by hand each time.
- Include ZFS as fixtures if `zfsutils-linux` is available on this host, or document it as a supported-but-unverified path if it isn't — do not skip the finding, state its actual status.
- Document explicitly which relationship each source (sysfs, `lsblk`, LVM tooling, MD tooling, ZFS tooling) actually provides, since the PRD's §5.1a/§5.2 assume sysfs is the ground truth and the others are corroborating.
- Any unknown or contradictory result between sources must resolve to `active_or_ineligible` — this is a testable property (`test_eligibility_states.py` gets a contradictory-sources fixture case here), not just a stated intent.

### 8. Exclusive physical-device access research
- Research and prototype **using loop devices only** — this investigation explicitly does not touch a real physical drive, consistent with §1's hard constraints.
- Determine whether an exclusive open can be retained (e.g. `O_EXCL`, a held file descriptor) and safely passed to QEMU as its backing store without reopening the path later (reopening reintroduces the TOCTOU gap this mechanism exists to close).
- Test, with actual induced scenarios: a competing process opening the same loop device, a competing mount attempt, and a simulated automounter reacting to the device appearing.
- **No "solved" claim** in the decision record unless non-cooperating access is demonstrably prevented (the competing open/mount fails) or at minimum reliably detected (the operation notices and aborts) — "we didn't test a hostile case" is a valid, honestly-stated remaining-uncertainty entry; a false "solved" is not.

### 9. Setup-intent trust model consolidation
Deliberately last, and deliberately scrutinized harder than the others — this is the one genuinely new security mechanism introduced by the PRD, and "signed" is exactly the kind of word that can end up claiming more than its actual mechanism provides (the same failure mode this whole review process exists to catch). The decision record must explicitly answer, not gesture at:

- **What does the signature protect against?** State the actual threat model in one sentence — e.g. "detects accidental corruption/mismatch between the installer GUI's choices and what offline staging applied" versus "defends against a hostile actor with filesystem access" are very different claims, and the record must say which one (if either) this mechanism actually achieves.
- **Signing key lifecycle** — where is the signing key generated, where does it live during the installer GUI's run, is it ephemeral per-run or persistent, and what happens to it after the bundle is produced.
- **Verification-key placement** — where does the destination-hardware first-boot TUI get the key it verifies against. **If the verification key is stored beside the bundle on the same target filesystem, it cannot defend against an attacker capable of rewriting the entire target filesystem** — the record must state this limitation plainly rather than letting "signed" imply a stronger guarantee. If that's the actual deployment shape, the honest framing is "integrity/corruption check," not "authentication."
- **Expiry** — does a bundle have a validity window, and what happens if offline staging and first boot are separated by an unexpectedly long time (drive shelved between builds, matching this project's own handoff-packet use case).
- **Replay protection and one-time consumption** — can the same bundle be reapplied to a second target, and should it be able to; is consumption tracked so a bundle can't be replayed against the same target twice with different results.
- **Schema/version binding** — the bundle declares the PRD-version/schema it was produced under, and the consuming TUI refuses a bundle it doesn't recognize rather than best-effort parsing it.
- **Target-install identity** — the bundle is bound to the specific install it was produced for (e.g. an install-session identifier), so a bundle from one attempt can't be silently applied to an unrelated one.

This decision record should end with a plain restatement of what "signed setup-intent bundle" is allowed to mean in the PRD from this point forward — updating PRD §5.6's language if the actual mechanism turns out to be integrity-only rather than authentication.

## 5. What "returning the plan" means here

This document and the nine stub decision records are the deliverable for this turn. No QEMU install has been run yet. Investigation 1 is the natural next step to actually execute (it's read-only research: confirming the assistant's real source/version and host compatibility) — flag if you'd rather I hold there too, otherwise I'll start on it next.

## 6. Milestone ledger (closeout, 2026-09-21)

All nine investigations complete. Status reflects what was actually demonstrated with evidence — a mixed result (real-tool-validated for one subsystem, synthetic-only for another) is recorded as partial, not rounded up to proven. See each linked decision record for full evidence; this table is a navigation aid, not a substitute for reading them.

| # | Investigation | Status | Note |
|---|---|---|---|
| 1 | [Assistant/ISO feasibility](decision-records/01-assistant-iso-feasibility.md) | **Proven** | Full GPG→hash chain of trust reproduced; assistant runs directly on the host, no chroot/nspawn needed; `prepare-iso --fetch-from http` found as the better default secret-delivery mode. |
| 2 | [Answer-file secrets](decision-records/02-answer-file-secrets.md) | **Proven** | Credential contract, exit-code untrustworthiness, and the answer-server design (pinned HTTPS + Baseline-owned TTL/single-use/hardware-fact binding) were all confirmed directly, including against a real installer client's real usage in Investigation 3. |
| 3 | [Sparse-image installation](decision-records/03-sparse-image-install.md) | **Proven** | `install_success_confirmed` on the corrected rerun, installer's own `'ok'`/100% completion sequence captured directly. Includes an honest self-correction: the original run was reclassified from an unsupported "success" claim to `install_outcome_indeterminate` before the corrected rerun. |
| 4 | [Fresh-NVRAM boot](decision-records/04-fresh-nvram-boot.md) | **Proven, explicitly scoped** | Legacy-BIOS reboot-to-disk and fresh-UEFI-NVRAM boot both reached a real login prompt. Proves portability across fresh OVMF state only, not universal physical-hardware UEFI compatibility — stated as such, not implied further. Found and fixed a real installer-media-reboot-loop defect (`once=d` now mandatory). |
| 5 | [Offline staging containment](decision-records/05-offline-staging-containment.md) | **Proven** | `defer-to-first-boot` verified directly against a disposable overlay of the real installed image — listening sockets, `dpkg --audit`, and `iperf3` disabled-state all confirmed before/after a real reboot. |
| 6 | [First-boot state machine](decision-records/06-first-boot-state-machine.md) | **Proven, after correction** | tty1 ownership, interrupted-run recovery under real `SIGKILL`, and completion-marker behavior all proven — but only after a real authorization-boundary defect (a `time.sleep(2)` auto-confirm) was caught, fixed, and the full test redone on a fresh run. |
| 7 | [Storage ancestry](decision-records/07-storage-ancestry.md) | **Partially proven** | 12/12 synthetic tests pass for every required fixture shape. Real-tool validation confirmed for LVM and ZFS (the ZFS sysfs-blindness finding is genuinely load-bearing). MD RAID and LUKS-on-LVM remain synthetic-only — `mdadm`/`cryptsetup` were absent from the test image — real validation deferred to Milestone 1. |
| 8 | [Exclusive physical-device access](decision-records/08-exclusive-access.md) | **Deferred to Milestone 3** | `flock` confirmed advisory (does not stop a non-cooperating process); udisks `OpenDevice` confirmed to provide no exclusivity. Real kernel `O_EXCL` enforcement against a whole block device could not be reached for testing on this host — genuinely unresolved, not claimed solved. A working FD-passing mechanism for QEMU (`-add-fd`+`host_device`/`fdset`) was proven as a reusable building block regardless of which exclusivity mechanism Milestone 3 ultimately uses. The investigation was also stopped short of two of its six planned checks (contention-while-held, disconnect-detection) at explicit user instruction to stop triggering interactive authorization dialogs — reported as not completed, not filled in with an inferred result. |
| 9 | [Setup-intent trust model](decision-records/09-setup-intent-trust-model.md) | **Partially proven** | Canonical serialization, strict duplicate-key rejection, Ed25519 signature verification, and a durable existence-based consumed-intent ledger are all proven via 16/16 synthetic tests. Two things remain explicitly unresolved and carried into Milestone 1+: real key-provisioning/rotation plumbing was not implemented (only a shape recommended), and replay protection cannot survive a combined rollback of both the ledger and the intent to an earlier snapshot without an independent monotonic trust anchor, which does not exist in the current design (see the record's Addendum). |

**Overall**: 6 of 9 fully proven, 2 partially proven (storage ancestry, setup-intent trust model — both have a real, working core with an explicitly scoped gap), 1 deferred to Milestone 3 (exclusive access — no enforcement mechanism was validated, by design and by instruction, since that requires real privilege this milestone was barred from using). Nothing was rejected outright; nothing is marked proven without decision-record evidence backing it.
