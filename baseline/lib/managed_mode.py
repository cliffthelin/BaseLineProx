"""Managed server mode is opt-in. Without it, a Baseline user only changes their own build and is never asked to connect to a parent.

Everything that involves a parent (the mirror and its version history, filing under a combination, the remote rebuild service) reads its settings here and does nothing when the mode is `standalone`, which is the
default and the state of every install until its operator turns managed mode on in the installer / build manager. The platform works fully without it; with it, the parent keeps every child's
each child's mirror and version history and can rebuild children remotely, which makes the whole more stable and more capable.

The settings are the operator's own data in a file outside the repository (next to the drives file on a build host, `/etc/baseline/managed.json` on an installed system).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from write_once import write_if_changed

MODES = ("standalone", "managed")
DEFAULTS = {"mode": "standalone", "mirror_root": None, "remote_rebuild": False}


class ManagedError(ValueError):
    pass


def config_path(environ=None) -> Path:
    env = os.environ if environ is None else environ
    if env.get("BASELINE_MANAGED_FILE"):
        return Path(env["BASELINE_MANAGED_FILE"])
    if env.get("BASELINE_DRIVES_FILE"):
        return Path(env["BASELINE_DRIVES_FILE"]).parent / "managed.json"
    return Path("/etc/baseline/managed.json")


def load(path=None) -> dict:
    """The settings, or the defaults (standalone) when there is no file or it cannot be read: a broken file never turns managed mode on."""
    try:
        data = json.loads(Path(path or config_path()).read_text())
    except (OSError, ValueError):
        return dict(DEFAULTS)
    if not isinstance(data, dict) or data.get("mode") not in MODES:
        return dict(DEFAULTS)
    if data.get("parent_vault") and not data.get("mirror_root"):          # an earlier name for the same setting: the mirror sits in the folder that held it
        data = dict(data, mirror_root=str(Path(data["parent_vault"]).parent))
    return {**DEFAULTS, **{k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}}


def is_managed(path=None) -> bool:
    return load(path)["mode"] == "managed"


def mirror_root(path=None) -> str | None:
    """Where the mirror lives (managed mode only): the drive or folder that holds every child's files and version history."""
    cfg = load(path)
    return cfg["mirror_root"] if cfg["mode"] == "managed" and cfg["mirror_root"] else None


def remote_rebuild_enabled(path=None) -> bool:
    cfg = load(path)
    return cfg["mode"] == "managed" and bool(cfg["remote_rebuild"])


def save(settings: dict, path=None) -> dict:
    mode = settings.get("mode", "standalone")
    if mode not in MODES:
        raise ManagedError(f"mode is one of {', '.join(MODES)}")
    cfg = {**DEFAULTS, **{k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}}
    if mode == "managed" and not cfg["mirror_root"]:
        raise ManagedError("managed mode needs the place the mirror is kept")
    if cfg["remote_rebuild"] and mode != "managed":
        raise ManagedError("remote rebuild is part of managed mode")
    write_if_changed(Path(path or config_path()), json.dumps(cfg, indent=1) + "\n")
    return cfg


def candidate_folders(mounts_text: str) -> list:
    """Places the mirror could live, offered as choices so nobody has to type a path: each mounted data drive (under /mnt, /media or /run/media)."""
    found = []
    for line in (mounts_text or "").splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] in ("tmpfs", "proc", "sysfs", "devtmpfs", "cgroup2", "overlay", "squashfs", "autofs", "efivarfs"):
            continue
        mount = parts[1].replace("\\040", " ")
        if mount.startswith(("/mnt/", "/media/", "/run/media/")):
            found.append({"folder": mount.rstrip("/"), "volume": mount.rstrip("/")})
    seen, out = set(), []
    for item in found:
        if item["folder"] not in seen:
            seen.add(item["folder"])
            out.append(item)
    return out
