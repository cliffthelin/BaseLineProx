"""Web hardening shared by both web apps (baseline_web.py and the standalone settings_web.py):
security headers, a SameSite session cookie, cross-site request protection for POSTs, and rate limiting
on every endpoint that checks a password. The lockout is temporary and capped, never permanent: it must
not be able to brick access (the machine's console is unaffected)."""
import http.client
import threading

import pytest
from fake_runner import FakeRunner

import settings_web as sw
import web_security as ws
from test_baseline_web import _RealServerCase, _base_deps


# --- the cookie ---------------------------------------------------------------

def test_the_session_cookie_is_httponly_and_samesite_strict():
    cookie = ws.session_cookie("abc123")
    parts = [p.strip() for p in cookie.split(";")]
    assert parts[0] == "session=abc123"
    assert "HttpOnly" in parts and "SameSite=Strict" in parts and "Path=/" in parts


def test_clearing_the_cookie_uses_the_same_attributes_and_expires_it():
    cookie = ws.clear_session_cookie()
    assert "Max-Age=0" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie


# --- cross-site request protection --------------------------------------------

def _h(**kw):
    return {k.replace("_", "-"): v for k, v in kw.items()}


def test_a_same_origin_post_is_allowed():
    assert ws.origin_ok(_h(Origin="http://10.0.0.5:8100", Host="10.0.0.5:8100"), has_cookie=True) is True


def test_a_cross_origin_post_is_refused_even_without_a_cookie():
    assert ws.origin_ok(_h(Origin="http://evil.example", Host="10.0.0.5:8100"), has_cookie=False) is False
    assert ws.origin_ok(_h(Origin="http://evil.example", Host="10.0.0.5:8100"), has_cookie=True) is False


def test_a_post_with_a_session_cookie_but_no_origin_or_referer_is_refused():
    assert ws.origin_ok(_h(Host="10.0.0.5:8100"), has_cookie=True) is False


def test_a_post_with_no_cookie_and_no_origin_is_allowed_for_scripts_and_curl():
    assert ws.origin_ok(_h(Host="10.0.0.5:8100"), has_cookie=False) is True


def test_the_referer_is_accepted_when_origin_is_absent():
    assert ws.origin_ok(_h(Referer="http://10.0.0.5:8100/settings", Host="10.0.0.5:8100"), has_cookie=True) is True
    assert ws.origin_ok(_h(Referer="http://evil.example/x", Host="10.0.0.5:8100"), has_cookie=True) is False


def test_the_null_origin_is_refused():
    assert ws.origin_ok(_h(Origin="null", Host="10.0.0.5:8100"), has_cookie=True) is False


def test_a_lookalike_host_is_not_the_same_origin():
    assert ws.origin_ok(_h(Origin="http://10.0.0.5:8100.evil.example", Host="10.0.0.5:8100"), has_cookie=True) is False


# --- the rate limiter ---------------------------------------------------------

def test_a_few_failures_do_not_lock_anyone_out():
    lim = ws.AttemptLimiter()
    for _ in range(4):
        lim.failure("login", "1.2.3.4", now=1000.0)
    assert lim.check("login", "1.2.3.4", now=1000.0) == 0


def test_repeated_failures_lock_that_client_temporarily():
    lim = ws.AttemptLimiter(max_failures=5, base_lock_s=30)
    for _ in range(5):
        lim.failure("login", "1.2.3.4", now=1000.0)
    wait = lim.check("login", "1.2.3.4", now=1000.0)
    assert 0 < wait <= 30
    assert lim.check("login", "1.2.3.4", now=1000.0 + 31) == 0       # and it expires by itself


def test_other_clients_are_not_locked_by_one_clients_failures():
    lim = ws.AttemptLimiter(max_failures=5)
    for _ in range(5):
        lim.failure("login", "1.2.3.4", now=1000.0)
    assert lim.check("login", "9.9.9.9", now=1000.0) == 0


def test_scopes_are_independent():
    lim = ws.AttemptLimiter(max_failures=5)
    for _ in range(5):
        lim.failure("login", "1.2.3.4", now=1000.0)
    assert lim.check("recovery", "1.2.3.4", now=1000.0) == 0


def test_a_success_clears_the_failures():
    lim = ws.AttemptLimiter(max_failures=5)
    for _ in range(4):
        lim.failure("login", "1.2.3.4", now=1000.0)
    lim.success("login", "1.2.3.4", now=1000.0)
    for _ in range(4):
        lim.failure("login", "1.2.3.4", now=1001.0)
    assert lim.check("login", "1.2.3.4", now=1001.0) == 0


