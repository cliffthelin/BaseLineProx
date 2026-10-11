"""The offline package cache a self-contained Baseline installer carries (INSTALLER_CACHE content, vanilla).

Built once on a machine with internet (baseline/bin/baseline-build-offline-cache) and verified on the target
before use (baseline/bin/baseline-first-boot-install). Layout:

    apt/        every .deb provision.sh installs, with all dependencies, plus Packages(.gz) - a flat local repository
    npm-cache/  npm's own cache, holding every tarball Claude Code needs
    MANIFEST.json  sha256 of every other file in the tree
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_INSTALL = re.compile(r"^\s*apt-get\s+install\s+(.*)$")


def provision_packages(provision_text: str) -> list:
    """The package names provision.sh installs with apt-get, in order - provision.sh stays the single source."""
    names = []
    for line in provision_text.splitlines():
        match = _INSTALL.match(line.split("#", 1)[0])
        if not match:
            continue
        for word in match.group(1).split():
            if word.startswith("-") or word in names:
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", word):
                raise ValueError(f"unexpected token in provision.sh apt-get line: {word!r}")
            names.append(word)
    if not names:
        raise ValueError("provision.sh installs no apt packages - refusing to build an empty cache")
    return names


def required_packages(repo_root) -> list:
    """Everything an offline install needs from apt: provision.sh's packages, then first-boot authorization's own
    diagnostic tools (firstboot_statemachine.DIAGNOSTIC_PACKAGES) - both read from the code, never copied."""
    import firstboot_statemachine
    import application_bundle
    names = provision_packages((Path(repo_root) / "boot/provision.sh").read_text())
    runtime = application_bundle.runtime_plan({"arch": "amd64", "os": "debian", "release": "13"})["packages"]
    return names + [p for p in firstboot_statemachine.DIAGNOSTIC_PACKAGES + runtime if p not in names]


APP_BUNDLE = "apps"


def verify_app_bundle(root, apps) -> list:
    """Every carried application: `<root>/apps/<app>/recipe.json` plus its archive, checked against the recipe's
    pinned sha256 (the checksum `baseline-apps install` itself re-checks). Names what is missing; never skips."""
    import json
    root = Path(root)
    report, missing = [], []
    for app in apps:
        folder = root / APP_BUNDLE / app
        archives = [p for p in (folder / "source.deb", folder / "source.tar.gz") if p.is_file()]
        if not (folder / "recipe.json").is_file() or len(archives) != 1:
            missing.append(app)
            continue
        recipe = json.loads((folder / "recipe.json").read_text())
        if sha256(archives[0]) != recipe["source"]["sha256"]:
            raise RuntimeError(f"{app}: the carried archive does not match its recipe's pinned checksum")
        report.append({"app": app, "version": recipe["source"]["version"], "bytes": archives[0].stat().st_size})
    if missing:
        raise RuntimeError(f"the carried application bundle lacks: {', '.join(missing)}")
    return report


def sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root) -> dict:
    root = Path(root)
    return {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.name not in ("MANIFEST.json", "LEARNED.json")}


def verify_manifest(root, manifest: dict) -> int:
    actual = build_manifest(root)
    if set(actual) != set(manifest):
        raise RuntimeError(f"carried files differ from the manifest: {sorted(set(actual) ^ set(manifest))[:5]}")
    bad = [name for name, digest in manifest.items() if actual[name] != digest]
    if bad:
        raise RuntimeError(f"carried files fail their checksums: {bad[:5]}")
    return len(manifest)


def verify_carried(root) -> int:
    """The base manifest together with what the drive learned since (cache_learn.py, LEARNED.json): every file must be
    listed in one or the other and match; a learned file may supersede a base one (a regenerated index, a newer
    application) or retire it. An unrecorded or altered file is refused."""
    import json
    root = Path(root)
    expected = dict(json.loads((root / "MANIFEST.json").read_text()))
    learned_path = root / "LEARNED.json"
    if learned_path.is_file():
        learned = json.loads(learned_path.read_text())
        for path in learned.get("removed", []):
            expected.pop(path, None)
        expected.update(learned.get("files", {}))
    return verify_manifest(root, expected)
