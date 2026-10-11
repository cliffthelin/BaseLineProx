"""The drive's cache learns what it had to fetch.

The self-contained installer carries a verified cache (offline_cache.py, MANIFEST.json, never rewritten). When a build or
the running system still has to fetch something online, that file is added to the same cache and recorded in
LEARNED.json (path -> sha256, plus where it came from and when), so the next rebuild finds it on the drive and depends on
outside resources less. `offline_cache.verify_carried` checks the base manifest together with these additions: a learned
file never trips the integrity check, and an unrecorded or altered file still does.

Nothing here downloads. It only keeps what was already downloaded, after checking it is a real package for this machine
(or an application whose archive matches its recipe's pinned checksum).
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import offline_cache

LEARNED = "LEARNED.json"
ARCHITECTURES = ("amd64", "all")


def _load(cache_root: Path) -> dict:
    try:
        record = json.loads((cache_root / LEARNED).read_text())
        if isinstance(record, dict):
            return record
    except (OSError, ValueError):
        pass
    return {"files": {}, "removed": [], "log": []}


def _save(cache_root: Path, record: dict) -> None:
    temporary = cache_root / (LEARNED + ".tmp")
    temporary.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    os.replace(temporary, cache_root / LEARNED)


def _control(deb: Path) -> dict | None:
    proc = subprocess.run(["dpkg-deb", "-f", str(deb), "Package", "Version", "Architecture"], capture_output=True,
                          text=True)
    if proc.returncode:
        return None
    fields = dict(line.split(": ", 1) for line in proc.stdout.splitlines() if ": " in line)
    return fields if {"Package", "Version", "Architecture"} <= set(fields) else None


def stanza(deb: Path) -> str:
    """One entry of a flat repository's Packages index (what dpkg-scanpackages writes for `.`)."""
    control = subprocess.run(["dpkg-deb", "-f", str(deb)], capture_output=True, text=True, check=True).stdout.strip()
    return (f"{control}\nFilename: ./{deb.name}\nSize: {deb.stat().st_size}\n"
            f"SHA256: {offline_cache.sha256(deb)}\n\n")


def _write_index(apt: Path, text: str) -> None:
    for name, data in (("Packages", text.encode()), ("Packages.gz", gzip.compress(text.encode()))):
        temporary = apt / (name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, apt / name)


def harvest(archives: Path, cache_root: Path, *, source: str) -> dict:
    """Keep every real, new package from `archives` (apt's download cache) in the carried repository."""
    archives, cache_root = Path(archives), Path(cache_root)
    apt = cache_root / "apt"
    record = _load(cache_root)
    report = {"learned": [], "skipped": []}
    index = (apt / "Packages").read_text() if (apt / "Packages").is_file() else ""
    for deb in sorted(archives.glob("*.deb")):
        if (apt / deb.name).exists():
            continue
        fields = _control(deb)
        if fields is None:
            report["skipped"].append({"file": deb.name, "reason": "not a readable Debian package"})
            continue
        if fields["Architecture"] not in ARCHITECTURES:
            report["skipped"].append({"file": deb.name, "reason": f"architecture {fields['Architecture']}"})
            continue
        partial = apt / (deb.name + ".partial")
        try:
            shutil.copyfile(deb, partial)
            digest = offline_cache.sha256(partial)
            if digest != offline_cache.sha256(deb):
                raise RuntimeError(f"{deb.name} did not copy intact")
            os.replace(partial, apt / deb.name)
        finally:
            partial.unlink(missing_ok=True)
        index += stanza(apt / deb.name)
        record["files"][f"apt/{deb.name}"] = digest
        record["log"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": f"apt/{deb.name}",
                              "package": fields["Package"], "version": fields["Version"], "source": source})
        report["learned"].append({"file": deb.name, "package": fields["Package"], "version": fields["Version"]})
    if report["learned"]:
        _write_index(apt, index)
        for name in ("Packages", "Packages.gz"):
            record["files"][f"apt/{name}"] = offline_cache.sha256(apt / name)
        _save(cache_root, record)
    return report


def learn_app(cache_root: Path, app: str, prepared: Path, *, source: str) -> dict:
    """Keep an application prepared online (`baseline-apps prepare`: archive + recipe) as the carried one."""
    import application_bundle
    cache_root, prepared = Path(cache_root), Path(prepared)
    if app not in application_bundle.APPS:
        raise RuntimeError(f"{app!r} is not one of the carried applications")
    archives = [p for p in (prepared / "source.deb", prepared / "source.tar.gz") if p.is_file()]
    if not (prepared / "recipe.json").is_file() or len(archives) != 1:
        raise RuntimeError(f"{prepared} lacks a recipe and exactly one archive")
    recipe = json.loads((prepared / "recipe.json").read_text())
    if offline_cache.sha256(archives[0]) != recipe["source"]["sha256"]:
        raise RuntimeError(f"{app}: the archive does not match its recipe's pinned checksum; not kept")
    target = cache_root / offline_cache.APP_BUNDLE / app
    record = _load(cache_root)
    staging = target.with_name(app + ".incoming")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copy2(archives[0], staging / archives[0].name)
    shutil.copy2(prepared / "recipe.json", staging / "recipe.json")
    previous = sorted(p.relative_to(cache_root).as_posix() for p in target.rglob("*") if p.is_file()) \
        if target.exists() else []
    if target.exists():
        shutil.rmtree(target)
    os.replace(staging, target)
    now = sorted(p.relative_to(cache_root).as_posix() for p in target.rglob("*") if p.is_file())
    for path in previous:
        if path not in now:
            record["removed"] = sorted(set(record["removed"]) | {path})
            record["files"].pop(path, None)
    for path in now:
        record["files"][path] = offline_cache.sha256(cache_root / path)
        if path in record["removed"]:
            record["removed"].remove(path)
    record["log"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": f"apps/{app}", "package": app,
                          "version": recipe["source"]["version"], "source": source})
    _save(cache_root, record)
    return {"app": app, "version": recipe["source"]["version"]}
