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
    names = provision_packages((Path(repo_root) / "boot/provision.sh").read_text())
    return names + [p for p in firstboot_statemachine.DIAGNOSTIC_PACKAGES if p not in names]


def sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root) -> dict:
    root = Path(root)
    return {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.name != "MANIFEST.json"}


def verify_manifest(root, manifest: dict) -> int:
    actual = build_manifest(root)
    if set(actual) != set(manifest):
        raise RuntimeError(f"carried files differ from the manifest: {sorted(set(actual) ^ set(manifest))[:5]}")
    bad = [name for name, digest in manifest.items() if actual[name] != digest]
    if bad:
        raise RuntimeError(f"carried files fail their checksums: {bad[:5]}")
    return len(manifest)
