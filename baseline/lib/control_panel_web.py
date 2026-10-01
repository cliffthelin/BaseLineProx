"""The real "Master Config" control-plane web application - not a
static form. Direct correction: "THIS IS A WEB APPLICATION THAT
INSTALLS SUBSTRATE CONTROL PLANES AND VMS AND IS A MASTER CONFIG LIST
THAT ALSO DRIVES STANDARD MANAGEMENT BEHAVIORS. IT IS NOT A FORM. I
NEVER WILL PASTE RESULTS INTO IT OR GENERATE JSONS TO USE SOMEWHERE
ELSE."

Every route below calls straight into the real, already-tested backend
modules (`drive_installer`, `config_diff`, `backup_restore`,
`update_pipeline`, `config_crypto`, `physical_device_safety`) with a
real `Runner` - never a copy-paste bridge, never a "run this command
and paste the output back" step. This module IS the bridge: it runs
on (or reachable from) the real target and does the real work itself.

Reuses this project's own proven pattern for exactly this kind of
surface (`settings_web.py`, PRD SS5.16): `http.server.HTTPServer` /
`BaseHTTPRequestHandler`, Runner-style dependency injection, and pure
`handle_*` functions returning a `RouteResult` so every route's real
decision logic is unit-testable with a `FakeRunner` - no real socket,
no real hardware - while the actual HTTP wiring stays a thin
pass-through, verified separately against a real running instance.
"""
from __future__ import annotations

import http.server
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

import backup_restore
import config_crypto
import config_diff
import web_gate
import drive_installer
import physical_device_safety as pds
import update_pipeline

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def read_text(self, path):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError

        def remove(self, path):
            raise NotImplementedError


DEFAULT_CONFIG_PATH = "/etc/baseline/install-config.json"


@dataclass
class RouteResult:
    outcome: str  # "applied" | "refused" | "handed_off"
    status: int
    body: dict


def _load_config(runner: Runner, config_path: str) -> dict | None:
    if not runner.path_exists(config_path):
        return None
    return json.loads(runner.read_text(config_path))


# ---------------------------------------------------------------------------
# Pure route logic - each one a real, direct call into an already-real
# backend module. No route here ever asks the caller to paste JSON in
# or hands back a command for the caller to run somewhere else.
# ---------------------------------------------------------------------------

def _not_from_web_app(origin, op: str):
    """None if the web application asked for this (a signed origin for `op`), else the refusal to return."""
    try:
        web_gate.require(origin, op, {})
    except web_gate.NotFromWebApp as exc:
        return RouteResult("refused", 403, {"detail": f"refused: {exc}"})
    return None


def handle_detect(runner: Runner, *, vg_name: str = drive_installer.DEFAULT_VG_NAME) -> RouteResult:
    result = drive_installer.detect_existing_baseline_install(runner, vg_name=vg_name)
    return RouteResult("applied", 200, result)


def handle_active_persona(runner: Runner) -> RouteResult:
    """Persona-aware wiring (work-queue item 25, decision record 78):
    the Backup card's own target path used to hardcode the legacy
    singular `/mnt/USER` mountpoint regardless of which
    persona is actually active - reuses `persist_bind_mounts.py`'s own
    active-persona marker directly rather than re-deriving it here, so
    a caller (the page's own JS) can default the field correctly
    instead of pointing at a mountpoint that may not even be mounted."""
    import persist_bind_mounts as pbm
    persona = pbm.get_active_persona(runner)
    mountpoint = pbm.user_mountpoint_for(persona)
    return RouteResult("applied", 200, {"persona": persona, "mountpoint": mountpoint})


def handle_differences(runner: Runner, *, config_path: str = DEFAULT_CONFIG_PATH,
                        network_interface: str = "eno1") -> RouteResult:
    config = _load_config(runner, config_path)
    if config is None:
        return RouteResult("handed_off", 409,
                            {"reason": f"no exported config found at {config_path} - "
                                       "export one from the Master Config first"})
    sections = config_diff.compute_full_diff(runner, config, network_interface=network_interface)
    return RouteResult("applied", 200, {"diff_sections": sections})


