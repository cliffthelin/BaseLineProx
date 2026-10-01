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
        for path in ("/hardware", "/installer-cache", "/app-isolation"):
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


# --- recovery needs the root password or machine passphrase ---------------

def _recovery_case(verify=lambda pw: pw == "right"):
    import admin_elevation
    sessions = sw.SessionStore()
    token = sessions.create("root", now=1700000000.0).token
    runner = FakeRunner()
    c = _RealServerCase(_base_deps(sessions=sessions, runner=runner,
                                   recovery_store=admin_elevation.ElevationStore(),
                                   recovery_verify_fn=verify))
    c.cookie, c.runner = token, runner
    return c


def test_recovery_with_only_a_login_shows_no_machine_state():
    c = _recovery_case()
    try:
        status, _, body = _request(c.port, "GET", "/recovery", cookie=c.cookie)
        assert b"currently-mounted" not in body and b"Personas" not in body
        assert b"password" in body.lower()
        assert c.runner.calls == []
    finally:
        c.close()


def test_recovery_exit_is_refused_without_the_recovery_credential():
    c = _recovery_case()
    try:
        status, location, _ = _request(c.port, "POST", "/recovery/exit", cookie=c.cookie)
        assert status in (303, 401, 403)
        assert c.runner.calls == []
    finally:
        c.close()


def test_a_wrong_recovery_credential_does_not_unlock():
    c = _recovery_case()
    try:
        _request(c.port, "POST", "/recovery/unlock", cookie=c.cookie, body=b"passphrase=wrong")
        _, _, body = _request(c.port, "GET", "/recovery", cookie=c.cookie)
        assert b"Personas" not in body
    finally:
        c.close()


def test_the_right_recovery_credential_unlocks_recovery():
    c = _recovery_case()
    try:
        _request(c.port, "POST", "/recovery/unlock", cookie=c.cookie, body=b"passphrase=right")
        status, _, body = _request(c.port, "GET", "/recovery", cookie=c.cookie)
        assert status == 200 and b"Personas" in body
    finally:
        c.close()


def test_unlocking_recovery_needs_a_login_first():
    c = _recovery_case(verify=lambda pw: True)
    try:
        status, _, _ = _request(c.port, "POST", "/recovery/unlock", body=b"passphrase=right")
        assert status in (303, 401)
        assert c.server.deps["recovery_store"].tickets == {}
    finally:
        c.close()


def test_the_elevation_store_does_not_open_recovery():
    """Admin elevation has its own (seeded-dev) passphrase; it must not unlock recovery."""
    import admin_elevation
    c = _recovery_case()
    try:
        elevation = admin_elevation.ElevationStore()
        elevation.grant(1700000000.0)
        c.server.deps["elevation_store"] = elevation
        _, _, body = _request(c.port, "GET", "/recovery", cookie=c.cookie)
        assert b"Personas" not in body
    finally:
        c.close()
