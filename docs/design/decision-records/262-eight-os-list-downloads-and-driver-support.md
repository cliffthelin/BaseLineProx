# 262 - The eight supported operating systems, how their images were obtained, and driver support for two machines

Date: 2026-10-16. Status: list recorded (git-ignored); three missing images downloaded and verified (see below); driver mapping verified against Debian 13's file index;
NOT yet rebuilt into the installer's offline cache or ISO, and the Latitude's profile is not confirmed against the machine itself.

## Operator instruction (2026-10-16)
"It used to be: Omarchy, Catchy, Debian, Qubes, NixOS, FydeOS, Bazzite and Ubuntu. Get them from DistroWatch unless you have a better plan. I downloaded them all before and
they were included in the installer cache along with the applications list that are to be installed and configured for each. Also driver support for the current machine and
for a Dell Latitude 5290, I believe the test laptop."

## The list (kept in `config/local/supported-os.json`, git-ignored, DR261)
Omarchy, CachyOS ("Catchy" is taken to mean CachyOS: please say if another system was meant), Debian 13, Qubes OS 4.3, NixOS 26.05, FydeOS, Bazzite, Ubuntu 26.04, plus the Kasm
entry (DR260). Each lists the applications to install and configure on it: the five of DR258 (VS Code, Spotify, Chrome, ChatGPT, Claude) for every OS, because no per-OS list
exists anywhere in the repository or in this conversation (DR258 question 1 is still open). `environments.py` now recognises Qubes, FydeOS and Bazzite; like every non-Debian/Ubuntu
system they are marked "helper" (the application bundle supports Ubuntu and Debian only), not "native".

## Images: what was already here, what was fetched, and why not DistroWatch
Already in `/mnt/INSTALLER_CACHE/isos` (and `~/.ubuntu26-usb`): Omarchy 4.0.4, CachyOS 260809, NixOS 26.05, Ubuntu 26.04.1 desktop, FydeOS v23.0 Preview 2 (an OVA), plus MX Linux and
SystemRescue, which are not on the list and were left alone. **Missing and downloaded:** Debian 13.7.0 DVD-1, Qubes OS R4.3.2, Bazzite stable (standard, not the NVIDIA variant).
DistroWatch only links to each project's own download page, so they were fetched from the projects themselves, where the signatures and checksums are published.
Verification (each as far as the project allows):
- **Debian:** `SHA512SUMS` verified against the Debian CD signing key (fingerprint DF9B 9C49 EAA9 2984 3258 9D76 DA87 E80D 6294 BE9B, which is the published one), then the ISO against it.
- **Qubes:** the Qubes master signing key's fingerprint was compared with the published 427F 11FD 0FAA 4B08 0123 F01C DDFA 1A3E 3687 9494; the release key is signed by it; the ISO's
  detached signature and the signed DIGESTS were checked with the release key.
- **Bazzite:** only a SHA-256 checksum served from the same host is published, which guards against a damaged download, not a tampered server. That is stated, not hidden.
The images were fetched into `/run/media/cane/CACHE/baseline-build/os-images` first and moved into `/mnt/INSTALLER_CACHE/isos` only after verification, then checked again in place.
**One download failed verification and was discarded:** the first Qubes file was damaged because two downloads of it overlapped (a slow mirror was replaced by the faster official server
mid-way, and the first process was still writing). Its size was wrong and the signature was BAD; it was deleted and fetched again once, and then verified. A size check alone would not
have been enough; the signature check is what caught it.
Final state: Debian 13.7.0 DVD-1 (4.0 GB, signature and SHA-512 good), Qubes R4.3.2 (8.5 GB, signature and SHA-256 good), Bazzite stable (7.9 GB, SHA-256 matches the published value).
That put the machine's root filesystem (where this cache lives) at 95% full, 50 GB free.

## Driver support (`driver_profiles.py`, `baseline-drivers`)
Package names were checked against Debian 13's own file index by the firmware file each kernel driver requests, not remembered:
MT7921K Wi-Fi and Bluetooth: `firmware-mediatek`; Intel Wireless-AC 8265 and its Bluetooth: `firmware-iwlwifi`; Kaby Lake graphics: `firmware-intel-graphics`; the Wi-Fi regulatory
database: `wireless-regdb`; CPU microcode: `amd64-microcode`/`intel-microcode`.
- **This machine** (ASUS desktop, Ryzen 9 7900X): read from its own `lspci`/`lsusb`: needs `amd64-microcode`, `firmware-mediatek`, `wireless-regdb`. The Intel I225-V and the NVMe drives need
  no firmware package; the RTX 3070 and Tesla P40 need none from Debian's firmware archive (a host NVIDIA driver is a separate choice; the cards are for passthrough).
- **Dell Latitude 5290:** `intel-microcode`, `firmware-iwlwifi`, `firmware-intel-graphics`, `wireless-regdb`. **Not confirmed**: derived from its journal (i915, an Intel Bluetooth controller,
  `regulatory.db` failing to load, which is a real gap `wireless-regdb` closes) and Dell's published configuration. `baseline-drivers` run on the laptop settles it.
- The installer cache's firmware catalog is now fed with these (three new packages), so a rebuilt cache carries them. **A cache built before this fails the "built for" check until it is
  rebuilt**, by design; the rebuild (a throwaway Proxmox install, with internet) has not been run.
- `baseline-drivers` reports "n/a" rather than "missing" off Debian proper (Ubuntu ships firmware in one `linux-firmware` package).

