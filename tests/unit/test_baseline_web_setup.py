"""First-run setup on the deployed app (v0.2 row 49): setting the machine
passphrase. It sits behind the normal login (an open page would let whoever
reaches a fresh machine first set its recovery passphrase) and works only
while no passphrase is set. Only a one-way hash is stored."""
import http.client

import pytest
from fake_runner import FakeRunner

import admin_elevation
import settings_web as sw
from test_baseline_web import _RealServerCase, _base_deps


class _Store:
    def __init__(self):
        self.hash = None

    def has_user_data(self):
        return self.hash is not None

    def get_machine_passphrase_hash(self):
        return self.hash

    def set_machine_passphrase_hash(self, h):
        self.hash = h


class _Source:
    def current_settings(self):
        return {"network": {"hostname": "baseline"}}


def _request(port, method, path, cookie=None, body=b""):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = f"session={cookie}"
    if method == "POST":
        headers.setdefault("Origin", f"http://127.0.0.1:{port}")      # a browser always sends Origin on a POST
    conn.request(method, path, body=body if method == "POST" else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    location = resp.getheader("Location")
    conn.close()
    return resp.status, location, data


@pytest.fixture
def app():
    store = _Store()
    sessions = sw.SessionStore()
    token = sessions.create("root", now=1700000000.0).token
    c = _RealServerCase(_base_deps(
        sessions=sessions, store=store, runner=FakeRunner(),
        source=_Source(), elevation_store=admin_elevation.ElevationStore(),
        recovery_store=admin_elevation.ElevationStore(),
        recovery_verify_fn=sw.AnyCredentialVerifier(sw.MachinePassphraseVerifier(store), lambda s: False)))
    c.store, c.cookie = store, token
    yield c
    c.close()


def test_the_setup_page_needs_a_login(app):
    status, location, _ = _request(app.port, "GET", "/setup")
    assert status == 303 and location.endswith("/login")


def test_setting_the_passphrase_needs_a_login(app):
    status, location, _ = _request(app.port, "POST", "/setup/machine-passphrase", body=b"passphrase=blue+heron")
    assert status in (303, 401)
    assert app.store.hash is None


def test_the_setup_page_offers_the_form_while_no_passphrase_is_set(app):
    status, _, body = _request(app.port, "GET", "/setup", cookie=app.cookie)
    assert status == 200 and b'name="passphrase"' in body and b"/setup/machine-passphrase" in body


def test_setting_the_passphrase_stores_only_a_one_way_hash(app):
    status, location, _ = _request(app.port, "POST", "/setup/machine-passphrase",
                                   cookie=app.cookie, body=b"passphrase=blue+heron+42")
    assert status == 303
    assert app.store.hash.startswith("$6$") and "blue heron" not in app.store.hash
    assert sw.MachinePassphraseVerifier(app.store)("blue heron 42") is True
    assert sw.MachinePassphraseVerifier(app.store)("blue heron 43") is False


def test_the_passphrase_then_unlocks_recovery_end_to_end(app):
    _request(app.port, "POST", "/setup/machine-passphrase", cookie=app.cookie, body=b"passphrase=blue+heron+42")
    _request(app.port, "POST", "/recovery/unlock", cookie=app.cookie, body=b"passphrase=blue+heron+42")
    status, _, body = _request(app.port, "GET", "/recovery", cookie=app.cookie)
    assert status == 200 and b"Personas" in body


def test_an_empty_passphrase_is_refused_and_nothing_is_stored(app):
    _request(app.port, "POST", "/setup/machine-passphrase", cookie=app.cookie, body=b"passphrase=")
    assert app.store.hash is None


def test_a_second_attempt_cannot_replace_an_existing_passphrase(app):
    _request(app.port, "POST", "/setup/machine-passphrase", cookie=app.cookie, body=b"passphrase=first-one")
    first = app.store.hash
    _request(app.port, "POST", "/setup/machine-passphrase", cookie=app.cookie, body=b"passphrase=attacker-two")
    assert app.store.hash == first
    assert sw.MachinePassphraseVerifier(app.store)("attacker-two") is False


def test_the_setup_page_says_so_once_a_passphrase_is_set(app):
    app.store.hash = sw._sha512crypt("x", "saltsalt")
    status, _, body = _request(app.port, "GET", "/setup", cookie=app.cookie)
    assert status == 200 and b'name="passphrase"' not in body and b"already set" in body


def test_without_a_store_setup_refuses_instead_of_crashing():
    sessions = sw.SessionStore()
    token = sessions.create("root", now=1700000000.0).token
    c = _RealServerCase(_base_deps(sessions=sessions, store=None))
    try:
        status, _, _ = _request(c.port, "POST", "/setup/machine-passphrase", cookie=token, body=b"passphrase=abc")
        assert status in (303, 409, 503)
    finally:
        c.close()


def test_the_notice_in_the_query_string_is_escaped_not_reflected(app):
    status, _, body = _request(app.port, "GET", "/setup?notice=%3Cscript%3Ealert(1)%3C/script%3E", cookie=app.cookie)
    assert status == 200
    assert b"<script>alert(1)</script>" not in body
    assert b"&lt;script&gt;" in body


def test_the_redirect_after_setting_encodes_its_notice(app):
    status, location, _ = _request(app.port, "POST", "/setup/machine-passphrase", cookie=app.cookie,
                                   body=b"passphrase=blue+heron+42")
    assert status == 303 and " " not in location


# --- every page that shows a `notice` must escape it ------------------------

PAYLOAD = "%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E"
RAW = b"<img src=x onerror=alert(1)>"


@pytest.mark.parametrize("path", ["/admin", "/recovery", "/settings", "/setup"])
def test_a_notice_query_value_is_never_reflected_as_markup(app, path):
    # recovery shows its notice only once unlocked; give it the credential first
    _request(app.port, "POST", "/setup/machine-passphrase", cookie=app.cookie, body=b"passphrase=blue+heron+42")
    _request(app.port, "POST", "/recovery/unlock", cookie=app.cookie, body=b"passphrase=blue+heron+42")
    status, _, body = _request(app.port, "GET", f"{path}?notice={PAYLOAD}", cookie=app.cookie)
    assert RAW not in body


def test_the_drive_admin_banner_escapes_its_notice():
    import baseline_web as bw
    page = bw.render_drive_admin_page(drives=[], volumes=[], actions=[], notice="<img src=x onerror=alert(1)>",
                                      notice_ok=True)
    assert RAW not in page and b"&lt;img" in page


def test_the_login_error_and_setup_and_recovery_renderers_escape():
    for html_bytes in (sw.render_login_page("<img src=x onerror=alert(1)>"),
                       sw.render_setup_page("account", "<img src=x onerror=alert(1)>"),
                       sw.render_recovery_page({}, "<img src=x onerror=alert(1)>"),
                       sw.render_recovery_locked_page("<img src=x onerror=alert(1)>")):
        assert RAW not in html_bytes
