"""Workspaces from other Kasm registries, offered through Baseline's own (DR264; operator 2026-10-17: add LinuxServer.io).

A Kasm registry is a static site: `versions.txt` (the schema versions it offers) and `<schema>/list.json`. Kasm documents adding a third-party registry as a UI step only (Workspaces >
Workspace Registry > Add), and Baseline points a fresh install at ONE registry (`--default-registry-url`). So Baseline reads the other registry's public list at build time, keeps what the
recipe names, and offers those workspaces beside its own. One address for Kasm to trust, what is offered is a chosen and reviewed subset, and a build with no internet can use the copy kept
from the last one.

Nothing from outside is taken on trust:
- a workspace is only included when the recipe names it (by its friendly name), so a registry that adds a hundred more adds nothing here;
- a registry entry's `run_config` and `exec_config` can run arbitrary commands (Kasm's own warning), so each included workspace is PINNED to a hash of exactly what is reviewable (its run
  configuration, exec configuration, image and image registry). If the upstream definition changes, it is left out and the report shows the new hash and definition until a person reads it
  and updates the recipe;
- run-configuration properties beyond the plain ones (`entrypoint`, `user` 1000, `environment`) are findings, and a finding stays a reason to exclude until the recipe accepts that exact one
  (`run_config.security_opt`), the same properties Kasm itself flags with an orange border;
- an entry with no compatibility entry for this Kasm's version is left out, unless the recipe says to assume the newest entry it has holds (`assume_compatible_from`), in which case it is
  included and marked UNVERIFIED in the report.
Images are not carried: a workspace from here is pulled from its own registry when first started, so it needs internet unless it is mirrored (DR264).
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA = "1.1"
MAX_LIST = 2 * 1024 * 1024
MAX_ICON = 512 * 1024
ID = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
VERSION = re.compile(r"^\d+\.\d+\.x$")
PLAIN_RUN_KEYS = ("entrypoint", "user", "environment")
_ICON_EXT = re.compile(r"\.(png|svg)$")
TIMEOUT_S = 30


class SourceError(ValueError):
    pass


def _json(raw: bytes, what: str):
    try:
        return json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError):
        raise SourceError(f"{what} is not valid JSON") from None


def fetch_bytes(url: str, limit: int, *, allow_http=False, opener=urllib.request.urlopen) -> bytes:
    scheme = urllib.parse.urlparse(url).scheme
    if scheme != "https" and not (allow_http and scheme == "http"):
        raise SourceError(f"{url} is not an https address")
    try:
        with opener(urllib.request.Request(url, headers={"User-Agent": "baseline-kasm-sources"}), timeout=TIMEOUT_S) as response:
            data = response.read(limit + 1)
    except OSError as exc:
        raise SourceError(f"could not fetch {url}: {exc}") from None
    if len(data) > limit:
        raise SourceError(f"{url} is larger than {limit} bytes")
    return data


def fetch_list(base: str, **kw) -> dict:
    """The other registry's list in schema 1.1, after checking it offers that schema and has the shape Baseline reads."""
    versions = fetch_bytes(base + "versions.txt", 4096, **kw).decode(errors="replace").split()
    if SCHEMA not in versions:
        raise SourceError(f"{base} does not offer schema {SCHEMA} (it offers: {', '.join(versions) or 'nothing'})")
    document = _json(fetch_bytes(f"{base}{SCHEMA}/list.json", MAX_LIST, **kw), "the registry list")
    if not isinstance(document, dict) or not isinstance(document.get("workspaces"), list):
        raise SourceError("the registry list has no workspaces")
    return document


def fetch_icon(base: str, name: str, **kw) -> bytes:
    if not _ICON_EXT.search(name) or "/" in name or name.startswith("."):
        raise SourceError(f"{name} is not a plain icon file name")
    data = fetch_bytes(f"{base}{SCHEMA}/icons/{urllib.parse.quote(name)}", MAX_ICON, **kw)
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") if name.endswith(".png") else data.lstrip().startswith((b"<svg", b"<?xml"))):
        raise SourceError(f"{name} is not the kind of image its name says")
    return data


