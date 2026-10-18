"""The application catalogue and the helper that installs an application on a given system (DR266 item 4; operator 2026-10-17).

Each entry says, per kind of route, how the application is installed: from the system's own package repository (`apt`, `pacman`), declared in a NixOS configuration (`nix`), as a Flatpak
(`flatpak`, for Bazzite and anywhere the repository has no package), as a portable app inside a Kasm desktop (`proot`), or as a service container behind Kasm's web gateway (`container`).
`route_for` picks one for a system from that system's own order of preference; `install_script` writes the shell that does it (non-interactive, every value validated first, nothing taken from the
person's input). Where no route fits, the answer says so instead of choosing something unsafe.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FORMAT = "baseline.app-catalogue/v1"
CATEGORIES = ("browsers", "developer-tools", "ai-tools", "media", "ai-image-tools", "office-tools")
ROUTES = ("apt", "pacman", "nix", "flatpak", "proot", "container")
# What each system prefers first. Immutable and declarative systems have narrower choices; Ubuntu's repository packages for browsers are snaps, so it prefers Flatpak.
PREFERENCE = {
    "debian": ("apt", "flatpak"), "ubuntu": ("flatpak", "apt"), "cachyos": ("pacman", "flatpak"), "omarchy": ("pacman", "flatpak"),
    "bazzite": ("flatpak",), "nixos": ("nix", "flatpak"), "kasm": ("proot", "container"),
}
_ID = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,80}$")
_FLATPAK = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}$")
_NIX_ATTR = re.compile(r"^[a-z][A-Za-z0-9_.-]{0,60}$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9./_-]{0,100}:[A-Za-z0-9_][A-Za-z0-9._-]{0,60}$")


class CatalogueError(ValueError):
    pass


def validate_entry(entry) -> dict:
    if not isinstance(entry, dict) or not _ID.match(str(entry.get("id", ""))) or entry.get("category") not in CATEGORIES or not str(entry.get("name", "")).strip():
        raise CatalogueError("an entry needs an id, a name and one of the known categories")
    routes = entry.get("routes")
    if not isinstance(routes, dict) or not routes or not set(routes) <= set(ROUTES):
        raise CatalogueError(f"{entry['id']}: routes are some of {', '.join(ROUTES)}")
    for route, params in routes.items():
        if not isinstance(params, dict):
            raise CatalogueError(f"{entry['id']}.{route}: parameters are an object")
        ok = {"apt": lambda p: _PACKAGE.match(str(p.get("package", ""))), "pacman": lambda p: _PACKAGE.match(str(p.get("package", ""))),
              "nix": lambda p: _NIX_ATTR.match(str(p.get("attr", ""))), "flatpak": lambda p: _FLATPAK.match(str(p.get("id", ""))),
              "proot": lambda p: _PACKAGE.match(str(p.get("name", ""))),
              "container": lambda p: _IMAGE.match(str(p.get("image", ""))) and isinstance(p.get("ports"), list) and all(isinstance(x, int) and 1 <= x <= 65535 for x in p["ports"])
              and str(p.get("config", "")).startswith("/")}[route](params)
        if not ok:
            raise CatalogueError(f"{entry['id']}.{route}: a value is not a plain name")
        only = params.get("only")
        if only is not None and (not isinstance(only, list) or not all(o in PREFERENCE for o in only)):
            raise CatalogueError(f"{entry['id']}.{route}: only lists known systems")
    data = entry.get("data", [])
    if not isinstance(data, list) or not all(isinstance(d, str) and d.startswith(("~/", "/")) and ".." not in d for d in data):
        raise CatalogueError(f"{entry['id']}: data paths are absolute or start with ~/")
    return entry


def load(path=None) -> dict:
    """{id: entry} from the catalogue file (default: config/app-catalogue.json beside the source), every entry validated and ids unique."""
    path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "app-catalogue.json"
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CatalogueError(f"the application catalogue cannot be read: {exc}") from None
    if document.get("format") != FORMAT or not isinstance(document.get("apps"), list):
        raise CatalogueError(f"the catalogue has format {FORMAT} and a list of apps")
    out = {}
    for entry in document["apps"]:
        validate_entry(entry)
        if entry["id"] in out:
            raise CatalogueError(f"{entry['id']} is listed twice")
        out[entry["id"]] = entry
    return out


def route_for(entry: dict, os_id: str):
    """(route, params) for this system, or (None, reason). The system's own preference order decides; a route restricted with `only` is skipped elsewhere."""
    order = PREFERENCE.get(os_id)
    if order is None:
        return None, f"{os_id} is not a system this catalogue knows"
    for route in order:
        params = entry["routes"].get(route)
        if params is not None and os_id in (params.get("only") or [os_id]):
            return route, params
    return None, f"{entry['name']} has no route that fits {os_id} (it offers: {', '.join(sorted(entry['routes']))})"


FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
# `apt-get update` exits non-zero when ANY source cannot be read (a leftover installer-medium line, a third-party repository that is down), though the lists that matter were fetched; the install that
# follows is what must succeed, so an update error is reported and not fatal.
_APT_UPDATE = 'apt-get update || echo "apt-get update reported errors; going on to the install" >&2'
_FLATPAK_FIRST = {"debian": _APT_UPDATE + "\napt-get install -y flatpak", "ubuntu": _APT_UPDATE + "\napt-get install -y flatpak", "cachyos": "pacman -Syu --noconfirm --needed flatpak", "omarchy": "pacman -Syu --noconfirm --needed flatpak",
                  "bazzite": "command -v flatpak >/dev/null"}


def install_script(entry: dict, os_id: str):
    """The shell that installs the application on this system, or None where the route is not an install-time command (nix is declared in the configuration; proot and container belong to the Kasm
    and service-host sides). Non-interactive and fail-fast."""
    route, params = route_for(entry, os_id)
    if route is None:
        raise CatalogueError(params)
    head = ["#!/bin/sh", "set -eu", "export DEBIAN_FRONTEND=noninteractive"]
    if route == "apt":
        return "\n".join(head + [_APT_UPDATE, f"apt-get install -y {params['package']}"]) + "\n"
    if route == "pacman":
        return "\n".join(head + [f"pacman -Syu --noconfirm --needed {params['package']}"]) + "\n"
    if route == "flatpak":
        prerequisite = _FLATPAK_FIRST.get(os_id)
        return "\n".join(head + ([prerequisite] if prerequisite else []) + [f"flatpak remote-add --if-not-exists --system flathub {FLATHUB}", f"flatpak install -y --system --noninteractive flathub {params['id']}"]) + "\n"
    return None


def nix_attrs(entries) -> list:
    """The nixpkgs attributes for the applications that have a nix route, for a NixOS configuration's systemPackages."""
    return [e["routes"]["nix"]["attr"] for e in entries if "nix" in e["routes"]]
