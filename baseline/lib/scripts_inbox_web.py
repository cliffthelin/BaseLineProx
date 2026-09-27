"""Real, login-gated HTTP CRUD server for scripts_inbox.py - "it's just
files with server and folder access to CRUD," per direct instruction:
a client (a phone, a laptop, anything that can log in and speak HTTP)
pushes a script into the inbox folder; an operator later runs it by
hand from a real Proxmox/Baseline terminal. This server never executes
anything itself - it only stores files.

Login-gated the same way settings_web.py already is -
`PasswordVerifier`, `SessionStore`, `handle_login`,
`FileBackedPasswordVerifier`, and `JsonFileStore` are all reused
directly from settings_web.py, not duplicated. This is a deliberate,
important difference from control_panel_web.py, which has no
authentication at all and is kept operator-invoked-only for exactly
that reason (decision record 65) - this server IS meant to be reached
over the network (that's the whole point), so it must never repeat
that gap. It uses its own separate credential store from settings-web's
own (a different data file), so a compromised scripts-inbox login
can't also reach settings, and vice versa.

Every route below is a pure handle_* function returning a RouteResult,
unit-testable with fakes - the same discipline every other web module
in this project already follows.
"""
from __future__ import annotations

import http.server
import json
import time
from dataclasses import dataclass
from urllib.parse import unquote

import scripts_inbox as si
from settings_web import FileBackedPasswordVerifier, JsonFileStore, SessionStore, handle_login


@dataclass
class RouteResult:
    outcome: str  # "applied" | "refused" | "handed_off"
    status: int
    body: dict


def handle_list(runner, sessions: SessionStore, token: str, now: float,
                 inbox_dir: str = si.DEFAULT_INBOX_DIR) -> RouteResult:
    if sessions.get(token, now) is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    return RouteResult("applied", 200, {"scripts": si.list_scripts(runner, inbox_dir)})


def handle_read(runner, sessions: SessionStore, token: str, name: str, now: float,
                 inbox_dir: str = si.DEFAULT_INBOX_DIR) -> RouteResult:
    if sessions.get(token, now) is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    content = si.read_script(runner, name, inbox_dir)
    if content is None:
        return RouteResult("refused", 404, {"error": f"{name} not found"})
    return RouteResult("applied", 200, {"name": name, "content": content})


def handle_write(runner, sessions: SessionStore, token: str, name: str, content: str, now: float,
                  inbox_dir: str = si.DEFAULT_INBOX_DIR) -> RouteResult:
    if sessions.get(token, now) is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    result = si.write_script(runner, name, content, inbox_dir)
    if result.ok:
        return RouteResult("applied", 200, {"detail": result.detail})
    return RouteResult("refused", 400, {"error": result.detail})


def handle_delete(runner, sessions: SessionStore, token: str, name: str, now: float,
                   inbox_dir: str = si.DEFAULT_INBOX_DIR) -> RouteResult:
    if sessions.get(token, now) is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    result = si.delete_script(runner, name, inbox_dir)
    if result.ok:
        return RouteResult("applied", 200, {"detail": result.detail})
    return RouteResult("refused", 404, {"error": result.detail})


# ---------------------------------------------------------------------------
# Real HTTP wiring - thin; all decision logic lives in the handle_*
# functions above so it's testable without opening a real socket.
# ---------------------------------------------------------------------------

class ScriptsInboxHandler(http.server.BaseHTTPRequestHandler):
    server_version = "baseline-scripts-inbox/1"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond(self, result: RouteResult) -> None:
        self._json(result.status, {"outcome": result.outcome, **result.body})

    def _token(self) -> str:
        return self.headers.get("X-Session-Token", "")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode()) if raw else {}
        except ValueError:
            return {}

    def do_POST(self):  # noqa: N802 - stdlib method name
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()
        body = self._read_json_body()

        if self.path == "/login":
            result = handle_login(deps["verifier"], deps["sessions"],
                                   body.get("username", ""), body.get("password", ""), now)
            return self._respond(RouteResult(result.outcome, result.status, result.body))

        if self.path.startswith("/api/scripts/"):
            name = unquote(self.path[len("/api/scripts/"):])
            result = handle_write(deps["runner"], deps["sessions"], self._token(), name,
                                   body.get("content", ""), now, deps["inbox_dir"])
            return self._respond(result)

        self._respond(RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}"}))

    def do_GET(self):  # noqa: N802 - stdlib method name
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()

        if self.path == "/api/scripts":
            result = handle_list(deps["runner"], deps["sessions"], self._token(), now, deps["inbox_dir"])
            return self._respond(result)

        if self.path.startswith("/api/scripts/"):
            name = unquote(self.path[len("/api/scripts/"):])
            result = handle_read(deps["runner"], deps["sessions"], self._token(), name, now, deps["inbox_dir"])
            return self._respond(result)

        self._respond(RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}"}))

    def do_DELETE(self):  # noqa: N802 - stdlib method name
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()

        if self.path.startswith("/api/scripts/"):
            name = unquote(self.path[len("/api/scripts/"):])
            result = handle_delete(deps["runner"], deps["sessions"], self._token(), name, now, deps["inbox_dir"])
            return self._respond(result)

        self._respond(RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}"}))


def build_real_server(*, bind_host: str = "0.0.0.0", bind_port: int = 8200,
                       data_path, inbox_dir: str = si.DEFAULT_INBOX_DIR):
    from pathlib import Path

    from repair import RealRunner

    store = JsonFileStore(Path(data_path))
    verifier = FileBackedPasswordVerifier(store)
    sessions = SessionStore()
    httpd = http.server.HTTPServer((bind_host, bind_port), ScriptsInboxHandler)
    httpd.deps = {  # type: ignore[attr-defined]
        "runner": RealRunner(), "verifier": verifier, "sessions": sessions,
        "clock": time.time, "inbox_dir": inbox_dir,
    }
    return httpd


def main() -> int:
    import os
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8200
    data_path = os.environ.get("BASELINE_SCRIPTS_INBOX_DATA", "/tmp/baseline-scripts-inbox/store.json")
    inbox_dir = os.environ.get("BASELINE_SCRIPTS_INBOX_DIR", si.DEFAULT_INBOX_DIR)
    server = build_real_server(bind_port=port, data_path=data_path, inbox_dir=inbox_dir)
    print(f"Baseline scripts inbox on http://0.0.0.0:{port}/  (login: root / baseline)")
    print(f"Data store: {data_path}")
    print(f"Inbox dir: {inbox_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
