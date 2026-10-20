"""Update an existing build's files without being root: only the commands the operator's sudoers file already allows without a password are used (activate the volume group, mount, unmount).

A volume is mounted, then bound again through an idmapped mount that shows root's files as the operator's own; writes through it are stored on disk owned by root, exactly as if root had made them.
Only files that differ are written (`write_once.copy_changed`); nothing is deleted. What it cannot do without root is reported, not skipped silently: installing packages, and anything that needs a chroot.

`deploy_plan` reads the build's own `boot/provision.sh` for where each file goes (its `cp`, `sync_tree` and `systemctl enable` lines), so the deployment is described in one place only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import write_once

SUDO = ["sudo", "-n"]
SKIP_DEST = ("/mnt/", "/dev/", "/proc/", "/sys/", "/run/")      # other volumes and live system folders are never written through the root volume
_CP = re.compile(r'^\s*cp\s+"\$SRC/(?P<src>[^"]+)"\s+(?P<dst>/\S+?)\s*(?:#.*)?$')
_TREE = re.compile(r'^\s*sync_tree\s+"\$SRC/(?P<src>[^"]+)"\s+(?P<dst>/\S+?)\s*(?:#.*)?$')
_CHMOD = re.compile(r'^\s*chmod\s+(?P<mode>[0-7]{3,4})\s+(?P<paths>/\S+(?:\s+/\S+)*)\s*(?:#.*)?$')
_ENABLE = re.compile(r'^\s*systemctl\s+enable\s+(?P<unit>[A-Za-z0-9@._-]+)\s*(?:#.*)?$')
_INSTALL_ACTIONS = re.compile(r'^\s*(apt-get install|npm install|dpkg -i|useradd|usermod|groupadd|update-initramfs|update-grub)\b')


class RootlessError(RuntimeError):
    pass


def deploy_plan(provision_text: str) -> dict:
    """{"copies": [(src, dst)], "trees": [(src, dst)], "modes": [(mode, path)], "enables": [unit], "needs_root": [line]} from provision.sh."""
    plan = {"copies": [], "trees": [], "modes": [], "enables": [], "needs_root": []}
    for line in provision_text.splitlines():
        if (m := _CP.match(line)):
            plan["copies"].append((m["src"], m["dst"]))
        elif (m := _TREE.match(line)):
            plan["trees"].append((m["src"], m["dst"]))
        elif (m := _CHMOD.match(line)):
            plan["modes"] += [(int(m["mode"], 8), p) for p in m["paths"].split()]
        elif (m := _ENABLE.match(line)):
            plan["enables"].append(m["unit"])
        elif _INSTALL_ACTIONS.match(line):
            plan["needs_root"].append(line.strip())
    return plan


def _run(argv, what, check=True):
    done = subprocess.run(argv, capture_output=True, text=True)
    if check and done.returncode:
        raise RootlessError(f"{what} failed: {(done.stderr or done.stdout or '').strip()[-300:]}")
    return done


class Volume:
    """One filesystem of the target, mounted read-write and shown through an idmapped bind mount (root's files appear as the operator's)."""

    def __init__(self, device, base, name):
        self.device, self.raw, self.view = device, Path(base) / f"{name}.raw", Path(base) / name
        self.mounted = []

    def __enter__(self):
        self.raw.mkdir(parents=True, exist_ok=True)
        self.view.mkdir(parents=True, exist_ok=True)
        _run([*SUDO, "mount", "-t", "ext4", "-o", "rw,nodev,nosuid", self.device, str(self.raw)], f"mounting {self.device}")
        self.mounted.append(self.raw)
        _run([*SUDO, "mount", "--bind", "-o", f"X-mount.idmap=b:0:{os.getuid()}:1", str(self.raw), str(self.view)], f"mapping {self.device} to your user")
        self.mounted.append(self.view)
        return self.view

    def __exit__(self, *exc):
        os.sync()
        for point in reversed(self.mounted):
            _run([*SUDO, "umount", str(point)], f"unmounting {point}", check=False)


def apply_plan(plan: dict, source: Path, root: Path) -> dict:
    """Copy what differs into `root` (the target's root filesystem as the operator sees it). Returns what was written and what was not."""
    source, root = Path(source), Path(root)
    report = {"copied": 0, "unchanged": 0, "missing_source": [], "skipped_dest": [], "modes_set": 0, "enabled": [], "needs_root": plan["needs_root"]}

    def target(dst):
        return root / dst.lstrip("/")

    for src, dst in plan["copies"]:
        if dst.startswith(SKIP_DEST):
            report["skipped_dest"].append(dst)
            continue
        s = source / src
        if not s.is_file():
            report["missing_source"].append(src)
            continue
        d = target(dst)
        if d.is_dir():
            d = d / s.name
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.is_file() and not d.is_symlink() and __import__("filecmp").cmp(s, d, shallow=False):
            report["unchanged"] += 1
        else:
            shutil.copy2(s, d)
            report["copied"] += 1
    for src, dst in plan["trees"]:
        if dst.startswith(SKIP_DEST) or not (source / src).is_dir():
            continue
        out = write_once.copy_changed(source / src, target(dst), shutil.ignore_patterns("__pycache__", "*.pyc"))
        report["copied"] += out["copied"]
        report["unchanged"] += out["unchanged"]
    for mode, path in plan["modes"]:
        t = target(path)
        if t.is_file() and not t.is_symlink() and (t.stat().st_mode & 0o7777) != mode:
            os.chmod(t, mode)
            report["modes_set"] += 1
    for unit in plan["enables"]:
        unit_file = target(f"/etc/systemd/system/{unit}")
        if not unit_file.is_file():
            continue
        wanted = re.search(r"^WantedBy=(\S+)", unit_file.read_text(), re.M)
        if wanted:
            wants = root / "etc/systemd/system" / f"{wanted.group(1)}.wants"
            link = wants / unit
            if not link.is_symlink():
                wants.mkdir(parents=True, exist_ok=True)
                os.symlink(f"/etc/systemd/system/{unit}", link)
                report["enabled"].append(unit)
    return report
