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

## Open points

- Where the persisted overlay for a VM lives (USER_ADMIN holds personal data; an APPDATA_* volume holds an application's data).
- SESSION_TEMP is currently mounted `noexec` and capped at 50 GiB; hosting VM disks needs its ceiling and clear-policy revisited.
- Whether the old 1 GB SUBSTRATE (recovery config, admin passphrase hash) belongs in USER_ADMIN, since the hash is not generic.
