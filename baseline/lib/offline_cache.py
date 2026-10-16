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
    import installer_cache
    names = provision_packages((Path(repo_root) / "boot/provision.sh").read_text())
    runtime = application_bundle.runtime_plan({"arch": "amd64", "os": "debian", "release": "13"})["packages"]
    wanted = list(firstboot_statemachine.DIAGNOSTIC_PACKAGES) + runtime + list(installer_cache.firmware_packages())
    return names + [p for p in dict.fromkeys(wanted) if p not in names]


BUILT_FOR = "BUILT_FOR.json"


def required_fingerprint(repo_root) -> str:
    """Identifies the set of apt packages the current code needs, independent of order and duplicates."""
    names = sorted(set(required_packages(repo_root)))
    return hashlib.sha256("\n".join(names).encode()).hexdigest()


def write_built_for(root, repo_root) -> None:
    """Record, inside the cache (and so in its manifest), the packages it was built to satisfy."""
    import json
    names = sorted(set(required_packages(repo_root)))
    record = {"required_packages": names, "sha256": hashlib.sha256("\n".join(names).encode()).hexdigest()}
    (Path(root) / BUILT_FOR).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")


def cache_is_current(root, repo_root) -> tuple:
    """(True, "") when the cache was built for exactly the packages the code needs now; otherwise (False, why).

    A cache built before provision.sh gained packages would be accepted by every other check (its manifest verifies, its applications
    are there) and the install would then fail offline at `apt-get install`; this is what refuses it up front."""
    import json
    path = Path(root) / BUILT_FOR
    if not path.is_file():
        return False, "it never recorded what it was built for (it predates that record), so it cannot be known to match"
    try:
        built = set(json.loads(path.read_text())["required_packages"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, f"its record of what it was built for is unreadable: {exc}"
    needed = set(required_packages(repo_root))
    lacking, extra = sorted(needed - built), sorted(built - needed)
    if not lacking and not extra:
        return True, ""
    parts = []
    if lacking:
        parts.append("lacks " + ", ".join(lacking[:8]) + (" ..." if len(lacking) > 8 else ""))
    if extra:
        parts.append("carries packages no longer needed: " + ", ".join(extra[:8]) + (" ..." if len(extra) > 8 else ""))
    return False, "it " + " and ".join(parts)


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


def seed_debs(seeds) -> list:
    """Every package already on hand: `<seed>/apt/*.deb` (an earlier cache, or the drive's carried one) and
    `<seed>/*.deb` (a flat folder), earlier seeds first, one file per package file name."""
    found = {}
    for seed in map(Path, seeds):
        for folder in (seed / "apt", seed):
            for deb in sorted(folder.glob("*.deb")) if folder.is_dir() else []:
                found.setdefault(deb.name, deb)
    return sorted(found.values(), key=lambda p: p.name)


def seed_apps(target, seeds) -> list:
    """Copy into `target` each application an earlier cache already carries (recipe + archive) and `target` lacks."""
    import shutil
    target = Path(target)
    reused = []
    for seed in map(Path, seeds):
        for folder in sorted((seed / APP_BUNDLE).glob("*")) if (seed / APP_BUNDLE).is_dir() else []:
            if (folder / "recipe.json").is_file() and not (target / folder.name).exists():
                shutil.copytree(folder, target / folder.name)
                reused.append(folder.name)
    return reused


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


KASM_BUNDLE = "kasm"


def carry_kasm_base(source, target) -> dict:
    """Copy the prepared Kasm base (baseline-build-kasm-base: the qcow2 and its KASM.json) into the cache as `kasm/`, after checking the base
    against its own manifest and that it says it holds no install state or secrets. A base that fails either is never carried."""
    import json
    import shutil
    source, target = Path(source), Path(target) / KASM_BUNDLE
    manifest = json.loads((source / "KASM.json").read_text())
    image = source / manifest["base"]
    if manifest.get("holds_install_state_or_secrets") is not False:
        raise RuntimeError("the Kasm base does not say it is free of install state and secrets; it is not carried")
    if sha256(image) != manifest["sha256"]:
        raise RuntimeError("the Kasm base does not match its manifest checksum; it is not carried")
    target.mkdir(parents=True)
    shutil.copyfile(image, target / image.name)
    shutil.copyfile(source / "KASM.json", target / "KASM.json")
    return {"base": image.name, "bytes": image.stat().st_size, "kasm_version": manifest.get("kasm_version")}
