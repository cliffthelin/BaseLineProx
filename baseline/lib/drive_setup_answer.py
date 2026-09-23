"""Boundary 2: answer delivery and ISO preparation (Milestone 1, §4).

Consolidates four previously-separate, already-proven experiment
modules (`experiments/m0-inv3/credential.py`, `answer_server.py`,
`wrapper.py`, `workspace.py`) into one boundary, per the PRD's own
reasoning: the credential feeds the answer content, the wrapper and
workspace guard the call that consumes it - these are tightly coupled
in practice and don't benefit from four separate files.

Four concerns, in dependency order:
1. Workspace - mode-0700 per-run directory with before/after inventory.
2. Credential - argv-free, high-entropy one-time password generation
   and hashing (`generate_one_time_password`, `hash_password_sha512crypt`).
3. Answer server - ephemeral, single-use, TTL-bounded HTTPS server
   (`EphemeralAnswerServer`) that serves the answer TOML exactly once,
   to a client presenting the expected synthetic hardware facts.
4. Prepare-iso wrapper (`AnswerRunner`-injectable, unlike 1-3 above) -
   `proxmox-auto-install-assistant prepare-iso`'s exit code is not
   trustworthy (decision record 02's finding: every observed failure
   still returned 0), so success is determined purely from explicit
   postconditions against the filesystem and the tool's own stdout,
   never the exit code, and the wrapper owns tmp-directory cleanup on
   every exit path.
"""
from __future__ import annotations

import http.server
import json
import logging
import os
import re
import secrets
import shutil
import ssl
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("drive_setup_answer")


# --------------------------------------------------------------------------
# 1. Workspace
# --------------------------------------------------------------------------

def create_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    ws = Path(tempfile.mkdtemp(prefix=f"baseline-{int(time.time())}-", dir=str(root)))
    os.chmod(ws, 0o700)
    mode = stat.S_IMODE(ws.stat().st_mode)
    assert mode == 0o700, f"workspace not 0700: {oct(mode)}"
    return ws


def inventory(ws: Path) -> dict:
    out = {}
    for p in sorted(ws.rglob("*")):
        try:
            st = p.stat(follow_symlinks=False)
            out[str(p.relative_to(ws))] = {
                "is_symlink": p.is_symlink(),
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
                "size": st.st_size,
                "mode": oct(stat.S_IMODE(st.st_mode)),
            }
        except FileNotFoundError:
            continue
    return out


