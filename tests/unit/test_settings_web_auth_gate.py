"""The standalone settings server (settings_web.py's own handler) gets the
same rule as baseline_web.py: nothing beyond the login screen without a
credential, recovery mode included. The /setup first-run routes are not
covered here - whether they stay open is an open decision."""
import http.client
import threading

import pytest
from fake_runner import FakeRunner

import settings_web as sw

GATED_GET = ["/recovery", "/admin", "/settings", "/api/export-config", "/no-such-route"]


@pytest.fixture
def server(tmp_path):
    runner = FakeRunner()
    srv = sw.build_real_server(bind_host="127.0.0.1", bind_port=0, data_path=tmp_path / "store.json", runner=runner)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    srv.runner = runner
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


def _request(server, method, path, cookie=None, body=b""):
    port = server.httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = f"session={cookie}"
    conn.request(method, path, body=body if method == "POST" else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    location = resp.getheader("Location")
    conn.close()
    return resp.status, location, data


@pytest.mark.parametrize("path", GATED_GET)
def test_unauthenticated_get_is_refused(server, path):
    status, location, _ = _request(server, "GET", path)
    assert status in (303, 401)
    if status == 303:
        assert location.endswith("/login")


def test_recovery_discovery_needs_a_login(server):
    status, _, body = _request(server, "GET", "/recovery")
    assert status != 200
    assert b"personas" not in body.lower()
    assert server.runner.calls == []


@pytest.mark.parametrize("path", ["/admin/elevate", "/settings/network", "/recovery/exit"])
def test_unauthenticated_post_is_refused(server, path):
    status, _, _ = _request(server, "POST", path, body=b"x=1")
    assert status in (303, 401, 404)
    assert status != 200
    assert server.runner.calls == []


def test_the_login_page_is_still_public(server):
    status, _, body = _request(server, "GET", "/login")
    assert status == 200 and b"password" in body.lower()


def test_a_valid_session_reaches_recovery(server):
    session = server.deps["sessions"].create("root", now=server.deps["clock"]())
    status, _, _ = _request(server, "GET", "/recovery", cookie=session.token)
    assert status == 200