# ---- review ------------------------------------------------------------------------------------------------------------------------------
def _entry_for(workspace: dict, version: str):
    return next((c for c in workspace.get("compatibility") or [] if isinstance(c, dict) and c.get("version") == version), None)


def findings(workspace: dict) -> list:
    """Run-configuration properties a person should have read and accepted: anything beyond the plain ones, a user that is not 1000, privileged mode. Named exactly as the recipe accepts them."""
    run = workspace.get("run_config") if isinstance(workspace.get("run_config"), dict) else {}
    out = [f"run_config.{key}" for key in sorted(run) if key not in PLAIN_RUN_KEYS]
    if str(run.get("user", "1000")) not in ("1000", "kasm-user"):
        out.append("run_config.user")
    return out


def review_hash(workspace: dict, image: str) -> str:
    """A hash of what is reviewable: the definition that can run commands, the image it runs, and the registry it is pulled from."""
    basis = {"run_config": workspace.get("run_config") or {}, "exec_config": workspace.get("exec_config") or {}, "image": image, "docker_registry": workspace.get("docker_registry") or ""}
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]


def definition(workspace: dict, image: str) -> dict:
    return {"image": image, "docker_registry": workspace.get("docker_registry") or "", "run_config": workspace.get("run_config") or {}, "exec_config": workspace.get("exec_config") or {}}


# ---- import --------------------------------------------------------------------------------------------------------------------------------
def _icon_name(source_id: str, workspace: dict) -> str:
    extension = "svg" if str(workspace.get("image_src", "")).endswith(".svg") else "png"
    slug = re.sub(r"[^a-z0-9]+", "-", str(workspace.get("friendly_name", "")).lower()).strip("-") or "workspace"
    return f"{source_id}-{slug}"[:41].rstrip("-") + f".{extension}"                    # always a name Baseline's registry will serve (kasm_registry.ICON_NAME)


def import_workspaces(document: dict, source: dict, kasm_version: str, label: str) -> tuple:
    """(entries for Baseline's list, report) for the workspaces `source` names. `kasm_version` is like 1.19.x. Every named workspace appears in the report, included or not, with why."""
    wanted_all = {w.get("friendly_name"): w for w in document.get("workspaces", []) if isinstance(w, dict)}
    entries, report = [], []
    for item in source.get("include", []):
        name = item["name"]
        row = {"source": source["id"], "name": name, "status": "excluded", "reason": "", "findings": [], "unverified": False, "requires_network": True}
        report.append(row)
        upstream = wanted_all.get(name)
        if upstream is None:
            row["reason"] = "the registry does not offer a workspace with that name"
            continue
        compatibility = _entry_for(upstream, kasm_version)
        if compatibility is None and source.get("assume_compatible_from"):
            compatibility = _entry_for(upstream, source["assume_compatible_from"])
            row["unverified"] = compatibility is not None
        if compatibility is None:
            offered = ", ".join(c.get("version", "?") for c in upstream.get("compatibility") or []) or "no version"
            row["reason"] = f"it has no entry for Kasm {kasm_version} (it lists: {offered}); the recipe can set assume_compatible_from to use an earlier entry"
            continue
        image = str(compatibility.get("image") or "")
        if not image:
            row["reason"] = "its compatibility entry names no image"
            continue
        found, accepted = findings(upstream), set(item.get("accept") or [])
        digest = review_hash(upstream, image)
        row.update(findings=found, image=image, review_hash=digest, definition=definition(upstream, image))
        unaccepted = [f for f in found if f not in accepted]
        if item.get("reviewed") != digest:
            row["reason"] = ("it has not been reviewed: read its definition below, then set reviewed to " if not item.get("reviewed") else "its definition changed since it was reviewed: read it again, then set reviewed to ") + digest
            continue
        if unaccepted:
            row["reason"] = "it needs a person to accept: " + ", ".join(unaccepted)
            continue
        entry = {"friendly_name": f"{name} ({label})", "image_src": _icon_name(source["id"], upstream), "architecture": list(upstream.get("architecture") or ["amd64"])}
        for field in ("description", "docker_registry", "run_config", "exec_config", "categories", "cores", "memory", "gpu_count", "cpu_allocation_method", "notes"):
            if upstream.get(field) is not None:
                entry[field] = upstream[field]
        entry["compatibility"] = [{"version": kasm_version, "image": image, "uncompressed_size_mb": int(compatibility.get("uncompressed_size_mb") or 0)}]
        entry["sha"] = hashlib.sha1(json.dumps(entry, sort_keys=True).encode()).hexdigest()
        row.update(status="included", reason="", icon=entry["image_src"], upstream_icon=str(upstream.get("image_src") or ""))
        entries.append(entry)
    return entries, report


