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
import re
from pathlib import Path

INSTALLER = "baseline/bin/baseline-first-boot-install"
MEDIA_SOURCE = "baseline-src"          # iso_builder.ISO_TARGET_DIR without the leading slash
PROXMOX_HOOK_LIMIT = 1024 * 1024       # prepare-iso: "Maximum file size for first-boot executable file is 1 MiB"

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SERIAL = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


_DEV_USER = re.compile(r"^[a-z][a-z0-9_-]{0,31}:\$6\$[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$")


_DEV_SSH_KEY = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]{20,800}( [A-Za-z0-9._@-]{1,64})?$")


def _exec_line(child_identity, dev_user=None, dev_ssh_keys=()):
    """The last line of the hook. With a child identity (installer_identity: the UUID the drive must carry, and its hardware serial)
    both are handed to the installer as environment variables; they are checked here so nothing but plain characters can reach a
    shell script."""
    plain = f'exec /usr/bin/python3 "$dest/{INSTALLER}"'
    extra = ""
    if dev_user is not None:
        if not isinstance(dev_user, str) or not _DEV_USER.match(dev_user):
            raise HookError("a development user must be 'name:sha512crypt-hash' (name lower-case letters, digits, _ and -)")
        extra = f" BASELINE_DEV_USER='{dev_user}'"      # only [a-z0-9_-:$./A-Za-z0-9] by the check above: safe inside single quotes
    if dev_ssh_keys:
        if dev_user is None:
            raise HookError("development SSH keys travel with a development user only")
        if not all(isinstance(k, str) and _DEV_SSH_KEY.match(k) for k in dev_ssh_keys):
            raise HookError("a development SSH key must be in the usual one-line form")
        extra += " BASELINE_DEV_SSH_KEYS='" + "|".join(dev_ssh_keys) + "'"     # plain characters only, checked above
    if child_identity is None:
        return plain if not extra else f'exec env{extra} /usr/bin/python3 "$dest/{INSTALLER}"'
    if (not isinstance(child_identity, dict) or set(child_identity) != {"uuid", "serial"}
            or not isinstance(child_identity["uuid"], str) or not _UUID.match(child_identity["uuid"])
            or not isinstance(child_identity["serial"], str) or not _SERIAL.match(child_identity["serial"])):
        raise HookError("a child identity must be a lowercase UUID and a plain hardware serial of at least 8 characters")
    return (f"exec env BASELINE_CHILD_UUID={child_identity['uuid']} BASELINE_CHILD_SERIAL={child_identity['serial']}{extra} "
            f'/usr/bin/python3 "$dest/{INSTALLER}"')


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
@EXEC@
"""


class HookError(RuntimeError):
    pass


def build_hook(repo_root, output_path, *, child_identity=None, dev_user=None, dev_ssh_keys=()) -> Path:
    repo_root, output_path = Path(repo_root), Path(output_path)
    if not (repo_root / INSTALLER).is_file() or not (repo_root / "boot/provision.sh").is_file():
        raise HookError(f"{repo_root} does not contain the on-target installer and provision.sh")
    hook = HOOK.replace("@EXEC@", _exec_line(child_identity, dev_user, dev_ssh_keys))
    if len(hook.encode()) >= PROXMOX_HOOK_LIMIT:
        raise HookError("the first-boot hook exceeds Proxmox's 1 MiB limit")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(hook)
    os.chmod(temporary, 0o755)
    os.replace(temporary, output_path)
    return output_path
