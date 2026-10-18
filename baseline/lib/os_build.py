"""Ready-made VMs: each listed operating system installed unattended, with its applications, into a base disk (DR258, DR267; operator 2026-10-17).

A base is built once, in QEMU on the build machine, from the image the installer already carries, and then used the way the Kasm base is: carried read-only, with a per-VM layer over it.
It holds NO account and NO secret: the first boot creates the person's account from a seed (cloud-init's NoCloud, `cidata`, or the operating system's own equivalent), so the same base
serves everyone and nothing of anyone's is in it (DR258 decision 5).

This module is the part with no side effects: the answer files, the way an answer file is put into an installer's initrd, and the guest script that installs the applications. The runner
that boots QEMU is `baseline-build-os-base`. Every operating system has its own unattended mechanism, and the table below says which and whether it has been run here.
"""
from __future__ import annotations

import gzip
import io
import re
import struct

# id -> how it is built unattended, and what is true of it. `verified` is only ever set when the build was run to the end here and the result booted.
METHODS = {
    "debian": {"method": "preseed answer file appended to the installer's initrd, booted straight from the carried DVD", "network": "mirror (cloud-init is not on the DVD)"},
    "ubuntu": {"method": "the Ubuntu cloud image with the desktop installed by cloud-init", "network": "required"},
    "omarchy": {"method": "the ISO's own unattended install: a drive labelled cidata with user_configuration.json and defer-provisioning", "network": "first boot only"},
    "nixos": {"method": "the live ISO driven over its serial console: partition, then nixos-install from a configuration", "network": "required"},
    "bazzite": {"method": "an Anaconda kickstart on an OEMDRV drive", "network": "not known"},
    "cachyos": {"method": "no unattended installer is documented: the live image's root is copied to the disk and a bootloader installed from the live system", "network": "not known"},
    "fydeos": {"method": "the VMware appliance (OVA) converted to a disk; not an installer", "network": "none"},
    "qubes": {"method": "an Anaconda kickstart for real hardware only: Qubes does not support running under another hypervisor", "network": "not known"},
}


class BuildError(ValueError):
    pass


# ---- answer files into an installer's initrd ------------------------------------------------------------------------------------------
def _cpio_newc(files: dict) -> bytes:
    """A newc cpio archive of {name: bytes}, which the kernel unpacks over the initramfs when it is appended to it (concatenated archives are valid)."""
    out = io.BytesIO()
    for index, (name, data) in enumerate(files.items(), start=1):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name):
            raise BuildError(f"{name!r} is not a plain file name")
        encoded = name.encode() + b"\0"
        header = "070701" + "".join(f"{v:08x}" for v in (index, 0o100644, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0))
        out.write(header.encode() + encoded)
        out.write(b"\0" * (-(110 + len(encoded)) % 4))
        out.write(data)
        out.write(b"\0" * (-len(data) % 4))
    trailer = b"TRAILER!!!\0"
    out.write(("070701" + "".join(f"{v:08x}" for v in (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(trailer), 0))).encode() + trailer)
    out.write(b"\0" * (-(110 + len(trailer)) % 4))
    return out.getvalue()


def initrd_with(initrd: bytes, files: dict) -> bytes:
    """The installer's initrd with `files` added at its root (a Debian installer reads /preseed.cfg from there by itself)."""
    return initrd + gzip.compress(_cpio_newc(files), 6)


# ---- Debian --------------------------------------------------------------------------------------------------------------------------
DEBIAN_TASKS = "standard, gnome-desktop"
DEBIAN_PACKAGES = ("cloud-init", "qemu-guest-agent")


