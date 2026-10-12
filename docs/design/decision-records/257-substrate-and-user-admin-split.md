# DR257 - SUBSTRATE is the publishable build; USER_ADMIN is everything personal; VMs live in SESSION_TEMP over a persisted overlay

Date: 2026-10-11. Status: design stated by the operator; audit done; nothing implemented yet. Supersedes the generic Proxmox names
(`root`, `swap`, `data`) in every report, plan and layout: only the agreed role names are used.

## The design (operator, 2026-10-11)

- **SUBSTRATE** is the Proxmox *build*: the GUI and kernel, the browser, the firewall, the Proxmox tools and the BASELINE OS. It is generic.
  It could be published openly and would reveal nothing about the computer, the user or their data. It is what the Proxmox installer calls
  `root`.
- **USER_ADMIN** holds every non-generic thing that belongs to that SUBSTRATE: personal configuration, installation details, browser use,
  credentials, PII, secure data. It must never be published.
- **SESSION_TEMP** replaces `swap` (swap space lives in it) and replaces `data`: virtual machines are built into SESSION_TEMP.
- **Overlay rule for VMs.** A fresh spin-up from INSTALLER_CACHE is not required every time, but the overlay that captures the differences
  is: the user gets the exact same result whether the VM was spun up from installation or kept across a restart, a reboot or to save loading
  time. The base image is reproducible from INSTALLER_CACHE; the user's differences are the persisted overlay.

## What the audit found on PC601 (rebuilt 2026-10-11)

Already on USER_ADMIN (bind-mounted by persist_bind_mounts): `/etc/baseline`, `/var/lib/baseline`, `/var/log/baseline`.
Still on the volume that is to become SUBSTRATE, and personal or machine-specific, so SUBSTRATE is **not publishable today**:

| Path | Why it is personal | Action |
|---|---|---|
| `/etc/shadow`, `/root`, `/root/.ssh`, `/home/*` | credential hashes, keys, user data | redirect to USER_ADMIN |
| `/etc/ssh` (host keys) | private host keys | redirect |
| `/var/lib/pve-cluster` (and `/etc/pve` made from it) | Proxmox users, ACLs, certificates, private keys | redirect, before pve-cluster starts |
| `/var/lib/pve-firewall`, `/var/lib/pve-manager`, `/var/lib/rrdcached` | rules, task history, metrics of this host | redirect |
| `/var/log` (journal, auth, pveproxy) | logins, addresses, activity | redirect |
| `/etc/machine-id`, `/etc/hostname`, `/etc/hosts`, `/etc/network/interfaces` | identify this machine; contain addresses | generic placeholder in SUBSTRATE, real file from USER_ADMIN, before networking |
| `/etc/baseline-dev` | development login hash | redirect (dev only) |
| Chromium kiosk profile (`--user-data-dir=/mnt/APPDATA_ADMIN/chromium/kiosk`) | browser use | move to USER_ADMIN; it is on APPDATA_ADMIN today |

## Consequences to build, in order

1. Rename the Proxmox volumes to the role names and drop the generic ones: host OS volume -> SUBSTRATE (the separate 1 GB SUBSTRATE
   role is merged into it), swap -> a swap file in SESSION_TEMP, `data` pool removed, `local-lvm` unregistered from Proxmox.
2. Extend the redirect list (`persist_bind_mounts.REDIRECT_PATHS`) with the paths above, with correct boot ordering for each. Risky ones
   (`/etc/shadow`, `/etc/ssh`, `/var/lib/pve-cluster`, network files) are tested in the rehearsal VM first, because a wrong order means no
   login or no network.
3. A publishability check: scan SUBSTRATE for anything not generic (keys, hashes, addresses, machine-id, user names) and fail the build if
   found.
4. VM storage: base images from INSTALLER_CACHE, per-VM overlay persisted (outside SESSION_TEMP's clear), running disks in SESSION_TEMP;
   the same result from a fresh spin-up or a kept overlay.

## Decisions added by the operator (2026-10-11, second message)

- **VMs never write to USER_ADMIN.** A VM's persisted overlay goes to **USER_DATA** (the user's volume: `USER_<PERSONA>`) or **APP_DATA**
  (`APPDATA_<PERSONA>`), depending on the data.
