"""The operator's list of operating systems to support (DR261).

The list is the operator's own choice, so it is never committed: the build machine's working copy is `config/local/supported-os.json` (git-ignored;
`config/supported-os.example.json` shows the shape) and the installed host keeps its copy on USER_ADMIN, where non-public host configuration lives (DR257).
Each entry also lists the applications to install and configure on it (default: all five; a Kasm entry has none, its workspaces are its applications).
Entries are checked here once, so everything that reads the list sees the same thing. Nothing in this module ever writes outside the file it is given.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HOST_COPY = Path("/mnt/USER_ADMIN/config/supported-os.json")
REPO_COPY = Path(__file__).resolve().parents[2] / "config" / "local" / "supported-os.json"
KINDS = ("vm", "container", "kasm")
APPS = ("vscode", "spotify", "chrome", "chatgpt", "claude")     # the five guest applications (DR258); an entry lists the ones to install and configure on it
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_ISO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


class OsListError(ValueError):
    pass


_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _workspaces(ident, raw, kind):
    """A Kasm entry may name the workspaces its base carries: [{key, image, friendly_name, persistent}]. None means the build's own default set."""
    if raw is None:
        return None
    if kind != "kasm":
        raise OsListError(f"{ident}: only a kasm entry has workspaces")
    if not isinstance(raw, list) or not raw:
        raise OsListError(f"{ident}: workspaces must be a non-empty list")
    out, keys, names = [], set(), set()
    for number, item in enumerate(raw, 1):
        if not isinstance(item, dict) or not _KEY.fullmatch(str(item.get("key", ""))) or not _KEY.fullmatch(str(item.get("image", ""))):
            raise OsListError(f"{ident}: workspace {number} needs a key and an image (lowercase letters, digits and dashes)")
        friendly = item.get("friendly_name")
        if not isinstance(friendly, str) or not friendly.strip() or len(friendly) > 60 or not isinstance(item.get("persistent"), bool):
            raise OsListError(f"{ident}: workspace {item['key']} needs a friendly_name (up to 60 characters) and persistent true or false")
        if item["key"] in keys or friendly in names:
            raise OsListError(f"{ident}: workspace keys and names must be unique")
        keys.add(item["key"])
        names.add(friendly)
        out.append({"key": item["key"], "image": item["image"], "friendly_name": friendly.strip(), "persistent": item["persistent"]})
    return out


def _entry(raw, position: int) -> dict:
    if not isinstance(raw, dict):
        raise OsListError(f"entry {position + 1} is not an object")
    ident, name = raw.get("id"), raw.get("name")
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise OsListError(f"entry {position + 1}: id must be lowercase letters, digits and dashes (1-32)")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise OsListError(f"{ident}: name is required (up to 80 characters)")
    kind = raw.get("kind", "vm")
    if kind not in KINDS:
        raise OsListError(f"{ident}: kind must be one of {', '.join(KINDS)}")
    iso = raw.get("iso")
    if iso is not None and (not isinstance(iso, str) or not _ISO.fullmatch(iso)):
        raise OsListError(f"{ident}: iso must be a file name, not a path")
    apps = raw.get("apps", list(APPS) if kind != "kasm" else [])
    if not isinstance(apps, list) or any(a not in APPS for a in apps) or len(set(apps)) != len(apps):
        raise OsListError(f"{ident}: apps must be a list without repeats from {', '.join(APPS)}")
    workspaces = _workspaces(ident, raw.get("workspaces"), kind)
    notes = raw.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 300:
        raise OsListError(f"{ident}: notes must be text up to 300 characters")
    return {"id": ident, "name": name.strip(), "kind": kind, "iso": iso, "apps": apps, "workspaces": workspaces, "notes": notes}