def debian_preseed(*, disk="/dev/vda", hostname="debian", tasks=DEBIAN_TASKS, packages=DEBIAN_PACKAGES, mirror="deb.debian.org", late_command="") -> str:
    """The answers that make Debian's installer run without a question. The account is locked and has no password (`!`), and root cannot log in: the person's account comes from the first
    boot's seed. A removable-path EFI loader is forced so the disk boots under whatever firmware variables the VM it is later used in has."""
    if not re.fullmatch(r"/dev/[a-z0-9]+", disk) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", hostname) or not re.fullmatch(r"[A-Za-z0-9.-]+", mirror):
        raise BuildError("disk, hostname or mirror is not a plain value")
    if not re.fullmatch(r"[a-z0-9, -]+", tasks) or not all(re.fullmatch(r"[a-z][a-z0-9+.-]+", p) for p in packages):
        raise BuildError("tasks or packages are not plain values")
    lines = [
        "d-i debian-installer/locale string en_US.UTF-8", "d-i keyboard-configuration/xkb-keymap select us", "d-i keyboard-configuration/layoutcode string us",
        "d-i keyboard-configuration/modelcode string pc105", "d-i keyboard-configuration/variantcode string",
        "keyboard-configuration keyboard-configuration/layout select English (US)", "keyboard-configuration keyboard-configuration/variant select English (US)",
        "d-i netcfg/choose_interface select auto", f"d-i netcfg/get_hostname string {hostname}", "d-i netcfg/get_domain string localdomain", f"d-i netcfg/hostname string {hostname}",
        "d-i mirror/country string manual", "d-i mirror/protocol string http", f"d-i mirror/http/hostname string {mirror}", "d-i mirror/http/directory string /debian", "d-i mirror/http/proxy string",
        "d-i passwd/root-login boolean false", "d-i passwd/make-user boolean true", "d-i passwd/user-fullname string Baseline administrator", "d-i passwd/username string baseline-admin",
        "d-i passwd/user-password-crypted password !",
        "d-i clock-setup/utc boolean true", "d-i time/zone string UTC", "d-i clock-setup/ntp boolean false",
        f"d-i partman-auto/disk string {disk}", "d-i partman-auto/method string regular", "d-i partman-auto/choose_recipe select atomic", "d-i partman-partitioning/confirm_write_new_label boolean true",
        "d-i partman/choose_partition select finish", "d-i partman/confirm boolean true", "d-i partman/confirm_nooverwrite boolean true",
        "d-i apt-setup/cdrom/set-first boolean false", "d-i apt-setup/cdrom/set-next boolean false", "d-i apt-setup/cdrom/set-failed boolean false",
        "d-i apt-setup/disable-cdrom-entries boolean true", "d-i apt-setup/use_mirror boolean true", "d-i apt-setup/non-free-firmware boolean true",
        f"tasksel tasksel/first multiselect {tasks}", f"d-i pkgsel/include string {' '.join(packages)}", "d-i pkgsel/upgrade select none",
        "popularity-contest popularity-contest/participate boolean false",
        "d-i grub-installer/only_debian boolean true", "d-i grub-installer/bootdev string default", "d-i grub-installer/force-efi-extra-removable boolean true",
        "d-i finish-install/reboot_in_progress note", "d-i debian-installer/exit/poweroff boolean true",
    ]
    if late_command:
        if "\n" in late_command:
            raise BuildError("a late command is one line")
        lines.append(f"d-i preseed/late_command string {late_command}")
    return "\n".join(lines) + "\n"


# ---- the applications ------------------------------------------------------------------------------------------------------------------
APPS_LABEL = "BASELINE-APPS"
PREBUILT_RECORD = "/var/lib/baseline/prebuilt.json"
VSCODE_DESKTOP = """[Desktop Entry]
Name=Visual Studio Code
Exec=/opt/vscode/code --no-sandbox %F
Icon=/opt/vscode/resources/app/resources/linux/code.png
Type=Application
Categories=Development;IDE;
Terminal=false
"""


def debian_apps_script(apps: dict) -> str:
    """Runs INSIDE the new system (Debian or Ubuntu) with the payload mounted at /mnt/payload: checks every package against the SHA-256 the build machine recorded when it fetched it from the
    publisher, installs each, and writes a record of what is installed. `apps` is {app: {file, medium, version, sha256, url}} as the build machine recorded it."""
    lines = ["#!/bin/sh", "set -eu", "export DEBIAN_FRONTEND=noninteractive", "cd /mnt/payload", "mkdir -p /var/lib/baseline", "installed=''"]
    for app, info in apps.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", app) or not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", info["file"]) or info["medium"] not in ("deb", "tar.gz"):
            raise BuildError(f"{app}: not a plain application entry")
        if not re.fullmatch(r"[0-9a-f]{64}", info.get("sha256") or ""):
            raise BuildError(f"{app}: no SHA-256 was recorded for it")
        if not re.fullmatch(r"[A-Za-z0-9.+:~_-]{1,128}", info.get("version") or ""):
            raise BuildError(f"{app}: its version is not a plain value")
        path = f"{app}/{info['file']}"
        lines.append(f"echo '{info['sha256']}  {path}' | sha256sum -c -")
        if info["medium"] == "deb":
            lines.append(f"apt-get install -y ./{path}")
        else:                                           # an editor shipped as a tarball: unpacked under /opt with a launcher
            lines += [f"mkdir -p /opt/{app}", f"tar -xzf {path} -C /opt/{app} --strip-components=1",
                      f"if [ -e /opt/{app}/chrome-sandbox ]; then chown root:root /opt/{app}/chrome-sandbox; chmod 4755 /opt/{app}/chrome-sandbox; fi",
                      f"ln -sf /opt/{app}/bin/code /usr/local/bin/code", "mkdir -p /usr/share/applications", f"cat > /usr/share/applications/{app}.desktop <<'DESKTOP'",
                      VSCODE_DESKTOP.rstrip("\n"), "DESKTOP"]
        lines.append(f"installed=\"$installed {app}={info['version']}\"")
    lines.append(f"printf '{{\"installed\": \"%s\"}}\\n' \"$installed\" > {PREBUILT_RECORD}")
    return "\n".join(lines) + "\n"


