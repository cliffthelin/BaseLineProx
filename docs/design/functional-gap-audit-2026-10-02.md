# Functional coverage audit — 2026-10-02

## Governing requirement

AI builds and improves the software that accomplishes the goals. Baseline's
normal operation must work with AI disconnected. A human uses the application;
background work uses deterministic services/jobs/schedules. An optional assistant
may request an existing operation through authorized controls. It must not
become the missing installer, scheduler, storage manager or recovery engine.

This is a source and workflow audit of the current application, not a new
hardware validation. GitHub branch `local/physical-device-safety` was confirmed
at `6a806d8366b57be875a84398e339f452200442d8` before this audit. Existing unit and
KVM evidence is preserved as such. Reference: DR120; prior app audit DR119.

## Implemented follow-ups (current, 2026-10-02)

DR121 replaces synchronous VM/LXC actions with persisted asynchronous jobs,
request deduplication, authenticated history, native stages, interruption review
and real LXC login rotation. DR122 adds explicit web recovery of a missing OS
or owned stopped partial clone after destructive rebuild boundaries, retaining
data. Actual disposable Proxmox checks passed; 2,882 guarded unit tests passed.
The historical F02/F03 findings below describe the audit baseline, not a claim
these shipped controls are still absent. F02/F03 remain partial for unfinished
initial allocations/templates, running partial clones, orphan/native-task repair,
non-Ubuntu/other-backend VM login recovery and power loss. DR123 adds managed
Ubuntu/Proxmox reset, pending-rotation journal and safe rebuild guard; actual
guest/hash/document checks passed with restricted-network test seed augmentation,
2,892 guarded unit tests. Ordinary-network firstboot remains unverified. DR124 adds F04 stopped LXC /home/root/data backup and new-name restore with actual Alpine boot/read/ACL/user-xattr proof on separate virtual disks. Full VM and physical off-drive restore remain open. F01 real app
lifecycle remains a distinct workflow gap; no application isolation was
proved by container recovery. No physical deployment in these follow-ups. DR125 narrows F01 planner prerequisites with collision-free keys and equivalent/nested/unsafe-target checks; applied app lifecycle remains open.

## Existing application means that should be retained

- Authenticated web login, settings, drive administration and action/job logs
  are software, not bot behavior (`baseline_web.py`, `drive_admin.py`).
- Operations provides run-now, signed schedules, backup verification/listing
  and archive test-restore. The scheduler runs inside the web service; it does
  not require an AI agent (`operations.py:Scheduler/execute`, `operations_page.py`).
- Ubuntu acquisition and environment creation, standard ISO VM allocation,
  base/overlay/start/stop/rebuild are exposed in `/vms` (`vm_page.perform`).
  DR117 proves a defined subset in disposable KVM, not full physical deployment.
- Native distro LXC creation/start/shutdown/rebuild is exposed in `/containers`
  (`container_page.perform`, `distro_containers.py`); DR118 proves 11 selected
  versions on actual Proxmox inside KVM.
- `.claude/agents/Bot*.md` describe optional browser callers of operations already
  implemented. Their existence neither fills missing backend capabilities nor
  establishes operational readiness. Keep humans able to perform the same
  actions; no always-running AI should be necessary.

## Gaps requiring application software

