"""The Kasm recipe: what the base is built from, and which of it is used (DR260, operator 2026-10-17).

A recipe is a template with the decisions written down, so a build is never "whatever happened to be installed" and a later build can adapt:
  components  Kasm's own building blocks, named by the installer role Kasm gives them (`db`, `app`, `agent`, `proxy`, `guac`), each with the images it needs and a state:
                required  Kasm does not run without it
                used      something we offer needs it
                unused    nothing we offer uses it, yet it is carried because the all-in-one install starts it; the note says what dropping it would take
  plugins     the Docker plugins the installer fetches (log driver, network sidecar), packed into the base
  workspaces  what a person can open (the entries `kasm_build` seeds)
  settings    server settings to set at install (name to value; checked against the release's own catalogue by kasm_settings; never secrets)
  registry    whether Baseline acts as a Kasm workspace registry, and the address Kasm is told (kasm_registry builds the file)
A recipe is checked against the Kasm release's own compose files: every image the release starts must belong to exactly one component, and a component naming an image the
release does not start is refused. So a new Kasm version that adds a component cannot slip into a build unnoticed: it has to be given a state first.
The recipe is recorded in the base's manifest, so the host knows what its base holds.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

FORMAT = "baseline.kasm-recipe/v1"
STATES = ("required", "used", "unused")
REPO_COPY = Path(__file__).resolve().parents[2] / "config" / "local" / "kasm-recipe.json"
_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ROLES = ("db", "app", "agent", "proxy", "guac")          # install.sh's own --role names (init_remote_db is a database helper, not a component)


class RecipeError(ValueError):
    pass


def default(workspaces) -> dict:
    """The recipe this product builds when nobody has written another: all-in-one Kasm, no server connections in use."""
    return {
        "format": FORMAT, "kasm_version": "1.19.0",
        "components": [
            {"id": "database", "role": "db", "images": ["postgres"], "state": "required", "note": "Kasm's own Postgres: users, settings, workspaces and sessions."},
            {"id": "application", "role": "app", "images": ["api", "manager"], "state": "required", "note": "The web API and the manager that schedules sessions."},
            {"id": "agent", "role": "agent", "images": ["agent"], "state": "required", "note": "Starts the workspace containers on this machine."},
            {"id": "proxy", "role": "proxy", "images": ["proxy"], "state": "required", "note": "The one HTTPS entrance."},
            {"id": "server-connections", "role": "guac", "images": ["kasm-guac", "rdp-gateway", "rdp-https-gateway"], "state": "unused",
             "note": "RDP, VNC and SSH to other machines. No workspace here uses it. Kasm's all-in-one install starts it, so it is carried; dropping it means "
                     "installing the roles separately (db, app, agent, proxy), which is not built."},
        ],
        "plugins": [
            {"id": "logging", "image": "kasmweb/kasm-logging-plugin", "tag": "1.1", "state": "required", "note": "Kasm's log driver."},
            {"id": "network", "image": "kasmweb/kasm-network-plugin", "tag": "1.5", "state": "unused",
             "note": "The network sidecar (VPN and egress features). Nothing offered here uses it; the installer installs it regardless."},
        ],
        "workspaces": [dict(w) for w in workspaces],
        "settings": {},
        "registry": {"enabled": False, "name": "Baseline", "description": "Workspaces carried by this Baseline host.", "list_url": ""},
    }


def compose_images(text: str) -> set:
    """The image names (no registry, no tag) the release's compose file starts."""
    document = yaml.safe_load(text) or {}
    return {str(service.get("image", "")).split("/")[-1].split(":")[0] for service in (document.get("services") or {}).values() if service.get("image")}