# ---- Ubuntu (the cloud image, with the desktop installed by cloud-init) -----------------------------------------------------------------
UBUNTU_PACKAGES = ("ubuntu-desktop-minimal", "qemu-guest-agent")


def ubuntu_cloud_config(*, packages=UBUNTU_PACKAGES) -> str:
    """The cloud-init user-data for the BUILD run: install the desktop, run the application script from the payload drive, and power off. It creates no account (the cloud image's default
    user has no password and no key), and the build's cloud-init state is cleaned afterwards so a later first boot reprovisions from its own seed."""
    if not all(re.fullmatch(r"[a-z][a-z0-9+.-]+", p) for p in packages):
        raise BuildError("packages are not plain values")
    listing = "\n".join(f"  - {p}" for p in packages)
    return f"""#cloud-config
package_update: true
packages:
{listing}
runcmd:
  - [sh, -c, "mkdir -p /mnt/payload && mount -o ro /dev/disk/by-label/{APPS_LABEL} /mnt/payload && sh /mnt/payload/install-apps.sh > /var/log/baseline-apps.log 2>&1 || touch /var/log/baseline-apps-failed; umount /mnt/payload || true"]
  - [systemctl, enable, qemu-guest-agent]
power_state:
  mode: poweroff
  timeout: 30
  condition: true
"""


# ---- NixOS (the live ISO's installer, run from a script) ---------------------------------------------------------------------------------
NIX_PACKAGES = ("vscode", "google-chrome", "spotify")
NIX_MISSING_APPS = ("chatgpt", "claude")        # no nixpkgs package for these two: they are reported as needing a helper, never silently skipped


def nix_configuration(*, packages=NIX_PACKAGES) -> str:
    """configuration.nix for the base. File systems are named by LABEL and the initrd carries the virtio, SCSI, SATA and NVMe drivers so the disk boots in whichever VM it is used in; GRUB is
    installed to the removable EFI path, so no firmware variable is needed. There are no users: the first boot's cloud-init (or the person) creates the account."""
    if not all(re.fullmatch(r"[a-z][a-z0-9_.-]*", p) for p in packages):
        raise BuildError("packages are not plain values")
    listing = " ".join(packages)
    return f"""{{ config, pkgs, ... }}:
{{
  boot.loader.grub = {{ enable = true; efiSupport = true; efiInstallAsRemovable = true; device = "nodev"; }};
  boot.loader.efi.canTouchEfiVariables = false;
  boot.initrd.availableKernelModules = [ "virtio_pci" "virtio_blk" "virtio_scsi" "sd_mod" "sr_mod" "ahci" "nvme" "xhci_pci" "usbhid" ];
  fileSystems."/" = {{ device = "/dev/disk/by-label/nixos"; fsType = "ext4"; }};
  fileSystems."/boot" = {{ device = "/dev/disk/by-label/ESP"; fsType = "vfat"; }};
  networking.hostName = "nixos";
  networking.networkmanager.enable = true;
  time.timeZone = "UTC";
  services.xserver.enable = true;
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;
  services.qemuGuest.enable = true;
  services.cloud-init.enable = true;
  services.cloud-init.network.enable = true;
  nixpkgs.config.allowUnfree = true;
  environment.systemPackages = with pkgs; [ {listing} ];
  system.stateVersion = "26.05";
}}
"""