def handle_backup(runner: Runner, *, dest: str, targets: list, config_only: bool = False,
                   now: float = None, origin=None) -> RouteResult:
    """`now` (real wall-clock time from the caller) records a fresh
    backup-success manifest per target on success - the durable proof
    `handle_restore`'s own hard gate checks before allowing any
    restore to touch USER (decision record 74)."""
    try:
        dest = backup_restore.check_new_backup_file(runner, dest, suffix=".tar.gz")
        if not config_only:
            targets = backup_restore.check_backup_sources(targets)
    except ValueError as exc:
        return RouteResult("refused", 422, {"detail": f"refused: {exc}"})
    refusal = _not_from_web_app(origin, "cpw_backup")
    if refusal:
        return refusal
    result = backup_restore.create_backup(runner, dest_path=dest, targets=targets,
                                           config_only=config_only, now=now)
    if not result.ok:
        return RouteResult("refused", 422, {"detail": result.detail})
    return RouteResult("applied", 200, {"detail": result.detail, "dest": dest})


def handle_backup_list(runner: Runner, *, archive: str) -> RouteResult:
    try:
        archive = backup_restore.check_existing_backup_file(runner, archive)
    except ValueError as exc:
        return RouteResult("refused", 422, {"detail": f"refused: {exc}"})
    contents = backup_restore.list_backup_contents(runner, archive)
    return RouteResult("applied", 200, {"contents": contents})


def handle_restore(runner: Runner, *, archive: str, dest_root: str, members: list = None,
                    now: float = None, origin=None) -> RouteResult:
    """`now` (real wall-clock time from the caller) is required to
    pass backup_restore.restore_backup's own hard gate: any restore
    touching USER refuses outright without a fresh backup
    manifest (decision record 74) - omitting `now` refuses too,
    matching that module's own fail-closed design."""
    try:
        archive = backup_restore.check_existing_backup_file(runner, archive)
        dest_root = backup_restore.check_restore_root(dest_root)
        members = backup_restore.check_restore_members(members)
    except ValueError as exc:
        return RouteResult("refused", 422, {"detail": f"refused: {exc}"})
    refusal = _not_from_web_app(origin, "cpw_restore")
    if refusal:
        return refusal
    result = backup_restore.restore_backup(runner, archive_path=archive, dest_root=dest_root,
                                            members=members or None, now=now)
    if not result.ok:
        return RouteResult("refused", 422, {"detail": result.detail})
    return RouteResult("applied", 200, {"detail": result.detail})


def handle_update(runner: Runner, *, config_path: str = DEFAULT_CONFIG_PATH,
                   categories: dict, network_interface: str = "eno1", origin=None) -> RouteResult:
    refusal = _not_from_web_app(origin, "cpw_update")
    if refusal:
        return refusal
    config = _load_config(runner, config_path)
    if config is None:
        return RouteResult("handed_off", 409,
                            {"reason": f"no exported config found at {config_path}"})
    summary = update_pipeline.apply_selective_update(runner, config, categories, network_interface=network_interface)
    if summary["failed"]:
        return RouteResult("refused", 422, summary)
    return RouteResult("applied", 200, summary)


def handle_validate_drive(pds_runner: "pds.Runner", *, path: str, min_size_bytes: int,
                           expected_serial=None) -> RouteResult:
    try:
        result = pds.validate_target_device(path, expected_serial=expected_serial,
                                             min_size_bytes=min_size_bytes, runner=pds_runner)
        return RouteResult("applied", 200, result)
    except pds.PhysicalDeviceSafetyError as exc:
        return RouteResult("refused", 422, {"error": str(exc)})