| ID / priority | Goal and current coverage | Missing means / why an agent currently gets involved | Completion evidence | Existing queue |
|---|---|---|---|---|
| F01 / P0 | Install, launch, update and reset isolated applications. `/app-isolation` previews paths only. | Actual app lifecycle controller: allocated identity, verified selected AppData storage, migration, sandbox launch, readiness, stop/update/reset/remove with protected data retained. No mount/apply action exists; a developer would have to assemble it manually. | Install two real apps through the app, deny cross-app state access, explicitly share a document, reset one app, retain the other and survive OS rebuild with AI disconnected. | 74 |
| F02 / P0 | Dependable long VM/LXC operations. Drive/backup actions have jobs; `/vms/action` and `/containers/action` execute synchronously. | A common durable job runner with queued/running/failed/completed states, actual progress, per-resource locks, request deduplication and restart reconciliation. `make_server` uses single-threaded HTTPServer; long downloads/creation can prevent other requests from being serviced. Existing `_JOBS` are process-memory daemon-thread records. | Browser reconnect and service restart during a long operation: no duplicate VM, truthful recovered state, page remains usable; retry uses recorded resource identity. Never blindly resume destructive work. | 67, 72, 73; new 75 |
| F03 / P0 | Recover incomplete containers and lost one-time logins. LXC stores preparing/creating/rebuilding phases and refuses incomplete bases. | Inspection and bounded recovery actions in the app: show owned resources, retry safe stage, abandon reservation without deleting unrelated resources, reset/reissue login after explicit authorization. Lost HTTP response currently loses the only cleartext login; no reset action. Need equivalent VM registration/bootstrap reconciliation. | Inject native failure and disconnect after create; human recovers through app. Specifically prove stale openEuler CT119 reservation cannot destroy the later openSUSE base119 (DR118). | 72, 73; new 75 |
| F04 / P0 | Restore retained guest/app state, not just checksum archives. | Guest inventory across selected stores, LXC bind-data inventory, quiesce/resume, backup manifest/base dependencies, restore into a separate target and validate it. `list_guests_on_local_lvm` excludes new split/external stores; vzdump excludes retained LXC binds. `_test_restore` restores the smallest non-guest archive and counts files, not boot/recovery of each workload. | Restore real split Ubuntu VM, LXC home/root/data and app profile from off-drive backup; boot/read actual data; original unchanged. Display coverage exclusions before backup. | 59, 60, 72, 73 |
| F05 / P1 | Install requested desktop/NAS/mobile environments from the app. `/vms` currently has vendor links and generic ISO controls. | Real recipes/source acquisition, publisher validation, resumable downloads, installer console access, firmware/graphics checks, retained filesystem/mount setup and readiness checks. OMV needs retained NAS disk controls. GrapheneOS emulator requires a separate build/run adapter; ChromeOS deployment remains a product-specific decision. A developer currently downloads/configures images outside Baseline. | At least one named distro installed through app controls, verified mounted retained state and clean rebuild; exact recipe identity shown. Unsupported products must remain explicit. | 73 |
| F06 / P1 | Manage external storage and all workload data through stable identities. Settings accept paths; changing them starts a new view, without migration. | Storage discovery/selection with actual class/mount identity; workload references independent of current default folder; space/preflight checks, adoption and transactional move/reattach. Root/data split with user-selected external storage must remain supported. | Change defaults without hiding old resources; move one stopped workload via app and reconnect safely after restart; missing mount never writes into substrate fallback. | 72, 73, 74 |
| F07 / P1 | Apply device/GPU and service networking choices. Hardware/GPU detection and modes exist; Quadlet fields/network generators exist. | Registry-to-workload apply controls and dependency setup, conflict checks, device attach/detach, real running-state verification, explicit service sharing. Setting GPU mode alone is not attachment; no verified app/container run follows it. | Assign a detected device/network to a real workload from app, observe actual access, detach and verify; retain truthful unavailable state. | 17–21, 25–26 |
| F08 / P1 | Prove installation/firstboot and the kiosk without an agent's transient service. Pipeline and gates exist; DR117 kiosk proof used a developer-started transient unit. | Product-owned install/reboot status and readiness feedback, actual fresh-host provision/deploy/firstboot verification. This is partly an integration/verification gap, not evidence that no installer exists. | Fresh disposable installation using shipped provision and services, reboot to gated GUI with no developer SSH fixes; then separately physical validation. | 72 |
| F09 / P1 | Update an application or OS and recover compatibility. Update helpers/settings exist, but universal versioned app/environment workflow does not. | Candidate generation, actual download/install/readiness states, data migration compatibility, promotion and rollback. Whole-host PVE boot generations need separate kernel/EFI/PVE-state scope. | Human performs update and rollback through app; service restart/power-loss leaves a bootable known state; retained data compatibility verified. | 67, 72, 74 |
| F10 / P1 | Resolve declared secret references and configure services. Schema guards references; no vault backend exists (queue8 explicitly states this). | Reference resolver and application-owned enrollment/rotation/revocation flow; service consumes a protected reference without relying on the agent to provide secrets. Credential entry stays with the human/system UI. | Real service uses reference, reference unavailable gives actionable refusal, rotation and rebuild retain correct access without plaintext logs. | 8 follow-up |
| F11 / P2 | Complete approvals and remote-access management. Daily approvals can be revoked; remote access is a read-only report. | Standing approval grant/revoke UI for existing API, clear grant lifetime/state and remote access configuration/status reconciliation if product scope needs those changes. Do not count read-only status as configuration. | Human grants/revokes through app with existing authorization; read-only page clearly separates observed state from configurable actions. | 67 |
| F12 / P2 | Change substrate later to Harvester without AI translating commands each time. | Explicit backend capabilities and an implemented/tested ACL/lifecycle/storage adapter. Current Proxmox selection via tool detection and QEMU fallback is not a Harvester backend. | Same supported app operation executes on real Harvester through its adapter; unsupported capabilities refuse explicitly. | 72 |

