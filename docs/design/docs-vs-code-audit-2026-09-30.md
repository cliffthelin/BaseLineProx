# Documentation vs code audit - 2026-09-30

Scope: 144 markdown files under `docs/` (excluding `archive/` and `salvage/`) plus `README.md`, checked against `baseline/lib/*.py` (78 modules) and `tests/unit` (1624 tests collected). Method: extract every backticked `*.py` name and `module.symbol` reference and check it exists; list lib modules no doc mentions; then read the README, INSTALL and work queue by hand for stale claims. Decision records are historical, so the fix for them is an annotation, not a rewrite. Each finding maps to a task in `v0.2-work-queue.md` (rows 27-35).

## A. Safety-relevant (do first)

**A1. Kernel device letters in the docs no longer match the machine.** `INSTALL.md` (table at line 33), DR46, DR48 and `SESSION_HANDOFF.md` name drives by kernel letter. Today `lsblk` shows serial `FD01N6557110C271B` (the docs' Proxmox substrate, "sdd") as `/dev/sdc`, and serial `MD89N41071210AP4E` (the docs' persistence backend, "sdb", repartitioned by DR46 and recorded there as confirmed disposable) as `/dev/sdd`. Code already keys on serials (`drive_admin.DEFAULT_TARGET_SERIALS`, `expected_serial=`), which is right; the docs and any operator instruction like "use /dev/sdd" are the exposure. Task 27.

**A2. Event to record: the persistence-backend drive was repartitioned this session.** At the operator's instruction ("free rein ... /dev/sdd") `boot/prepare_scratch_drive.sh --apply` was run against serial `MD89N41071210AP4E`. Before the wipe it held an `iso9660` image labelled `OMARCHY_202609` and no LVM or recognizable persistence layout. It is now a 200G / 100G / 176.9G GPT (`proxmox-rehearsal`, `luks-scratch`, `scratch-data`); p3 is ext4, p2 is empty, the kernel has not re-read the table. The drive the docs call the Proxmox substrate (serial `FD01N6557110C271B`, now `sdc`) was not touched. `INSTALL.md` and the v0.1/v0.2 queues still list the old role. Task 28.

**A3. Work-queue row 14** ("real target hardware for `/dev/sdd`'s current install") describes `/dev/sdd` as a complete Proxmox install (`pve` VG, two VMs). By serial that install is on `sdc`, not the drive now called `sdd`. Task 29.

## B. Stale references (code moved or never built)

| Doc | Reference | Reality | Task |
|---|---|---|---|
| DR81 `81-recovery-mode.md` | `recovery_web.py` | no such module; logic is in `recovery_mode.py` / `recovery_tiers.py`, page in `settings_web.py` | 30 |
| DR11, DR12 | `harness.propose_repair` | now in `repair.py` | 30 |
| DR12 | `firstboot_network_repair._observed_dev` | removed | 30 |
| DR59 | `quadlet.write_and_enable` | removed | 30 |
| DR43, DR44 | `hermes.py`, `opencode.py` | no such files; adapters live in `harness_adapter.py`, `providers.py`, `acp_*.py` | 30 |
| `SESSION_HANDOFF.md` | `local_receive.py`, `remote_backup3.py` | not in repo | 31 |
| `drive-setup-gui-v2-prd.md` (status: draft) and `milestone-0-plan.md` | 10 planned test files (`test_answer_file`, `test_stable_identity`, `test_handoff_transaction`, `test_secret_handling`, `test_eligibility_states`, `test_backend_surface`, ...) | none exist anywhere in `tests/`; PRD does not say they are unbuilt | 32 |

The scan also flagged `harness.env`, `sensors_history.db`, `sensors_collect.timer`, `network.target` - these are file/unit names, not code references; no action.

## C. Coverage gaps

- **C1.** `settings_web_gate.py` (and `baseline/bin/baseline-settings-web-gate`) is mentioned in no doc. Task 33.
- **C2.** `README.md` lists only Steps 1-7 (`hardware.py`, `network.py`, `harness.py`, the CLI) and a "Status (V0.1 vertical slice)" block; the lib has 78 modules (registry, settings store, GPU admin, quadlet, drive admin, self-installer, recovery, web apps...) that the README does not mention. Task 34.
- **C3.** Work-queue rows 24-26 (mine) need test counts kept current: row 25 says 32 tests, there are 33; fixed in this pass.
- **C4.** Decision records exist for work through row 22 but none for rows 23-26 (the hardened-appliance work records its decisions in the PRD). Task 35.

## D. Verified in sync (no action)

All `module.symbol` references in `INSTALL.md` and the README resolve; `DEFAULT_TARGET_SERIALS` in code matches the serials in `INSTALL.md`; `testpersistence-prd.md` and `hardened-appliance-prd.md` reference modules that exist.

## E. Test-suite note

At audit time 3 tests fail (`test_baseline_web.py` x2, `test_settings_web.py` x1). They fail on uncommitted edits to `baseline_web.py` / `settings_web.py` made outside this work (a new `sysinfo` key and page text), not on code changed here. Task 36.
