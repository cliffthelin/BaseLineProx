#!/usr/bin/env python3
"""Install the five carried applications from the drive's own installer cache, with no network.

Run as root on an installed Baseline host (the allscript rehearsal does, in its VM). Uses the real `baseline-apps`:
install-runtime (the runtime packages, from the drive's carried repository), then for each application `install` (the
recipe's pinned checksum and package identity are re-checked) and `preflight` (does the sandbox work for it).
Prints one summary line and writes /var/log/baseline-apps-offline.json. Launching needs a display and is not tried.
"""
import json
import subprocess
import sys
from pathlib import Path

CACHE = Path("/mnt/INSTALLER_CACHE/installer/expanded/baseline-cache")
APPS = ("vscode", "spotify", "chrome", "chatgpt", "claude")
CLI = "/opt/baseline/bin/baseline-apps"
GENERATIONS = Path("/var/lib/baseline-apps/generations")
DATA = Path("/mnt/APPDATA_ADMIN/baseline-apps")


def run(*argv):
    proc = subprocess.run([str(a) for a in argv], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    report = {}
    code, out, err = run(CLI, "install-runtime")
    report["runtime"] = {"ok": code == 0, "detail": (err.strip() or out.strip())[-240:]}
    GENERATIONS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    for app in APPS:
        folder = CACHE / "apps" / app
        archive = next((p for p in (folder / "source.deb", folder / "source.tar.gz") if p.is_file()), None)
        generation, data = GENERATIONS / f"offline-{app}", DATA / app
        if archive is None:
            report[app] = {"ok": False, "detail": "not carried"}
            continue
        code, out, err = run(CLI, "install", folder / "recipe.json", archive, generation, data)
        entry = {"installed": code == 0, "detail": err.strip()[-200:]}
        if code == 0:
            code, out, err = run(CLI, "preflight", generation, data)
            try:
                entry["preflight"] = json.loads(out).get("usable")
            except ValueError:
                entry["preflight"] = err.strip()[-160:]
        report[app] = entry
    report["ok"] = report["runtime"]["ok"] and all(
        report[a].get("installed") and report[a].get("preflight") is True for a in APPS)
    Path("/var/log/baseline-apps-offline.json").write_text(json.dumps(report, indent=1))
    print("APPS-OFFLINE " + json.dumps({k: (v.get("ok", v.get("installed")) if isinstance(v, dict) else v)
                                         for k, v in report.items()}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
