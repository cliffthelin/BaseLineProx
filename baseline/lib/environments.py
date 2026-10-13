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
    for needle, family in (("cachyos", "arch"), ("omarchy", "arch"), ("nixos", "nixos"), ("rescue", "rescue")):
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


def render(rows) -> bytes:
    head = "".join(f"<th>{html.escape(a)}</th>" for a in APPS)
    body = "".join(
        f"<tr><td>{html.escape(r['iso'])}</td><td>{html.escape(r['os'])} {html.escape(r['release'])}</td>"
        + "".join(f"<td>{html.escape(r['apps'][a])}</td>" for a in APPS)
        + f"<td>{html.escape(r['state'])}{(' (' + html.escape(r['vm']) + ')') if r['vm'] else ''}</td></tr>" for r in rows)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Environments</title></head><body><h1>Environments</h1>"
            "<p>Every OS image this drive carries, against the five guest applications. <b>native</b>: the application bundle supports "
            "the platform; <b>helper</b>: needs an adapter that is not built yet; <b>none</b>: nothing of ours runs there. "
            "No environment has the applications set up yet; create an environment from <a href='/vms'>Virtual machines</a>.</p>"
            f"<table><thead><tr><th>Image</th><th>OS</th>{head}<th>Environment</th></tr></thead><tbody>{body}</tbody></table>"
            "</body></html>").encode()
