# 260 - Kasm Workspaces on top of Proxmox, aligned with the overlay and persistence design

Date: 2026-10-16. Status: built; the guest side is verified end to end in a QEMU test guest (below); the Proxmox side is unit-tested with a fake Proxmox and NOT yet run on a
real Proxmox host. Each claim says which. Builds on DR257 (volume roles), DR258 (environments, application containers) and DR259 (layered settings, launcher, Proxmox overlay).

## Operator instruction (2026-10-16)
"Build in Kasm on top of Proxmox and align Kasm to build the overlays and persistence data like I have been designing to. Include configuring Kasm to do these
things in the installer setup so that it can be ready immediately on a new setup."

## Why a VM, and which one
Kasm is a Docker-based platform (Postgres, API, manager, agent, proxy, guacamole, RDP gateways, then one container per workspace session). Docker on the
Proxmox host would rewrite iptables/forwarding that Proxmox's firewall and guest networking depend on, and Kasm officially supports a dedicated machine, so it
runs in **its own VM**. Kasm 1.19.0's installer lists Debian 13 as supported, which is also the host's release, so the VM is **Debian 13** (genericcloud image).

## How Kasm's data maps onto the volumes (the point of this record)
| Kasm data | Where it lives | Volume / layer | Why |
|---|---|---|---|
| Debian 13 + Docker + Kasm installer + the service and workspace images | the base image `kasm-base-<ver>-debian13.qcow2` on INSTALLER_CACHE | **base**, vanilla, read-only, reproducible | no secrets, no install state; rebuilt only by the build |
| The VM's root and Docker's container layers and running workspace sessions | a copy-on-write overlay of the base | **SESSION_TEMP**, disposable | a reset or rebuilt OS starts fresh; nothing personal is on it |
| Kasm's platform state: `/opt/kasm` (configuration, certificates and private keys, logs) **and** Postgres's data (users, sessions, workspace settings) | a persistent disk with serial `baseline-kasm-admin` | **APPDATA_ADMIN** (the admin persona's application data) | secrets and the user database; DR257 says VMs never write to USER_ADMIN, so the platform's state is the administrator's *application data*, not host configuration |
| Workspace persistent profiles `/mnt/kasm_profiles/{user_id}/{image_id}` (a person's profiles together; one folder per workspace) (browser profile, editor settings, files) | a persistent disk with serial `baseline-kasm-prof` (a virtio serial is 20 characters at most) | **APPDATA_PERSONAL** | a person's application data is theirs and goes only to their AppData volume |
| Kasm's generated administrator credentials | Baseline's credential vault | **USER_ADMIN** (the host's own, encrypted at rest, DR258) | the host generated them and keeps its copy; Kasm's own copies stay on APPDATA_ADMIN |
Nothing personal is on SUBSTRATE, INSTALLER_CACHE or the base. Postgres's data is a named Docker volume, which would sit in Docker's data directory on the
disposable root; it is created as a bind volume onto `/opt/kasm/data/db` on the admin disk **before** Kasm installs, and re-created at every boot (Docker's
record of it is on the root; the data is not).

## How it is made ready on a new setup
1. **Build time (online, once)** - `baseline-build-kasm-base` (`kasm_build.py`): verifies the Debian image (SHA-512) and the Kasm bundle (SHA-256), boots
   Debian 13 under QEMU, installs Docker 26 and Compose, makes the fixed `kasm` (6500) and `kasm_db` users, **pulls** the eight service images and the carried
   workspace images at the static `1.19.0` tag (Kasm's own offline archives are not used: they carry only four workspaces), packs the two Docker plugins the
   installer would otherwise fetch from the registry (log driver, sidecar network), records every image digest in `KASM.json`, and makes the image generic (no
   machine id, host keys or cloud-init state). It does **not** run Kasm's installer, so the image holds no secrets and no install state (`KASM.json` says so
   and the setup refuses a base whose manifest does not).
2. **Carried with the installer** - `baseline-build-offline-cache --kasm-base DIR` copies the base into the offline cache as `kasm/` (checked first against its
   manifest), so the installer's own manifest covers it and a new setup needs no internet.
3. **On the target** - `baseline-kasm-setup.timer` (enabled by `provision.sh`, retries until done, then only makes sure the VM runs) starts
   `baseline-kasm setup` once first boot has completed and Proxmox's storage is reconciled. `kasm_setup.py`: checks the volumes are mounted and the base
   matches its manifest; sizes the VM from the host (a quarter of its memory, 6-16 GiB; half its cores, 2-4; refuses a host under 12 GiB); registers three
   directory storages; makes the root as a qcow2 overlay on the vanilla base (in SESSION_TEMP) and the two data disks as bare sparse qcow2 (reserved, never written)
   in APPDATA_ADMIN and APPDATA_PERSONAL, attached by serial; builds the VM with the guest agent on; starts it; **generates the four credentials and stores them in
   the USER_ADMIN vault before the guest is told them** (a vault that cannot be written is a refusal; a rebuild reuses the stored ones because the database was made
   with them); sends them to `baseline-kasm-install` on stdin through the guest agent. Existing disks are never replaced; a rebuilt VM reattaches them under the
   recorded VMID. The page `/workspaces` (and the Home, navigation and kiosk bookmark entries) shows the state and the link.
4. **Inside the guest, `baseline-kasm-install`** - `install.sh --install-profile noninteractive --accept-eula --no-start --use-static-images` with the offline
   service archive (lists no images: they are already loaded) and the two plugin archives; then `db_init` seeds the carried workspaces from the bundle's own list
   trimmed to what is carried (six entries, each with its own image id, the persistent ones with a profile path, and `group_images` rebuilt so users can see
   them); the Postgres data is copied to a bind volume on the admin disk and the stack is started by `baseline-kasm-start`; it waits for the health check and
   writes `installed.json` last.
5. **Every later boot** - `baseline-kasm.service` (in the base) mounts the disks by serial and runs `baseline-kasm-start`: the `kasm` user comes with the base,
   the Docker network and the DB volume binding are re-created (Docker's record of them is on the disposable root; the data is not), and `docker compose up -d` runs
   with no pulls.

## Workspaces offered (the user's choice of shape, from the reference conversation)
Browser (temporary, nothing kept), Browser (personal, its own profile), Development desktop, VS Code, Firefox, Terminal. A personal workspace must be started
with `persistent_profile_mode: Enabled`: neither the profile path nor the "enforce persistence" flag alone mounts it. Documents are meant to live in the user's
own data, not inside a profile. Resetting a profile through Kasm's API is destructive and, when built, goes through explicit authorization (not built).

## Verified, and how (QEMU test guest on this machine, no network: user-mode networking with `restrict=on`)
- The base builds in about 7 minutes plus flattening; **15.5 GiB** compressed, all 13 image digests recorded.
- Offline install on a fresh overlay: Kasm installed in 87 s with no registry access and reported healthy; the user signs in and sees the six workspaces.
- A personal session mounts the profile from the dedicated disk (`/mnt/kasm_profiles/<user>/<image>` -> `/home/kasm-user`); Postgres's data is on the admin
  disk (the volume is a bind onto `/opt/kasm/data/db`).
- **Reset-root proof (twice):** the overlay was thrown away and a new one booted over the same base and the same two disks: Kasm came back healthy without a
  reinstall, with the same user id and workspace ids, and a file written in the personal workspace before the reset was there afterwards. A file written in the
  temporary workspace was not there in the next temporary session.
Problems found on the way and fixed: no network in the build guest with an emulated e1000 NIC (virtio needed); a failed build step left the VM running (now a
failure marker and poweroff); a 22-character disk serial was truncated (limit 20); the seed rolled back silently because `group_images` named removed images and
`db_init -q` was wrong; `db_init -i` recreates the DB volume without the bind (copy then swap); a stopped container held the volume; the fresh root lacked the
`kasm` user and network and `bin/start` pulled `-rolling` images (own start script, `--use-static-images`); the installer fetches two Docker plugins from the registry
even in offline mode (now packed in the base).

## Not verified (each a step of the plan, not an assumption to hide)
- `kasm_setup.py` against a real Proxmox host (`pvesm`, `qm create` with directory-storage volumes, `qm guest exec`): unit-tested against a scripted fake only.
- The carried base inside the installer ISO and the first-boot path (a QEMU rehearsal of a whole new setup with Kasm). The ISO grows by the base's size
  (about 15.5 GiB) and INSTALLER_CACHE holds it twice (the ISO and its expanded copy).
- Nested virtualization: the Kasm VM inside a Proxmox that is itself a VM needs 8 GiB or more of memory to give it.
- Kasm Workspaces Community Edition is free to use and is **not fully open source** (the platform's license restricts it; KasmVNC and the workspace images are
  open). Used without activation; its limits apply. The page says so.
- Smaller base: the Ubuntu desktop image alone is about 11 GB uncompressed; dropping it (or carrying only Chrome and VS Code) cuts the base to a fraction.
  Open choice for the operator.
