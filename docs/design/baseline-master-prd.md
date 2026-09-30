# PRD: BaselineOS - master document (purpose, design, recipe, workplace)

Status: **proposal for operator review.** Consolidates every existing Baseline PRD, plan and decision record plus the 2026-09-30 hardened-appliance work. It does not replace them: where it disagrees with an accepted decision record, the record wins until a new record supersedes it (AGENTS.md governance order). Nothing in this document has been applied to real hardware.

Sources read for this pass: `AGENTS.md`, `README.md`, `docs/INSTALL.md`, `docs/SESSION_HANDOFF.md` (head and drive history), `docs/adr/0001`, `docs/design/testpersistence-prd.md`, `drive-setup-gui-v2-prd.md`, `hardened-appliance-prd.md`, both work queues, the audit of 2026-09-30, and decision records 46-47, 76, 79, 81, 83, 85-86, 89, 98-99 in full or in part, plus all 116 record titles. Claims below about older work are taken from those records; they are marked *(record)* and were not re-verified by running anything. Each record states its own unit-vs-real-hardware status; this PRD does not upgrade any of them.

## 1. Purpose (the paragraph a future session must not lose)

BaselineOS turns one machine into an operator-controlled **Proxmox-substrate appliance** whose state is separated by lifetime, whose configuration lives in registries the operator edits by selection (never by typing serials or paths), and which can **produce a working copy of itself on another drive from a recipe rather than by cloning bytes**. The substrate is disposable and rebuildable; the operator's data, credentials and configuration survive it, live on named volumes with fixed roles, and are never put at risk by a rebuild or by another persona's account. Every destructive action on real hardware goes through tested code that re-verifies the target by serial immediately before writing.

If a change does not serve that paragraph, it needs a decision record explaining why.

## 2. Standing principles (extracted; each cites where the operator stated it)

1. **Detection narrows what exists, never which mode** (GPU modes, `gpu_admin`, record 94). Operator chooses.
2. **Selectable, never typed.** No serial, path or passphrase is asked for by keyboard where the system can offer options; `SettingDef.options` is enforced (record 86).
3. **Configuration lives in User Persistence / registries**; nothing configuration-wise outside them must survive reboot (record 86).
4. **No ad hoc destructive commands.** Every destructive helper takes the dict from `physical_device_safety.validate_target_device`, never a bare path; built and tested first, then run (record 49, AGENTS.md).
5. **Kernel letters are never identity.** Re-resolve by serial every time (AGENTS.md; audit A1).
6. **Self-install is the default path**; plain "Install" is a human override only (record 86).
7. **Substrate is disposable; change is not a reason to reinstall** (memory `qcow2_overlay_vs_disposable_substrate`; record 99).
8. **TDD, RED first**; "unit-tested against fakes" and "verified on real hardware" are different claims and must be stated separately (AGENTS.md).
9. **No placeholders presented as real**; explicit "not implemented / not verified" is preferred (AGENTS.md).
10. **One registry mechanism**, three generic tables, GLOBAL vs PROTECTED scope; no bespoke table per registry type (record 89).
11. **Credentials are fresh, one-time, unassociated with the operator** and never stored or typed by an agent (AGENTS.md).
12. **Privilege is checked, not assumed.** Check device-file permissions and group membership before concluding a real action is blocked; if blocked, give the operator the exact command, never route around (AGENTS.md). *Correction recorded 2026-09-30: an agent told the operator "needs root" for raw partitioning that the `disk` group already allowed. LVM genuinely needs root here; raw device writes do not.*

## 3. Storage model (authoritative: testpersistence-prd §3/§3a, records 46-47, 68, 73, 76, 98)

Volumes on one drive, defined in `baseline/lib/drive_installer.py` (the single source; this table restates it):