NIX_PARTITION = ["parted -s /dev/vda mklabel gpt mkpart ESP fat32 1MiB 513MiB set 1 esp on mkpart root ext4 513MiB 100%",
                 "mkfs.fat -F32 -n ESP /dev/vda1", "mkfs.ext4 -q -L nixos /dev/vda2",
                 "mount /dev/disk/by-label/nixos /mnt", "mkdir -p /mnt/boot /mnt/etc/nixos", "mount /dev/disk/by-label/ESP /mnt/boot"]


# ---- Omarchy (the ISO's own unattended install) -------------------------------------------------------------------------------------------
OMARCHY_PACKAGES = ("base-devel", "git", "omarchy-keyring", "omarchy-settings", "omarchy", "omarchy-nvim", "qemu-guest-agent")
OMARCHY_MIRRORS = ("https://mirror.omarchy.org/$repo/os/$arch", "https://mirror.rackspace.com/archlinux/$repo/os/$arch", "https://geo.mirror.pkgbuild.com/$repo/os/$arch")
_MIB, _GIB = 1024 * 1024, 1024 * 1024 * 1024


def _size(value: int) -> dict:
    return {"sector_size": {"unit": "B", "value": 512}, "unit": "B", "value": value}


def omarchy_user_configuration(*, disk_bytes: int, disk="/dev/vda", hostname="omarchy", timezone="UTC", keyboard="us", kernel="linux-omarchy", packages=OMARCHY_PACKAGES,
                               services=("qemu-guest-agent",), encrypt=False) -> str:
    """`user_configuration.json` as Omarchy's own configurator writes it for a full-disk, deferred-provisioning install (read from the configurator inside the carried ISO, schema 3.0.9):
    the owner is created at the first boot, so nothing personal is in it. Encryption is off by default for a VM base: a passphrase prompt at every boot suits a laptop, not a VM whose
    disk is protected by the storage under it, and an encrypted base would need a throwaway passphrase kept somewhere."""
    if not re.fullmatch(r"/dev/[a-z0-9]+", disk) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", hostname) or not re.fullmatch(r"[A-Za-z0-9_/+-]{1,40}", timezone) \
            or not re.fullmatch(r"[a-z]{2,10}", keyboard) or not re.fullmatch(r"linux[a-z0-9-]*", kernel):
        raise BuildError("disk, hostname, timezone, keyboard or kernel is not a plain value")
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._-]*", p) for p in (*packages, *services)):
        raise BuildError("packages or services are not plain values")
    if disk_bytes < 20 * _GIB:
        raise BuildError("Omarchy needs a disk of at least 20 GiB")
    boot_start, boot_size = _MIB, 2 * _GIB
    main_start = boot_start + boot_size
    main_size = disk_bytes // _MIB * _MIB - main_start - _MIB
    boot_id, main_id = "ea21d3f2-82bb-49cc-ab5d-6f81ae94e18d", "8c2c2b92-1070-455d-b76a-56263bab24aa"
    disk_config = {"config_type": "default_layout", "device_modifications": [{"device": disk, "wipe": True, "partitions": [
        {"btrfs": [], "dev_path": None, "flags": ["boot", "esp"], "fs_type": "fat32", "mount_options": [], "mountpoint": "/boot", "obj_id": boot_id, "size": _size(boot_size),
         "start": _size(boot_start), "status": "create", "type": "primary"},
        {"btrfs": [{"mountpoint": "/", "name": "@"}, {"mountpoint": "/home", "name": "@home"}, {"mountpoint": "/var/log", "name": "@log"}, {"mountpoint": "/var/cache/pacman/pkg", "name": "@pkg"}],
         "dev_path": None, "flags": [], "fs_type": "btrfs", "mount_options": ["compress=zstd"], "mountpoint": None, "obj_id": main_id, "size": _size(main_size),
         "start": _size(main_start), "status": "create", "type": "primary"}]}]}
    if encrypt:
        disk_config["disk_encryption"] = {"encryption_type": "luks", "lvm_volumes": [], "iter_time": 2000, "partitions": [main_id]}
    document = {
        "app_config": None, "archinstall-language": "English", "auth_config": {}, "audio_config": {"audio": "pipewire"},
        "bootloader_config": {"bootloader": "Limine", "uki": False, "removable": False}, "custom_commands": [],
        "omarchy_install": {"input_method": "none", "input_xkb_layout": "", "mode": "full_disk", "defer_provisioning": True, "target_mount": "/mnt",
                            "boot": {"esp_mount": "/boot", "esp_path": "/EFI/limine", "efi_binary": "limine_x64.efi", "enable_fallback": True}, "storage": {"kernel": kernel}},
        "disk_config": disk_config, "hostname": hostname, "kernels": [kernel], "network_config": {"type": "iso"}, "ntp": True, "parallel_downloads": 8, "script": None,
        "services": list(services), "swap": True, "timezone": timezone, "locale_config": {"kb_layout": keyboard, "sys_enc": "UTF-8", "sys_lang": "en_US.UTF-8"},
        "mirror_config": {"custom_repositories": [], "custom_servers": [{"url": u} for u in OMARCHY_MIRRORS], "mirror_regions": {}, "optional_repositories": []},
        "packages": list(packages), "profile_config": {"gfx_driver": None, "greeter": None, "profile": {}}, "version": "3.0.9"}
    import json
    return json.dumps(document, indent=4) + "\n"


