"""The launcher's model (DR259): tiles for VMs and containers, what a right-click offers, and Proxmox console addresses for the run modes.

Pure functions; no I/O. A tile is named by its constant identifier (`naming`), never by its name. Nothing here claims an application is
installed in a guest: nothing reports that yet, so `installed` is None and the page says "not reported".

Run modes are Proxmox's own console pages opened in a browser window: Console is xterm.js on the VM's serial port, Window and Fullscreen
are noVNC. They are addresses, not an embedded frame (DR259: cross-origin embedding is not relied on).
"""
from __future__ import annotations

import re
import zlib

import environments

MODES = (("console", "Console"), ("window", "Window"), ("fullscreen", "Fullscreen"))
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$")
_NODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
RECIPE_RELEASE = {"ubuntu-desktop": ("ubuntu", "24.04"), "ubuntu-server": ("ubuntu", "24.04")}      # ubuntu_environment pins noble
MIN_MEMORY_MB, MAX_CPUS = 256, 128


def _int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what} must be a whole number")
    return value


def os_of(vm: dict) -> tuple:
    recipe = vm.get("recipe")
    if recipe in RECIPE_RELEASE:
        return RECIPE_RELEASE[recipe]
    for source in (vm.get("name"), vm.get("iso"), vm.get("base")):
        if source:
            family, release = environments.classify(str(source))
            if family != "unknown":
                return family, release
    return "unknown", ""


def _support(family: str, release: str) -> str:
    if (family, release) in environments.NATIVE:
        return "native"
    return "none" if family in ("rescue", "unknown") else "helper"


def _state(vm: dict) -> str:
    """running, stopped, unknown (Proxmox status could not be read) or preparing (a container that is not ready yet)."""
    if vm.get("phase") not in (None, "ready"):
        return "preparing"
    if vm.get("running") is None:
        return "unknown"
    return "running" if vm["running"] else "stopped"


_NOT_OPENABLE = {"stopped": "Start it first", "unknown": "Proxmox status unavailable", "preparing": "Still being prepared"}


def _modes(kind: str, state: str, serial) -> list:
    out = []
    for mode, label in MODES:
        if state != "running":
            out.append({"id": mode, "label": label, "enabled": False, "hint": _NOT_OPENABLE[state]})
        elif kind == "ct" and mode != "console":
            out.append({"id": mode, "label": label, "enabled": False, "hint": "A container has no graphical console"})
        elif mode == "console" and kind == "vm" and serial is False:
            out.append({"id": mode, "label": label, "enabled": False, "hint": "This VM has no serial port; use Window"})
        else:
            hint = "Needs a serial port on the VM" if (mode == "console" and kind == "vm" and serial is None) else ""
            out.append({"id": mode, "label": label, "enabled": True, "hint": hint})
    return out


def build_tile(vm: dict, *, os_id: str, node: str, kind: str = "vm") -> dict:
    if kind == "vm":
        family, release = os_of(vm)
    else:
        family, release = ("linux", "")
        if vm.get("template"):
            found, rel = environments.classify(str(vm["template"]))
            if found != "unknown":
                family, release = found, rel
    state = _state(vm)
    support = _support(family, release)
    return {
        "id": os_id, "name": vm["name"], "vmid": vm.get("vmid"), "kind": kind, "node": node,
        "state": state, "os": {"family": family, "release": release},
        "icon": {"letter": (family[:1] or "?").upper(), "hue": zlib.crc32(family.encode()) % 360},
        "apps": [{"key": a, "support": support, "installed": None} for a in environments.APPS] if kind == "vm" else [],
        "modes": _modes(kind, state, vm.get("serial")),
        "memory_mb": vm.get("memory_mb"), "cpus": vm.get("cpus"), "base": vm.get("base"), "iso": vm.get("iso"),
        "recipe": vm.get("recipe"), "persistence_disk": vm.get("persistence_disk"), "persistence_gb": vm.get("persistence_gb"),
        "template": vm.get("template"), "os_storage": vm.get("os_storage"), "data_path": vm.get("data_path"),
    }