| Volume | Class | Size range | Mount options | Holds |
|---|---|---|---|---|
| `BASELINE` | 1 substrate / app state | 5-50 GB | `nosuid,nodev` | app, VM, LXC state; never daily-driver data, never installer cache |
| `INSTALLER_CACHE` | 0 | 50-200 GB | `nosuid,nodev,noexec` | vanilla ISOs, packages, backups (`isos/`, `seed/`, `backups/`, `encrypted_backups/`, `backup_manifests/`); never customized |
| `SESSION_TEMP` | 6-ish | 5-50 GB | `nosuid,nodev,noexec` | staging/quarantine; nothing promoted without a decision |
| `SUBSTRATE_PERSISTENCE` | 2 | 1 GB fixed | `nosuid,nodev,noexec` | recovery + substrate config, encrypted admin passphrase |
| `USER_PERSISTENCE_<PERSONA>` | 2-5 | 50-200 GB each | `nosuid,nodev` | one isolated volume per persona (default `admin` = root-like, `personal` = daily driver) |

Sizing: `compute_adaptive_plan` (min first, cap at max, real space wins between). For a 512 GB drive: 31 / 136 / 31 / 1 / 136 / 136 GB.

Two physical forms exist and both must stay supported: **LVM logical volumes inside Proxmox's `pve` VG** on the install drive (`drive_installer`), and **plain GPT partitions named for the volume** on a carrier drive (record 46, `carrier_layout.py`, 2026-09-30). Identity on a carrier is the GPT partition name; ext4 labels are truncated to 16 characters and collide for the two persona volumes (known defect, §10).

## 4. Capability inventory (what already exists)

Status wording follows each record. "Unit" = tested against fakes; "QEMU" = run under QEMU; "Real" = exercised on physical hardware. Test suite at 2026-09-30: 1624 collected, 3 failing on other sessions' uncommitted web edits (audit E).

| Area | Capability | Key modules / records | Status per record |
|---|---|---|---|
| Install | Unattended Proxmox install via answer file over HTTPS (never `--fetch-from iso`); assistant ISO; ISO remaster carrying this repo | `drive_setup_*`, `iso_builder`, `self_installer`; 01-02, 19-21, 60, 68 | QEMU proven end to end (60, 93); not run on a physical target from the web action (85) |
| Install | Self-installer as default keyboard-free path, settings from registry presets | `self_installer`, `settings_store`, `drive_admin`; 85, 86, 99 | Unit + QEMU; real launch not verified (85) |
| Install | QEMU guest/answer-server fixes (net, serial shadowing, stale processes, boot order) | 106-116 | Fixed, QEMU |
| First boot | State machine, tty1 ownership, offline staging, additive DHCP repair, bridge repair | `firstboot_*`, `repair`, `ifnet_config`, `topology`; 06, 12, 14, 25-26; ADR 0001 | QEMU + real V0.1 bare-metal test (ADR 0001) |
| Network | Staged diagnostics NIC->LLM provider; tether fallback | `network`; changelog/network | Real (V0.1); tether path untested on real USB |
| Storage | Volume set, adaptive sizing, per-mount options, telemetry | `drive_installer`; 46, 68, 71, 73, 98 | Unit; 98: real machine had too little free space for the new minimums |
| Storage | Physical device safety gate; serial/size/boot-device checks | `physical_device_safety`; 49 | Unit + used live 2026-09-30 |
| Persistence | Multi-persona volumes, admin elevation, persist bind mounts, scripts inbox | `persistence_pool`, `admin_elevation`, `persist_*`; 62, 63, 69, 70, 75, 76, 78 | Unit; crypto mechanics live with openssl (76) |
| Backup/Recovery | 24 h backup-freshness gate, recurring encrypted backup, recovery mode + tiers; USB recovery withdrawn | `backup_restore`, `backup_recurring`, `recovery_mode`, `recovery_tiers`; 74, 77, 79, 81 | Unit; 79: does not yet target a separate physical device |
| Control plane | Registry (GLOBAL/PROTECTED), settings store (SQLite, per-group), dependencies table, health check | `registry`, `settings_store`, `dependencies`; 87-95 | Unit + QEMU smoke (93) + real `/etc/baseline` (92) |
| Control plane | Configurator pipeline, control panel, admin tab, differences page, telemetry cadence | `config_pipeline`, `control_panel_web`, `settings_web`, `baseline_web`; 50-55, 64, 65, 72, 80, 83 | Unit; web app run live (83) |
| Drive admin | Self-installer-only model, per-drive Baseline detection/repair, hardware tab | `drive_admin`, `hardware`; 83, 99 | Unit + live browser (99); "update selected" logic is a placeholder |
| Harness | Read-only harness, chat tab (warm session, streaming), ACP adapters, write-scope grant, status bar | `harness*`, `acp_*`, `providers`; 31-44 | Unit; real Claude subscription in V0.1 |
| Workloads | VM/LXC/Docker provisioning, pinned community scripts, Podman Quadlet, GPU admin + device wiring, HA/HAOS under QEMU | `vm_provision`, `vm_scripts`, `quadlet`, `gpu_admin`; 34-36, 57-59, 61, 66, 94, 96, 97 | Unit + QEMU; not real hardware |
| Hardened appliance (new) | layer digests + PCR extend; Caddyfile renderer; registry-backed routes; host readiness report; carrier layout | `measured_boot`, `gateway_config`, `gateway_routes`, `host_readiness`, `carrier_layout` | Unit only; `host_readiness` and `carrier_layout` were also run on the dev machine 2026-09-30 |

