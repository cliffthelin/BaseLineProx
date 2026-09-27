#!/usr/bin/env python3
"""Real, permanent regression check: every `baseline/lib/*.py` module
transitively imported by any bin script `provision.sh` copies must
itself also be copied by `provision.sh` - otherwise that bin script
crashes with `ModuleNotFoundError` the first time it actually runs on
real hardware, invisibly, since nothing in the unit-test suite
exercises `provision.sh`'s own copy list against the current, real
import graph.

Found this exact bug for real (decision record 63): `firstboot_statemachine.py`
imports `config_pipeline` (which imports `config_apply`), and
`baseline/bin/baseline` transitively needs `harness_adapter`,
`harness_registry`, `harness_events`, `clipboard_osc52`, and
`status_bar` - none of the seven were ever added to `provision.sh`'s
copy list when the modules that need them were wired in. Fixed
alongside this checker so the fix can never silently regress.

    tools/check_provision_deploys_all_imports.py [--repo-root PATH]

Exits 1 and prints the missing module(s) if any gap is found; exits 0
otherwise. Pure, read-only - never modifies anything.
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path


def _local_modules(lib_dir: Path) -> set:
    return {p.stem for p in lib_dir.glob("*.py")}


def _imports_of(path: Path, local_modules: set) -> set:
    tree = ast.parse(path.read_text(), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found & local_modules


def _transitive_closure(entry_modules: set, lib_dir: Path, local_modules: set) -> set:
    seen = set()
    stack = list(entry_modules)
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = lib_dir / f"{mod}.py"
        if path.exists():
            for dep in _imports_of(path, local_modules):
                if dep not in seen:
                    stack.append(dep)
    return seen


def find_missing_lib_dependencies(repo_root: Path) -> list:
    """Pure (beyond reading real files under `repo_root`) - parses
    provision.sh's own copy list plus every bin script it copies'
    real, transitive local-module import graph, and returns the
    sorted list of local `lib/*.py` module names that graph needs but
    provision.sh never copies. Empty list = no gap."""
    lib_dir = repo_root / "baseline" / "lib"
    bin_dir = repo_root / "baseline" / "bin"
    provision_text = (repo_root / "boot" / "provision.sh").read_text()

    local_modules = _local_modules(lib_dir)
    copied_lib = set(re.findall(r"lib/([a-zA-Z0-9_]+)\.py", provision_text))
    copied_bin = set(re.findall(r'bin/([a-zA-Z0-9_-]+)"', provision_text))

    needed = set()
    for bin_name in copied_bin:
        bin_path = bin_dir / bin_name
        if not bin_path.exists():
            continue
        entry_mods = _imports_of(bin_path, local_modules)
        needed |= _transitive_closure(entry_mods, lib_dir, local_modules)

    return sorted(m for m in needed if m not in copied_lib)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="check_provision_deploys_all_imports")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args(argv)

    missing = find_missing_lib_dependencies(Path(args.repo_root))
    if missing:
        print("MISSING from provision.sh's copy list (would crash on real deployment):")
        for m in missing:
            print(f"  {m}.py")
        return 1
    print("OK: every module transitively needed by a provisioned bin script is copied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
