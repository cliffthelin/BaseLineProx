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


def _modes(kind: str, running: bool, serial) -> list:
    out = []
    for mode, label in MODES:
        if not running:
            out.append({"id": mode, "label": label, "enabled": False, "hint": "Start it first"})
        elif kind == "ct" and mode != "console":
            out.append({"id": mode, "label": label, "enabled": False, "hint": "A container has no graphical console"})
        elif mode == "console" and kind == "vm" and serial is False:
            out.append({"id": mode, "label": label, "enabled": False, "hint": "This VM has no serial port; use Window"})
        else:
            hint = "Needs a serial port on the VM" if (mode == "console" and kind == "vm" and serial is None) else ""
            out.append({"id": mode, "label": label, "enabled": True, "hint": hint})
    return out


def build_tile(vm: dict, *, os_id: str, node: str, kind: str = "vm") -> dict:
    family, release = os_of(vm) if kind == "vm" else ("linux", "")
    running = bool(vm.get("running"))
    support = _support(family, release)
    return {
        "id": os_id, "name": vm["name"], "vmid": vm.get("vmid"), "kind": kind, "node": node,
        "state": "running" if running else "stopped", "os": {"family": family, "release": release},
        "icon": {"letter": (family[:1] or "?").upper(), "hue": zlib.crc32(family.encode()) % 360},
        "apps": [{"key": a, "support": support, "installed": None} for a in environments.APPS] if kind == "vm" else [],
        "modes": _modes(kind, running, vm.get("serial")),
        "memory_mb": vm.get("memory_mb"), "cpus": vm.get("cpus"), "base": vm.get("base"), "iso": vm.get("iso"),
        "recipe": vm.get("recipe"), "persistence_disk": vm.get("persistence_disk"), "persistence_gb": vm.get("persistence_gb"),
    }


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
    running = tile["state"] == "running"
    items = [{"id": f"open_{m['id']}", "label": f"Open: {m['label']}", "enabled": m["enabled"], "hint": m["hint"]} for m in tile["modes"]]
    if running:
        items += [{"id": "shutdown", "label": "Shut down", "enabled": True, "hint": ""},
                  {"id": "force_stop", "label": "Force stop", "enabled": True, "hint": "Recent writes can be lost"}]
    else:
        items.append({"id": "start", "label": "Start", "enabled": True, "hint": ""})
    items.append({"id": "details", "label": "Details", "enabled": True, "hint": ""})
    items.append({"id": "vm_settings", "label": "VM settings", "enabled": tile["kind"] == "vm" and not running,
                  "hint": "" if not running else "Shut the VM down to change its memory or CPUs"})
    items.append({"id": "os_settings", "label": "OS settings", "enabled": tile["kind"] == "vm", "hint": ""})
    items.append({"id": "applications", "label": "Applications", "enabled": tile["kind"] == "vm", "hint": ""})
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
    return rows


def validate_vm_settings(memory_mb, cpus) -> dict:
    memory_mb, cpus = _int(memory_mb, "memory"), _int(cpus, "CPUs")
    if memory_mb < MIN_MEMORY_MB:
        raise ValueError(f"memory must be at least {MIN_MEMORY_MB} MB")
    if not 1 <= cpus <= MAX_CPUS:
        raise ValueError(f"CPUs must be between 1 and {MAX_CPUS}")
    return {"memory_mb": memory_mb, "cpus": cpus}
