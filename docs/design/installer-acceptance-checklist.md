# Installer and physical acceptance checklist — 2026-10-04

Current implementation review: DR158–165. This checklist follows the seven requested
outcomes. No outcome below is complete solely because unit or browser fixture
tests pass. PC401 is the selected physical target; PC601 remains unchanged.
All repeatable target operations belong to the production web application.

## 1. Inputs and sources (queue 72, 74, 76, 78)

- [x] Persist owned installer and recipe drafts; aggregate in Master Config (DR150).
- [x] Include the console check required by provision.sh in the ISO source payload.
- [x] Web input preparation captures current code, saved plan, settings and recipe.
- [x] SHA256 manifest verifies the exact captured file set and rejects changes.
- [x] Preflight lists missing host tools, source locks/files/digests and target packages.
- [x] Resolve installed source payload under /opt/baseline-src.
- [x] Ubuntu pinned vanilla source acquisition, cache identity guard and actual file download via the web (DR159). DR165 additionally acquired the actual Canonical image through authenticated web jobs in the disposable KVM host; physical cache deployment remains unverified.
- [x] Refuse unverified or changed imported Ubuntu bases; VM preparation uses the same cache source handler (DR159).
- [ ] Acquire and expose every remaining required publisher artifact through Installer Cache.
- [ ] Verify publisher provenance/signatures where available; local hashes alone are insufficient.
- [ ] Bundle the target OS apt dependency closure, version-pinned NodeSource and Claude npm sources.
- [ ] Connect associated hardware packages, application locks and source updates to preparation.
- [ ] Revalidate external artifact bytes immediately before consuming them.
- [ ] Produce and prove the final installer containing the completed dependency set.

Prepared input bundles are code/configuration snapshots in private control-plane
state, not copies of vanilla installers inside persistent user data. A completed
preparation job means capture completed, never that installation is ready.

## 2. One Build/Rebuild action (queue 72, 78)

- [x] Existing Drive Administration determines install versus rebuild/update (DR147).
- [x] Installer Plan validates and compiles fresh serial/PARTUUID choices.
- [ ] Reconcile Installer Plan with the existing recognized Proxmox LVM target.
- [ ] Implement one authenticated Build/Rebuild submission using a verified snapshot.
- [ ] Re-resolve serial, boot exclusion, ownership and recovery requirements before every destructive stage.
- [ ] Execute compiled stages with real backends; no placeholder success.

## 3. Recoverable installation (queue 74, 78)

- [x] Existing durable jobs reserve work and retain status across disconnects.
- [x] Input preparation uses durable jobs and request deduplication.
- [x] Interrupted source preparation has its own source-file inspection, not VM inspection.
- [ ] Persist installation stage inputs, outcomes and checkpoints.
- [ ] Reconcile actual target state before any resumed stage; never blindly replay.
- [ ] Integrate storage, Proxmox, Baseline, configuration and guest provisioning into that journal.
- [ ] Exercise disconnect, service restart and interruption during actual installation.

## 4. First boot and browser (queue 74, 75, 78)

- [x] Existing storage and persistence services gate parts of startup.
- [x] Existing Proxmox kiosk on tty3 and Baseline TUI on tty1. Kiosk uses verified retained AppData and waits for pveproxy (DR163); DR165 proved current-source cage/Chromium rendering and automatic startup after virtual host restart. Native physical startup remains open.
- [x] One authenticated readiness report covering mounted storage identities/capacity, network and native Proxmox/Baseline unit states (DR162); implemented, not physical runtime proof.
- [ ] Default browser/VT startup and portal navigation to Proxmox, Baseline and TUI.
- [x] Unit refusal checks for unavailable storage/network and failed services (DR162); fake runners/direct handlers.
- [ ] Prove readiness and refusal on the actual installed system.
- [ ] Prove native cold boot of the finished physical drive.

## 5. Workload access and switching (queue 72, 73, 74, 75)

- [x] Existing VM/container lifecycle handlers and durable workload jobs.
- [x] Ubuntu builder applies selected locale/desktop/homepage via a cloud-init configuration overlay, preserves it for OS rebuild and offers native guest verification (DR163). DR165 proved GDM login, Firefox rendering and native configuration verification after two actual OS rebuilds in nested Proxmox/KVM; physical deployment remains open.
- [ ] Integrate general recipe-stack and installer-selected workload creation.
- [ ] Browser guest consoles and desktop access with portal switching.
- [ ] Prove VM/LXC creation, startup, console access and switching on installed Proxmox.

## 6. Persistent user/application state (queue 72, 74, 76, 78)

- [x] Existing storage-role/persistence code and earlier selected-file recovery proof (DR146).
- [ ] Enforce physical USER_*/APPDATA_* routing for all intended workloads and browser profiles.
- [~] DR165 proved retained Ubuntu login, document hash and Firefox-created bookmark after two OS rebuilds in nested Proxmox/KVM. Broader application databases and physical routing/rebuild acceptance remain open.
- [ ] Prove interrupted-update, reboot and backup/restore preservation using actual data checks.

## 7. Final physical acceptance (queue 78)

- [ ] Resolve PC401 pinned mounts through the approved native host-restart workflow.
- [ ] Reinspect target identities and mounts after restart.
- [ ] Install using the final installer and production web Build/Rebuild action.
- [ ] Cold boot into portal; access Proxmox and Baseline TUI.
- [ ] Create/start/switch VM and LXC workloads and open their consoles/desktops.
- [ ] Save user/application data, rebuild disposable layers and verify retained bytes.
- [ ] Reboot, interrupt an update, restore a backup and verify data again.
- [ ] Record actual physical evidence and update INSTALL.md before marking completion.

DR157 independently rechecked the PC401 blocker: 23 distinct mount namespaces
across 45 processes. Its actual read-only fstab, policy and GRUB prerequisite
checks passed, but boot was refused before QEMU. These are separate physical
configuration results, not installation/runtime proof in DR158. DR146 disk-QEMU proof does not establish native cold boot
or proof after the volume-group rename. DR156 physical networking proof does not
establish installed Proxmox readiness. No physical drive changed in DR158.