def omarchy_cidata(*, disk_bytes: int, encrypt=False, **kw) -> dict:
    """The files of the `cidata` drive: the configuration, the marker that defers the account to the owner's first boot, and the encryption choice."""
    return {"user_configuration.json": omarchy_user_configuration(disk_bytes=disk_bytes, encrypt=encrypt, **kw), "defer-provisioning": "",
            "user_encrypt_installation.txt": "true\n" if encrypt else "false\n"}


# ---- Bazzite (Anaconda with a kickstart; the image is on the ISO) ------------------------------------------------------------------------
BAZZITE_LABEL = "bazzite-x86_64-stable"


SEED_HEREDOC = "BASELINE_SEED_EOF"
SEED_UNIT = """[Unit]
Description=Baseline first boot: the owner from the seed disk
Before=sddm.service display-manager.service plasmalogin.service gdm.service systemd-user-sessions.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /etc/baseline-seed/seed_runner.py

[Install]
WantedBy=multi-user.target
"""


def seed_runner_install_script(runner: str) -> str:
    """Shell lines that put the seed runner (baseline/lib/seed_runner.py) and its unit in a system that has no cloud-init, enabled without a running systemd, so the owner is made from the
    seed disk at the first boot, before any login screen. The runner is a file the build reads from this repository, never text from the network."""
    if SEED_HEREDOC in runner or "%end" in runner:
        raise BuildError("the runner text cannot contain the end marker of the file that carries it")
    return "\n".join([
        "mkdir -p /etc/baseline-seed /etc/systemd/system/multi-user.target.wants",
        f"cat > /etc/baseline-seed/seed_runner.py <<'{SEED_HEREDOC}'", runner.rstrip("\n"), SEED_HEREDOC,
        f"cat > /etc/systemd/system/baseline-seed.service <<'{SEED_HEREDOC}'", SEED_UNIT.rstrip("\n"), SEED_HEREDOC,
        "chmod 644 /etc/baseline-seed/seed_runner.py /etc/systemd/system/baseline-seed.service",
        "ln -sf /etc/systemd/system/baseline-seed.service /etc/systemd/system/multi-user.target.wants/baseline-seed.service",
        "chcon -t systemd_unit_file_t /etc/systemd/system/baseline-seed.service || true",         # SELinux: the unit is labelled as a unit; the runner is only read by python
        "chcon -h -t systemd_unit_file_t /etc/systemd/system/multi-user.target.wants/baseline-seed.service || true", ""])


