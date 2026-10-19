"""Name the drives this machine builds for (the installer's drives file, as a console page).

The file ({"drives": {"NAME": "SERIAL"}}) is operator data on a git-ignored volume, never in the repository. A name is a short plain label; a
serial can be named only while the drive is attached and never when it is the drive this machine runs from. Loading uses the same rules as
`baseline-allscript-install` so the two can never disagree about which drives exist.
"""
from __future__ import annotations

import html
import json
import os
import re
import tempfile
from pathlib import Path

_NAME = re.compile(r"[A-Za-z0-9_-]{1,20}")
_SERIAL = re.compile(r"[A-Za-z0-9_.-]{8,64}")


def default_path() -> Path:
    return Path(os.environ.get("BASELINE_DRIVES_FILE") or "/var/lib/baseline/drives.json")


def load(path=None) -> dict:
    try:
        raw = json.loads(Path(path or default_path()).read_text())["drives"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {str(n): s for n, s in raw.items() if _NAME.fullmatch(str(n)) and isinstance(s, str) and _SERIAL.fullmatch(s)}


def attached(runner) -> list:
    done = runner.run(["lsblk", "-J", "-b", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN,TYPE,MOUNTPOINTS"], timeout=15)
    if done.returncode != 0:
        return []
    try:
        tree = json.loads(done.stdout)["blockdevices"]
    except (ValueError, KeyError, TypeError):
        return []

    def mounts(node):
        found = [m for m in (node.get("mountpoints") or []) if m]
        for child in node.get("children") or []:
            found += mounts(child)
        return found
    disks = []
    for node in tree:
        if node.get("type") != "disk" or not node.get("serial"):
            continue
        disks.append({"name": node["name"], "serial": str(node["serial"]).strip(), "model": (node.get("model") or "").strip(),
                      "size_gib": round(int(node.get("size") or 0) / 2 ** 30), "transport": node.get("tran") or "",
                      "boot": "/" in mounts(node)})
    return disks


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"drives": data}, handle, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def assign(path, name, serial, disks) -> dict:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("a drive name is 1 to 20 letters, digits, dashes or underscores")
    match = next((d for d in disks if d["serial"] == serial), None)
    if match is None:
        raise ValueError("that drive is not attached")
    if match["boot"]:
        raise ValueError("that is the drive this machine runs from; it cannot be named as a build target")
    current = load(path)
    if name in current or serial in current.values():
        raise ValueError("that name or that drive is already in the list")
    current[name] = serial
    _write(path, current)
    return current


def remove(path, name) -> dict:
    current = load(path)
    current.pop(name, None)
    _write(path, current)
    return current


def render(disks, names, notice="") -> bytes:
    by_serial = {s: n for n, s in names.items()}
    rows = ""
    for d in disks:
        named = by_serial.get(d["serial"])
        if d["boot"]:
            action = "the drive this machine runs from"
        elif named:
            action = (f'<form method="post" action="/drive-names/remove"><input type="hidden" name="name" value="{html.escape(named, quote=True)}">'
                      "<button type=\"submit\">Remove the name</button></form>")
        else:
            action = ('<form method="post" action="/drive-names/assign">'
                      f'<input type="hidden" name="serial" value="{html.escape(d["serial"], quote=True)}">'
                      "<input name=\"name\" maxlength=\"20\" pattern=\"[A-Za-z0-9_-]+\" placeholder=\"a short name\" required> "
                      "<button type=\"submit\">Name this drive</button></form>")
        rows += (f"<tr><td>{html.escape(named or 'not named')}</td><td>{html.escape(d['model'])}</td><td>{d['size_gib']} GiB</td>"
                 f"<td>{html.escape(d['transport'])}</td><td>{action}</td></tr>")
    note = f"<p>{html.escape(notice)}</p>" if notice else ""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Name your drives</title></head><body><h1>Name your drives</h1>"
            f"{note}<p>The drives this computer may build and rebuild. A name is how you refer to a drive when you start an install.</p>"
            "<table><thead><tr><th>Name</th><th>Drive</th><th>Size</th><th>Connection</th><th></th></tr></thead>"
            f"<tbody>{rows or '<tr><td colspan=5>None found</td></tr>'}</tbody></table></body></html>").encode()
