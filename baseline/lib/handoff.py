#!/usr/bin/env python3
"""Baseline handoff packets - the "what's not on GitHub" backup
(harness.env, SSH host/root keys, interface aliases, hardware snapshot,
event logs) as a single, passphrase-encrypted, portable file. Used by
baseline-setup-wizard both to CREATE a packet at the end of setting up a
host, and to RESTORE from one when setting up a new/replacement drive
that should inherit a previous build's identity and state.

Encryption is GPG symmetric (AES256, SHA512 S2K) - a passphrase, not a
username+password pair; a username/host LABEL is carried in the
manifest alongside the passphrase-protected content so a wizard can
show "this packet was made for <label> on <date>" before decrypting
anything, without that label itself needing to be secret or being part
of the key derivation.
"""
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

MANIFEST_NAME = "handoff_manifest.json"

# (source path, name inside the packet). Directories are copied whole;
# files are copied individually. Anything missing is skipped, not fatal
# - a fresh host won't have a harness.env yet, for instance.
_DIR_SOURCES = [
    ("/etc/baseline", "etc-baseline"),
    ("/var/lib/baseline", "var-lib-baseline"),
    ("/var/log/baseline", "var-log-baseline"),
]
_FILE_SOURCES = [
    ("/etc/ssh/ssh_host_ecdsa_key", "ssh-host-keys/ssh_host_ecdsa_key"),
    ("/etc/ssh/ssh_host_ecdsa_key.pub", "ssh-host-keys/ssh_host_ecdsa_key.pub"),
    ("/etc/ssh/ssh_host_ed25519_key", "ssh-host-keys/ssh_host_ed25519_key"),
    ("/etc/ssh/ssh_host_ed25519_key.pub", "ssh-host-keys/ssh_host_ed25519_key.pub"),
    ("/etc/ssh/ssh_host_rsa_key", "ssh-host-keys/ssh_host_rsa_key"),
    ("/etc/ssh/ssh_host_rsa_key.pub", "ssh-host-keys/ssh_host_rsa_key.pub"),
    ("/root/.ssh/id_rsa", "root-ssh/id_rsa"),
    ("/root/.ssh/id_rsa.pub", "root-ssh/id_rsa.pub"),
    ("/root/.ssh/config", "root-ssh/config"),
    ("/etc/machine-id", "machine-id"),
    ("/etc/hostname", "hostname"),
]
# Proxmox's own authorized_keys lives behind /etc/pve (a fuse mount) and
# root/.ssh/authorized_keys is usually a symlink to it - read the real
# content rather than copying the symlink, which wouldn't resolve
# anywhere useful on a different host.
_AUTHORIZED_KEYS_SRC = "/etc/pve/priv/authorized_keys"
_AUTHORIZED_KEYS_DEST = "root-ssh/authorized_keys"


def collect(staging_dir: Path, host_label: str) -> dict:
    """Copy every private-state source that exists into staging_dir,
    write a manifest, return the manifest dict (also on disk as
    MANIFEST_NAME inside staging_dir)."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    included = []

    for src, rel in _DIR_SOURCES:
        src_path = Path(src)
        if src_path.is_dir():
            dest = staging_dir / rel
            shutil.copytree(src_path, dest, dirs_exist_ok=True)
            included.append(rel)

    for src, rel in _FILE_SOURCES:
        src_path = Path(src)
        if src_path.is_file():
            dest = staging_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)
            included.append(rel)

    try:
        authorized_keys = Path(_AUTHORIZED_KEYS_SRC).read_text()
        dest = staging_dir / _AUTHORIZED_KEYS_DEST
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(authorized_keys)
        included.append(_AUTHORIZED_KEYS_DEST)
    except OSError:
        pass

    manifest = {
        "host_label": host_label,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "has_harness_token": (staging_dir / "etc-baseline" / "harness.env").exists(),
        "has_interface_aliases": (staging_dir / "etc-baseline" / "interface_aliases.json").exists(),
        "files_included": sorted(included),
    }
    (staging_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    return manifest


def build_archive(staging_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as tf:
        for item in sorted(staging_dir.iterdir()):
            tf.add(item, arcname=item.name)


def encrypt(archive_path: Path, encrypted_path: Path, passphrase: str) -> None:
    """GPG symmetric AES256 encryption. Passphrase goes in via a pipe
    (--passphrase-fd 0), never as a CLI argument or env var, so it never
    appears in `ps` output or shell history."""
    proc = subprocess.run(
        ["gpg", "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
         "--s2k-digest-algo", "SHA512", "--s2k-count", "65011712",
         "--passphrase-fd", "0", "--output", str(encrypted_path), str(archive_path)],
        input=passphrase.encode(), capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gpg encrypt failed: {proc.stderr.decode(errors='replace').strip()}")


def decrypt(encrypted_path: Path, archive_path: Path, passphrase: str) -> None:
    proc = subprocess.run(
        ["gpg", "--batch", "--yes", "--decrypt", "--passphrase-fd", "0",
         "--output", str(archive_path), str(encrypted_path)],
        input=passphrase.encode(), capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gpg decrypt failed - wrong passphrase, or not a valid handoff packet: "
                            f"{proc.stderr.decode(errors='replace').strip()}")


def read_manifest(archive_path: Path) -> dict:
    with tarfile.open(archive_path, "r:gz") as tf:
        member = tf.getmember(MANIFEST_NAME)
        f = tf.extractfile(member)
        return json.loads(f.read())


def create_packet(host_label: str, encrypted_output: Path, passphrase: str) -> dict:
    """End-to-end: collect -> archive -> encrypt -> clean up the
    intermediate plaintext. Returns the manifest for display to the
    operator."""
    with tempfile.TemporaryDirectory(prefix="baseline-handoff-") as tmp:
        staging = Path(tmp) / "staging"
        manifest = collect(staging, host_label)
        archive_path = Path(tmp) / "packet.tar.gz"
        build_archive(staging, archive_path)
        encrypt(archive_path, encrypted_output, passphrase)
    os.chmod(encrypted_output, 0o600)
    return manifest


def open_packet(encrypted_path: Path, passphrase: str, extract_to: Path) -> dict:
    """End-to-end: decrypt -> extract -> return manifest. extract_to is
    created if needed; caller applies the extracted files to the
    running system explicitly (this function never writes outside
    extract_to)."""
    with tempfile.TemporaryDirectory(prefix="baseline-handoff-") as tmp:
        archive_path = Path(tmp) / "packet.tar.gz"
        decrypt(encrypted_path, archive_path, passphrase)
        manifest = read_manifest(archive_path)
        extract_to.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(extract_to, filter="data")
    return manifest
