"""Remote-access status: read-only. Which ways in are up (SSH, Tailscale) and what is listening."""
import pytest
from fake_runner import FakeProc, FakeRunner

import remote_access as ra


def runner(answers):
    rules = [((lambda a, argv=list(argv): a[:len(argv)] == argv), proc) for argv, proc in answers.items()]
    return FakeRunner(command_responses=rules)


SS = ("State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
      "LISTEN 0      4096   0.0.0.0:22         0.0.0.0:*\n"
      "LISTEN 0      128    0.0.0.0:8100       0.0.0.0:*\n"
      "LISTEN 0      128    127.0.0.1:631      0.0.0.0:*\n"
      "LISTEN 0      128    [::]:22            [::]:*\n")


def test_reports_ssh_tailscale_and_listening_ports():
    r = runner({("systemctl", "is-active", "ssh.socket"): FakeProc(0, "active\n"),
                ("tailscale", "ip", "-4"): FakeProc(0, "100.115.151.9\n"),
                ("tailscale", "status"): FakeProc(0, "100.115.151.9 desktop cane@ linux -\n100.117.222.1 iphone cane@ iOS idle\n"),
                ("ss", "-ltn"): FakeProc(0, SS)})
    s = ra.collect(r)
    assert s["ssh"]["active"] is True
    assert s["tailscale"]["ip"] == "100.115.151.9" and s["tailscale"]["peers"] == 1
    assert {"0.0.0.0:22", "0.0.0.0:8100", "[::]:22"} <= {p["address"] for p in s["listening"]}
    assert s["warnings"] == []


def test_a_listener_on_a_port_other_than_ssh_and_the_web_app_is_called_out():
    r = runner({("ss", "-ltn"): FakeProc(0, SS + "LISTEN 0 128 0.0.0.0:23 0.0.0.0:*\n")})
    s = ra.collect(r)
    assert any("23" in w for w in s["warnings"])


def test_password_ssh_is_flagged(monkeypatch):
    r = runner({("sshd", "-T"): FakeProc(0, "passwordauthentication yes\npermitrootlogin yes\n")})
    s = ra.collect(r)
    assert any("password" in w.lower() for w in s["warnings"]) and any("root" in w.lower() for w in s["warnings"])


def test_missing_tools_are_reported_not_raised():
    class Broken(FakeRunner):
        def run(self, argv, timeout=10):
            raise FileNotFoundError(argv[0])
    s = ra.collect(Broken())
    assert s["ssh"]["active"] is None and s["tailscale"]["ip"] is None and s["listening"] == []


def test_nothing_is_ever_changed():
    r = runner({("ss", "-ltn"): FakeProc(0, SS)})
    ra.collect(r)
    allowed = {"systemctl", "tailscale", "ss", "sshd"}
    assert all(c[0] in allowed for c in r.calls)
    assert not any(a in c for c in r.calls for a in ("restart", "start", "stop", "enable", "disable", "set", "up", "down"))


# -- the page ----------------------------------------------------------------------

def _case(role="admin", status=None):
    import settings_web as sw
    from test_baseline_web import _RealServerCase, _base_deps
    from test_hitl_web import Clock
    clock = Clock()
    sessions = sw.SessionStore()
    sessions.create("someone", clock(), role=role)
    deps = _base_deps(sessions=sessions, clock=clock, remote_status=lambda: status or {
        "ssh": {"active": True}, "tailscale": {"ip": "100.1.2.3", "peers": 2},
        "listening": [{"address": "0.0.0.0:22", "port": "22"}], "warnings": ["SSH accepts passwords; key-only login is safer"]})
    return _RealServerCase(deps)


def test_the_page_shows_status_and_warnings_to_an_admin():
    case = _case()
    try:
        status, body = case.get("/remote-access")
        assert status == 200 and b"100.1.2.3" in body and b"0.0.0.0:22" in body and b"key-only" in body
    finally:
        case.close()


@pytest.mark.parametrize("role", ["operator", "bot:backup_offdrive", "bot:repair"])
def test_limited_logins_cannot_see_it(role):
    case = _case(role=role)
    try:
        assert case.get("/remote-access")[0] == 403
    finally:
        case.close()