def parse(text: str) -> list:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise OsListError(f"the list is not valid JSON: {exc}") from None
    rows = data.get("os") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise OsListError('the list needs an "os" array')
    entries = [_entry(row, i) for i, row in enumerate(rows)]
    seen = set()
    for entry in entries:
        if entry["id"] in seen:
            raise OsListError(f"{entry['id']} is listed twice")
        seen.add(entry["id"])
    return entries


def locate(environ=None, host=HOST_COPY, repo=REPO_COPY):
    """The list in use: the path named by BASELINE_OS_LIST, else the host's copy on USER_ADMIN, else the build machine's git-ignored working copy."""
    environ = os.environ if environ is None else environ
    named = environ.get("BASELINE_OS_LIST")
    for path in ([Path(named)] if named else []) + [Path(host), Path(repo)]:
        if path.is_file():
            return path
    return None


def load(path=None) -> list:
    """The checked entries; an empty list when no list exists yet (nothing is assumed about which systems the operator wants)."""
    path = Path(path) if path is not None else locate()
    return parse(path.read_text()) if path is not None else []


NAMES = {"debian": "Debian", "ubuntu": "Ubuntu", "nixos": "NixOS", "cachyos": "CachyOS", "bazzite": "Bazzite", "omarchy": "Omarchy", "fydeos": "FydeOS",
         "qubes": "Qubes OS", "mx": "MX Linux"}
NOT_GUESTS = ("proxmox",)            # the host's own installer source is not a system to run as a guest


def _token(filename: str) -> str:
    """The system an image file is for, from its name: `Qubes-R4.3.2-x86_64.iso` -> `qubes`, `proxmox-ve-source.iso` -> `proxmox`."""
    stem = re.split(r"[-_.\d]", filename.rsplit("/", 1)[-1], maxsplit=1)[0].lower()
    return re.sub(r"[^a-z0-9]", "", stem)


def derived(base_ids=(), image_names=()) -> list:
    """The systems this machine can offer, worked out from what it carries, with nobody having to write a list: one entry per ready-made base and one per image file whose system has no base. The
    entries are the same checked shape as a written list (all five guest applications by default), and a list the operator does write, if any, takes the place of this one."""
    entries, seen = [], set()
    images = list(image_names)
    for ident in sorted(base_ids):
        if not _ID.fullmatch(ident):
            continue
        iso = next((n for n in images if _token(n) == ident and _ISO.fullmatch(n)), None)
        entries.append(_entry({"id": ident, "name": NAMES.get(ident, ident.title()), "kind": "vm", **({"iso": iso} if iso else {})}, len(entries)))
        seen.add(ident)
    for name in sorted(images):
        ident = _token(name)
        if not ident or ident in seen or ident in NOT_GUESTS or not _ID.fullmatch(ident) or not _ISO.fullmatch(name):
            continue
        entries.append(_entry({"id": ident, "name": NAMES.get(ident, ident.title()), "kind": "vm", "iso": name}, len(entries)))
        seen.add(ident)
    return entries


def render(entries) -> str:
    """The list as the file USER_ADMIN keeps (the shape `parse` reads)."""
    rows = [{k: v for k, v in e.items() if v not in (None, "", [], {})} | {"apps": e["apps"]} for e in entries]
    return json.dumps({"os": rows}, indent=1) + "\n"


def derive_from_cache(cache_root) -> list:
    """The list of systems for a drive, worked out from what its INSTALLER_CACHE carries (ready-made bases and OS images). Each entry presets the five guest applications."""
    root = Path(cache_root)
    bases_dir = root / "installer/expanded/baseline-cache/os-bases"
    bases = set()
    try:
        for manifest in sorted(bases_dir.glob("*-base.json")):
            try:
                if (bases_dir / json.loads(manifest.read_text())["base"]).is_file():
                    bases.add(manifest.name[:-len("-base.json")])
            except (OSError, ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    images = []
    try:
        images = sorted(p.name for p in (root / "isos").iterdir() if p.is_file())
    except OSError:
        pass
    return derived(bases, images)