def handle_backup_encrypt(runner: Runner, *, in_path: str, out_path: str, password: str, origin=None) -> RouteResult:
    """The password never touches an argv, a log line, or disk beyond
    an ephemeral 0600 temp file that is removed immediately after -
    the same discipline this project's key-handling code already
    established (baseline-drive-inventory's own docstring)."""
    try:
        in_path = backup_restore.check_existing_backup_file(runner, in_path, what="in_path")
        out_path = backup_restore.check_new_backup_file(runner, out_path, suffix=".gpg", what="out_path")
    except ValueError as exc:
        return RouteResult("refused", 422, {"detail": f"refused: {exc}"})
    refusal = _not_from_web_app(origin, "cpw_encrypt")
    if refusal:
        return refusal
    fd, pw_path = tempfile.mkstemp(prefix=".baseline-cpw-")
    try:
        os.chmod(pw_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(password)
        result = config_crypto.encrypt_file(runner, in_path=in_path, out_path=out_path, password_file=pw_path)
    finally:
        try:
            os.remove(pw_path)
        except OSError:
            pass
    if not result.ok:
        return RouteResult("refused", 422, {"detail": result.detail})
    return RouteResult("applied", 200, {"detail": result.detail, "out_path": out_path})


def handle_backup_decrypt(runner: Runner, *, in_path: str, out_path: str, password: str, origin=None) -> RouteResult:
    try:
        in_path = backup_restore.check_existing_backup_file(runner, in_path, what="in_path")
        out_path = backup_restore.check_new_backup_file(runner, out_path, suffix=".tar.gz", what="out_path")
    except ValueError as exc:
        return RouteResult("refused", 422, {"detail": f"refused: {exc}"})
    refusal = _not_from_web_app(origin, "cpw_decrypt")
    if refusal:
        return refusal
    fd, pw_path = tempfile.mkstemp(prefix=".baseline-cpw-")
    try:
        os.chmod(pw_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(password)
        result = config_crypto.decrypt_file(runner, in_path=in_path, out_path=out_path, password_file=pw_path)
    finally:
        try:
            os.remove(pw_path)
        except OSError:
            pass
    if not result.ok:
        return RouteResult("refused", 422, {"detail": result.detail})
    return RouteResult("applied", 200, {"detail": result.detail, "out_path": out_path})


# ---------------------------------------------------------------------------
# Real HTTP wiring - thin; all decision logic lives in the handle_*
# functions above so it's testable without opening a real socket.
# ---------------------------------------------------------------------------

class ControlPanelHandler(http.server.BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
        pass

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode()) if raw else {}
        except ValueError:
            return {}

    def do_GET(self):  # noqa: N802
        deps = self.server.deps  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            return self._html(200, render_index_page().encode())

        if parsed.path == "/api/detect":
            result = handle_detect(deps["runner"], vg_name=deps.get("vg_name", drive_installer.DEFAULT_VG_NAME))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if parsed.path == "/api/active-persona":
            result = handle_active_persona(deps["runner"])
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if parsed.path == "/api/differences":
            result = handle_differences(deps["runner"], config_path=deps["config_path"],
                                         network_interface=deps.get("network_interface", "eno1"))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if parsed.path == "/api/backup/list":
            archive = (qs.get("archive") or [""])[0]
            result = handle_backup_list(deps["runner"], archive=archive)
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        result = RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}"})
        self._json(result.status, {"outcome": result.outcome, **result.body})

    def do_POST(self):  # noqa: N802
        deps = self.server.deps  # type: ignore[attr-defined]
        body = self._read_json_body()

        if self.path == "/api/backup":
            result = handle_backup(deps["runner"], dest=body.get("dest", ""),
                                    targets=body.get("targets", []), config_only=bool(body.get("config_only")),
                                    now=time.time())
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if self.path == "/api/restore":
            result = handle_restore(deps["runner"], archive=body.get("archive", ""),
                                     dest_root=body.get("dest_root", "/mnt"), members=body.get("members", []),
                                     now=time.time())
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if self.path == "/api/update":
            result = handle_update(deps["runner"], config_path=deps["config_path"],
                                    categories=body.get("categories", {}),
                                    network_interface=deps.get("network_interface", "eno1"))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if self.path == "/api/validate-drive":
            result = handle_validate_drive(deps["pds_runner"], path=body.get("path", ""),
                                            min_size_bytes=int(body.get("min_size_bytes", 0)),
                                            expected_serial=body.get("expected_serial"))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if self.path == "/api/backup/encrypt":
            result = handle_backup_encrypt(deps["runner"], in_path=body.get("in_path", ""),
                                            out_path=body.get("out_path", ""), password=body.get("password", ""))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if self.path == "/api/backup/decrypt":
            result = handle_backup_decrypt(deps["runner"], in_path=body.get("in_path", ""),
                                            out_path=body.get("out_path", ""), password=body.get("password", ""))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        result = RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}"})
        self._json(result.status, {"outcome": result.outcome, **result.body})


def make_server(*, runner: Runner, pds_runner, config_path: str = DEFAULT_CONFIG_PATH,
                vg_name: str = drive_installer.DEFAULT_VG_NAME, network_interface: str = "eno1",
                host: str = "127.0.0.1", port: int = 8642) -> http.server.HTTPServer:
    server = http.server.HTTPServer((host, port), ControlPanelHandler)
    server.deps = {  # type: ignore[attr-defined]
        "runner": runner, "pds_runner": pds_runner, "config_path": config_path,
        "vg_name": vg_name, "network_interface": network_interface,
    }
    return server


def render_index_page() -> str:
    return _INDEX_HTML


_INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Baseline Control Panel</title>
<style>
body{font-family:ui-sans-serif,system-ui,sans-serif;background:#121319;color:#eceef3;margin:0;padding:24px;}
.baseline-nav{display:flex;gap:1.25rem;padding:0 0 1rem;margin-bottom:1rem;border-bottom:2px solid #2a2d38;font-size:.95rem;}
.baseline-nav a{color:#a7abbc;text-decoration:none;padding:.25rem .1rem;}
.baseline-nav a.active{color:#eceef3;font-weight:700;border-bottom:2px solid #5b93ff;}
h1{font-size:20px;} h2{font-size:15px;margin-top:28px;}
.card{background:#191b22;border:1px solid #2a2d38;border-radius:10px;padding:16px 20px;margin-bottom:16px;}
button{background:#5b93ff;color:#fff;border:none;border-radius:7px;padding:8px 14px;font-weight:700;cursor:pointer;margin-right:8px;}
button:disabled{background:#2a2d38;color:#6f7386;cursor:not-allowed;}
input,select{background:#1c1e27;color:#eceef3;border:1px solid #2a2d38;border-radius:6px;padding:6px 8px;}
pre{background:#1c1e27;padding:10px;border-radius:8px;overflow-x:auto;font-size:12px;}
.row{margin-bottom:8px;}
.status{font-size:12px;color:#a7abbc;}
label{display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:13px;}
</style></head>
<body>
<h1>Baseline Control Panel</h1>

<div class="card">
  <h2>Target drive for install</h2>
  <button onclick="detect()">Detect</button>
  <div id="detectResult"></div>
</div>

<div class="card">
  <h2>Differences</h2>
  <button onclick="differences()">Check differences</button>
  <div id="diffResult"></div>
</div>

<div class="card">
  <h2>Backup</h2>
  <div class="row">Destination: <input id="backupDest" value="/mnt/INSTALLER_CACHE/backups/baseline-backup.tar.gz" size="50"></div>
  <div class="row">Targets (comma-separated paths): <input id="backupTargets" value="" size="50" placeholder="loading active persona..."></div>
  <button onclick="runBackup()">Run backup</button>
  <div id="backupResult"></div>
</div>

<div class="card">
  <h2>Restore</h2>
  <div class="row">Archive: <input id="restoreArchive" size="50"></div>
  <button onclick="listBackup()">List contents</button>
  <button onclick="runRestore()">Restore</button>
  <div id="restoreResult"></div>
</div>

<div class="card">
  <h2>Update existing install</h2>
  <label><input type="checkbox" id="catDrivers" checked> Drivers</label>
  <label><input type="checkbox" id="catConfigs" checked> Configs</label>
  <button onclick="runUpdate()">Run update</button>
  <div id="updateResult"></div>
</div>

<script>
async function callApi(path, opts){
  const res = await fetch(path, opts);
  const body = await res.json();
  return body;
}
async function loadActivePersona(){
  const body = await callApi("/api/active-persona");
  if (body.mountpoint) document.getElementById("backupTargets").value = body.mountpoint;
}
loadActivePersona();
async function detect(){
  const body = await callApi("/api/detect");
  document.getElementById("detectResult").innerHTML = "<pre>" + JSON.stringify(body, null, 2) + "</pre>";
}
async function differences(){
  const body = await callApi("/api/differences");
  document.getElementById("diffResult").innerHTML = "<pre>" + JSON.stringify(body, null, 2) + "</pre>";
}
async function runBackup(){
  const dest = document.getElementById("backupDest").value;
  const targets = document.getElementById("backupTargets").value.split(",").map(s=>s.trim()).filter(Boolean);
  const body = await callApi("/api/backup", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({dest, targets})});
  document.getElementById("backupResult").innerHTML = "<pre>" + JSON.stringify(body, null, 2) + "</pre>";
}
async function listBackup(){
  const archive = document.getElementById("restoreArchive").value;
  const body = await callApi("/api/backup/list?archive=" + encodeURIComponent(archive));
  document.getElementById("restoreResult").innerHTML = "<pre>" + JSON.stringify(body, null, 2) + "</pre>";
}
async function runRestore(){
  const archive = document.getElementById("restoreArchive").value;
  const body = await callApi("/api/restore", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({archive, dest_root:"/mnt"})});
  document.getElementById("restoreResult").innerHTML = "<pre>" + JSON.stringify(body, null, 2) + "</pre>";
}
async function runUpdate(){
  const categories = {drivers: document.getElementById("catDrivers").checked, configs: document.getElementById("catConfigs").checked};
  const body = await callApi("/api/update", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({categories})});
  document.getElementById("updateResult").innerHTML = "<pre>" + JSON.stringify(body, null, 2) + "</pre>";
}
</script>
</body></html>
"""


def main() -> int:
    """The standalone control panel has NO login: anyone who can reach its port could run backups and restores
    as root. Its routes are served by the merged, login-gated app (baseline-web), so this entry point no longer
    starts a server."""
    import sys
    print("The standalone control panel server has no login and is retired. Use baseline-web, which serves the "
          "same pages behind the login.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
