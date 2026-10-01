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


def test_a_login_alone_does_not_open_recovery(server):
    session = server.deps["sessions"].create("root", now=server.deps["clock"]())
    status, _, _ = _request(server, "GET", "/recovery", cookie=session.token)
    assert status == 401


# --- first-run account creation: only while there is no user data ---------

class _FakeStore:
    def __init__(self, has_data):
        self._has = has_data
        self.added = []

    def has_user_data(self):
        return self._has

    def add_user(self, username, hash_):
        self.added.append(username)

    def save_pending_account(self, username, hash_):
        pass

    def set_machine_passphrase_hash(self, hash_):
        self.passphrase_set = True

    def set_elevation_hash(self, hash_):
        self.elevation_set = True


def _with_store(server, has_data):
    server.deps["store"] = _FakeStore(has_data)
    server.deps["hasher"] = lambda pw: "hashed:" + pw
    return server.deps["store"]


def test_new_account_is_created_on_a_machine_with_no_user_data(server):
    store = _with_store(server, has_data=False)
    status, _, _ = _request(server, "POST", "/setup/new-account",
                            body=b"username=first&password=pw&passphrase=blue+heron&elevation_passphrase=key")
    assert status == 200 and store.added == ["first"] and store.passphrase_set and store.elevation_set


def test_new_account_is_refused_once_any_user_data_exists(server):
    store = _with_store(server, has_data=True)
    status, location, _ = _request(server, "POST", "/setup/new-account",
                                   body=b"username=second&password=pw&passphrase=x&elevation_passphrase=y")
    assert status in (303, 401, 403) and store.added == []


@pytest.mark.parametrize("path", ["/setup", "/setup/rebuild"])
def test_setup_pages_need_a_login_once_user_data_exists(server, path):
    _with_store(server, has_data=True)
    method = "GET" if path == "/setup" else "POST"
    status, location, _ = _request(server, method, path, body=b"x=1")
    assert status in (303, 401) and (location is None or location.endswith("/login"))


def test_setup_page_is_open_only_while_there_is_no_user_data(server):
    _with_store(server, has_data=False)
    status, _, _ = _request(server, "GET", "/setup")
    assert status == 200


def test_setup_is_closed_when_the_store_state_is_unknown(server):
    server.deps["store"] = None
    status, _, _ = _request(server, "GET", "/setup")
    assert status in (303, 401)


# --- recovery needs the root password or machine passphrase ---------------

def _logged_in(server):
    return server.deps["sessions"].create("root", now=server.deps["clock"]()).token


def test_recovery_with_only_a_login_shows_no_machine_state(server):
    token = _logged_in(server)
    status, _, body = _request(server, "GET", "/recovery", cookie=token)
    assert b"currently-mounted" not in body and b"Personas" not in body
    assert b"password" in body.lower()          # asks for the credential instead
    assert server.runner.calls == []


def test_recovery_exit_is_refused_without_the_recovery_credential(server):
    token = _logged_in(server)
    status, _, _ = _request(server, "POST", "/recovery/exit", cookie=token)
    assert status in (303, 401, 403)
    assert server.runner.calls == []


def test_a_wrong_recovery_credential_does_not_unlock(server):
    server.deps["recovery_verify_fn"] = lambda pw: pw == "right"
    token = _logged_in(server)
    _request(server, "POST", "/recovery/unlock", cookie=token, body=b"passphrase=wrong")
    status, _, body = _request(server, "GET", "/recovery", cookie=token)
    assert b"Personas" not in body


def test_the_right_recovery_credential_unlocks_recovery(server):
    server.deps["recovery_verify_fn"] = lambda pw: pw == "right"
    token = _logged_in(server)
    _request(server, "POST", "/recovery/unlock", cookie=token, body=b"passphrase=right")
    status, _, body = _request(server, "GET", "/recovery", cookie=token)
    assert status == 200 and b"Personas" in body


def test_unlocking_recovery_needs_a_login_first(server):
    server.deps["recovery_verify_fn"] = lambda pw: True
    status, location, _ = _request(server, "POST", "/recovery/unlock", body=b"passphrase=right")
    assert status in (303, 401)
    assert server.deps["recovery_store"].tickets == {}
