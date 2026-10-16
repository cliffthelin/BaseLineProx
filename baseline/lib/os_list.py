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
    notes = raw.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 300:
        raise OsListError(f"{ident}: notes must be text up to 300 characters")
    return {"id": ident, "name": name.strip(), "kind": kind, "iso": iso, "apps": apps, "notes": notes}


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