P0 means a goal can lose track of state or cannot currently be completed in the
application; P1 means core capability is only partly covered; P2 means later scope.
These priorities emphasize functionality. Existing credential/storage rules still
apply, but this audit does not propose another approval system or replace tools
that already work.

## Do not substitute bot coverage for capability coverage

For each goal, record separately:

1. Human-visible application entry point.
2. Deterministic backend operation and prerequisites.
3. Actual completion/readiness checks (launched/allocated is not ready).
4. Protected data ownership, retention and backup coverage.
5. Failure/restart recovery, with no developer shell required.
6. Verification level: source, fake-backed tests, actual KVM service, or physical.

A bot can use an entry point only after these exist. A shell command used by an
integration test is legitimate evidence; it is a product gap when that command
is necessary for ordinary users and no application-owned operation covers it.
Not every unverified step requires new software: F08 explicitly needs shipped-
service integration validation before deciding which additional code is missing.

## Build sequence

First, implement F02/F03 as a shared workload job/reconciliation mechanism for
already-working native operations. Then ship F04 restore coverage alongside
F01's first real application lifecycle. Extend F05/F06 recipes/storage after the
basic transactions are recoverable. Device/network and updates build on those
same operations; optional AI invokes them but never substitutes for them.

The no-AI acceptance run must cover install, normal launch, stop, reset, update,
backup, restore, browser disconnect and application-service restart. A required
human credential/confirmation is a normal product interaction; an AI agent
composing a shell command or repairing metadata is not a completed workflow.

## Audit limits

Inspected current route handlers, page actions, Operations scheduler/jobs,
VM/LXC lifecycle modules, app planner/Quadlet, backup selector/restore and
existing queues/evidence. No new application implementation or live hardware
verification performed. No production success claim is added. Pure documentation
checks and referenced symbol existence were checked; historical records stay
append-only. Runtime gaps remain open, not fixed by writing this report.

## DR126 installer/recipe follow-up

Installer wiring and portable OS/app configuration composition now have a source
and design audit: installer-overlay-template-audit-2026-10-02.md, row76. One
reusable builder plus guest reconciler is recommended. Export is declarative
configuration only; fresh instantiate, retained rebuild and private restore are
separate actions. This is an implementation specification, not shipped capability.

## DR129 extraction/replacement recovery follow-up

Human durable read-only installed deb metadata/location inspection now exists
for managed Ubuntu VMs, proved with actual Bash query in disposable Proxmox.
Inspection is not recipe export or clean-install verification. Queue76 still
requires reviewed app-specific capture, source/dependency locks and clean-target
install/apply/launch tests. Queue77 now tracks encrypted independent destination/
key recovery and restoration with original storage unavailable. Earlier F01–F12
findings retain their historical scope; no generic runtime app isolation claim.
