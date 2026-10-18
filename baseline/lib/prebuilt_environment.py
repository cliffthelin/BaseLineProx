"""Ready-made operating systems as VMs (DR258, DR267): a prebuilt base, an overlay over it, the owner's account made at the first boot, and a retained home.

`baseline-build-os-base` produces a read-only base for each listed system, with its desktop and applications already installed and no account in it. This makes a VM from one the way
`ubuntu_environment` makes an Ubuntu VM: the host's `create_overlay` gives a disposable OS layer over the base and a separate retained disk for the person's files; the base is never written.

The person is the Proxmox user who is already signed in (operator 2026-10-17: "the user is logged in already from Proxmox and the user persists until we make more Proxmox users"). So no machine
gets a login of its own and no password is generated or shown: the one account in the VM carries that user's name, has no password at all (nothing to guess or leak), may use sudo without being
asked, and the console signs it straight in. The name is kept once in `owner.json` beside the retained disks so every VM has the same user. Systems whose own first-boot setup creates the owner
(Omarchy, Bazzite, FydeOS) get the overlay and the retained disk and no seed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path

import vm_host as vh

OWNER_FILE = "owner.json"
OWNER_UID = 1100                      # the same on every system, and clear of the default users (1000 is taken by the installer's own account on Debian, `ubuntu` on Ubuntu), so a retained home belongs to the owner everywhere
_RESERVED = frozenset({"root", "admin", "administrator", "baseline", "guest", "system", "operator", "daemon", "nobody"})
_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
# id -> does it take a cloud-init seed, and which display manager must wait for the retained home
SYSTEMS = {
    "debian": {"seed": True, "greeter": "gdm3"}, "ubuntu": {"seed": True, "greeter": "gdm3"}, "nixos": {"seed": True, "greeter": None}, "cachyos": {"seed": True, "greeter": "sddm"},
    "omarchy": {"seed": False, "greeter": None}, "bazzite": {"seed": False, "greeter": None}, "fydeos": {"seed": False, "greeter": None},
}


class PrebuiltError(vh.VmError):
    pass


def base_name(os_id: str) -> str:
    if os_id not in SYSTEMS:
        raise PrebuiltError(f"{os_id} has no ready-made base")
    return f"{os_id}-base"


def read_manifest(source_dir, os_id: str) -> dict:
    try:
        manifest = json.loads((Path(source_dir) / f"{os_id}-base.json").read_text())
    except (OSError, ValueError) as exc:
        raise PrebuiltError(f"no readable manifest for the {os_id} base: {exc}") from None
    if manifest.get("holds_install_state_or_secrets") is not False:
        raise PrebuiltError(f"the {os_id} base does not say it is free of install state and secrets")
    return manifest


def install_base(host, os_id: str, source_dir) -> Path:
    """Make the carried base available to the host as a base image: checked against its own manifest first, then linked (not copied) so the carried file stays the one copy. Never replaces a base."""
    source_dir = Path(source_dir)
    manifest = read_manifest(source_dir, os_id)
    image = source_dir / manifest["base"]
    if image.is_symlink() or not image.is_file():
        raise PrebuiltError(f"the {os_id} base image is missing")
    digest = hashlib.sha256()
    with open(image, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != manifest["sha256"]:
        raise PrebuiltError(f"the {os_id} base does not match its manifest checksum")
    host.bases_dir.mkdir(parents=True, exist_ok=True)
    target = host.base_path(base_name(os_id))
    if target.exists() or target.is_symlink():
        return target
    target.symlink_to(image.resolve())
    return target


def cloud_config(os_id: str, *, owner: str, initialize_home: bool, hostname: str, extra: dict = None) -> str:
    """The seed's user-data: mount (or on a fresh disk, make) the retained home, create the owner's account (no password, sudo without a prompt, signed in at the console), and have the display
    manager wait for the home."""
    spec = SYSTEMS[os_id]
    if not _NAME.match(owner) or owner in _RESERVED:
        raise PrebuiltError("the owner's account name is a plain lowercase name that is not a reserved one")
    initialize = """
    if blkid -p "$disk" >/dev/null 2>&1; then
        echo 'Refusing to format an existing or unrecognized home filesystem' >&2; exit 1
    fi
    cmp -n 1048576 "$disk" /dev/zero || { echo 'Home disk is not blank' >&2; exit 1; }
    mkfs.ext4 -q -L baseline-home "$disk"
