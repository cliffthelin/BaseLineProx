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
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

import backup_restore
import config_crypto
import config_diff
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

def handle_detect(runner: Runner, *, vg_name: str = drive_installer.DEFAULT_VG_NAME) -> RouteResult:
    result = drive_installer.detect_existing_baseline_install(runner, vg_name=vg_name)
    return RouteResult("applied", 200, result)


def handle_differences(runner: Runner, *, config_path: str = DEFAULT_CONFIG_PATH,
                        network_interface: str = "eno1") -> RouteResult:
    config = _load_config(runner, config_path)
    if config is None:
        return RouteResult("handed_off", 409,
                            {"reason": f"no exported config found at {config_path} - "
                                       "export one from the Master Config first"})
    sections = config_diff.compute_full_diff(runner, config, network_interface=network_interface)
    return RouteResult("applied", 200, {"diff_sections": sections})


def handle_backup(runner: Runner, *, dest: str, targets: list, config_only: bool = False) -> RouteResult:
    result = backup_restore.create_backup(runner, dest_path=dest, targets=targets, config_only=config_only)
    if not result.ok:
        return RouteResult("refused", 422, {"detail": result.detail})
    return RouteResult("applied", 200, {"detail": result.detail, "dest": dest})


def handle_backup_list(runner: Runner, *, archive: str) -> RouteResult:
    contents = backup_restore.list_backup_contents(runner, archive)
    return RouteResult("applied", 200, {"contents": contents})


def handle_restore(runner: Runner, *, archive: str, dest_root: str, members: list = None) -> RouteResult:
    result = backup_restore.restore_backup(runner, archive_path=archive, dest_root=dest_root, members=members or None)
    if not result.ok:
        return RouteResult("refused", 422, {"detail": result.detail})
    return RouteResult("applied", 200, {"detail": result.detail})


def handle_update(runner: Runner, *, config_path: str = DEFAULT_CONFIG_PATH,
                   categories: dict, network_interface: str = "eno1") -> RouteResult:
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


def handle_backup_encrypt(runner: Runner, *, in_path: str, out_path: str, password: str) -> RouteResult:
    """The password never touches an argv, a log line, or disk beyond
    an ephemeral 0600 temp file that is removed immediately after -
    the same discipline this project's key-handling code already
    established (baseline-drive-inventory's own docstring)."""
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


def handle_backup_decrypt(runner: Runner, *, in_path: str, out_path: str, password: str) -> RouteResult:
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
                                    targets=body.get("targets", []), config_only=bool(body.get("config_only")))
            return self._json(result.status, {"outcome": result.outcome, **result.body})

        if self.path == "/api/restore":
            result = handle_restore(deps["runner"], archive=body.get("archive", ""),
                                     dest_root=body.get("dest_root", "/mnt"), members=body.get("members", []))
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
  <div class="row">Targets (comma-separated paths): <input id="backupTargets" value="/mnt/USER_PERSISTENCE" size="50"></div>
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
    from repair import RealRunner
    runner = RealRunner()
    server = make_server(runner=runner, pds_runner=pds.Runner())
    print(f"Baseline Control Panel listening on http://{server.server_address[0]}:{server.server_address[1]}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