def test_repeat_offenders_wait_longer_but_never_more_than_the_cap():
    lim = ws.AttemptLimiter(max_failures=3, base_lock_s=30, max_lock_s=900)
    now, waits = 1000.0, []
    for _ in range(12):
        for _ in range(3):
            lim.failure("login", "1.2.3.4", now=now)
        wait = lim.check("login", "1.2.3.4", now=now)
        waits.append(wait)
        now += wait + 1
    assert waits[1] > waits[0] and max(waits) <= 900 and waits[-1] == 900


def test_old_failures_age_out():
    lim = ws.AttemptLimiter(max_failures=5, window_s=900)
    for _ in range(4):
        lim.failure("login", "1.2.3.4", now=1000.0)
    lim.failure("login", "1.2.3.4", now=1000.0 + 901)                  # the earlier four are outside the window
    assert lim.check("login", "1.2.3.4", now=1000.0 + 901) == 0


def test_a_flood_from_many_addresses_trips_a_global_lock_that_also_expires():
    lim = ws.AttemptLimiter(global_max_failures=20, global_lock_s=300)
    for i in range(20):
        lim.failure("login", f"10.0.0.{i}", now=1000.0)
    assert lim.check("login", "10.0.0.250", now=1000.0) > 0
    assert lim.check("login", "10.0.0.250", now=1000.0 + 301) == 0


def test_the_limiter_does_not_grow_without_bound():
    lim = ws.AttemptLimiter(max_tracked=100)
    for i in range(5000):
        lim.failure("login", f"10.{i // 250}.{i % 250}.1", now=1000.0 + i)
    assert lim.tracked() <= 100


# --- headers and CSRF, over real sockets (baseline_web) -----------------------

