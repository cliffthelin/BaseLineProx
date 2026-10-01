# BaselineOS

A bare-metal Proxmox host with a Baseline layer on top: a tty1 console with
deterministic hardware and network status, a login-gated web app (settings, admin,
recovery, drive administration, hardware, installer cache, app isolation), and a
read-only AI harness constrained to Baseline's own tools. The whole system lives on
a few named volumes so it can be rebuilt from an installer cache without losing the
operator's data.

**Where to look first**

- [`docs/layers/README.md`](docs/layers/README.md): the system from the physical drive up to the applications, one page per layer, with a status for every item.
- [`docs/design/v0.2-work-queue.md`](docs/design/v0.2-work-queue.md): the live roadmap. Statuses elsewhere are only as current as their date.
- [`docs/design/baseline-master-prd.md`](docs/design/baseline-master-prd.md): purpose and design. [`docs/INSTALL.md`](docs/INSTALL.md): what is real and verified on hardware, and what is not.
- [`AGENTS.md`](AGENTS.md): rules for anyone (human or agent) touching real drives or credentials.
- `docs/design/decision-records/`: why each piece is the way it is. They are dated history and are annotated, not rewritten.

## Security rules in force

- **Nothing is reachable beyond the login screen without a credential.** There is no guest user. Every web route except `/`, `/login` and `/logout` needs a session.
- **Recovery mode** needs a login and then this machine's root password (or its machine passphrase).
- **A new account** can be created only while the machine has no user data. There are no seeded or default credentials.
- **Passwords and passphrases are stored only as salted one-way hashes**: a candidate can be checked for a match, nothing stored can be decrypted.
- Drives are identified by **serial number, never by `/dev/sdX`**, and every destructive step goes through `physical_device_safety.validate_target_device` (block device, minimum size, never the boot drive). Baseline acts only on the two SK hynix drives it is set up with: that allowlist is enforced (v0.2 row 55).

- **Backups** go to a separate drive and are add-only: Baseline adds a new `baseline-backups/` folder and files inside it and never deletes, overwrites or replaces anything. It refuses a destination on either SK hynix drive.

## Salvage boundary

This project has a precursor (`cliffthelin/baseline_os`, plus a physical precursor
USB stick). `docs/salvage/OLD_BASELINE_NOTES.md` documents what was learned from
it. **No source files from that project are copied into this repo.** Contributors
should not reach back into the old tree for code; if a pattern from it seems
useful, describe it and reimplement it here.

## Layout

- `boot/`: Proxmox integration. `provision.sh` turns a fresh Proxmox install into a Baseline host; the systemd units (`baseline.service` for tty1, `baseline-web.service`, firstboot, kiosk, scripts inbox, recurring backup, sensors, dependency check); `prepare_scratch_drive.sh`.
- `baseline/bin/`: installed entry points (the `baseline` CLI, `baseline-web`, `baseline-firstboot`, the `*-gate` start gates, backup, recovery, ISO builder and others). Each is a thin wrapper over a module in `lib/`.
- `baseline/lib/`: the application, 80 modules. Grouped below.
- `tests/unit/`: the test suite (about 1,950 tests as of 2026-09-30; run `python3 -m pytest -q`). Most use injected fake runners, so almost nothing touches a real host.
- `tools/`: QEMU harness and safety scripts, the test-persistence experiments, deploy and denylist checks.
- `packaging/`: the `baseline-drive-setup` package.
- `Guardian/`: a separate Rust workspace (`guardian-sync`) and its evidence.
- `docs/`: layer pages, PRDs and work queues, decision records, changelogs, salvage notes.

### `baseline/lib/` by area

| Area | Modules |
|---|---|
| Core console (V0.1 slice) | `hardware`, `network`, `harness`, `providers`, `status_bar`, `stream_json`, `tether`, `diagnostics`, `netpref` |
| AI harness adapters | `harness_adapter`, `harness_events`, `harness_registry`, `opencode_adapter`, `acp_protocol`, `acp_transport`, `clipboard_osc52` |
| Web apps | `baseline_web` (the deployed merged app), `settings_web`, `control_panel_web`, `scripts_inbox_web`; start gates `settings_web_gate`, `kiosk_gate`, `scripts_inbox_gate` |
| Access and recovery | `admin_elevation`, `recovery_mode`, `recovery_tiers`, `setup_intent`, `install_identity` |
| Settings, registry, naming | `settings_store`, `registry`, `naming`, `dependencies`, `config_apply`, `config_pipeline`, `config_diff`, `config_crypto`, `update_pipeline` |
| Drives and volumes | `drive_installer`, `baseline_drive_layout`, `drive_admin`, `persist_bind_mounts`, `persistence_pool` (superseded), `physical_device_safety`, `hardware_inventory`, `installer_cache`, `backup_restore`, `backup_recurring`, `handoff`, `scripts_inbox` |
| Installer pipeline | `drive_setup_acquire`, `drive_setup_answer`, `drive_setup_install`, `self_installer`, `iso_builder`, `firstboot_statemachine` |
| Host network repair | `repair`, `repair_additive`, `repair_additive_persist`, `repair_rollback`, `firstboot_network_repair`, `topology`, `ifnet_config` |
| Applications and isolation | `appdata`, `quadlet`, `docker_provision`, `gateway_config`, `gateway_routes`, `browser_policy`, `gui_session` |
| VMs and containers on Proxmox | `vm_provision`, `pct_provision`, `vm_scripts`, `proxmox_detect`, `proxmox_vm_metrics` |
| Hardware and sensors | `gpu_admin`, `host_readiness`, `measured_boot`, `sensors_collect`, `sensors_history`, `sensors_interval_control` |

## Status

**V0.1 vertical slice** (tty1 ownership, deterministic hardware, staged network
diagnostics, a read-only harness answering from real machine state): built and
proven under QEMU on two Proxmox installs. Not done: the bare-metal boot test, the
USB-tether fallback (needs real USB hardware), and the full unplug-and-recover demo
as one continuous run.

**V0.2 is in progress.** Built and unit-tested: the volume set and its on-drive
layout, ID-keyed per-persona AppData planning, the installer-cache catalog, Quadlet
units (containers and networks), the login-gated web app, first-run setup, recovery
gating, the registry and settings store. Verified on real hardware: the Baseline
drive's partition layout. **Nothing in the volume or AppData plans has been
applied to a running system**, and no container has been started from a generated
unit. See the work queue for the real list and for items still open (for example,
a first-run route on the deployed app, row 49).

## Provisioning

`boot/provision.sh` turns a fresh Proxmox VE install into a Baseline host: disables
the enterprise repos (no subscription assumed), installs `inxi`, `python3-rich`,
Node.js 22 (via NodeSource, since Debian's own package is too old for Claude
Code), and Claude Code itself, deploys the app and installs the systemd units. Run
it as root, then run `baseline-auth-setup.sh` separately and interactively (it needs
a real login to complete OAuth).

## Non-goals

Phone Rescue Channel and full VAULT (LUKS, pairing, trust) remain deferred.
Per-persona AppData and the application-isolation layer are planned and tested but
not applied. See the master PRD and the work queue for the current boundaries.
