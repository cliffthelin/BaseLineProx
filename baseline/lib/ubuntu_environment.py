"""Ubuntu environments: verified vanilla source, disposable root, retained /home.

The recipe provisions exactly one authenticated administrative account. It
never enables a guest login or accepts an operator's existing credentials.
Only the fresh user disk may be initialized. Rebuild seeds contain no mkfs.
Desktop installation requires network access on the first boot.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import drive_setup_answer as answer
import vm_host as vh

# Read from Canonical's HTTPS SHA256SUMS on 2026-10-01. The source is
# byte-pinned; publisher-signature verification is a later increment.
IMAGE_SHA256 = "6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2"
IMAGE_URL = ("https://cloud-images.ubuntu.com/releases/noble/release-20260926/"
             "ubuntu-24.04-server-cloudimg-amd64.img")
BASE_NAME = "ubuntu-noble-20260926"
USERNAME = "baseline-admin"


class UbuntuError(vh.VmError):
    pass


def _homepage(url: str) -> str:
    parsed = urlsplit(url)
    if (not re.fullmatch(r"https?://[A-Za-z0-9.:\[\]-]+/?", url)
            or not parsed.hostname or parsed.port != 8006 or parsed.path not in ("", "/")):
        raise UbuntuError("homepage must be a Proxmox http(s) endpoint on port 8006")
    return url


def cloud_config(*, password_hash: str, desktop: bool = True,
                 homepage: str = "https://baseline.invalid:8006", initialize_home: bool = False) -> str:
    _homepage(homepage)
    if not password_hash.startswith("$6$") or any(c in password_hash for c in "\n\r"):
        raise UbuntuError("a salted password hash is required, never a plaintext credential")
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
        "disable_root": True,
        "ssh_pwauth": False,
        "users": [{"name": USERNAME, "uid": 1000, "groups": ["sudo"],
                   "shell": "/bin/bash", "lock_passwd": False, "hashed_passwd": password_hash,
                   "sudo": ["ALL=(ALL) ALL"]}],
        "package_update": True,
        "packages": ["qemu-guest-agent"] + (["ubuntu-desktop-minimal", "firefox"] if desktop else []),
        "bootcmd": [["bash", "-c", prepare_home]],
        "mounts": [["LABEL=baseline-home", "/home", "ext4", "defaults", "0", "2"]],
        "write_files": [],
        "runcmd": [["systemctl", "enable", "--now", "qemu-guest-agent"]],
    }
    if desktop:
        config["write_files"].append({
            "path": "/etc/systemd/system/gdm3.service.d/baseline-home.conf", "permissions": "0644",
            "content": "[Unit]\nRequiresMountsFor=/home\nConditionPathExists=/run/baseline-home-ready\n",
        })
        config["write_files"].append({
            "path": "/etc/firefox/policies/policies.json", "permissions": "0644",
            "content": json.dumps({"policies": {"Homepage": {"URL": homepage, "StartPage": "homepage"},
                                                "DontCheckDefaultBrowser": True}}),
        })
        config["runcmd"].extend([
            ["mkdir", "-p", "/etc/firefox"],
            # Ubuntu Firefox is a snap and reads the policy here, rather
            # than at the deb Firefox path used above.
            ["cp", "/etc/firefox/policies/policies.json", "/etc/firefox/policies.json"],
            ["systemctl", "set-default", "graphical.target"],
            ["systemctl", "start", "gdm3"],
        ])
    checks = ("test -e /run/baseline-home-ready; "
              "findmnt --mountpoint /home >/dev/null; "
              "systemctl is-active --quiet qemu-guest-agent; ")
    if desktop:
        checks += "systemctl is-active --quiet gdm3; snap list firefox >/dev/null; "
    checks += "touch /var/lib/baseline-environment-ready"
    config["runcmd"].append(["bash", "-ec", checks])
    # JSON is a YAML subset. No quoting ambiguity around password hashes
    # or shell snippets; cloud-init reads this as ordinary cloud-config.
    return "#cloud-config\n" + json.dumps(config, indent=2) + "\n"


def _run(host, argv):
    rc, out, err = host.run(argv)
    if rc:
        raise UbuntuError(f"{argv[0]} failed: {err.strip()[-400:]}")
    return out


def install_base(host, *, source: Path, expected_sha256: str = IMAGE_SHA256,
                 name: str = BASE_NAME) -> Path:
    vh.VmHost._check_store(host.store)
    vh.VmHost._need_name(name)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise UbuntuError("invalid source digest")
    if not source.is_file() or source.is_symlink():
        raise UbuntuError("source must be a regular downloaded image")
    with source.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected_sha256:
        raise UbuntuError("Ubuntu source digest mismatch")
    target = host.base_path(name)
    if target.exists():
        raise UbuntuError(f"base {name} already exists; never overwrite a backing image")
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = target.with_suffix(".new")
    try:
        _run(host, ["qemu-img", "convert", "-f", "qcow2", "-O", "qcow2", str(source), str(fresh)])
        if not fresh.is_file():
            raise UbuntuError("qemu-img produced no base image")
        os.chmod(fresh, 0o444)
        os.replace(fresh, target)
    finally:
        fresh.unlink(missing_ok=True)
    return target


def acquire_base(host, *, cache_dir: Path) -> Path:
    """Download only the pinned vanilla image. Other OS sources remain
    selectable through the ordinary ISO/template path."""
    target = host.base_path(BASE_NAME)
    if target.is_file():
        return target
    cache_dir = Path(cache_dir)
    if cache_dir.resolve().is_relative_to("/mnt"):
        mount = Path("/mnt") / cache_dir.resolve().parts[2]
        if not os.path.ismount(mount):
            raise UbuntuError(f"{mount} must be mounted before downloading installers")
    cache_dir.mkdir(parents=True, exist_ok=True)
    source = cache_dir / f"{BASE_NAME}.img"
    if not source.is_file():
        fresh = source.with_suffix(".partial")
        try:
            _run(host, ["curl", "--fail", "--location", "--proto", "=https", "--max-time", "300",
                        "--retry", "2", "--output", str(fresh), IMAGE_URL])
            with fresh.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != IMAGE_SHA256:
                raise UbuntuError("downloaded Ubuntu source digest mismatch")
            os.replace(fresh, source)
            os.chmod(source, 0o444)
        finally:
            fresh.unlink(missing_ok=True)
    return install_base(host, source=source)


def write_seed(host, name, profile, *, initialize_home: bool):
    d = host.vm_dir(name)
    seed = d / "seed"
    seed.mkdir(mode=0o700, exist_ok=True)
    userdata = cloud_config(password_hash=profile["password_hash"], desktop=profile["desktop"],
                            homepage=profile["homepage"], initialize_home=initialize_home)
    for filename, content in (
        ("user-data", userdata),
        ("meta-data", json.dumps({"instance-id": profile["instance_id"], "local-hostname": name})),
    ):
        path = seed / filename
        path.write_text(content)
        os.chmod(path, 0o600)
    fresh = d / "seed.new.iso"
    try:
        _run(host, ["xorriso", "-as", "mkisofs", "-volid", "cidata", "-joliet", "-rock",
                    "-o", str(fresh), str(seed / "user-data"), str(seed / "meta-data")])
        if not fresh.is_file():
            raise UbuntuError("seed builder produced no ISO")
        os.chmod(fresh, 0o600)
        os.replace(fresh, d / "seed.iso")
    finally:
        fresh.unlink(missing_ok=True)


def create(host, name: str, *, base: str = BASE_NAME, desktop: bool = True,
           homepage: str = "https://baseline.invalid:8006", memory_mb: int = 4096,
           cpus: int = 2, disk_gb: int = 40, persistence_gb: int = 32,
           password_factory=answer.generate_one_time_password, password_hasher=None) -> dict:
    _homepage(homepage)
    if not 8 <= int(disk_gb) <= 4096:
        raise UbuntuError("Ubuntu root disk must be at least 8 GB")
    password = password_factory()
    hashed = (password_hasher or (lambda p: answer.hash_password_sha512crypt(p, secrets.token_hex(8))))(password)
    spec = host.create_overlay(name, base=base, memory_mb=memory_mb, cpus=cpus, persistence_gb=persistence_gb)
    profile = {"recipe": "ubuntu-desktop" if desktop else "ubuntu-server", "base": base, "desktop": bool(desktop),
               "homepage": homepage, "password_hash": hashed, "instance_id": secrets.token_hex(16),
               "disk_gb": int(disk_gb)}
    # Retained metadata is separate from the home filesystem and contains
    # only the one-way hash, never the one-time cleartext value.
    profile_path = Path(spec["persistence_disk"]).parent / "profile.json"
    profile_path.write_text(json.dumps(profile, indent=2))
    os.chmod(profile_path, 0o600)
    try:
        _run(host, ["qemu-img", "resize", str(host.disk_path(name)), f"{int(disk_gb)}G"])
        write_seed(host, name, profile, initialize_home=True)
        spec.update({"recipe": profile["recipe"], "seed": True, "disk_gb": int(disk_gb)})
        host._write_spec(name, spec)
        host.configure_uefi(name)
    except Exception:
        # Never silently destroy retained state to undo a failed setup.
        # The incomplete machine remains stopped and can be inspected.
        raise
    return {"name": name, "username": USERNAME, "password": password.decode("ascii"),
            "message": "Created. Save the one-time login, then start the environment."}


def rebuild(host, name: str) -> None:
    spec = host._need_stopped(name)
    data = Path(spec.get("persistence_disk", ""))
    profile_path = data.parent / "profile.json"
    if not data.is_file() or not profile_path.is_file():
        raise UbuntuError("retained data or its profile is missing; refusing rebuild")
    profile = json.loads(profile_path.read_text())
    # Build the safe seed before touching the OS overlay. The retained disk
    # can never be formatted by a rebuild, even if it becomes corrupt.
    write_seed(host, name, profile, initialize_home=False)
    host.rollback(name)
    _run(host, ["qemu-img", "resize", str(host.disk_path(name)), f'{profile["disk_gb"]}G'])
    host._write_spec(name, spec)