# ---- keeping a copy so a build with no internet still works ---------------------------------------------------------------------------------
def load(source: dict, cache_dir, **kw) -> tuple:
    """(list document, {icon file name: bytes}, note) for a source: fresh from the network, or the copy kept by the last build when the network fails. Raises SourceError with neither."""
    cache = Path(cache_dir) / source["id"]
    base = source["url"]
    try:
        document = fetch_list(base, **kw)
        icons = {}
        for item in source.get("include", []):
            upstream = next((w for w in document["workspaces"] if isinstance(w, dict) and w.get("friendly_name") == item["name"]), None)
            if upstream and upstream.get("image_src"):
                try:
                    icons[str(upstream["image_src"])] = fetch_icon(base, str(upstream["image_src"]), **kw)
                except SourceError:
                    continue                                        # a missing icon is never fatal
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "list.json").write_text(json.dumps(document))
        (cache / "icons").mkdir(exist_ok=True)
        for name, data in icons.items():
            (cache / "icons" / name).write_bytes(data)
        return document, icons, "fetched now"
    except SourceError as failure:
        try:
            document = json.loads((cache / "list.json").read_text())
            icons = {p.name: p.read_bytes() for p in (cache / "icons").glob("*") if p.is_file() and not p.is_symlink()}
        except (OSError, ValueError):
            raise SourceError(f"{failure}; and there is no copy from an earlier build to use") from None
        return document, icons, f"used the copy from an earlier build because: {failure}"


def merge_into(document: dict, sources: list, kasm_version: str, registry_out, cache_dir, **kw) -> list:
    """Add the included workspaces of every source to Baseline's registry `document` (in place), put their icons under `<registry_out>/1.1/icons/`, and write `<registry_out>/sources.json`: the
    report of every workspace asked for, included or not, with the reason, the review hash and the definition to read. A source that cannot be fetched (and has no copy) adds nothing and says
    so; the rest of the build goes on. Returns the report rows."""
    registry_out = Path(registry_out)
    version = re.sub(r"\.\d+$", ".x", kasm_version)
    rows, notes = [], []
    for source in sources:
        label = source.get("name") or source["id"]
        try:
            upstream, icons, note = load(source, cache_dir, **kw)
        except SourceError as exc:
            notes.append({"source": source["id"], "url": source["url"], "error": str(exc)})
            rows += [{"source": source["id"], "name": i["name"], "status": "excluded", "reason": f"the registry could not be read: {exc}", "findings": [], "unverified": False, "requires_network": True}
                     for i in source["include"]]
            continue
        entries, report = import_workspaces(upstream, source, version, label)
        icon_dir = registry_out / SCHEMA / "icons"
        for entry, row in zip(entries, [r for r in report if r["status"] == "included"]):
            data = icons.get(row["upstream_icon"])
            if data:
                icon_dir.mkdir(parents=True, exist_ok=True)
                (icon_dir / entry["image_src"]).write_bytes(data)
        document["workspaces"].extend(entries)
        notes.append({"source": source["id"], "url": source["url"], "name": upstream.get("name", ""), "note": note})
        rows += report
    document["workspacecount"] = len(document["workspaces"])
    registry_out.mkdir(parents=True, exist_ok=True)
    (registry_out / "sources.json").write_text(json.dumps({"sources": notes, "workspaces": rows}, indent=1))
    return rows