## 5. New and folded-in requirements

### N1. Recipe-driven self-replication (the drive copies its design, not its bytes)

A drive must be able to produce a working, correctly-laid-out drive on another device **without `dd`, image cloning or block copy**. Definition of *cloning* for this PRD: copying bytes of a drive or volume so the copy inherits identity, secrets or persona data. Definition of *replication*: re-running the recipe against a new, validated target.

- N1.1 **Recipe** = a canonical manifest of everything needed to rebuild the drive's *structure and software*: the volume set and sizes (from `drive_installer`), mount options, the pinned source artifacts (Proxmox ISO and assistant, each by URL + sha256), the repo commit and file manifest that get baked into the ISO, the selected `settings_store` presets, and the list of registry entries of GLOBAL scope that define the layout (e.g. gateway routes).
- N1.2 **Recipe digest.** The recipe is exported as canonical JSON and hashed with `measured_boot.layer_digest("recipe", ...)`. Two drives built from the same recipe carry the same digest; any change is visible. The digest, not the bytes, is the equality test.
- N1.3 **Replication pipeline** reuses the existing stages in order: `physical_device_safety.validate_target_device` -> `drive_setup_acquire` -> `drive_setup_answer` (HTTP answer, one-time credential) -> `iso_builder` -> `drive_setup_install` -> `carrier_layout` / `drive_installer.ensure_baseline_volumes`. The pipeline gains one new first step: load and verify the recipe, refuse on digest mismatch.
- N1.4 **Never copied**: drive/partition identity (new serial and GPT GUIDs), credentials (fresh one-time values), persona data, backups, the encrypted admin passphrase, TPM-sealed keys. These are recreated or re-enrolled on the new drive.
- N1.5 **Replica proof** = recipe digest recomputed from the new drive's own registries equals the source digest, plus `host_readiness`-style checks pass. Not a byte comparison.
- N1.6 The recipe lives on `SUBSTRATE_PERSISTENCE` (config/recovery data, small, noexec) with a read-only copy embedded in the self-installer ISO, so a drive that has lost everything else can still be rebuilt (matches the "substrate may lose everything" requirement, testpersistence §9a). See Q1.

### N2. Workplace environment and charter (so purpose and design are not forgotten)

Problem recorded in AGENTS.md and repeated on 2026-09-30: sessions lose established facts and act on a partial picture (this session wiped a drive with an invented layout before reading `drive_installer.py`, DR49 or AGENTS.md).