def available_to_create(listing, isos, vms, host_mb=None, bases=()) -> list:
    """The operating systems the supported-OS list asks for that have no VM yet, as launcher entries (DR262): name, family, whether the image is carried, and the
    applications the list plans for it. Built ones are tiles already; Kasm is the workspaces component, not a guest OS."""
    import os_profiles
    rows = environments.listed_catalogue(listing, isos, vms, bases)
    by_id = {e["id"]: e for e in listing}
    out = []
    for r in rows:
        if r["state"] != "not built":
            continue
        entry = by_id[r["id"]]
        item = {"id": r["id"], "name": r["name"], "os": {"family": r["os"], "release": r["release"]}, "iso": r["iso"] if r["image"] != "none listed" else "",
                "image": r["image"], "apps": [{"key": a, "support": lvl} for a, lvl in r["apps"].items() if a in entry["apps"]]}
        item.update(os_profiles.plan_for(entry, image_carried=r["image"] == "carried", host_mb=host_mb, carried_as=r.get("carried_as"), base_carried=r["id"] in bases))
        out.append(item)
    return out


def console_path(kind: str, vmid, name: str, node: str, mode: str) -> str:
    if kind not in ("vm", "ct"):
        raise ValueError("kind must be vm or ct")
    vmid = _int(vmid, "the Proxmox ID")
    if not 100 <= vmid <= 999_999_999:
        raise ValueError("the Proxmox ID is out of range")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("the name has characters a console address cannot carry")
    if not isinstance(node, str) or not _NODE.fullmatch(node):
        raise ValueError("the node name is not valid")
    if mode not in dict(MODES):
        raise ValueError("unknown run mode")
    if kind == "ct":
        if mode != "console":
            raise ValueError("a container has only a console")
        return f"/?console=lxc&xtermjs=1&vmid={vmid}&vmname={name}&node={node}&cmd="
    if mode == "console":
        return f"/?console=kvm&xtermjs=1&vmid={vmid}&vmname={name}&node={node}&cmd="
    return f"/?console=kvm&novnc=1&vmid={vmid}&vmname={name}&node={node}&resize=off&cmd="


def menu_for(tile: dict) -> list:
    state = tile["state"]
    running = state == "running"
    items = [{"id": f"open_{m['id']}", "label": f"Open: {m['label']}", "enabled": m["enabled"], "hint": m["hint"]} for m in tile["modes"]]
    if running:
        items.append({"id": "shutdown", "label": "Shut down", "enabled": True, "hint": ""})
        if tile["kind"] == "vm":                    # the container page has no forced stop, so none is offered
            items.append({"id": "force_stop", "label": "Force stop", "enabled": True, "hint": "Recent writes can be lost"})
    elif state == "stopped":
        items.append({"id": "start", "label": "Start", "enabled": True, "hint": ""})
    items.append({"id": "details", "label": "Details", "enabled": True, "hint": ""})
    items.append({"id": "vm_settings", "label": "VM settings", "enabled": tile["kind"] == "vm" and state == "stopped",
                  "hint": "Shut the VM down to change its memory or CPUs" if tile["kind"] == "vm" and running else ""})
    items.append({"id": "os_settings", "label": "OS settings", "enabled": True, "hint": ""})
    items.append({"id": "applications", "label": "Applications", "enabled": tile["kind"] == "vm",
                  "hint": "" if tile["kind"] == "vm" else "Containers have no application set yet"})
    return items


def details(tile: dict) -> list:
    rows = [("Name", tile["name"]), ("Identifier", tile["id"]), ("Proxmox ID", str(tile["vmid"])), ("State", tile["state"]),
            ("Operating system", f"{tile['os']['family']} {tile['os']['release']}".strip())]
    if tile["kind"] == "vm":
        rows += [("Memory", f"{tile['memory_mb']} MB"), ("CPUs", str(tile["cpus"]))]
        rows.append(("Disk", f"overlay on {tile['base']}" if tile.get("base") else "standalone disk"))
        if tile.get("persistence_disk"):
            rows.append(("Retained user disk", f"{tile['persistence_gb']} GB ({tile['persistence_disk']})"))
        if tile.get("iso"):
            rows.append(("Installer image", f"{tile['iso']} (attached)"))
    else:
        rows += [("Template", str(tile.get("template") or "unknown")), ("Storage", str(tile.get("os_storage") or "unknown")),
                 ("Data folder", str(tile.get("data_path") or "unknown"))]
    return rows


def validate_vm_settings(memory_mb, cpus) -> dict:
    memory_mb, cpus = _int(memory_mb, "memory"), _int(cpus, "CPUs")
    if memory_mb < MIN_MEMORY_MB:
        raise ValueError(f"memory must be at least {MIN_MEMORY_MB} MB")
    if not 1 <= cpus <= MAX_CPUS:
        raise ValueError(f"CPUs must be between 1 and {MAX_CPUS}")
    return {"memory_mb": memory_mb, "cpus": cpus}
