"""Builds the first-boot hook the Proxmox auto-installer runs once on the newly installed system.

The hook is a small POSIX shell script (Proxmox allows at most 1 MiB). The installer ISO already carries the
Baseline source at /baseline-src (iso_builder), and the installer medium stays attached during first boot because
the installed drive keeps its own copy of it. So the hook finds the attached ISO 9660 medium that carries
/baseline-src, copies the source to /opt/baseline-src and hands over to baseline/bin/baseline-first-boot-install,
which finishes the installation from the drive itself: no machine running the installer and no internet.
Embedded with `proxmox-auto-install-assistant prepare-iso --on-first-boot`; enabled by the answer's [first-boot].

For checking without a real medium: BASELINE_HOOK_MEDIA names a directory standing in for the mounted medium,
BASELINE_HOOK_DEST overrides the destination and BASELINE_HOOK_EXTRACT_ONLY=1 stops after copying.
"""
from __future__ import annotations

import os
from pathlib import Path

INSTALLER = "baseline/bin/baseline-first-boot-install"
MEDIA_SOURCE = "baseline-src"          # iso_builder.ISO_TARGET_DIR without the leading slash
PROXMOX_HOOK_LIMIT = 1024 * 1024       # prepare-iso: "Maximum file size for first-boot executable file is 1 MiB"

HOOK = f"""#!/bin/sh
# Baseline first-boot hook: copy the installer carried on the attached medium and finish the installation.
set -eu
dest="${{BASELINE_HOOK_DEST:-/opt/baseline-src}}"
media="${{BASELINE_HOOK_MEDIA:-}}"
mnt=""
if [ -z "$media" ]; then
    mnt="$(mktemp -d)"
    for dev in $(lsblk -rpno NAME,FSTYPE | awk '$2 == "iso9660" {{print $1}}'); do
        if mount -o ro "$dev" "$mnt" 2>/dev/null; then
            if [ -f "$mnt/{MEDIA_SOURCE}/boot/provision.sh" ]; then media="$mnt"; break; fi
            umount "$mnt"
        fi
    done
fi
if [ -z "$media" ] || [ ! -f "$media/{MEDIA_SOURCE}/boot/provision.sh" ]; then
    echo "Baseline: no attached installer medium carries /{MEDIA_SOURCE}; leave the installer attached" >&2
    exit 1
fi
staging="$dest.new.$$"
rm -rf "$staging"
mkdir -p "$staging"
cp -R "$media/{MEDIA_SOURCE}/." "$staging/"
if [ -n "$mnt" ]; then umount "$mnt"; rmdir "$mnt"; fi
rm -rf "$dest"
mv "$staging" "$dest"
[ "${{BASELINE_HOOK_EXTRACT_ONLY:-0}}" = "1" ] && exit 0
exec /usr/bin/python3 "$dest/{INSTALLER}"
"""


class HookError(RuntimeError):
    pass


def build_hook(repo_root, output_path) -> Path:
    repo_root, output_path = Path(repo_root), Path(output_path)
    if not (repo_root / INSTALLER).is_file() or not (repo_root / "boot/provision.sh").is_file():
        raise HookError(f"{repo_root} does not contain the on-target installer and provision.sh")
    if len(HOOK.encode()) >= PROXMOX_HOOK_LIMIT:
        raise HookError("the first-boot hook exceeds Proxmox's 1 MiB limit")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(HOOK)
    os.chmod(temporary, 0o755)
    os.replace(temporary, output_path)
    return output_path