## Not done
Rebuilding the offline cache and the installer ISO with the new images and packages; reading the Latitude's real hardware; wiring the list into the launcher and the installer's image
offer; the per-OS application lists beyond the five-for-all default; the Qubes-specific handling (it is Xen-based and needs its own install path); FydeOS is a preview OVA.

## Update (same day): Baseline owns the list; Proxmox and Kasm read it
Operator agreed to the split proposed after DR262 was first written.
- **Carried by the installer:** the installer ISO's staging copies the private working list to `config/supported-os.json` next to the source; first boot's new `os-list` step copies it to
  `/mnt/USER_ADMIN/config/supported-os.json` (validated first; a list the host already has is never overwritten; a bad or absent list never stops the install).
  It travels on the ISO rather than in the offline cache so a list change does not mean rebuilding the 19 GB cache.
- **Which images the installer offers** follow the list (in its order, FydeOS's OVA included; an image the list names but the cache lacks is reported). An explicit `--os-iso`
  and the rehearsal's smallest-image default still win.
- **Proxmox side:** the Environments page is built from the list's VM entries (their apps, "not planned" for the rest, "image missing" when the cache lacks the file); with no usable
  list it shows every carried image as before and says why.
- **Kasm side:** a Kasm entry may name its workspaces (`workspaces: [{key, image, friendly_name, persistent}]`); `baseline-build-kasm-base` carries exactly those, and the Workspaces page
  shows what the carried base's manifest says it holds. A different set means rebuilding the base (the images are preloaded), not editing it live.
- **`baseline-allscript-install --kasm-base DIR`** makes the cache carry the base, and treats a cache without it as stale; the rehearsal VM is now 16 GiB with a 128 GiB sparse disk so Kasm's VM
  fits inside it.

## Update: the launcher shows what the list asks for and is not built yet
The launcher's home screen gains an "Available to create" row of dashed tiles, one per VM entry in the supported-OS list that has no VM yet (Kasm is not a guest OS and is not a tile): the OS
name, whether its image is carried ("not built · create" or "not built · image missing"), and a link to Virtual machines to create it. Built systems stay ordinary tiles. A list that cannot be
read is a notice and never hides the tiles; no list means no row. The tile does not create the VM itself: creation stays in Virtual machines. Checked in the browser with a sample state; the
unit tests cover the model, the state and the real route.

## Update: the tiles create the VM
An "Available to create" tile now creates the VM: a confirmation names the sizes (disk, memory, CPUs, UEFI) and the image, then it posts the existing `create_iso` action, so it runs through the
same job machinery and audit as Virtual machines. The VM is created stopped. Starting sizes per system are in `os_profiles.py` (Omarchy 64 GB / 8 GiB / 4 CPUs, CachyOS 64/6/4, Debian 32/4/2,
NixOS 40/4/2, Bazzite 80/8/4, Ubuntu 40/4/2; anything else 32/4/2) and are starting points, not requirements published by the projects; memory is cut to half of a small host's, and a host with
under 4 GiB is refused. Two entries are **refused with a reason shown on the tile** rather than created badly: **Qubes** (it runs its own Xen hypervisor and wants the hardware to itself) and
**FydeOS** (an OVA appliance; importing appliances is not built). So is any entry whose image is not carried. Checked in the browser (blocked tile explains itself; an allowed tile posts exactly the
create action); the plans and the route are unit-tested. Not yet run against a real Proxmox host.
Also: `provision.sh` now stages `os_profiles.py`, `driver_profiles.py` and `baseline-drivers`; a guard test caught the first of these missing.

## Verified: the list reaches USER_ADMIN on a real installed host
The installed system from rehearsal run 24 (whose ISO predated the `os-list` step) was booted as a throwaway overlay (the original disk untouched) with this repository shared read-only into it, and
the real `step_os_list` from `baseline-first-boot-install` was run inside it against the real working list: 9 entries were carried to `/mnt/USER_ADMIN/config/supported-os.json` (root, mode 0644, folder
created), the step's record was written, and `os_list.load()` with no arguments then read the 9 ids back from that host copy. Not exercised: the ISO staging copy end to end in a rebuilt installer
(unit-tested), and a second run being a no-op (unit-tested).

## Verified: a tile's plan creates a VM on a real Proxmox, and two bugs that only a real host showed
On the installed rehearsal host (a throwaway overlay of it, the real VM library, nested KVM) the launcher's plan for a listed entry was handed to the real `create_iso` action: VM 101 was created with
OVMF firmware and an EFI disk, the carried 2.2 GB image attached as its cdrom, a 32 GB disk on the user volume, 4 GiB of memory, and it started and ran.
That first run found, and a second run confirmed fixed:
- **Image names:** Proxmox names images by volume (`installer-cache:iso/<file>`), while the list gives plain file names. Matching whole names would have marked every listed image "missing" on a real host (the
  unit tests had used a local folder's plain names). Matching is now on the file name (`environments.match_image`), and the plan carries the name the host itself uses, which is what `create_iso` looks up.
- **The Kasm seed in the image picker:** the Kasm VM's cloud-init seed ISO was listed first among the images to install, because its storage is registered with ISO content. That storage is now hidden from the
  image list (`HIDDEN_ISO_STORAGES`).
Still the case (not mine, left as it was): the per-VM installer copies in `baseline-os` also appear in that image list.