def _req(port, method, path, cookie=None, body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    if cookie:
        h["Cookie"] = f"session={cookie}"
    conn.request(method, path, body=body if method == "POST" else None, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    out = (resp.status, {k.lower(): v for k, v in resp.getheaders()}, data)
    conn.close()
    return out


def _web_case(**over):
    sessions = sw.SessionStore()
    token = sessions.create("root", now=1700000000.0).token
    c = _RealServerCase(_base_deps(sessions=sessions, runner=FakeRunner(), **over))
    c.cookie = token
    return c


REQUIRED_HEADERS = ("content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy",
                    "cache-control", "permissions-policy")


@pytest.mark.parametrize("path,authed", [("/login", False), ("/hardware", True), ("/hardware", False)])
def test_every_response_carries_the_security_headers(path, authed):
    c = _web_case()
    try:
        status, headers, _ = _req(c.port, "GET", path, cookie=c.cookie if authed else None)
        for name in REQUIRED_HEADERS:
            assert name in headers, f"{name} missing on {path} (status {status})"
        assert headers["x-content-type-options"] == "nosniff" and headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert "form-action 'self'" in headers["content-security-policy"]
        assert "no-store" in headers["cache-control"]
    finally:
        c.close()


def test_json_error_and_redirect_responses_also_carry_the_headers():
    c = _web_case()
    c.server.deps["verifier"] = type("V", (), {"verify": lambda self, u, p: False})()
    try:
        for method, path in (("GET", "/api/detect"), ("GET", "/settings"), ("POST", "/login")):
            _, headers, _ = _req(c.port, method, path, body=b"username=x&password=y",
                                 headers={"Origin": f"http://127.0.0.1:{c.port}"})
            assert "x-frame-options" in headers, (method, path)
    finally:
        c.close()


def test_the_session_cookie_set_at_login_is_samesite_strict():
    c = _web_case()
    c.server.deps["verifier"] = type("V", (), {"verify": lambda self, u, p: (u, p) == ("root", "pw")})()
    try:
        status, headers, _ = _req(c.port, "POST", "/login", body=b"username=root&password=pw",
                                  headers={"Origin": f"http://127.0.0.1:{c.port}"})
        assert status == 303 and "samesite=strict" in headers["set-cookie"].lower()
        assert "httponly" in headers["set-cookie"].lower()
    finally:
        c.close()


def test_a_cross_site_post_to_a_state_changing_route_is_refused_and_does_nothing():
    c = _web_case()
    try:
        status, _, _ = _req(c.port, "POST", "/drive-admin/action", cookie=c.cookie,
                            body=b'{"action_id":"repair","params":{"device_path":"/dev/sdb"}}',
                            headers={"Origin": "http://evil.example", "Content-Type": "application/json"})
        assert status == 403
        status, _, _ = _req(c.port, "POST", "/recovery/exit", cookie=c.cookie, headers={"Origin": "http://evil.example"})
        assert status == 403
    finally:
        c.close()


def test_a_cookie_post_with_no_origin_is_refused():
    c = _web_case()
    try:
        status, _, _ = _req(c.port, "POST", "/recovery/exit", cookie=c.cookie)
        assert status == 403
    finally:
        c.close()


def test_a_same_origin_post_still_works():
    c = _web_case()
    try:
        status, _, _ = _req(c.port, "POST", "/recovery/exit", cookie=c.cookie,
                            headers={"Origin": f"http://127.0.0.1:{c.port}"})
        assert status in (200, 303)
    finally:
        c.close()


# --- rate limiting over real sockets ------------------------------------------

def _bad_login(c, n):
    out = []
    for _ in range(n):
        out.append(_req(c.port, "POST", "/login", body=b"username=root&password=wrong",
                        headers={"Origin": f"http://127.0.0.1:{c.port}"})[0])
    return out


def test_repeated_bad_logins_are_throttled_with_retry_after():
    c = _web_case()
    c.server.deps["verifier"] = type("V", (), {"verify": lambda self, u, p: False})()
    try:
        statuses = _bad_login(c, 8)
        assert statuses[:5] == [401] * 5 and 429 in statuses[5:]
        status, headers, _ = _req(c.port, "POST", "/login", body=b"username=root&password=wrong",
                                  headers={"Origin": f"http://127.0.0.1:{c.port}"})
        assert status == 429 and int(headers["retry-after"]) > 0
    finally:
        c.close()


def test_a_correct_password_is_not_accepted_while_locked_out_so_there_is_no_oracle():
    c = _web_case()
    c.server.deps["verifier"] = type("V", (), {"verify": lambda self, u, p: p == "right"})()
    try:
        _bad_login(c, 6)
        status, _, _ = _req(c.port, "POST", "/login", body=b"username=root&password=right",
                            headers={"Origin": f"http://127.0.0.1:{c.port}"})
        assert status == 429
    finally:
        c.close()


def test_the_lockout_expires_and_the_right_password_then_works():
    now = {"t": 1700000000.0}
    c = _web_case()
    c.server.deps["clock"] = lambda: now["t"]
    c.server.deps["verifier"] = type("V", (), {"verify": lambda self, u, p: p == "right"})()
    try:
        _bad_login(c, 6)
        now["t"] += 1000                                                    # past the longest first lockout
        status, headers, _ = _req(c.port, "POST", "/login", body=b"username=root&password=right",
                                  headers={"Origin": f"http://127.0.0.1:{c.port}"})
        assert status == 303 and "session=" in headers["set-cookie"]
    finally:
        c.close()


def test_recovery_unlock_attempts_are_throttled_too():
    c = _web_case(recovery_store=__import__("admin_elevation").ElevationStore(), recovery_verify_fn=lambda s: False)
    try:
        statuses = [_req(c.port, "POST", "/recovery/unlock", cookie=c.cookie, body=b"passphrase=guess",
                         headers={"Origin": f"http://127.0.0.1:{c.port}"})[0] for _ in range(9)]
        assert 429 in statuses
    finally:
        c.close()


def test_admin_elevation_attempts_are_throttled_too():
    c = _web_case(elevation_store=__import__("admin_elevation").ElevationStore(), elevation_verify_fn=lambda s: False)
    try:
        statuses = [_req(c.port, "POST", "/admin/elevate", cookie=c.cookie, body=b"passphrase=guess",
                         headers={"Origin": f"http://127.0.0.1:{c.port}"})[0] for _ in range(9)]
        assert 429 in statuses
    finally:
        c.close()


def test_unlocking_recovery_with_the_right_credential_still_works_when_not_locked():
    c = _web_case(recovery_store=__import__("admin_elevation").ElevationStore(), recovery_verify_fn=lambda s: s == "right")
    try:
        _req(c.port, "POST", "/recovery/unlock", cookie=c.cookie, body=b"passphrase=right",
             headers={"Origin": f"http://127.0.0.1:{c.port}"})
        status, _, body = _req(c.port, "GET", "/recovery", cookie=c.cookie)
        assert status == 200 and b"Personas" in body
    finally:
        c.close()


# --- the standalone settings server gets the same protections ------------------

@pytest.fixture
def standalone(tmp_path):
    srv = sw.build_real_server(bind_host="127.0.0.1", bind_port=0, data_path=tmp_path / "s.db", runner=FakeRunner())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.deps["verifier"] = type("V", (), {"verify": lambda self, u, p: False})()
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


def test_the_standalone_server_sends_the_security_headers(standalone):
    port = standalone.httpd.server_address[1]
    _, headers, _ = _req(port, "GET", "/login")
    for name in REQUIRED_HEADERS:
        assert name in headers


def test_the_standalone_server_refuses_a_cross_site_post_and_throttles_logins(standalone):
    port = standalone.httpd.server_address[1]
    status, _, _ = _req(port, "POST", "/login", body=b"username=a&password=b", headers={"Origin": "http://evil.example"})
    assert status == 403
    statuses = [_req(port, "POST", "/login", body=b"username=a&password=b",
                     headers={"Origin": f"http://127.0.0.1:{port}"})[0] for _ in range(8)]
    assert 429 in statuses