def validate(recipe, release_images=None) -> dict:
    if not isinstance(recipe, dict) or recipe.get("format") != FORMAT:
        raise RecipeError(f"a recipe has format {FORMAT}")
    components = recipe.get("components")
    if not isinstance(components, list) or not components:
        raise RecipeError("a recipe lists its components")
    seen_ids, owner = set(), {}
    for item in components:
        if not isinstance(item, dict) or not _ID.fullmatch(str(item.get("id", ""))):
            raise RecipeError("every component needs an id (lowercase letters, digits and dashes)")
        ident = item["id"]
        if ident in seen_ids:
            raise RecipeError(f"component {ident} is listed twice")
        seen_ids.add(ident)
        if item.get("role") not in ROLES:
            raise RecipeError(f"{ident}: role must be one of {', '.join(ROLES)}")
        if item.get("state") not in STATES:
            raise RecipeError(f"{ident}: state must be one of {', '.join(STATES)}")
        images = item.get("images")
        if not isinstance(images, list) or not images or not all(isinstance(i, str) and _IMAGE.fullmatch(i) for i in images):
            raise RecipeError(f"{ident}: images must be a non-empty list of image names")
        for image in images:
            if image in owner:
                raise RecipeError(f"image {image} belongs to both {owner[image]} and {ident}")
            owner[image] = ident
        if not isinstance(item.get("note", ""), str) or len(item.get("note", "")) > 400:
            raise RecipeError(f"{ident}: the note is text up to 400 characters")
    if any(item["state"] == "unused" and item["role"] in ("db", "app", "agent") for item in components):
        raise RecipeError("the database, application and agent roles cannot be unused: Kasm does not run without them")
    for plugin in recipe.get("plugins", []):
        if not isinstance(plugin, dict) or not _ID.fullmatch(str(plugin.get("id", ""))) or plugin.get("state") not in STATES \
                or not re.fullmatch(r"^[a-z0-9/-]+$", str(plugin.get("image", ""))) or not re.fullmatch(r"^[0-9][0-9.]*$", str(plugin.get("tag", ""))):
            raise RecipeError("a plugin needs an id, an image, a numeric tag and a state")
    if not isinstance(recipe.get("workspaces"), list) or not recipe["workspaces"]:
        raise RecipeError("a recipe lists its workspaces")
    settings = recipe.get("settings", {})
    if not isinstance(settings, dict) or not all(isinstance(k, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,60}", k) for k in settings):
        raise RecipeError("settings are a mapping from a setting name to its value")
    registry = recipe.get("registry", {})
    if not isinstance(registry, dict) or not isinstance(registry.get("enabled", False), bool):
        raise RecipeError("registry says whether it is enabled")
    if registry.get("enabled"):
        if not re.fullmatch(r"https?://[A-Za-z0-9.:\[\]-]+(/[A-Za-z0-9._~/-]*)?/", str(registry.get("list_url", ""))):
            raise RecipeError("an enabled registry needs a list_url: an http(s) address ending in a slash")
        if not str(registry.get("name", "")).strip():
            raise RecipeError("a registry needs a name")
    if release_images is not None:
        missing = sorted(set(release_images) - set(owner))
        extra = sorted(set(owner) - set(release_images))
        if missing:
            raise RecipeError("this Kasm release starts images the recipe gives no state: " + ", ".join(missing))
        if extra:
            raise RecipeError("the recipe names images this Kasm release does not start: " + ", ".join(extra))
    return recipe


def service_images(recipe: dict) -> list:
    """Every image of every component, in the recipe's order: all of them are carried (an unused component is still started by the all-in-one stack)."""
    return [image for item in recipe["components"] for image in item["images"]]


def locate(environ=None, repo=REPO_COPY):
    environ = os.environ if environ is None else environ
    named = environ.get("BASELINE_KASM_RECIPE")
    for path in ([Path(named)] if named else []) + [Path(repo)]:
        if path.is_file():
            return path
    return None


def load(workspaces, path=None) -> dict:
    """The recipe in use: the file named, or the working copy (`config/local/kasm-recipe.json`, git-ignored), or the default. Always validated."""
    path = Path(path) if path is not None else locate()
    if path is None:
        return validate(default(workspaces))
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise RecipeError(f"{path} cannot be read as a recipe: {exc}") from None
    return validate(data)


def summary(recipe: dict) -> dict:
    """What a host needs to show: which components are in the base and whether anything offered uses them."""
    return {"components": [{k: c[k] for k in ("id", "role", "state", "images", "note") if k in c} for c in recipe["components"]],
            "plugins": [{k: p[k] for k in ("id", "state", "note") if k in p} for p in recipe.get("plugins", [])],
            "settings": dict(recipe.get("settings", {})), "registry": {k: v for k, v in recipe.get("registry", {}).items() if k in ("enabled", "name", "list_url")}}
