# 270 - What the nested Proxmox rehearsal showed (2026-10-18)

Date: 2026-10-18. Status: the offline cache and installer ISO were rebuilt with the new content (Kasm base8 plus the Debian and Ubuntu ready-made bases, 28.6 GB cache, 406 packages), the full install was run in the nested rehearsal (no network), and the ready-made VMs were made and booted through the real web service on real Proxmox. Six defects that only a real host could show were found and fixed.

## What ran, and how
- `baseline-allscript-install --stage cache` (28 645 MiB), then `--stage rehearse` with `--kasm-base kasm/base8 --os-bases os-bases/rehearsal-set`: ISO built, installed to the 128 GiB nested drive with no network, the first-boot authorization screen shown and CONFIRM typed, the kiosk showed the Proxmox login, and the VM shut down cleanly. This was run twice (the second time after the SSH-key fix below).
- The installed disk was then booted again with SSH and web forwarded to the host, and a throwaway account (random password, never printed) drove the web service like a browser.

## Verified on the real host
- Kasm VM 100 (`baseline-kasm`, from base8) is created on the first boot and running; the Workspaces page says "Kasm is ready"; the settings and suggestions pages render and the Wiki folder is written.
- The launcher's "Available to create" list shows Debian and Ubuntu as ready-made (`prebuilt`), and Omarchy, CachyOS, NixOS, Bazzite, Qubes and FydeOS as not carried or blocked, each with its reason.
- A ready-made Debian VM and a ready-made Ubuntu VM were created through `POST /vms/action` (`create_prebuilt`) and the job store, and registered with Proxmox: overlay disk, retained `baseline-home` disk, first-boot seed CD, OVMF with an EFI disk, guest agent. Each booted, the guest agent answered in 18-24 s, the owner account is the signed-in Proxmox user (uid 1100, password locked, passwordless sudo), the retained disk is mounted at `/home`, and the console is signed in with no login. The launcher shows the VM as a tile with console, window and fullscreen modes.
- virtiofs drive sharing (DR269): `pvesh create /cluster/mapping/dir` and `qm set --virtiofs0` worked; the guest read a file the host wrote and its own write landed on the host volume. The test mapping was removed.

## Defects found and fixed (each with a test)
1. The job store's parameter allow-list did not include `os`, which the launcher sends: every ready-made create was refused (409).
2. A creation that failed after the VMID was reserved left its record behind, so every retry answered "already exists or has retained state". The Proxmox host now discards what the failed attempt made (never a VM Proxmox already knows).
3. A disk smaller than the system itself failed inside `qemu-img` after the VM was registered; it is now refused first, with the size needed.
4. The ready-made path ignored a chosen home-disk size (always 32 GB); it is now honoured.
5. Ubuntu's GDM reads `/etc/gdm3/custom.conf`, not `daemon.conf`; the seed writes both and Ubuntu now signs the owner in.
6. (Not shown to be needed.) The development SSH key given at install time looked unusable on the first boot, so a development key now also travels with the development user into `/etc/baseline-dev/authorized_keys`, which sshd reads (rehearsal and development only). A later run showed the refusals were probably not the guest's doing at all: see the last section. The change is harmless and stays, but it was not proven to fix anything.

## Second run: the whole carried set on a larger nested drive (2026-10-18)
The cache drive was raised to 2 TB, so the rehearsal drive became 384 GiB and the cache carries all seven built bases plus Kasm (53.6 GB, 406 packages). The full install ran offline again; with the room, no headroom workaround was needed and all six ready-made systems were created through `POST /vms/action` in 6-21 s each.

Booting each one on the real Proxmox found three more defects, fixed with tests and re-verified on a fresh VM of each:
7. NixOS: `bash` is not on cloud-init's PATH, so the home script exited 127 and nothing was mounted or signed in. The script is now plain `/bin/sh` with a PATH that covers NixOS, and NixOS gets its GDM autologin by replacing the store-linked `/etc/gdm/custom.conf` with a real file after the home is mounted.
8. CachyOS: `/home` is already a mountpoint (a btrfs subvolume), so "mount unless /home is a mountpoint" skipped the retained disk and then failed its own check. The disk is now mounted over it when the topmost mount's source is not the retained disk.
9. CachyOS: its login manager is Plasma Login Manager (`plasmalogin`), not SDDM; it now gets `/etc/plasmalogin.conf.d` autologin (and the SDDM file too, for a base that still has it).
Also found while building the set: the cache stage called a two-base cache "complete" when seven were wanted; a cache missing a wanted base, or holding an older build, is now stale.

Result per system on the real Proxmox (booted, guest agent up in 12-18 s): Debian, Ubuntu, NixOS and CachyOS each have the owner (uid 1100, password locked, passwordless sudo), a signed-in graphical session, and the retained disk mounted at `/home`. Omarchy reaches its own first-boot setup screen ("Press Return to Start Setup"), as designed.