def diff_inventory(before: dict, after: dict) -> dict:
    added = {k: v for k, v in after.items() if k not in before}
    removed = {k: v for k, v in before.items() if k not in after}
    changed = {
        k: (before[k], after[k])
        for k in before.keys() & after.keys()
        if before[k] != after[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


# --------------------------------------------------------------------------
# 2. Credential - argv-free by design. No Runner injection here: the
# security property under test is precisely that the plaintext never
# touches argv/env/shell, and openssl is a standard tool always present
# on the target - faking this call would test less than running it for
# real.
# --------------------------------------------------------------------------

def generate_one_time_password(num_bytes: int = 32) -> bytes:
    return secrets.token_urlsafe(num_bytes).encode("ascii")


def hash_password_sha512crypt(password: bytes, salt: str) -> str:
    if b"\n" in password:
        raise ValueError("password must not contain newlines (crypt salt/format constraint)")
    argv = ["openssl", "passwd", "-6", "-salt", salt, "-stdin"]
    proc = subprocess.run(argv, input=password + b"\n", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, shell=False, check=True)
    return proc.stdout.decode("ascii").strip()


def hash_password_yescrypt(password: bytes, salt: str) -> str | None:
    if shutil.which("mkpasswd") is None:
        return None
    argv = ["mkpasswd", "--method=yescrypt", "--salt", salt, "--stdin"]
    proc = subprocess.run(argv, input=password + b"\n", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, shell=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("ascii").strip()


# --------------------------------------------------------------------------
# 3. Ephemeral answer server
# --------------------------------------------------------------------------

class SessionState:
    def __init__(self, session_id: str, answer_toml: str, expected_mac: str,
                 expected_dmi_product: str, ttl_seconds: float):
        self.session_id = session_id
        self.answer_toml = answer_toml
        self.expected_mac = expected_mac.lower()
        self.expected_dmi_product = expected_dmi_product
        self.created = time.monotonic()
        self.expires = self.created + ttl_seconds
        self.consumed = False
        self.lock = threading.Lock()

    def redacted_id(self) -> str:
        return self.session_id[:8] + "..." if self.session_id else "(none)"


@dataclass
class RequestOutcome:
    path: str
    result: str  # "consumed" | "denied_unknown_session" | "denied_expired" | "denied_already_consumed" | "denied_hw_mismatch"
    ts: float = field(default_factory=time.monotonic)


def _check_hardware(payload: dict, expected_mac: str, expected_dmi_product: str) -> tuple[bool, bool]:
    macs = []
    for iface in payload.get("network_interfaces", []) or []:
        m = iface.get("mac")
        if m:
            macs.append(str(m).lower())
    mac_ok = expected_mac in macs if macs else False

    dmi = payload.get("dmi", {}) or {}
    system = dmi.get("system", {}) or {}
    product = str(system.get("name", ""))
    dmi_ok = product == expected_dmi_product
    return mac_ok, dmi_ok


class AnswerHandler(http.server.BaseHTTPRequestHandler):
    server_version = "baseline-answer/1"

    def log_message(self, fmt, *args):
        log.info("client=%s %s", self.client_address[0], fmt % args)

    def do_POST(self):
        session: SessionState = self.server.session  # type: ignore[attr-defined]
        timeline: list = self.server.timeline  # type: ignore[attr-defined]
        path = self.path

        expected_path = f"/answer/{session.session_id}"
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"

        if path != expected_path:
            timeline.append(RequestOutcome(path="(redacted-mismatch)", result="denied_unknown_session"))
            log.info("POST to unrecognized session path -- denied")
            self._respond(404, b"not found")
            return

        with session.lock:
            if session.consumed:
                timeline.append(RequestOutcome(path=session.redacted_id(), result="denied_already_consumed"))
                self._respond(403, b"already consumed")
                return
            if time.monotonic() > session.expires:
                timeline.append(RequestOutcome(path=session.redacted_id(), result="denied_expired"))
                self._respond(410, b"expired")
                return

            try:
                payload = json.loads(raw_body or b"{}")
            except json.JSONDecodeError:
                payload = {}

            mac_ok, dmi_ok = _check_hardware(payload, session.expected_mac, session.expected_dmi_product)
            if not (mac_ok and dmi_ok):
                timeline.append(RequestOutcome(path=session.redacted_id(), result="denied_hw_mismatch"))
                self._respond(403, b"hardware mismatch")
                return

            session.consumed = True
            timeline.append(RequestOutcome(path=session.redacted_id(), result="consumed"))
            self._respond(200, session.answer_toml.encode("utf-8"), content_type="application/toml")

    def _respond(self, code: int, body: bytes, content_type: str = "text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class EphemeralAnswerServer:
    def __init__(self, bind_host: str, bind_port: int, cert_path: str, key_path: str,
                 session: SessionState):
        self.timeline: list = []
        self.httpd = http.server.HTTPServer((bind_host, bind_port), AnswerHandler)
        self.httpd.session = session  # type: ignore[attr-defined]
        self.httpd.timeline = self.timeline  # type: ignore[attr-defined]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]


# --------------------------------------------------------------------------
# 4. Prepare-iso wrapper - Runner-injectable, matching drive_setup_acquire's
# pattern, since this is exactly the kind of external-tool-invocation
# boundary that benefits from FakeRunner testing (no real assistant
# binary or real ISO needed to test the postcondition logic itself).
# --------------------------------------------------------------------------

class AnswerRunner:
    def run(self, argv: list[str], timeout: float = 120) -> "AnswerProc":
        raise NotImplementedError

    def path_exists(self, path: Path) -> bool:
        raise NotImplementedError

    def is_regular_file(self, path: Path) -> bool:
        raise NotImplementedError

    def is_symlink(self, path: Path) -> bool:
        raise NotImplementedError

    def file_size(self, path: Path) -> int:
        raise NotImplementedError

    def read_bytes(self, path: Path) -> bytes:
        raise NotImplementedError

    def resolve(self, path: Path) -> Path:
        raise NotImplementedError

    def listdir(self, path: Path) -> list[Path]:
        raise NotImplementedError

    def remove_tree_or_file(self, path: Path) -> None:
        raise NotImplementedError


@dataclass
class AnswerProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class RealAnswerRunner(AnswerRunner):
    def run(self, argv, timeout=120):
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
            return AnswerProc(proc.returncode, out, err, timed_out=False)
        except subprocess.TimeoutExpired:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate(timeout=5)
            return AnswerProc(-9, out, err, timed_out=True)

    def path_exists(self, path):
        return Path(path).exists()

    def is_regular_file(self, path):
        return Path(path).is_file() and not Path(path).is_symlink()

    def is_symlink(self, path):
        return Path(path).is_symlink()

    def file_size(self, path):
        return Path(path).stat().st_size

    def read_bytes(self, path):
        return Path(path).read_bytes()

    def resolve(self, path):
        return Path(path).resolve()

    def listdir(self, path):
        return list(Path(path).iterdir())

    def remove_tree_or_file(self, path):
        p = Path(path)
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()


FAILURE_PATTERNS = [
    re.compile(r"^Error:", re.MULTILINE),
    re.compile(r"panicked at", re.MULTILINE),
    re.compile(r"not able to be installed", re.MULTILINE),
    re.compile(r"Permission denied", re.MULTILINE),
]


@dataclass
class PostconditionResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class PrepareIsoOutcome:
    ok: bool
    output_path: Path | None
    postconditions: list = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    cleanup_ok: bool = False
    cleanup_detail: str = ""


def _cleanup_tmp(runner: AnswerRunner, tmp_dir: Path) -> tuple[bool, str]:
    if not runner.path_exists(tmp_dir):
        return True, "tmp_dir did not exist"
    leftovers = runner.listdir(tmp_dir)
    for item in leftovers:
        try:
            runner.remove_tree_or_file(item)
        except FileNotFoundError:
            pass
    remaining = runner.listdir(tmp_dir)
    if remaining:
        return False, f"cleanup could not remove: {[str(p) for p in remaining]}"
    return True, f"removed {len(leftovers)} leftover item(s)" if leftovers else "already empty"


def prepare_iso_defensively(
    runner: AnswerRunner,
    binary: Path, source_iso: Path, answer_file: Path | None, fetch_from: str,
    output_path: Path, tmp_dir: Path, workspace_root: Path, *,
    expected_fetch_mode: str, expected_url: str | None = None,
    expected_fingerprint: str | None = None,
    min_size: int, max_size: int,
    forbidden_iso_strings: list[bytes],
    extra_args: list[str] | None = None,
    timeout: float = 120.0,
) -> PrepareIsoOutcome:
    """Never trusts prepare-iso's or inspect-iso's exit code (decision
    record 02's finding: every observed failure still returned 0) -
    success is determined purely from explicit postconditions against
    the filesystem and the tools' own stdout text."""
    argv = [str(binary), "prepare-iso", str(source_iso), "--fetch-from", fetch_from,
            "--output", str(output_path), "--tmp", str(tmp_dir)]
    if answer_file is not None:
        argv += ["--answer-file", str(answer_file)]
    if extra_args:
        argv += extra_args

    checks: list[PostconditionResult] = []
    outcome = PrepareIsoOutcome(ok=False, output_path=None)

    try:
        proc = runner.run(argv, timeout=timeout)
        outcome.exit_code = proc.returncode
        outcome.stdout = proc.stdout
        outcome.stderr = proc.stderr

        checks.append(PostconditionResult(
            "no_timeout", not proc.timed_out,
            "prepare-iso exceeded bound, process group killed" if proc.timed_out else "",
        ))

        combined = proc.stdout + "\n" + proc.stderr
        failure_hits = [p.pattern for p in FAILURE_PATTERNS if p.search(combined)]
        checks.append(PostconditionResult(
            "stdout_stderr_clean", len(failure_hits) == 0,
            f"matched patterns: {failure_hits}" if failure_hits else "",
        ))

        exists = runner.path_exists(output_path)
        checks.append(PostconditionResult("output_exists", exists))
        if exists:
            checks.append(PostconditionResult("output_is_regular_file", runner.is_regular_file(output_path)))

            resolved = runner.resolve(output_path)
            inside = str(resolved).startswith(str(runner.resolve(workspace_root)) + "/")
            checks.append(PostconditionResult("output_inside_workspace", inside, str(resolved)))

            size = runner.file_size(output_path)
            size_ok = min_size <= size <= max_size
            checks.append(PostconditionResult("output_size_plausible", size_ok, f"size={size} bounds=[{min_size},{max_size}]"))

            insp_argv = [str(binary), "inspect-iso", str(output_path)]
            insp_proc = runner.run(insp_argv, timeout=30.0)
            iout = insp_proc.stdout
            inspect_ok = "Auto-install:  enabled" in iout or "Auto-install: enabled" in iout
            checks.append(PostconditionResult("inspect_iso_structure_ok", inspect_ok, iout.strip()[:400]))

            fetch_mode_ok = f"Fetch mode:    {expected_fetch_mode}" in iout or f"Fetch mode: {expected_fetch_mode}" in iout
            checks.append(PostconditionResult("fetch_mode_matches", fetch_mode_ok))

            if expected_url is not None:
                checks.append(PostconditionResult("url_matches", expected_url in iout))
            if expected_fingerprint is not None:
                checks.append(PostconditionResult("fingerprint_matches", expected_fingerprint in iout))

            token_absent = "HTTP auth token" not in iout
            checks.append(PostconditionResult("no_auth_token_embedded", token_absent))

            if forbidden_iso_strings:
                raw = runner.read_bytes(output_path)
                found = [s for s in forbidden_iso_strings if s in raw]
                checks.append(PostconditionResult(
                    "no_forbidden_canaries_in_iso", len(found) == 0,
                    f"found: {found}" if found else "",
                ))

            outcome.output_path = output_path if all(c.ok for c in checks) else None
    finally:
        cleanup_ok, cleanup_detail = _cleanup_tmp(runner, tmp_dir)
        outcome.cleanup_ok = cleanup_ok
        outcome.cleanup_detail = cleanup_detail
        checks.append(PostconditionResult("tmp_cleanup_verified", cleanup_ok, cleanup_detail))

    outcome.postconditions = checks
    outcome.ok = all(c.ok for c in checks)
    return outcome