""" if initialize_home else """
    echo 'Retained home filesystem missing or damaged; recovery required' >&2; exit 1
"""
    prepare_home = """set -eu
disk=/dev/disk/by-id/virtio-baseline-home
[ -b "$disk" ] || { echo 'Retained home disk is absent' >&2; exit 1; }
if [ "$(blkid -s TYPE -o value "$disk" || true)" != ext4 ] ||
   [ "$(blkid -s LABEL -o value "$disk" || true)" != baseline-home ]; then
""" + initialize + """
fi
mkdir -p /home
if ! mountpoint -q /home; then mount -t ext4 "$disk" /home; fi
actual=$(findmnt -n -o SOURCE --mountpoint /home)
[ "$(readlink -f "$actual")" = "$(readlink -f "$disk")" ] ||
    { echo 'Wrong filesystem mounted at /home' >&2; exit 1; }
touch /run/baseline-home-ready
"""
    config = {
        "disable_root": True, "ssh_pwauth": False, "hostname": hostname, "preserve_hostname": False,
        "users": [{"name": owner, "uid": OWNER_UID, "groups": ["sudo", "wheel"], "shell": "/bin/bash", "lock_passwd": True, "sudo": ["ALL=(ALL) NOPASSWD:ALL"]}],
        "bootcmd": [["bash", "-c", prepare_home]],
        "write_files": [{"path": "/etc/baseline-environment.json", "permissions": "0644", "content": json.dumps({"format": "baseline.prebuilt-environment/v1", "os": os_id}, sort_keys=True) + "\n"}],
        "runcmd": [["systemctl", "enable", "--now", "qemu-guest-agent"]],
    }
    if spec["greeter"]:                                  # the login screen must not appear before the retained home is mounted
        config["write_files"].append({"path": f"/etc/systemd/system/{spec['greeter']}.service.d/baseline-home.conf", "permissions": "0644",
                                      "content": "[Unit]\nRequiresMountsFor=/home\nConditionPathExists=/run/baseline-home-ready\n"})
        if spec["greeter"] == "gdm3":                       # sign the owner straight in at the console
            config["write_files"].append({"path": "/etc/gdm3/daemon.conf", "permissions": "0644", "content": f"[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin={owner}\n"})
        elif spec["greeter"] == "sddm":
            config["write_files"].append({"path": "/etc/sddm.conf.d/baseline-autologin.conf", "permissions": "0644", "content": f"[Autologin]\nUser={owner}\n"})
    for key, items in (extra or {}).items():             # an application environment adds files, mounts and first-boot commands after the base ones
        if key not in ("write_files", "runcmd", "mounts", "packages") or not isinstance(items, list):
            raise PrebuiltError("extra seed content is write_files, runcmd, mounts or packages")
        config.setdefault(key, [])
        config[key] = list(config[key]) + list(items)
    return "#cloud-config\n" + json.dumps(config, indent=2) + "\n"


def owner_account(host, session_user: str) -> str:
    """The account name every VM gives its owner: kept in owner.json the first time (so it persists until more Proxmox users are made), taken from the Proxmox user who is signed in, and when
    that name cannot be a Linux account name (root, or something odd) the plain name `owner`."""
    store = Path(host.persistence_store)
    record = store / OWNER_FILE
    try:
        kept = json.loads(record.read_text()).get("username")
        if isinstance(kept, str) and _NAME.match(kept) and kept not in _RESERVED:
            return kept
    except (OSError, ValueError, AttributeError):
        pass
    name = str(session_user or "").strip().lower()
    name = name if _NAME.match(name) and name not in _RESERVED else "owner"
    store.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"username": name}))
    os.chmod(record, 0o644)
    return name


def _run(host, argv):
    rc, out, err = host.run(argv)
    if rc:
        raise PrebuiltError(f"{argv[0]} failed: {err.strip()[-400:]}")
    return out


def _need_disk_at_least_the_systems_own(host, base: str, disk_gb: int) -> None:
    """The overlay cannot be smaller than the base it sits on; said before anything is created, not as a qemu-img failure afterwards."""
    try:
        virtual = int(json.loads(_run(host, ["qemu-img", "info", "--output=json", str(host.base_path(base))]))["virtual-size"])
    except (ValueError, KeyError, TypeError, PrebuiltError):
        return                                                      # unreadable: qemu-img's own refusal at resize time still applies
    if disk_gb * 2**30 < virtual:
        raise PrebuiltError(f"the disk must be at least {-(-virtual // 2**30)} GB, the size of the system itself")


def write_seed(host, name: str, os_id: str, profile: dict, *, initialize_home: bool, extra: dict = None) -> None:
    folder = host.vm_dir(name)
    seed = folder / "seed"
    seed.mkdir(mode=0o700, exist_ok=True)
    files = (("user-data", cloud_config(os_id, owner=profile["owner"], initialize_home=initialize_home, hostname=name, extra=extra)),
             ("meta-data", json.dumps({"instance-id": profile["instance_id"], "local-hostname": name})))
    for filename, content in files:
        path = seed / filename
        path.write_text(content)
        os.chmod(path, 0o600)
    fresh = folder / "seed.new.iso"
    try:
        _run(host, ["xorriso", "-as", "mkisofs", "-volid", "cidata", "-joliet", "-rock", "-o", str(fresh), str(seed / "user-data"), str(seed / "meta-data")])
        if not fresh.is_file():
            raise PrebuiltError("the seed builder produced no ISO")
        os.chmod(fresh, 0o600)
        os.replace(fresh, folder / "seed.iso")
    finally:
        fresh.unlink(missing_ok=True)


def create(host, name: str, os_id: str, *, owner: str, memory_mb=4096, cpus=2, disk_gb=None, persistence_gb=32, extra: dict = None) -> dict:
    """A VM from the carried base of `os_id`: an overlay (the base is never written), a retained home disk, and, for systems that take one, a first-boot seed that makes the owner's account. No
    password exists anywhere in it."""
    base = base_name(os_id)
    if not host.base_path(base).is_file():
        raise PrebuiltError(f"the {os_id} base is not installed on this host")
    if disk_gb:
        _need_disk_at_least_the_systems_own(host, base, int(disk_gb))
    spec = host.create_overlay(name, base=base, memory_mb=memory_mb, cpus=cpus, persistence_gb=persistence_gb)
    if disk_gb:
        _run(host, ["qemu-img", "resize", str(host.disk_path(name)), f"{int(disk_gb)}G"])
    result = {"name": name, "os": os_id}
    if SYSTEMS[os_id]["seed"]:
        profile = {"os": os_id, "base": base, "owner": owner, "instance_id": secrets.token_hex(16)}
        profile_path = Path(spec["persistence_disk"]).parent / "profile.json"
        profile_path.write_text(json.dumps(profile))
        os.chmod(profile_path, 0o600)
        write_seed(host, name, os_id, profile, initialize_home=True, extra=extra)
        spec.update({"recipe": f"prebuilt-{os_id}", "seed": True})
        result.update(owner=owner, message=f"Created. Start it and it signs {owner} straight in; there is no separate login.")
    else:
        result["message"] = "Created. The system's own first-boot setup asks you to make the account when you start it."
    host._write_spec(name, spec)
    host.configure_uefi(name)
    return result