def bazzite_kickstart(*, hostname="bazzite", image="/run/install/repo/bazzite-stable", runner=None) -> str:
    """The kickstart for an unattended Bazzite install. It names the container image carried on the ISO (the same `ostreecontainer` line the ISO's own interactive defaults use) and wipes
    the target disk. The ISO's defaults would also create a user with a known password; this creates none and locks root: the owner is made at the first boot, from the seed disk, by the seed
    runner this installs when `runner` (its source text) is given."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", hostname) or not re.fullmatch(r"/run/install/repo/[A-Za-z0-9][A-Za-z0-9._-]*", image):
        raise BuildError("hostname or image path is not a plain value")
    lines = [
        "# Baseline: unattended install of the Bazzite image on the ISO. No account is created.", "text",
        f"ostreecontainer --url={image} --transport=oci --no-signature-verification",
        "lang en_US.UTF-8", "keyboard us", "timezone UTC --utc", f"network --bootproto=dhcp --device=link --activate --hostname={hostname}",
        "zerombr", "clearpart --all --initlabel --disklabel=gpt", "autopart", "bootloader --timeout=1", "rootpw --lock", "poweroff"]
    if runner is not None:
        lines += ["", "%post --erroronfail", seed_runner_install_script(runner), "%end"]
    return "\n".join(lines) + "\n"


# ---- CachyOS (the live image's own installer, headless) ------------------------------------------------------------------------------------
CACHY_BUILD_USER = "baseline-build"


def cachyos_config(*, user_pass: str, root_pass: str, disk="/dev/vda", hostname="cachyos", desktop="kde") -> str:
    """The headless config for `cachyos-installer --config` (documented in the installer's docs/config.md). The installer REQUIRES a user and passwords, so the build uses a throwaway user with
    random passwords made for this one build; the tidy step deletes that user and locks root, so the base keeps no usable credential."""
    import json
    if not re.fullmatch(r"/dev/[a-z0-9]+", disk) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", hostname) or not re.fullmatch(r"[a-z]{2,20}", desktop):
        raise BuildError("disk, hostname or desktop is not a plain value")
    if len(user_pass) < 16 or len(root_pass) < 16:
        raise BuildError("the throwaway passwords must be long and random")
    return json.dumps({"install_type": "simple", "headless_mode": True, "device": disk, "fs_name": "btrfs", "subvolumes": "default", "allow_auto_partition": True, "hostname": hostname,
                       "timezone": "UTC", "user_name": CACHY_BUILD_USER, "user_pass": user_pass, "root_pass": root_pass, "desktop": desktop, "bootloader": "grub", "autologin": False,
                       "post_install": "/root/post-install.sh"}, indent=2) + "\n"


def cachyos_post_install() -> str:
    """Runs in the live system after the installer has finished AND unmounted the target (as the installer's own log shows), so this mounts the installed root and its EFI partition itself,
    adds the guest agent and cloud-init, puts a boot loader on the removable EFI path so the disk boots under any firmware variables, and unmounts again."""
    return """#!/bin/bash
set -u
disk=${1:-/dev/vda}
root=$(lsblk -nrpo NAME,FSTYPE "$disk" | awk '$2=="btrfs" {print $1; exit}')
esp=$(lsblk -nrpo NAME,FSTYPE "$disk" | awk '$2=="vfat" {print $1; exit}')
[ -n "$root" ] && [ -n "$esp" ] || { echo "cannot find the installed root and EFI partitions on $disk" >&2; exit 1; }
mkdir -p /mnt
mount -o subvol=@ "$root" /mnt || exit 1
mkdir -p /mnt/boot/efi && mount "$esp" /mnt/boot/efi || exit 1
status=0
arch-chroot /mnt pacman -S --noconfirm --needed cloud-init qemu-guest-agent || status=1
for unit in qemu-guest-agent cloud-init-local cloud-init-main cloud-init-network cloud-config cloud-final; do arch-chroot /mnt systemctl enable "$unit" || true; done
[ -d /sys/firmware/efi ] && { arch-chroot /mnt grub-install --target=x86_64-efi --efi-directory=/boot/efi --removable || status=1; }
sync
umount -R /mnt
[ "$status" -eq 0 ] && touch /tmp/baseline-post-install-done
exit "$status"
"""


# ---- first boot: the owner's account comes from a seed, never from the base ---------------------------------------------------------------------
def first_boot_seed(*, username: str, ssh_keys=(), hostname: str, instance_id: str) -> dict:
    """The two files of a cloud-init NoCloud drive (label `cidata`) that make the owner's account on the first boot of a VM made from a base. The owner is the Proxmox user who is already signed in,
    so the account has NO password (nothing to guess, store or show), may use sudo without a prompt, and the console signs it in; SSH keys are optional for remote use."""
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username) or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", hostname) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", instance_id):
        raise BuildError("username, hostname or instance id is not a plain value")
    keys = [k.strip() for k in ssh_keys]
    if not all(re.fullmatch(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+|sk-ssh-ed25519@openssh.com) [A-Za-z0-9+/=]+( [^\n]{0,80})?", k) for k in keys):
        raise BuildError("an SSH key is not in the usual one-line form")
    lines = ["#cloud-config", "users:", f"  - name: {username}", "    uid: 1100", "    groups: [sudo, wheel]", "    sudo: ALL=(ALL) NOPASSWD:ALL", "    shell: /bin/bash", "    lock_passwd: true"]
    if keys:
        lines += ["    ssh_authorized_keys:"] + [f"      - {k}" for k in keys]
    lines += ["ssh_pwauth: false", "disable_root: true"]
    return {"user-data": "\n".join(lines) + "\n", "meta-data": f"instance-id: {instance_id}\nlocal-hostname: {hostname}\n"}
