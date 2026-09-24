"""Detection for the five expected Baseline diagnostic tools, driven by
tools_manifest.json rather than hardcoded names.

NUT and ProxMenux are deliberately NOT in this list (see design doc,
"Explicitly deferred"): NUT is deferred because this machine has no UPS,
and the ordinary package inventory (collectors/system.py) already shows
NUT packages if they happen to exist - no special service inspection is
needed. ProxMenux detection is deferred until it is intentionally
evaluated, not probed here.
"""
import json
import os

from .status_notes import notes as _notes

_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "..", "tools_manifest.json")


def load_manifest(path=None):
    with open(path or _MANIFEST_PATH) as f:
        return json.load(f)


def collect(runner, manifest=None):
    manifest = manifest if manifest is not None else load_manifest()
    results = {}
    for tool in manifest["tools"]:
        name = tool["name"]
        binary = tool["detect"]["binary"]
        found = runner.which(binary)
        if not found:
            results[name] = {"available": False, "reason": f"{binary} not on PATH"}
            continue
        version_result = runner.run(tool["detect"]["version_command"])
        pkg_version = None
        pkg_cmd = tool.get("package_version_command")
        if pkg_cmd:
            pkg_result = runner.run(pkg_cmd)
            if pkg_result.ok:
                pkg_version = pkg_result.stdout.strip()
        results[name] = {
            "available": True,
            "binary_path": found,
            "version_output": version_result.stdout.strip() if version_result.ok else None,
            "package_version": pkg_version,
            "_collection_notes": _notes((version_result, f"{binary} version command")),
        }
    return results
