# Installer wiring, rebuild continuity and portable recipe audit

2026-10-02. Source/design audit only; no new runtime or hardware verification.
Decision record126. User request supersedes further planner-only implementation
as the immediate task. Existing DR117–125 evidence retains its original scope.

## Recommendation

Keep one Baseline application and one substrate installer. Add a separately
scoped environment/application builder inside that application, reusing durable
jobs and backend adapters. Its versioned recipe engine should be independently
callable by a future installer UI/CLI, but a second independent installer must
not duplicate identity, persistence, credentials or destructive rebuild logic.

The substrate installer installs Proxmox/Baseline and storage prerequisites.
The environment builder installs OS generations and applications inside selected
VMs/containers. A guest-side reconciler owns guest mounts, app identities,
config rendering and namespace launch. The host orchestrator owns backend IDs,
attachment identity and journals. Do not mount a guest's app overlays on the
Proxmox host or turn the kiosk profile into daily-driver AppData.

## Source evidence and wiring points

| Current component | Present behavior | Required wiring |
|---|---|---|
| self_installer.build_and_write_self_installer, drive_admin build_self_installer | Verified-source acquisition, one-time HTTP answer, source/provision baked into ISO, install launch; launch is not completion | Stage versioned recipe/reconciler modules via provision; install-completion/readiness remains row72. Do not bake user state or credentials into portable templates. |
| drive_installer.baseline_volumes_for/ensure_baseline_volumes | AppData volume model exists | Actual selected mount/class/serial/UUID verification, missing-mount refusal; physical six-volume layout currently has no APPDATA volume. Support selected external storage; no incidental repartition. |
| vm_page.perform, baseline_web workload action routes, WorkloadJobs | Authenticated durable VM/LXC jobs, saved outcomes, restart inspection, one-time credentials | Import/inspect/compose/build/rebuild/export recipe actions using same jobs, immutable recipe digest and allocated target identities. No autonomous destructive replay. |
| ubuntu_environment.create/write_seed/rebuild | Verified Ubuntu base, disposable OS root, retained home; saved private profile and non-formatting rebuild seed | Recipe-driven packages/config plus guest reconciler; broader retained paths, service state and machine identity inventory. Existing profile contains a hash/instance ID and is not a shareable template. |
| VmHost.rollback/freeze_as_base; ProxmoxVmHost | Stopped root replacement and native lifecycle; standalone disk freeze | Candidate generation and readiness before promotion; retained manifest/attachment verification and recovery journal. Freezing a customized disk is not content-free recipe export. |
| appdata.plan_for, /app-isolation | Planned per-app paths/owners; DR125 lexical validation | Verified runtime paths, selected AppData, stable app identity, protected control registry, stopped migration, launch/stop/reset and explicit sharing. No apply adapter currently exists. |
| container_backup.backup/restore | DR124 stopped home/root/data archive, new-name restore, unchanged same-host base | Data-backup binding to recipe digest and dependencies; cross-host/base reacquisition still unsupported. Separate this archive from recipe-only export. |
| installer_cache acquisition | Vanilla artifact provenance and pinned-source support | Resolve recipe dependencies from configured cache or source; custom built generations stored separately, never relabel customized bytes as vanilla cache. |

## Rebuild with only volatile-state loss

The goal is achievable for a workload with complete declared durable-state
coverage, reproducible installation/configuration and compatible reattachment.
It is not true for arbitrary current VMs. Ubuntu currently retains home, not
arbitrary /etc changes, additional packages, /var/lib databases, /root state,
service secrets or every machine identity. A standard full disk remains valid;
never retrofit a resettable root without an explicit migration plan.

Classify every writable path before offering the stronger rebuild operation:

| State | Placement and lifecycle |
|---|---|
| Vendor OS/app bytes | Pinned executable base or installed from locked sources; reacquirable. |
| Portable declarative configuration | Versioned recipe and allowlisted rendered defaults; reproducible on fresh state. |
| Local identity and secret bindings | Protected private control metadata/vault references; retain on same-machine rebuild, regenerate on fresh instantiation. |
| Personal app settings, databases, certificates and sessions | App-private persistent storage with schema/version; never shared by recipe export. |
| Documents, media and selected shared files | Protected user volumes, explicitly granted to apps; no reset operation deletes them. |
| Cache/temp/runtime state | Explicit disposable locations. RAM processes, connections and unsaved edits are volatile. |

Before root replacement: verify identity and complete coverage, stop new writes,
request app save/checkpoint, cleanly stop services/VM, flush durable storage and
verify backup/snapshot policy. Persist a recovery journal, build a new candidate
root, reattach unchanged state, recreate mount/permission policy before login,
run OS and application readiness plus actual data-read checks, then promote.
Keep the prior root recoverable until candidate success. Database schema changes
require compatible data snapshots/migration; replacing an old root against
new-format data is not a reliable rollback. No automatic replay on interruption.

The contract is all acknowledged/flushed durable state retained, only volatile
state expected lost. Unflushed writes and power failure need separate guarantees.
Unknown data paths block a lossless-rebuild badge; unsaved edits need app-specific
save/recovery integration. Direct human actions use the same deterministic API,
with AI disconnected. Non-login app service identities are not guest human users.

## Portable OS and application templates

Use a proposed Baseline Recipe v1 envelope with JSON Schema and canonical digest.
This is a project format proposal, not an implemented parser or an existing
universal interoperability standard. Adapters may render cloud-init, OCI/Quadlet,
Flatpak or Nix declarations where those tools actually support the target.
JSON transport alone does not make executable semantics portable.

Separate four artifacts:

1. OS recipe: distro/release/architecture, pinned base/source hashes, firmware
requirements, locked packages/repositories, selected config defaults, mount roles,
bootstrap and readiness adapter versions.
2. App recipe: stable recipe ID, medium and pinned source, compatible OS/runtime,
non-login identity policy, private path declarations, disposable paths, permission
and sharing requests, allowlisted settings and migration/reset policy.
3. Stack recipe: ordered references to exact OS/app recipe digests plus explicit
overrides. Lock resolved dependency graph and adapter versions. Detect dependency
cycles, incompatible OS/arch, nested mounts, port/device conflicts and duplicate
config ownership. Unknown/conflicting keys refuse; never silent last-wins.
4. Private deployment binding: actual VMID, volume serial/UUID, AppData location,
user identity, secret references and local Proxmox URL. Never included in shared
recipes. A private data backup references the locked recipe separately.

A configuration-only export contains manifests and approved config values,
not disk overlays, whole profiles, binaries, documents, browser history/cookies,
credentials, hashes, SSH host keys, machine IDs or captured user databases.
Configuration can itself contain sensitive content: explicit per-adapter export
allowlist, preview and human selection are required. Unknown fields/paths refuse
export. Permit only structured known adapters initially, not arbitrary imported
shell scripts. Export settings that point at a file as symbolic roles; payloads
are excluded unless explicitly part of a non-personal reusable default.

Deriving a recipe from an overlay needs an inspection/promotion workflow:
stop/quiesce -> compare declared configuration with pinned base -> classify each
change -> preview approved additions/updates/deletions -> promote to recipe ->
rebuild a fresh candidate -> compare effective settings. A raw upper directory
or qcow2 diff cannot reliably distinguish configuration from user content.
OverlayFS has whiteouts, opaque directories, metadata and lower dependencies;
export normalized settings/file operations, not internal whiteout devices.
No generic copy-all /etc or Chromium-profile export. Package changes belong in
locked package declarations, not a filesystem delta mislabeled configuration.

Example conceptual stack (references intentionally symbolic, not runnable):

```yaml
format: baseline.recipe/v1
kind: stack
os: {recipe: ubuntu-desktop, digest: REQUIRED_LOCKED_DIGEST}
apps:
  - {recipe: chromium, digest: REQUIRED_LOCKED_DIGEST}
configuration:
  chromium: {homepage_role: environment_console}
storage_roles:
  documents: {mode: retained, required_on_rebuild: true}
  app_private: {mode: retained, required_on_rebuild: true}
instantiate: {user_data: fresh, secrets: fresh}
```

Fresh instantiate allocates empty private state and fresh machine/app identities,
requests local storage/secret/service bindings, renders environment_console to
the local Proxmox URL, and installs through supported adapters. It copies no
source user's data. Rebuild instead binds existing data and original local
identity after verification. These are separate explicit operations. Exporting a
recipe is not backing up data; restoring a private backup is a third operation.

## Composition and layer mechanics

Compose recipes into a resolved desired configuration, then materialize OS/app
generations. Do not blindly concatenate qcow2 or OverlayFS uppers from different
bases. Deterministic ordering and explicit conflicts are part of the recipe.
App filesystem overlays belong inside the guest launch namespace; executable
isolation remains distinct from write placement. Native OCI/Flatpak mechanisms
should remain their real confinement adapter. Custom lower snapshots must be
separate from vanilla source, and upper/work must share a suitable filesystem.

## Delivery and acceptance sequence

1. Recipe schema/validator/lock resolver and coverage inventory, with rejected
conflicts and unknown state; export preview strips private runtime fields.
2. Ubuntu adapter + guest reconciler + Chromium private profile migration/launch,
selected mounted storage and trusted control registry. Two-app denial and shared
document proof, AI disconnected, before claiming application isolation.
3. Human build/rebuild/export/import UI on durable jobs; safe candidate promotion
and interruption inspection. Rebuild retains app settings/documents and identity.
4. Capture allowlisted settings into reusable recipe, stack with a second app,
instantiate a new blank-user-data VM, and verify expected configuration only.
5. Backup/restore private data against exact recipe; cross-host remapping and
compatibility checks; power-loss proof and broader distro/media adapters later.

Rows72/73/74/75 plus new row76 track this work. Acceptance must prove ordinary
human web actions, browser disconnect/restart, incompatible import refusal,
original unchanged, actual app state after rebuild, no source secrets/content in
export, and a new VM booting the locked stack without original user data.
Source audit only: no TDD production change, new unit/native test, VM boot or
physical operation occurred. Existing records are retained as history; current
queue/audit/install/handoff gain this request and findings.

## Primary references

- [Linux OverlayFS](https://kernel.org/doc/html/latest/filesystems/overlayfs.html):
whiteouts/opaque directories, copy-up and lower/upper/work constraints support
rejecting raw overlay export as a portable configuration format.
- [NixOS manual](https://nixos.org/manual/nixos/stable/): declarative system
configuration informs the recipe/generation approach; adopting NixOS is not
required or claimed.
- [cloud-init instance data](https://cloudinit.readthedocs.io/en/latest/topics/instancedata.html):
instance identity is runtime data, not a reusable user's identity template.

## DR127 implementation follow-up

Initial configuration-only JSON validation/export/digests and copied stack locks
are implemented with baseline-recipes validate/compose/verify CLI. Strict initial
Ubuntu/Chromium allowlists; unsupported/private/ambiguous inputs refuse. This
narrows the proposed parser gap, not deployment or full coverage. Structured JSON
Schema, source acquisition/package locks, web integration, capture and runtime
adapters remain open. No new hardware or native runtime verification.
