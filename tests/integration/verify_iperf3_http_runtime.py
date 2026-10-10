"""Actual unified HTTP server, sessions and SQLite; no FakeRunner or mock API.

Issues only a project-generated throwaway session. No operator credentials,
network test or physical write is used by this HTTP contract check.
"""
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import baseline_web
from repair import RealRunner
import settings_web


def verify():
    with tempfile.TemporaryDirectory(prefix="baseline-iperf-http-") as folder:
        store = settings_web.LocalAppStore(Path(folder) / "settings.sqlite")
        sessions = settings_web.SessionStore()
        session = sessions.create("iperf-runtime-" + secrets.token_hex(6), time.time())
        ready = threading.Event()
        holder = {}
        def serve():
            worker_store = settings_web.LocalAppStore(Path(folder) / "settings.sqlite")
            deps = {"clock": time.time, "sessions": sessions, "store": worker_store,
                    "source": settings_web.FileBackedSettingsSource(worker_store),
                    "applier": settings_web.SystemSectionApplier(worker_store, RealRunner())}
            server = baseline_web.make_server(deps=deps, host="127.0.0.1", port=0)
            holder["server"] = server
            ready.set()
            try:
                server.serve_forever()
            finally:
                server.server_close()
                worker_store._conn.close()
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        if not ready.wait(10):
            raise RuntimeError("Real HTTP server did not start")
        server = holder["server"]
        origin = f"http://127.0.0.1:{server.server_port}"

        def post(path, body, *, cookie=True, request_origin=None, form=False):
            headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
                       "Origin": request_origin or origin}
            if cookie:
                headers["Cookie"] = f"session={session.token}"
            payload = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
            request = urllib.request.Request(origin + path, data=payload, headers=headers)
            try:
                response = urllib.request.urlopen(request, timeout=10)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                payload = response.read()
                return response.status, (json.loads(payload) if "application/json" in response.headers.get("Content-Type", "")
                                         else payload.decode())

        try:
            status, _ = post("/diagnostics/iperf3/run", {"role": "server", "port": 49152}, cookie=False)
            assert status == 401, status
            status, _ = post("/diagnostics/iperf3/run", {"role": "server", "port": 49152}, request_origin="http://untrusted.invalid")
            assert status == 403, status
            options = {"iperf3": {"role": "server", "port": 49152}}
            status, result = post("/settings/diagnostics", options)
            assert status == 200 and "no network test" in result["detail"].lower(), result
            assert store.settings()["diagnostics"]["iperf3"]["port"] == 49152
            status, result = post("/diagnostics/iperf3/run", {"role": "client", "peer_address": "", "port": 49152})
            assert status == 422 and "peer" in result["detail"].lower(), result
            status, result = post("/diagnostics/iperf3/run", {"role": "client", "role__type": "str",
                                  "peer_address": "", "peer_address__type": "str", "port": "49993", "port__type": "int"}, form=True)
            assert status == 422 and "peer" in result.lower(), result
            print(json.dumps({"actual_http": True, "unauthenticated_refused": True, "cross_site_refused": True,
                              "options_saved_without_test": True, "missing_peer_refused": True,
                              "typed_manual_form_verified": True,
                              "scope": "actual HTTP/session/SQLite contracts; no active test or physical deployment"}))
        finally:
            server.shutdown()
            worker.join(timeout=5)
            sessions.sessions.clear()
            store._conn.close()


if __name__ == "__main__":
    verify()
