#!/usr/bin/env python3
"""First-boot seed runner for ready-made bases that have no cloud-init (Bazzite, Omarchy).

The other ready-made systems read a NoCloud seed disk (volume label `cidata`) with cloud-init. This applies the same `user-data` with the
small part of cloud-config a VM's owner needs, using only the Python standard library so it can ship inside any base:

  bootcmd      every boot  (the retained home is mounted again each time; a failure here stops everything after it)
  hostname, write_files, users, mounts, runcmd      once per instance (the seed's `instance-id`)

Users are made with a fixed uid, no password (the account is locked) and, when the seed says so, passwordless sudo: the owner is the signed-in
Proxmox user, so there is nothing to type and nothing to store. Groups the system does not have are left out (Fedora has `wheel`, not `sudo`).

`apply` takes the text of both seed files, an injected command runner and a root directory, so it is checked without touching a system.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

STATE_DIR = "/var/lib/baseline-seed"
_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_GROUP = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_PATH = re.compile(r"^/[A-Za-z0-9._/@+-]{1,200}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$")


class SeedError(Exception):
    pass


def parse_user_data(text: str) -> dict:
    head, _, body = text.partition("\n")
    if head.strip() != "#cloud-config":
        raise SeedError("the seed's user-data is not a cloud-config")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise SeedError(f"the seed's user-data is not readable: {exc}") from None
    if not isinstance(data, dict):
        raise SeedError("the seed's user-data is not a mapping")
    return data


def instance_id(meta: str) -> str:
    match = re.search(r"^instance-id:\s*(\S+)\s*$", meta or "", re.M)
    if not match:
        raise SeedError("the seed's meta-data has no instance-id")
    return match.group(1)


def _under(root, path: str) -> Path:
    if not _PATH.match(path) or ".." in path.split("/"):
        raise SeedError(f"{path!r} is not a plain absolute path")
    return Path(root) / path.lstrip("/")


def _run(run, argv, what, check=True):
    code, out, err = run(argv)
    if check and code:
        raise SeedError(f"{what} failed: {(err or out).strip()[-300:]}")
    return code, out, err


def _write_files(items, run, root):
    for item in items or []:
        target = _under(root, str(item.get("path", "")))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content", "")))
        mode = str(item.get("permissions", "0644"))
        if not re.fullmatch(r"0?[0-7]{3,4}", mode):
            raise SeedError("a file mode is not an octal number")
        os.chmod(target, int(mode, 8))
        run(["restorecon", "-F", str(target)])                          # SELinux systems label it as the system's own policy says; elsewhere nothing happens


def _make_user(user, run, root):
    name = str(user.get("name", ""))
    if not _NAME.match(name):
        raise SeedError(f"{name!r} is not a plain account name")
    uid = user.get("uid")
    if uid is not None and not (isinstance(uid, int) and 1000 <= uid <= 59999):
        raise SeedError("an account's uid is a number between 1000 and 59999")
    if run(["getent", "passwd", name])[0] == 0:
        return False                                                      # an account that exists (a retained home's owner) is left alone
    groups = []
    for group in user.get("groups") or []:
        if not _GROUP.match(str(group)):
            raise SeedError("a group name is not plain")
        if run(["getent", "group", str(group)])[0] == 0:
            groups.append(str(group))
    shell = str(user.get("shell", "/bin/bash"))
    if not _PATH.match(shell):
        raise SeedError("a shell is not a plain path")
    argv = ["useradd", "-m", "-s", shell]
    if uid is not None:
        argv += ["-u", str(uid)]
    if groups:
        argv += ["-G", ",".join(groups)]
    _run(run, argv + [name], f"making the account {name}")
    if user.get("lock_passwd", True):
        _run(run, ["passwd", "-l", name], f"locking the password of {name}")
    rules = user.get("sudo") or []
    if rules:
        drop = _under(root, f"/etc/sudoers.d/90-baseline-{name}")
        drop.parent.mkdir(parents=True, exist_ok=True)
        drop.write_text("".join(f"{name} {rule}\n" for rule in rules))
        os.chmod(drop, 0o440)
        code, out, err = run(["visudo", "-cf", str(drop)])
        if code:
            drop.unlink(missing_ok=True)
            raise SeedError(f"sudo rule for {name} is not valid: {(err or out).strip()[-200:]}")
    return True


def apply(user_data: str, meta: str, *, run, root="/", state_dir=STATE_DIR) -> dict:
    config = parse_user_data(user_data)
    instance = instance_id(meta)
    for user in config.get("users") or []:                                # validated before anything runs, so a bad seed changes nothing
        if not _NAME.match(str(user.get("name", ""))):
            raise SeedError(f"{user.get('name')!r} is not a plain account name")
    for item in config.get("write_files") or []:
        _under(root, str(item.get("path", "")))
    for command in config.get("bootcmd") or []:                           # every boot: the retained home must be there before anything uses it
        if not isinstance(command, list) or not all(isinstance(a, str) for a in command):
            raise SeedError("a boot command is a list of words")
        code, out, err = run(command)
        if code:
            raise SeedError(f"a boot command failed ({(err or out).strip()[-300:] or 'no message'}); the retained home may not be mounted")
    state = Path(state_dir)
    marker = state / "instance-id"
    if marker.is_file() and marker.read_text().strip() == instance:
        return {"instance": instance, "skipped": "already applied for this instance"}
    done = {"instance": instance, "users": []}
    hostname = config.get("hostname")
    if hostname:
        if not _HOST.match(str(hostname)):
            raise SeedError("the hostname is not plain")
        name_file = _under(root, "/etc/hostname")
        name_file.parent.mkdir(parents=True, exist_ok=True)
        name_file.write_text(str(hostname) + "\n")
        run(["hostname", str(hostname)])
    _write_files(config.get("write_files"), run, root)
    run(["systemctl", "daemon-reload"])
    for user in config.get("users") or []:
        if _make_user(user, run, root):
            done["users"].append(user["name"])
    for entry in config.get("mounts") or []:
        if not isinstance(entry, list) or not all(isinstance(a, str) and "\n" not in a for a in entry):
            raise SeedError("a mount is a list of fstab fields")
        fstab = _under(root, "/etc/fstab")
        fstab.parent.mkdir(parents=True, exist_ok=True)
        with open(fstab, "a") as handle:
            handle.write("\t".join(entry) + "\n")
    for command in config.get("runcmd") or []:
        argv = command if isinstance(command, list) else ["/bin/sh", "-c", str(command)]
        _run(run, argv, f"first-boot command {argv[0]}", check=False)    # a failing convenience (restarting the greeter) never undoes the account
    state.mkdir(parents=True, exist_ok=True)
    marker.write_text(instance + "\n")
    return done


class RealRun:
    def __call__(self, argv):
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, "", str(exc)
        return done.returncode, done.stdout, done.stderr


def find_seed(run, wait_s=25):
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        code, out, _ = run(["blkid", "-L", "cidata"])
        if code == 0 and out.strip():
            return out.strip()
        time.sleep(2)
    return None


def main() -> int:
    run = RealRun()
    device = find_seed(run)
    if device is None:
        print("baseline-seed: no seed disk (label cidata); nothing to do")
        return 0
    mount = Path("/run/baseline-seed")
    mount.mkdir(parents=True, exist_ok=True)
    try:
        _run(run, ["mount", "-o", "ro", device, str(mount)], "mounting the seed disk")
        user_data = (mount / "user-data").read_text()
        meta = (mount / "meta-data").read_text()
    finally:
        run(["umount", str(mount)])
    result = apply(user_data, meta, run=run)
    print("baseline-seed:", json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SeedError as exc:
        print(f"baseline-seed: STOPPED: {exc}", file=sys.stderr)
        sys.exit(1)
