# 118 — Real distro linked containers and requested-system status

Date: 2026-10-01 (operator timezone)
Status: accepted increment; physical deployment and requested desktop/NAS/mobile installs remain open.
Related: DR117; v0.2 queue rows 60, 72, 73.

## Decision and implementation

Add `/containers` to the authenticated Baseline web application. Use the actual host's `pveam available --section system` catalog, native checksum-verified `pveam download`, `pct create/template`, and `pct clone --full 0`. Only active LVM-thin or ZFS storage with rootdir content is offered for linked roots. Directory storage is not mislabeled as providing linked LXC overlays. This is native Proxmox copy-on-write, not OverlayFS. Containers share the substrate kernel; this does not provide a separate distro kernel, desktop or browser.

Keep three bind directories outside disposable OS/cache storage: `/home`, `/root`, `/data`. Unprivileged containers use the standard UID mapping (host 100000 = container root); custom mappings, changed identities, redirected paths, unexpected root volume ownership and additional mounts are refused before destructive rebuild. Rebuild requires clean shutdown, detaches binds before destroying only the OS container, then recreates the same CTID from its immutable template and reattaches retained data. Packages and `/etc` reset. Partial native failures retain explicit incomplete records and require inspection; no automatic destructive recovery.

Create a fresh high-entropy one-time root login with the existing project generator. Hash via the existing helper and set through `pct exec ... chpasswd -e` stdin, never command arguments. Persist only its hash in mode-0600 control metadata; return the password once to the authenticated admin, without URLs, audit logs or browser storage. Console mode requires login, not an autologin shell. Anonymous pages redirect to login and limited operator roles cannot access these controls.

Vanilla template archives remain structurally separate from protected bind data. Native download can return zero despite failing: require a real nonempty regular archive before allocation. Cache destinations through symlinks or under protected/disposable named volumes are refused. External paths including `/run/media/...` are valid; runtime account paths and system directories remain refused. No limitation to the physical Baseline drive is introduced.

## What actually ran

Real Proxmox 9.2.2, kernel 7.0.2-6-pve, in the approved disposable KVM clone of the existing Proxmox substrate. Physical backing opened read-only, writes in the `/tmp` qcow2 overlay. Neither physical SK hynix drive was written. This is actual native Proxmox execution inside QEMU/KVM, **not bare-metal deployment** and not a mock.

The live host returned 21 system templates in 12 families. For one chosen template per family, native download and setup were followed by actual boot, `/etc/os-release`, LVM clone origin, credential-hash match, writes to all three retained areas and a disposable `/etc` sentinel, clean shutdown, production rebuild, same CTID, retained content, reset OS sentinel and unchanged password hash. Eleven passed:

| Family | Actual guest release | CT/base |
|---|---|---|
| AlmaLinux | 10.0 | 105/104 |
| Alpine | 3.23.2 | 106/102 |
| Arch | rolling | 108/107 |
| CentOS Stream | 9 | 110/109 |
| Debian | 13.1 | 112/111 |
| Devuan | 5 | 114/113 |
| Fedora | 43 | 116/115 |
| Gentoo OpenRC | 2.17 | 118/117 |
| openSUSE Leap | 16.0 | 120/119 |
| Rocky | 10.0 | 122/121 |
| Ubuntu | 26.04 | 124/123 |

Exact archives, actual config and origin evidence: `docs/verification/118/distro-live.json`. These proofs establish boot and local data preservation, not all package installation, network/DNS behavior or every catalog version. ZFS remains unit-covered only; live execution used LVM-thin.

openEuler `openeuler-25.03-default_20250507_amd64.tar.xz` failed in `PVE::LXC::Setup::post_create_hook`. Cause is unresolved; no unsupported-version claim is made. This version's template is disabled in the selector and refused in production before allocation. Its failed preparing reservation recorded CT119, but Proxmox freed that ID and it was subsequently used by the valid openSUSE base. **Never destroy CT119 as cleanup for the failed openEuler record.** Incomplete metadata needs identity-aware inspection, not a blanket delete.

Authenticated real HTTP additionally created Alpine CT125 from base102, wrote a document and disposable OS file, cleanly shut it down, rebuilt through the web action, checked retained document/reset OS file, and shut it down again. Anonymous redirect and wrong synthetic root password HTTP401 were checked. Final deployed pages retain no cleartext credentials.

## Requested systems: do not substitute parent distributions

The user subsequently named SparkyLinux, MX Linux, Zorin OS, Bazzite, CachyOS, Omarchy, OpenMediaVault, ChromeOS and GrapheneOS. They are listed on `/vms` with official sources and explicit **not installed or boot-verified** status. No Debian template is called MX/Sparky/Zorin/OMV, no Arch template is called CachyOS/Omarchy, and no Fedora template is called Bazzite.

The web ISO path now exposes existing UEFI configuration and overlay retained-disk size selection. Unit tests verify these controls against fake hosts; this increment did not boot any requested ISO. Generic ISO installation → clean shutdown/eject → freeze as base → overlay is available, but distro-specific retained-home setup is not automated. Its separate blank retained disk is not mounted by magic. Do not reset an OS until actual filesystem/mount/profile preservation is verified. OMV needs separately retained NAS disks and ownership/backup/recovery controls, not just retained `/home`; those controls remain open.

Official references inspected:

- Sparky: https://sparkylinux.org/download/
- MX source: https://mxlinux.org/download-links/ (browser fetch failed; no release/image verification claimed)
- Zorin: https://zorin.com/os/download/
- Bazzite: https://bazzite.gg/ and https://docs.bazzite.gg/General/Installation_Guide/install-guide/ — OCI build format is not a ready LXC desktop.
- CachyOS: https://cachyos.org/download/
- Omarchy: https://omarchy.org/ — official ISO and VM trials; use actual installed desktop, not Arch relabeling.
- OMV: https://www.openmediavault.org/download.html and https://docs.openmediavault.org/en/stable/installation/index.html
- ChromeOS/Flex: https://support.google.com/chrome/a/answer/11542901 — Flex is distinct; no Google ChromeOS guest recipe implemented.
- GrapheneOS: https://grapheneos.org/build#emulator and https://grapheneos.org/faq#supported-devices — source-built x86_64 development emulator exists; it is not a production Pixel release or LXC image. Emulator integration is not implemented.

## Validation and remaining work

RED tests were activated before implementation. Unit native runners use fakes, socket tests use actual HTTP with fake Proxmox, and the full unit suite retains the hardware guard (extended to `pct/qm/pvesh/pvesm/pveam`). Actual Proxmox checks above are separate. Final test count and source fingerprints live in `docs/verification/118/README.md`.

**Bind mounts are not covered by vzdump** (https://raw.githubusercontent.com/proxmox/pve-docs/master/pct.adoc). Dedicated quiesced backup/restore remains row60. Physical named-volume mounts, full provision.sh deployment, host restart and production kiosk ordering remain row72. Requested distro installations, firmware/graphics/kernel compatibility, retained filesystem setup, OMV NAS disk controls, GrapheneOS emulator and ChromeOS deployment decisions remain row73. Docker is not implemented by this LXC increment. Harvester ACL/backend work remains open.

This extends DR117's Ubuntu/VM result without changing its historical evidence. Current INSTALL, layer documents and queue now distinguish real native LXC proof from requested systems still uninstalled. Historical records are append-only.
