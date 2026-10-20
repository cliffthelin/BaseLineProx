"""Who the person is: the one who runs the installer (operator, 2026-10-19: "Cane must be root").

The installer is run by the person who owns the machine, and the system knows who that is (the name that asked for root). That name is recorded once on USER_ADMIN (`config/operator.json`) and
is the account every machine Baseline makes gives its owner, with full administrator rights (no password, sudo without a prompt: root-equivalent). A Proxmox sign-in as `root` is the same person.
Nothing is guessed: no name means the person is asked, and no generic account is ever made. Never overwrites a name already recorded.
"""
from __future__ import annotations

import json
import os
import pwd
import re
from pathlib import Path

FILE = "config/operator.json"
_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def invoking_user(environ=None) -> str | None:
    """The person who started the install, from what the elevation carried (BASELINE_OPERATOR), sudo (SUDO_USER) or pkexec (PKEXEC_UID); never root."""
    environ = os.environ if environ is None else environ
    for key in ("BASELINE_OPERATOR", "SUDO_USER"):
        name = str(environ.get(key, "")).strip().lower()
        if _NAME.match(name) and name != "root":
            return name
    uid = str(environ.get("PKEXEC_UID", "")).strip()
    if uid.isdigit():
        try:
            name = pwd.getpwuid(int(uid)).pw_name.lower()
        except KeyError:
            return None
        if _NAME.match(name) and name != "root":
            return name
    return None


def read(path) -> str | None:
    try:
        name = json.loads(Path(path).read_text()).get("username")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and _NAME.match(name) and name != "root" else None


def record(admin_root, name) -> dict:
    """Write the name to USER_ADMIN once. {"file", "result"}; an existing record is kept exactly as it is."""
    target = Path(admin_root) / FILE
    if read(target):
        return {"file": FILE, "result": "kept the drive's own"}
    if not name:
        return {"file": FILE, "result": "not written: nobody to record (run the installer as yourself, not as root directly)"}
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.write_text(json.dumps({"username": name}) + "\n")
    tmp.replace(target)
    return {"file": FILE, "result": "added", "username": name}