- N2.1 **Charter**: one short document (this PRD's §1-§3, kept under one screen) that every volume's `agentIndex.md` points to, and that is embedded in the self-installer ISO and in the repo. It states purpose, principles, the volume table and the required-reading list.
- N2.2 **`agentIndex.md` per volume**, generated from `drive_installer`'s definitions, never hand-written (generator: `carrier_layout.agent_index`, written 2026-09-30 for all six carrier volumes). It names the volume's role, mount options, the drive serial, and the rules. Regenerated whenever the layout changes; a test fails if the index disagrees with `drive_installer`.
- N2.3 **Workplace** = the place the recipe, charter and source live together and an agent is directed to first. Proposed: the repo checkout as source of truth; `BASELINE:/hardened-appliance/` style copies are backups, not the workplace. Decision needed (Q2): whether the workplace is (a) the repo on the dev machine, (b) a git worktree carried on a volume, or (c) a dedicated volume.
- N2.4 **Required-reading gate.** `physical_device_safety.validate_target_device` is already the choke point for destructive work. Add a check that refuses unless the caller passes a charter digest matching the repo's current charter file, so acting without loading the charter fails in code, not by convention. (Proposal; Q3.)
- N2.5 **Docs-vs-code guard.** A unit test implementing the 2026-09-30 audit's mechanical scan (referenced files and `module.symbol` names must exist; every `lib` module must be mentioned in a doc), run in the normal suite, so drift fails CI instead of accumulating. Findings already filed as queue rows 27-36.
- N2.6 **Decision record for every real-hardware action**, written before or with the action (AGENTS.md completion report). The 2026-09-30 drive re-layout and placement have no record yet (task in §9).

### N3. Hardened appliance (from `hardened-appliance-prd.md`, kept as the detailed spec)

Components: Proxmox host on a dedicated NVMe with iGPU-only display and a Chromium kiosk (R1.x); IOMMU/VFIO GPU mapping as an operator-chosen profile (R2.x, conflict C1/C2 resolved there); Caddy gateway with `/chat`, `/media`, `/data` from a registry type and Authelia-style forward-auth (R3.x); LUKS + TPM with per-layer manifest hashing, sealed to a stable PCR set and config integrity by signed manifest (R4.x, research R-2/R-3 closed in §14 of that PRD). Status: pure slices and research done; everything on real hardware outstanding. Blocking facts found 2026-09-30: the AMD iGPU is disabled in BIOS; the kernel command line lacks `amd_iommu=on iommu=pt`; `tpm2-tools` is not installed; Secure Boot is off or unknown.

### N4. Integrity of the recipe and layers (ties N1 to measured boot)

`measured_boot` provides layer digests and PCR extension. The recipe digest (N1.2) and each registry layer digest are the values extended and, later, signed (R-3). PCR selection is still open: not 12/13 (systemd-stub owns them), a local-use PCR TBD.

## 6. Architecture in one view

```
            charter (N2.1)  +  recipe (N1)   <- live on SUBSTRATE_PERSISTENCE, embedded in the ISO
                     |
   validate_target_device -> acquire -> answer(HTTP, one-time cred) -> iso_builder -> install
                     |                                                       |
         carrier_layout / drive_installer  ---------------------------> volumes (§3), agentIndex per volume
                     |
   registries (GLOBAL on SUBSTRATE_PERSISTENCE/BASELINE, PROTECTED on USER_PERSISTENCE)
        settings | dependencies | gateway_route | gpu modes | ...
                     |
   host: iGPU display/kiosk | Caddy gateway | VFIO or CDI GPUs | measured boot (digests, PCR, signed manifest)
```

## 7. Acceptance cases (new; existing ones stay in their PRDs)

- M1 Replica from recipe: a QEMU virtual disk built through the pipeline has the same recipe digest as the source. *QEMU first, never a physical drive first.*
- M2 Clone refusal: the pipeline has no code path that reads a source drive's blocks; a test asserts no `dd`/`cp` of a block device appears in any argv it builds.
- M3 Identity not inherited: replica has a different serial, GPT GUIDs and credentials than the source.
- M4 Recipe tamper: changing one registry value, or one pinned hash, changes the digest and the pipeline refuses.
- M5 Index accuracy: every volume's `agentIndex.md` matches `drive_installer` (test).
- M6 Docs guard: the mechanical audit passes (test).
- M7 Charter gate: a destructive helper called without the current charter digest refuses and runs nothing.
- H-suite: the hardened-appliance acceptance cases A1.1-A3.4, corrected, stay as defined there.

## 8. Roadmap (gated; no calendar)

- P0 (no hardware, doing now): this PRD, recipe schema and digest (pure), index/drift tests (N2.2, N2.5), charter file.
- P1 (no hardware): recipe loader + replication pipeline wiring with fakes for every stage; M2-M4.
- P2 (QEMU): replica to a virtual disk, M1/M3; reuse the record 93/97 smoke-test pattern.
- P3 (operator present): hardened-appliance H3-H6 (VFIO in QEMU first, forward-auth spike, `systemd-cryptenroll` on a scratch volume, signed manifests).
- P4 (operator present, physical): replica to a real drive, only after P2 is green and a decision record exists.

## 9. Immediate tasks (also in `v0.2-work-queue.md`)

Existing rows 23-39 (hardened appliance, audit fixes, carrier layout, label collision) plus: write decision records for the 2026-09-30 carrier re-layout and placement (AGENTS.md completion rule); create the charter file; add the drift and index tests; define the recipe schema.

## 10. Known debt and corrections carried into this PRD

- ext4 label truncation makes `USER_PERSISTENCE_ADMIN` and `_PERSONAL` both `USER_PERSISTENCE` in `drive_installer.format_and_label_argv` (row 38).
- `registry.py` GLOBAL scope still writes to `BASELINE`, not `SUBSTRATE_PERSISTENCE`, the more honest home (record 98).
- Record 79: recurring backup does not yet target a separate physical device.
- Record 99: "update selected" version logic is a placeholder.
- Docs name drives by kernel letter; letters have shifted (audit A1, row 27).
- The serial `MD89N41071210AP4E` history: INSTALL.md lists it as "persistence backend (`sdb`)"; the 2026-09-28 handoff says that drive was then being repurposed for an unrelated project; on 2026-09-30 the operator directed it be used for Baseline, and it was re-laid out with Baseline's volumes (PRD §15 of the hardened appliance doc). Its earlier role and this change should be reconciled in INSTALL.md (row 28).
- A copy of the hardened-appliance work sits on this drive's `BASELINE` volume and `INSTALLER_CACHE/seed/`. `BASELINE` is a class-1 disposable volume and `INSTALLER_CACHE` must stay vanilla; both placements are questionable under AGENTS.md storage rules and need your ruling (Q4).
- Process failures this session (for N2): acted before reading AGENTS.md / `drive_installer`; wiped a drive with an improvised layout outside `physical_device_safety`; reported "needs root" without checking group access; discarded requested partitions when correcting; wrote no decision record.

## 11. Open questions for the operator

- Q1 Does the recipe belong on `SUBSTRATE_PERSISTENCE` (proposed), on `BASELINE`, or in a new volume? Should a copy ride inside the ISO?
- Q2 What is "the workplace environment": the repo, a worktree carried on a volume, or a dedicated volume? Where do you want an agent pointed first?
- Q3 Do you want the charter-digest gate (N2.4) to be a hard refusal in `validate_target_device`, or an advisory warning?
- Q4 Are the hardened-appliance copy on `BASELINE` and the tarball on `INSTALLER_CACHE/seed/` acceptable, or should they be removed (class-1 and vanilla-only rules)?
- Q5 From the hardened-appliance PRD: are both NVIDIA cards moving into Proxmox; what are the "7 layers"; does the 100 TB array exist; desktop VM or host kiosk only; discrete TPM or AMD fTPM?
- Q6 Should this PRD replace `hardened-appliance-prd.md` as the top-level document, with that file kept as the N3 detail spec (proposed)?
