"""The boot-time machine check (DR256): which machine is this, what does that ask for, and do whatever can be done now.

`run_once` is what the timer runs. It compares the current machine with the profiles this drive keeps (machine_context.observe), then runs the
queued tasks that are due: deterministic ones as soon as the substrate is up, helper-only ones never from here (they stay queued for the AI
stage, which is when something exists to help). A mismatch never fails or denies anything: a task that cannot be settled deterministically
is deferred to the helper with the reason.

Executors return None (not settled yet, try again later) or (outcome, detail): "done", "not_needed" or "defer".
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

import drive_installer as di
import machine_context as mc
import references

STATE_DIR = Path("/var/lib/baseline/machines")
CACHE_ROOT = Path("/mnt/INSTALLER_CACHE/expanded/baseline-cache")
HARNESS_ENV = Path("/etc/baseline/harness.env")


def probe_stages(*, mounted=os.path.ismount, unit_active=None, connect=None, harness_env=HARNESS_ENV) -> set:
    """Which readiness stages are up right now: substrate, gui, browser, internet, ai (machine_context.STAGES)."""
    unit_active = unit_active or (lambda unit: subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0)

    def reach(address=("1.1.1.1", 443)):
        try:
            socket.create_connection(address, timeout=3).close()
            return True
        except OSError:
            return False
    connect = connect or reach
    up = set()
    if mounted("/mnt/BASELINE"):
        up.add("substrate")
    if unit_active("baseline-kiosk.service"):
        up.update({"gui", "browser"})
    if connect():
        up.add("internet")
        try:
            if Path(harness_env).read_text().strip():
                up.add("ai")
        except OSError:
            pass
    return up


# --- executors -------------------------------------------------------------------------------------------------------------------

def _slug(ctx) -> str:
    return str(ctx["profile"] or "unknown").replace("/", "_")[:48]


def discover_hardware(ctx):
    raw, error = ctx["collect"]()
    if raw is None:
        return "defer", f"the hardware inventory could not be collected: {error}"
    out = Path(ctx["state_dir"]) / f"{_slug(ctx)}.hardware.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, indent=1))
    return "done", f"hardware inventory for this machine saved to {out}"


def check_installer_cache(ctx):
    manifest = Path(ctx["cache_root"]) / "MANIFEST.json"
    if not manifest.is_file():
        return "not_needed", "this drive carries no installer cache to check"
    import offline_cache
    try:
        count = offline_cache.verify_manifest(ctx["cache_root"], json.loads(manifest.read_text()))
    except (OSError, ValueError, RuntimeError) as exc:
        return "defer", f"the carried installer cache does not verify on this machine: {exc}"
    return "done", f"{count} carried packages verified"


def _check_roles(prefix):
    def check(ctx):
        problems = []
        for _, _, _, label, mountpoint in di.baseline_volumes_for(tuple(ctx["personas"])):
            if not label.startswith(prefix):
                continue
            if not ctx["mounted"](mountpoint):
                problems.append(f"{label} is not mounted at {mountpoint}")
            elif not os.access(mountpoint, os.W_OK):
                problems.append(f"{label} is mounted but not writable")
            else:
                try:
                    if os.statvfs(mountpoint).f_bavail == 0:
                        problems.append(f"{label} has no free space")
                except OSError as exc:
                    problems.append(f"{label} could not be measured: {exc}")
        if problems:
            return "defer", "; ".join(problems)
        return "done", f"every {prefix}* volume is mounted, writable and has room"
    return check


def retry_fingerprint(ctx):
    fingerprint = mc.read_fingerprint(ctx["read"])
    return ("done", "the machine can now be identified") if any(k in fingerprint for k in mc.IDENTITY_KEYS) else None


def recheck_changed_parts(ctx):
    import bridge_port
    return "done", "network bridge re-checked: " + json.dumps(bridge_port.run()).replace("\n", " ")[:160]


EXECUTORS = {
    "discover-hardware": discover_hardware,
    "check-installer-cache": check_installer_cache,
    "check-appdata": _check_roles("APPDATA_"),
    "check-user-data": _check_roles("USER_"),
    "retry-fingerprint": retry_fingerprint,
    "recheck-changed-parts": recheck_changed_parts,
}                      # rebuild-vm-config and resolve-incompatibilities have no executor: they are for the helper


def run_once(*, read=None, stages=None, collect=None, mounted=os.path.ismount, state_dir=STATE_DIR, cache_root=CACHE_ROOT,
             personas=di.DEFAULT_PERSONAS) -> dict:
    host = references.current_host()
    if host is None:
        return {"state": "no_host_identifier", "ran": []}
    read = read or mc.file_reader()
    observed = mc.observe(host, mc.read_fingerprint(read))
    ready = probe_stages() if stages is None else set(stages)
    if collect is None:
        import hardware
        collect = hardware.collect
    ctx = {"read": read, "profile": observed["profile"], "host": host, "state_dir": state_dir, "cache_root": cache_root,
           "collect": collect, "mounted": mounted, "personas": personas}
    ran = []
    for task_id, attrs in mc.due(ready):
        executor = EXECUTORS.get(attrs["kind"])
        if executor is None:
            continue
        # a task belongs to the profile that queued it: do not run another machine's checks against this one
        outcome = executor(dict(ctx, profile=attrs.get("profile") or ctx["profile"]))
        if outcome is None:
            continue
        verdict, detail = outcome
        if verdict == "defer":
            mc.defer(task_id, detail)
        else:
            mc.complete(task_id, outcome=verdict, detail=detail)
        ran.append({"task": task_id, "outcome": verdict, "detail": detail})
    return {"state": observed["state"], "profile": observed["profile"], "ran": ran, "ready": sorted(ready)}
