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

## Not verified, and why
- Ollama's LXC and the app VMs' first-boot install: the rehearsal has no network and does not carry the container template.
- NFS and SMB mounts (no file server), the remaining four ready-made systems on Proxmox (not in the rehearsal's set), and the retained home surviving a destroy-and-rebuild of a ready-made VM (the generic rebuild is unit-tested; not repeated here).
- A failure after the VM is registered (seed or UEFI step) still leaves a registered, stopped VM; it can be deleted from the VM page. Only failures before registration clean up after themselves.

## Rehearsal-only workarounds (not in the repo)
- The nested drive's volume group is full (the cache alone is 60 GB of the 80 GB cache volume), so the library's 10 GiB free-space headroom could not be met; a drop-in on the VM runs the web service with the headroom lowered (`/usr/local/bin/baseline-web-rehearsal`). Real hardware (512 GB) does not need it. A rehearsal with the full six-base cache needs a larger nested drive.
- Root SSH with the development key was refused on the first attempts after the rehearse stage on three fresh installs, then accepted after a later boot of the same disk. On the third, the SSH client saw host key `ITkq...` while the guest's own host key (unchanged since install) is `L08y...`: something other than the guest's sshd answered the forwarded port 22481. What it was is not established (no other process held the port when checked afterwards; the guest was running and its sshd listening). Next rehearsal: compare `ssh-keyscan` with the guest's key before concluding anything about authentication.
