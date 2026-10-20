"""Baseline as a Kasm third-party workspace registry (DR260; operator 2026-10-17).

A registry is a static site whose `<root>/<schema>/list.json` lists workspaces; an administrator adds its address under Workspaces > Workspace Registry (or an install is told it with the
installer's documented `--default-registry-url`). This builds that file in the published schema 1.1 (shape read from Kasm's own public registry and its documentation): `name`,
`workspacecount`, `icon`, `description`, `list_url`, `contact_url`, `modified`, `workspaces`, `channels`, `default_channel`; each workspace has `friendly_name`, `description`,
`image_src`, `architecture`, `categories`, `docker_registry`, `run_config`, `exec_config`, sizing, and `compatibility` entries naming the Kasm version and the image.

Third-party registries are not signed (Kasm's own carries a `signature`); whether a given Kasm accepts an unsigned one is checked on a live Kasm, not assumed. The workspace definitions
(run and exec configuration) are the release's own, copied from its seed, so what a person installs from here behaves like what ships.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

SCHEMA = "1.1"
ICON_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}\.(png|svg)$")
_FIELDS = ("description", "docker_registry", "run_config", "exec_config", "categories", "cores", "gpu_count", "cpu_allocation_method", "notes")


class RegistryError(ValueError):
    pass


def _image_entry(images_seed: dict, image: str) -> dict:
    for entry in images_seed.get("images", []):
        if str(entry.get("name", "")).split("/")[-1].split(":")[0] == image:
            return entry
    raise RegistryError(f"the release's seed has no workspace image named {image}")


def workspace(entry: dict, recipe_workspace: dict, *, kasm_version: str, image_tag: str) -> dict:
    icon = str(entry.get("image_src") or "").rsplit("/", 1)[-1]                        # the file Kasm itself calls it (ubuntu.png for the Ubuntu desktop image)
    out = {"friendly_name": recipe_workspace["friendly_name"], "image_src": icon if ICON_NAME.fullmatch(icon) else f"{recipe_workspace['image']}.png", "architecture": ["amd64"]}
    for field in _FIELDS:
        if entry.get(field) is not None:
            out[field] = entry[field]
    if entry.get("memory_bytes"):
        out["memory"] = int(entry["memory_bytes"]) // (1024 * 1024)
    out["compatibility"] = [{"version": re.sub(r"\.\d+$", ".x", kasm_version), "image": f"kasmweb/{recipe_workspace['image']}:{image_tag}",
                             "uncompressed_size_mb": int(entry.get("uncompressed_size_mb") or 0)}]
    out["sha"] = hashlib.sha1(json.dumps(out, sort_keys=True).encode()).hexdigest()
    return out


def build(workspaces, images_seed_text: str, *, name: str, description: str, list_url: str, contact_url: str = "", kasm_version: str = "1.19.0",
          image_tag: str = "1.19.0", now_ms=None) -> dict:
    """The registry document for these recipe workspaces. One entry per DISTINCT image: the same image offered twice (a temporary and a personal browser) is one workspace to install;
    how it keeps profiles is an install-time choice, not part of the registry."""
    if not name.strip() or not list_url.endswith("/") or not list_url.startswith(("https://", "http://")):
        raise RegistryError("a registry needs a name and a list_url that is an http(s) address ending in a slash")
    import yaml            # only the build needs it; the host that serves and fetches icons does not
    seed = yaml.safe_load(images_seed_text) or {}
    seen, entries = set(), []
    for item in workspaces:
        if item["image"] in seen:
            continue
        seen.add(item["image"])
        label = item.get("registry_name") or item["friendly_name"].split(" (")[0]
        entries.append(workspace(_image_entry(seed, item["image"]), dict(item, friendly_name=label), kasm_version=kasm_version, image_tag=image_tag))
    return {"name": name, "workspacecount": len(entries), "icon": "/img/favicon.png", "description": description, "list_url": list_url, "contact_url": contact_url,
            "modified": int(now_ms if now_ms is not None else time.time() * 1000), "workspaces": entries, "channels": [], "default_channel": ""}


def render(document: dict) -> str:
    return json.dumps(document, indent=1, sort_keys=False) + "\n"


def files(document: dict) -> dict:
    """The whole static site, path to text: Kasm first reads `versions.txt` (the schema versions the registry offers; without it a live Kasm reports "does not appear to have a
    valid schema list", found 2026-10-17), then `<schema>/list.json`."""
    return {"versions.txt": SCHEMA + "\n", f"{SCHEMA}/list.json": render(document)}


def icon_names(document: dict) -> list:
    """The icon files a registry's workspaces name, in order, each once. They are served under `<root>/1.1/icons/` (the layout of Kasm's own registry)."""
    seen = []
    for entry in document.get("workspaces", []):
        name = entry.get("image_src", "")
        if ICON_NAME.fullmatch(str(name)) and name not in seen:
            seen.append(name)
    return seen
