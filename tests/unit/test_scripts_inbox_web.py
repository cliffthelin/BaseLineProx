"""Tests for scripts_inbox_web.py - the auth-gated HTTP CRUD server for
scripts_inbox.py. Login-gated the same way settings_web.py already is
(PasswordVerifier/SessionStore/handle_login/FileBackedPasswordVerifier
all reused directly from settings_web.py, not duplicated) - a
deliberate difference from control_panel_web.py, which has no
authentication at all and is deliberately kept operator-invoked-only
for exactly that reason (decision record 65). This server is meant to
be reachable over the network (that's the whole point - a phone
pushing a script), so it must never repeat that gap.

Exercises the handle_* functions directly with a fake runner and a
real SessionStore/in-memory clock, not real sockets - the real HTTP
wiring is a thin pass-through, same discipline as every other web
module in this project.
"""
import scripts_inbox_web as siw
from settings_web import SessionStore


class FakeInboxRunner:
    def __init__(self):
        self.files = {}
        self.dirs = set()

    def makedirs(self, path):
        self.dirs.add(str(path))

    def listdir(self, path):
        prefix = str(path).rstrip("/") + "/"
        return [p[len(prefix):] for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix):]]

    def path_exists(self, path):
        return str(path) in self.files or str(path) in self.dirs

    def read_text(self, path):
        return self.files[str(path)]

    def write_text_atomic(self, path, content):
        self.files[str(path)] = content

    def remove(self, path):
        del self.files[str(path)]


def _logged_in_sessions(now=1000.0):
    sessions = SessionStore()
    session = sessions.create("root", now)
    return sessions, session.token


# -- handle_list --------------------------------------------------------

def test_handle_list_refuses_without_a_valid_session():
    r = FakeInboxRunner()
    sessions = SessionStore()
    result = siw.handle_list(r, sessions, "no-such-token", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "refused"
    assert result.status == 401


def test_handle_list_returns_scripts_for_an_authenticated_session():
    r = FakeInboxRunner()
    r.files["/inbox/a.sh"] = "echo a\n"
    sessions, token = _logged_in_sessions()
    result = siw.handle_list(r, sessions, token, 1000.0, inbox_dir="/inbox")
    assert result.outcome == "applied"
    assert result.body["scripts"] == ["a.sh"]


# -- handle_read --------------------------------------------------------

def test_handle_read_refuses_without_a_valid_session():
    r = FakeInboxRunner()
    sessions = SessionStore()
    result = siw.handle_read(r, sessions, "bad", "a.sh", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "refused"
    assert result.status == 401


def test_handle_read_returns_404_for_a_missing_script():
    r = FakeInboxRunner()
    sessions, token = _logged_in_sessions()
    result = siw.handle_read(r, sessions, token, "missing.sh", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "refused"
    assert result.status == 404


def test_handle_read_returns_content_for_an_authenticated_session():
    r = FakeInboxRunner()
    r.files["/inbox/a.sh"] = "echo hi\n"
    sessions, token = _logged_in_sessions()
    result = siw.handle_read(r, sessions, token, "a.sh", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "applied"
    assert result.body["content"] == "echo hi\n"


# -- handle_write --------------------------------------------------------

def test_handle_write_refuses_without_a_valid_session():
    r = FakeInboxRunner()
    sessions = SessionStore()
    result = siw.handle_write(r, sessions, "bad", "a.sh", "echo hi\n", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "refused"
    assert result.status == 401
    assert "/inbox/a.sh" not in r.files


def test_handle_write_creates_a_script_for_an_authenticated_session():
    r = FakeInboxRunner()
    sessions, token = _logged_in_sessions()
    result = siw.handle_write(r, sessions, token, "a.sh", "echo hi\n", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "applied"
    assert r.files["/inbox/a.sh"] == "echo hi\n"


def test_handle_write_refuses_an_unsafe_name_even_when_authenticated():
    r = FakeInboxRunner()
    sessions, token = _logged_in_sessions()
    result = siw.handle_write(r, sessions, token, "../evil.sh", "rm -rf /\n", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "refused"
    assert result.status == 400
    assert not any("evil" in k for k in r.files)


# -- handle_delete --------------------------------------------------------

def test_handle_delete_refuses_without_a_valid_session():
    r = FakeInboxRunner()
    r.files["/inbox/a.sh"] = "echo hi\n"
    sessions = SessionStore()
    result = siw.handle_delete(r, sessions, "bad", "a.sh", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "refused"
    assert result.status == 401
    assert "/inbox/a.sh" in r.files


def test_handle_delete_removes_a_script_for_an_authenticated_session():
    r = FakeInboxRunner()
    r.files["/inbox/a.sh"] = "echo hi\n"
    sessions, token = _logged_in_sessions()
    result = siw.handle_delete(r, sessions, token, "a.sh", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "applied"
    assert "/inbox/a.sh" not in r.files


def test_handle_delete_returns_404_for_a_missing_script():
    r = FakeInboxRunner()
    sessions, token = _logged_in_sessions()
    result = siw.handle_delete(r, sessions, token, "missing.sh", 1000.0, inbox_dir="/inbox")
    assert result.outcome == "refused"
    assert result.status == 404


# -- real server construction (no real socket opened in this test) -------

def test_build_real_server_wires_real_auth_and_real_runner(tmp_path):
    data_path = tmp_path / "store.json"
    inbox_dir = tmp_path / "inbox"
    httpd = siw.build_real_server(bind_host="127.0.0.1", bind_port=0,
                                   data_path=data_path, inbox_dir=str(inbox_dir))
    try:
        assert "verifier" in httpd.deps
        assert "sessions" in httpd.deps
        assert httpd.deps["inbox_dir"] == str(inbox_dir)
        # no seeded default account: nobody can log in until first-run setup creates one
        assert httpd.deps["verifier"].verify("root", "baseline") is False
        assert httpd.deps["verifier"].verify("root", "wrong") is False
    finally:
        httpd.server_close()