**Bazzite and Omarchy: fixed by a seed runner (below).** Their first boots originally asked for an account (Bazzite showed a login screen with no account at all; Omarchy asked for a username and password).

## Not verified, and why
- Ollama's LXC and the app VMs' first-boot install: the rehearsal has no network and does not carry the container template.
- NFS and SMB mounts (no file server), the remaining four ready-made systems on Proxmox (not in the rehearsal's set), and the retained home surviving a destroy-and-rebuild of a ready-made VM (the generic rebuild is unit-tested; not repeated here).
- A failure after the VM is registered (seed or UEFI step) still leaves a registered, stopped VM; it can be deleted from the VM page. Only failures before registration clean up after themselves.

## Rehearsal-only workarounds (not in the repo)
- The nested drive's volume group is full (the cache alone is 60 GB of the 80 GB cache volume), so the library's 10 GiB free-space headroom could not be met; a drop-in on the VM runs the web service with the headroom lowered (`/usr/local/bin/baseline-web-rehearsal`). Real hardware (512 GB) does not need it. A rehearsal with the full six-base cache needs a larger nested drive.
- Root SSH with the development key was refused on the first attempts after the rehearse stage on three fresh installs, then accepted after a later boot of the same disk. On the third, the SSH client saw host key `ITkq...` while the guest's own host key (unchanged since install) is `L08y...`: something other than the guest's sshd answered the forwarded port 22481. What it was is not established (no other process held the port when checked afterwards; the guest was running and its sshd listening). Next rehearsal: compare `ssh-keyscan` with the guest's key before concluding anything about authentication.


## Owners for Bazzite and Omarchy from the seed (2026-10-18, later)
Neither base has cloud-init. A small stdlib-only runner (`baseline/lib/seed_runner.py`, unit `baseline-seed.service`, ordered before the login manager) reads the same `cidata` seed disk and applies the part of cloud-config a VM's owner needs: the retained-home script every boot; once per instance the hostname, files, accounts (fixed uid 1100, password locked, passwordless sudo, only groups the system has), mounts, and first-boot commands. It logs to `/var/lib/baseline-seed/baseline-seed.log` (Bazzite and Omarchy keep no journal across some boots, so a failure must not be silent) and writes failing first-boot commands into its result.
- **Bazzite:** the runner is installed by the kickstart's `%post` during the base build. Verified on the rehearsal's Proxmox: owner uid 1100, retained disk mounted at `/var/home`, signed in to Plasma. It needed two seed fixes found by booting it: SDDM signs in only when told the session (`Session=plasma.desktop`), and a freshly formatted retained disk's root has no SELinux label so the login manager could not enter the home (`restorecon` after mounting).
- **Omarchy:** it makes its owner with its own `omarchy-provision-owner`, which prompts for a password and sets it on root as well. `baseline/lib/omarchy_owner.py` runs Omarchy's own provisioning functions with the answers from the seed (the vendor script is patched in memory and refused if it is not the shape this was written for), then locks both passwords, keeps the autologin Omarchy would remove after one boot, and grants sudo without a prompt. The account is made first with uid 1100 so Omarchy's script resumes it. Verified: uid 1100, both passwords locked, passwordless sudo, hostname set, Omarchy desktop signed in. A machine started with no seed still shows Omarchy's own interactive setup.
- Omarchy's installer is its own orchestrator and ignores archinstall's `custom_commands` (tried, found not to run, and removed). The runner is installed into the finished base by `baseline-build-os-base`: a helper VM with a guest agent (the Debian base) opens the base's disk, runs the install script in a chroot of its root filesystem, checks the files and unmounts (`inject` does the same to an existing base).
- Both rebuilt bases replace the earlier ones in the `os-bases/out` folder (the earlier ones are kept in `previous-without-seed-runner/`); the offline cache must be rebuilt to carry them.

## PC401 features salvaged onto PC601 (2026-10-18)
Codex's candidate `93688c0` (six PC401 reliability features) applied cleanly to this branch and its 258 + 50 focused tests pass. It was incomplete in two ways that only the whole suite shows: `baseline_drive_layout.py` is a third caller of the stricter format guard and did not pass the validated serial (the layout action refused every drive; five tests failed), and about thirty test fixtures used PC401's serial as the drive under test, which the PC601 lane now correctly refuses. The caller was fixed from PC401's own change and the fixtures were aligned to PC601's serial only where the lane guard is in play (PC401's serial stays in the tests that check the other-lane refusal). Full unit suite after integration: 4900 passed, 3 expected failures.
Kept before the PC401 branch ends: decision records 301-308, their evidence (`docs/verification/307`, `308`) and `tests/integration/verify_pc401_disposable_guest.py`. Not carried, deliberately: PC401's installer UUID and the three lane-identity tests that pin it.
Still open, as Codex's handoff says: none of this was exercised in an installed Proxmox QEMU guest (VG rename interruption, partial migration retry and collisions, refusal to move live databases, retained Proxmox state, missing settings mount, PC601 refusing PC401), and native PC601 cold boot remains a separate acceptance step.
