# Edit a Baseline install plan

DR138, 2026-10-03. The authenticated /install-plan page is a read-only plan
editor, not a provisioning wizard. The roles/run job, mount application and
installer first-boot connection still need implementation.

1. Open Baseline's local web interface, sign in yourself, and choose Installer
   plan. Opening the page alone does not query hardware.
2. Choose Discover and autofill. The server establishes its boot-drive identity,
   reads a fresh lsblk listing and checks enrollment. Ambiguous choices stay
   unset. Existing Proxmox and Baseline disks can be kept/retained.
3. Edit the JSON choices: environment name and desktop/server variant; selected
   applications; administrator and guest cache/generation/private-data paths;
   and deliberately chosen serials/retained PARTUUIDs. Only Ubuntu24.04 can be
   provisioned by the current compiled environment adapter. Changing a path
   does not migrate existing data or establish a physical mount.
4. Choose Validate current choices. Each action discovers again. Errors are
   shown without claiming installation. Missing volumes, changed partitions,
   invalid fields or unsupported apps must be resolved before compiling.
5. Choose Preview stage parameters to see inputs for the existing drive,
   Ubuntu and app stages. No stage is executed. Export validated plan saves
   the plan JSON locally. Editing invalidates the export until revalidated;
   late responses cannot overwrite newer choices.

Actual read-only discovery on this machine found Proxmox
FD01N6557110C271B and Baseline MD89N41071210AP4E. It selected keep and retain,
then refused compilation: the current six-volume layout lacks APPDATA_ADMIN
and APPDATA_PERSONAL required by the eight-volume schema. No drive was enrolled,
formatted, mounted or modified. Do not format to make the schema match: an
explicit storage mapping/migration must be designed and reviewed first.

The real headless-Chromium walkthrough used synthetic drive listings; separate
native discovery used actual physical metadata. These prove different things.
No complete install, physical mount application or first boot was verified.
Existing ISO DR134 does not yet contain DR135/DR138; provisioning source now
copies the page module, but a new ISO needs packaging and boot verification
when the remaining installer execution changes are ready.

The existing CLI remains baseline-install-plan autofill, validate and compile.
Application-specific examples are in BASELINE_BUILD_WALKTHROUGH.md. Durable
jobs, PARTUUID fstab application, cache/data routing, physical boot and encrypted
independent restore remain open in queue72/75/76 and59/60/77.

## Existing AppData on another enrolled drive (DR140)

Main previously lacked this installer framework entirely. DR140 integrates it
and adds explicit dedicated AppData mapping. After Discover and autofill, choose
a discovered AppData target, then Apply mapping to plan. Repeat for each persona.
Only existing ext4 APPDATA_<PERSONA> partitions on enrolled drives with unique
PARTUUIDs are offered. Entering another user's volume, cache partition, unknown
drive or cloned/replaced identity refuses. The picker fills persona/serial/GUID;
the mapping is stored in storage.appdata, not as a bare /dev/sdX path.

Example optional field (replace placeholders with discovered identities):

```json
{"appdata":{"admin":{"serial":"ENROLLED_DRIVE","partuuid":"DISCOVERED_GUID"}}}
```

This is the appdata field inside storage, alongside substrate and baseline.
An explicit external mapping removes that persona's APPDATA requirement from
the Baseline drive; all six core/user volumes still need real identities.
Compiled appdata entries carry a separate PARTUUID mount and expected serial.
No fstab entry is applied and no app profile is moved by this editor. Existing
local AppData remains supported; explicit overrides do not emit duplicate mounts.

The actual machine still lacks ready AppData volumes. The software will not
create fictional targets or silently put AppData into USER/INSTALLER_CACHE.
Creating a volume/container, migrating existing app data, joining host storage
to guest mounts and executing the installer as a resumable job remain unfinished.
