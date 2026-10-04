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
