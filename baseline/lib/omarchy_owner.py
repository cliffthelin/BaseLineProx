#!/usr/bin/env python3
"""Omarchy's own first-boot account setup, fed from the seed instead of a form.

Omarchy installed in deferred-provisioning mode makes its owner at the first boot with `omarchy-provision-owner`, which asks for a username and a password on the console (and sets that
password on root too). A VM made from the base takes its owner from the signed-in Proxmox user, with no password at all, so this runs Omarchy's OWN provisioning functions (the account,
groups, hostname, the finalizing of the user's configuration) with the answers taken from the seed, and then:

  * the password Omarchy needs is a random one nobody sees, locked on the user and on root straight afterwards,
  * the sign-in the setup grants for the first boot is kept (Omarchy removes it again after one boot on unencrypted installs),
  * the owner gets sudo without a prompt, like the owners of the other ready-made systems.

The vendor script is read from the installed system and patched in memory; if it is not the shape this was written for (Omarchy 4.0.x) it is refused, not guessed at. A system that
has no pending first-boot setup is left alone, and a machine started without a seed still shows Omarchy's own interactive setup.

Takes the owner's account name and the hostname: `omarchy_owner.py <owner> <hostname>`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

VENDOR = "/usr/bin/omarchy-provision-owner"
_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_HOST = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


class OwnerError(Exception):
    pass


def seeded_script(vendor: str, *, owner: str, hostname: str) -> str:
    """The vendor script with its final `main` call replaced by: the answers, then Omarchy's own `run_provisioning`."""
    if not _NAME.match(owner or "") or not _HOST.match(hostname or ""):
        raise OwnerError("the owner's name and the hostname are plain lowercase names")
    lines = vendor.split("\n")
    mains = [i for i, line in enumerate(lines) if line.strip() == "main"]
    if len(mains) != 1 or "run_provisioning()" not in vendor or "STATE_FILE=" not in vendor or "LOG_FILE=" not in vendor:
        raise OwnerError("this Omarchy's first-boot script is not the one this was written for")
    block = [
        f"username={owner}",
        "password=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')",
        "full_name=''", "email_address=''", f"hostname={hostname}", "timezone=UTC",
        'touch "$LOG_FILE"', 'chmod 600 "$LOG_FILE"', 'echo account >"$STATE_FILE"',
        'run_provisioning >>"$LOG_FILE" 2>&1',
    ]
    lines[mains[0]:mains[0] + 1] = block
    return "\n".join(lines).rstrip("\n") + "\n"


OWNER_UID = 1100                                                          # the same in every ready-made system, so a retained home belongs to the owner everywhere


def provision(owner: str, hostname: str, *, run, root="/", work_dir="/run/baseline-seed") -> dict:
    root = Path(root)
    if not (root / "var/lib/omarchy/provisioning/pending").exists():
        return {"skipped": "no first-boot setup is pending"}
    vendor = (root / VENDOR.lstrip("/")).read_text()
    script = seeded_script(vendor, owner=owner, hostname=hostname)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    target = work / "omarchy-owner-seeded.sh"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
    with os.fdopen(fd, "w") as handle:
        handle.write(script)
    if run(["getent", "passwd", owner])[0] != 0:                          # made here, with the fixed uid; Omarchy's script then resumes this account (it adds the groups) instead of choosing a uid
        code, out, err = run(["useradd", "-u", str(OWNER_UID), "-m", "-s", "/bin/bash", owner])
        if code:
            raise OwnerError(f"making the account {owner} failed: {(err or out).strip()[-300:]}")
    code, out, err = run(["bash", str(target)])
    target.unlink(missing_ok=True)
    if code:
        raise OwnerError(f"Omarchy's own account setup failed: {(err or out).strip()[-300:] or 'no message'}")
    for account in (owner, "root"):
        run(["passwd", "-l", account])                                    # the random password was only ever needed by Omarchy's script
    once = root / "etc/systemd/system/omarchy-provision-autologin-once.service"
    for leftover in (once, root / "etc/systemd/system/graphical.target.wants/omarchy-provision-autologin-once.service"):
        if leftover.is_symlink() or leftover.exists():
            leftover.unlink()
    sddm = root / "etc/sddm.conf.d/baseline-autologin.conf"
    sddm.parent.mkdir(parents=True, exist_ok=True)
    sddm.write_text(f"[Autologin]\nUser={owner}\nSession=omarchy.desktop\n")
    sudoers = root / f"etc/sudoers.d/90-baseline-{owner}"
    sudoers.parent.mkdir(parents=True, exist_ok=True)
    sudoers.unlink(missing_ok=True)
    sudoers.write_text(f"{owner} ALL=(ALL) NOPASSWD:ALL\n")
    os.chmod(sudoers, 0o440)
    run(["systemctl", "daemon-reload"])
    return {"owner": owner, "hostname": hostname}


class RealRun:
    def __call__(self, argv):
        done = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
        return done.returncode, done.stdout, done.stderr


def main(argv) -> int:
    if len(argv) != 3:
        print("usage: omarchy_owner.py <owner> <hostname>", file=sys.stderr)
        return 2
    try:
        print("omarchy-owner:", provision(argv[1], argv[2], run=RealRun()))
    except OwnerError as exc:
        print(f"omarchy-owner: STOPPED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