- **A VM behaves like an Ubuntu installer drive** that loads all of the user's data, the installed applications and their app data, with
  everything needed to overlay it again held in one of those two volumes.
- **USER_DATA holds the association to APP_DATA** (user x OS -> app-data tree) so the right app data is shown per user and per OS.
- **The admin passphrase verifier moves to USER_ADMIN** with a locked-in lookup: the system finds it there and nowhere else. It must be
  protected even inside USER_ADMIN so that opening the volume does not reveal it, yet the system can tell when it is given correctly.
- **SESSION_TEMP's limits are to be discussed** (below).

## Resulting VM layering

| Layer | Where | Lifetime |
|---|---|---|
| Base: the OS image | INSTALLER_CACHE (read-only, reproducible; a fresh spin-up from it is optional) | permanent |
| Session layer: the VM's running writes | SESSION_TEMP (a copy-on-write disk over the base) | ephemeral |
| User overlay: the user's data and settings | USER_DATA | persisted |
| App overlay: installed applications and their data | APP_DATA, selected through the association held in USER_DATA | persisted |

Spin-up applies base + user overlay + app overlay; a kept session and a fresh one therefore give the same result.

## Does Proxmox support this? Tested, 2026-10-11 (PC601, writes discarded)

The layering above needs nothing outside Proxmox. On the real PC601 each role volume was registered as a plain directory storage
(`pvesm add dir ... --content images`) and one VM was created that Proxmox accepted and started:

| Layer | Placed on | Proxmox view |
|---|---|---|
| Base OS | an ISO in INSTALLER_CACHE (already Proxmox ISO storage `baseline-isos`) | `ide2` CD-ROM |
| Session disk | qcow2 on SESSION_TEMP | `scsi0` |
| User overlay | qcow2 on USER_<PERSONA> (USER_DATA) | `scsi1` |
| App overlay | qcow2 on APPDATA_<PERSONA> (APP_DATA) | `scsi2` |

Proxmox then manages these as ordinary VM disks (snapshots, backup, console). What it does not do, and Baseline must:

- **Merge the layers inside the guest.** Proxmox attaches disks; the guest OS must combine them. This is OS-specific: Ubuntu's live ISO has a
  persistence mechanism, the other carried images (MX, CachyOS, NixOS, omarchy, jrescue) differ or need a first-boot step. It is the real limit
  on "the same result fresh or kept", so a per-OS adapter is part of the work.
- **Hold the association** user x OS -> app-data tree (kept in USER_DATA) and attach the right disks through Proxmox's API.
- **Bound virtual size.** A qcow2 may claim more space than its role volume has (a 1 GiB disk on a 974 MiB volume works while sparse); virtual
  disk sizes must be capped to what the volume can grow to (volume_growth.py), or the disk fails late.

## Naming of things that run

Not everything is a VM image, so no umbrella term such as "Baseline VM image" is used. The kinds are:

- **Things Proxmox runs:** a VM image (ISO or disk) and an LXC template. Containers already follow this pattern in the repo: an immutable
  template, a disposable OS layer, and retained `/home`, `/root`, `/data` folders that survive a rebuild.
- **Applications packaged as Flatpak, AppImage, Snap, Nix or OCI images:** not Proxmox objects; they run inside a VM or container and keep
  their data in APP_DATA.

naming.py already encodes this with a medium letter (V VM, L LXC, C OCI, F Flatpak, A AppImage, S Snap, N Nix, D deb, I ISO), and the
identifier scheme (DR255) already has the kinds `vm` (a VM or a container) and `application`. Those terms stay.

## Proposed defaults for SESSION_TEMP (for discussion)

Keep it `noexec` (it holds disk images, not programs the host runs). Remove the 50 GiB ceiling and let volume growth extend it on demand.
Clear the session layer when a VM is stopped and not marked "keep", never the overlays.

## Passphrase verifier (proposal)

Store only a verifier, never the passphrase: a memory-hard hash (argon2id) of the passphrase combined with a secret that is not in USER_ADMIN
(sealed to the TPM when there is one, else derived from the machine's own protected key material), so a copy of the volume alone cannot be
attacked offline, while the running system can still check a given passphrase.

## Open points

- Whether the secret for the verifier is TPM-sealed or derived (this drive moves between machines, which argues for derived).
