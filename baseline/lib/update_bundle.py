"""Prepare the reviewed update bundle that `baseline-rebuild-drive` applies to an existing build: the committed code, copied and checksummed, with the plan that says it is an update of that drive.

The bundle is made from the repository as it is committed now (refused when the working copy has uncommitted changes in what is carried, so what is applied is exactly a commit). It never touches a drive.
"""
from __future__ import annotations

import time
from pathlib import Path

import build_currency
import installer_inputs


class BundleError(RuntimeError):
    pass


def prepare_update_bundle(runner, repo, bundles_dir, target: str, *, now=None, known_targets=()) -> Path:
    if known_targets and target not in known_targets:
        raise BundleError(f"{target!r} is not a drive this machine builds for; known: {', '.join(sorted(known_targets))}")
    state = build_currency.source_state(runner, repo)
    if state["dirty"]:
        raise BundleError(f"the working copy has uncommitted changes ({', '.join(state['dirty'][:5])}); commit them first so the update is exactly a commit")
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now if now is not None else time.time()))
    folder = Path(bundles_dir) / f"{target.lower()}-{stamp}"
    plan = {"installed_update": {"serial": target}}
    report = installer_inputs.prepare(Path(repo), folder, plan=plan, settings={}, recipe=None, artifact_locks={})
    installer_inputs.verify(folder)
    if not report.get("prepared"):
        raise BundleError("the bundle was not prepared")
    return folder
