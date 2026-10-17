"""The environments catalogue (DR258): each carried OS image against the five guest applications.

States are honest: "native" means the application bundle supports that platform (application_bundle's own targets); "helper" means the OS
needs an adapter that is not built; "none" means nothing of ours runs there. An environment is "built" only when a VM or container of that
name exists. Nothing here claims an application is installed: the build that installs them is the open DR258 work.
"""
from __future__ import annotations

import html
import re

APPS = ("vscode", "spotify", "chrome", "chatgpt", "claude")
NATIVE = {("ubuntu", "24.04"), ("ubuntu", "26.04"), ("debian", "13")}      # mirrors application_bundle's supported targets
_RULES = (
    (re.compile(r"ubuntu-(\d\d\.\d\d)", re.I), "ubuntu"),
    (re.compile(r"debian-(\d+)", re.I), "debian"),
    (re.compile(r"^MX-(\d+)", re.I), "debian"),             # MX Linux is Debian-based, but its release is not Debian's: no native claim
)


def classify(iso: str):
    name = iso.lower()
    for pattern, family in _RULES:
        m = pattern.search(iso)
        if m:
            release = m.group(1) if family != "debian" or name.startswith("debian") else ""
            return ("mx" if name.startswith("mx-") else family), release
    for needle, family in (("cachyos", "arch"), ("omarchy", "arch"), ("nixos", "nixos"), ("rescue", "rescue"),
                           ("qubes", "qubes"), ("fydeos", "chromeos"), ("bazzite", "fedora")):
        if needle in name:
            return family, ""
    return "unknown", ""


def catalogue(isos, vms) -> list:
    names = {vm.get("name"): vm for vm in vms}
    rows = []
    for iso in sorted(isos):
        family, release = classify(iso)
        if (family, release) in NATIVE:
            level = "native"
        elif family == "rescue":
            level = "none"
        else:
            level = "helper"
        built = next((n for n in names if n and family in n.lower() and (not release or release in n)), None)
        rows.append({"iso": iso, "os": family, "release": release, "apps": {a: level for a in APPS},
                     "state": "built" if built else "not built", "vm": built})
    return rows


def match_image(iso: str, carried) -> str | None:
    """The carried image the list's file name refers to, or None. A local image folder names images by file name; Proxmox names them by volume
    (`installer-cache:iso/<file>`), so the match is on the file name, and what is returned is the name the host itself uses (what its create action takes)."""
    wanted = iso.rsplit("/", 1)[-1]
    for name in carried:
        if name == iso or name.rsplit("/", 1)[-1] == wanted:
            return name
    return None


def listed_catalogue(listing, isos, vms) -> list:
    """The catalogue built from the operator's supported-OS list (DR261/262) instead of from whatever images happen to be on the drive: one row per VM entry, in the
    list's order, with the applications that entry asks for (others are "not planned") and "image missing" when the cache does not carry its file. Kasm entries are
    the workspaces component, not a guest OS, so they are not rows here."""
    names = {vm.get("name"): vm for vm in vms}
    rows = []
    for entry in listing:
        if entry["kind"] == "kasm":
            continue
        iso = entry.get("iso") or ""
        carried_as = match_image(iso, isos) if iso else None
        family, release = classify(iso) if iso else ("unknown", "")
        level = "native" if (family, release) in NATIVE else "none" if family == "rescue" else "helper"
        built = next((n for n in names if n and (entry["id"] in n.lower() or (family != "unknown" and family in n.lower() and (not release or release in n)))), None)
        rows.append({"iso": iso or entry["name"], "id": entry["id"], "name": entry["name"], "os": family, "release": release,
                     "apps": {a: (level if a in entry["apps"] else "not planned") for a in APPS},
                     "image": "carried" if carried_as else ("missing" if iso else "none listed"), "carried_as": carried_as,
                     "state": "built" if built else "not built", "vm": built})
    return rows


def _image_cell(row) -> str:
    if "name" not in row:
        return html.escape(row["iso"])
    return f"<b>{html.escape(row['name'])}</b><br><small>{html.escape(row['iso'])}: image {html.escape(row['image'])}</small>"


def render(rows) -> bytes:
    head = "".join(f"<th>{html.escape(a)}</th>" for a in APPS)
    body = "".join(
        f"<tr><td>{_image_cell(r)}</td><td>{html.escape(r['os'])} {html.escape(r['release'])}</td>"
        + "".join(f"<td>{html.escape(r['apps'][a])}</td>" for a in APPS)
        + f"<td>{html.escape(r['state'])}{(' (' + html.escape(r['vm']) + ')') if r['vm'] else ''}</td></tr>" for r in rows)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Environments</title></head><body><h1>Environments</h1>"
            "<p>Every OS image this drive carries, against the five guest applications. <b>native</b>: the application bundle supports "
            "the platform; <b>helper</b>: needs an adapter that is not built yet; <b>none</b>: nothing of ours runs there; <b>not planned</b>: your list does not ask for it on that OS. "
            "No environment has the applications set up yet; create an environment from <a href='/vms'>Virtual machines</a>.</p>"
            f"<table><thead><tr><th>Image</th><th>OS</th>{head}<th>Environment</th></tr></thead><tbody>{body}</tbody></table>"
            "</body></html>").encode()
