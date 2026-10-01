"""Nothing beyond the login screen without a credential (direct instruction,
2026-09-30): no guest user exists, and no setting can grant one access. Every
route except the login routes needs a valid session - GET and POST alike,
state-changing or read-only, and including recovery mode."""
import http.client

import pytest
from fake_runner import FakeRunner

import settings_web as sw
from test_baseline_web import _RealServerCase, _base_deps

GATED_GET = [
    "/hardware", "/installer-cache", "/app-isolation", "/recovery", "/setup",
    "/drive-admin", "/drive-admin/actions", "/master-config", "/api/detect",
    "/api/active-persona", "/api/export-config", "/admin", "/settings",
    "/no-such-route",
]
GATED_POST = ["/recovery/exit", "/drive-admin/action", "/api/backup", "/admin/elevate"]
PUBLIC = ["/", "/login"]


def _request(port, method, path, cookie=None, body=b""):
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


@pytest.fixture
def case():
    runner = FakeRunner()
    c = _RealServerCase(_base_deps(runner=runner))
    c.runner = runner
    yield c
    c.close()


@pytest.mark.parametrize("path", GATED_GET)
def test_unauthenticated_get_is_refused(case, path):
    status, location, body = _request(case.port, "GET", path)
    if path.startswith("/api/"):
        assert status == 401
    else:
        assert status == 303 and location.endswith("/login")
    assert b"serial" not in body.lower() and b"PCI" not in body


@pytest.mark.parametrize("path", GATED_POST)
def test_unauthenticated_post_is_refused_and_does_nothing(case, path):
    status, location, _ = _request(case.port, "POST", path, body=b"x=1")
    assert status in (303, 401)
    if status == 303:
        assert location.endswith("/login")
    assert case.runner.calls == []


def test_a_made_up_session_cookie_is_not_a_session(case):
    status, location, _ = _request(case.port, "GET", "/hardware", cookie="not-a-real-token")
    assert status == 303 and location.endswith("/login")


@pytest.mark.parametrize("path", PUBLIC)
def test_login_page_is_the_only_public_page(case, path):
    status, _, body = _request(case.port, "GET", path)
    assert status == 200 and b"password" in body.lower()


def test_a_valid_session_reaches_the_pages():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1700000000.0)
    c = _RealServerCase(_base_deps(sessions=sessions))
    try:
        for path in ("/hardware", "/installer-cache", "/app-isolation", "/recovery"):
            status, _, _ = _request(c.port, "GET", path, cookie=session.token)
            assert status == 200, path
    finally:
        c.close()


def test_an_expired_session_is_refused():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1.0)   # long expired against the fixed clock
    c = _RealServerCase(_base_deps(sessions=sessions))
    try:
        status, location, _ = _request(c.port, "GET", "/hardware", cookie=session.token)
        assert status == 303 and location.endswith("/login")
    finally:
        c.close()
