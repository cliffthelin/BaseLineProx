"""System shutdown and restart from the browser (operator, 2026-10-14: the GUI "needs to support system Shutdown and Restart").

Driven through the real HTTP server with a real session. The runner is the only fake, because the real commands would power off the machine
running the tests. What is proved is the exact command, that it needs a session and an explicit confirmation, and that nothing a person types
can change the command."""
import pytest

import power_control
from test_new_web_routes import case, req  # noqa: F401  (case is a pytest fixture)


class Done:
    returncode = 0
    stdout = ""
    stderr = ""


class Runner:
    def __init__(self):
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        return Done()


@pytest.fixture
def runner(case):  # noqa: F811
    r = Runner()
    case.server.deps["power_runner"] = r  # type: ignore[attr-defined]
    case.server.deps["audit"] = lambda event: r.calls.append(["audit", event["event"], event.get("action")])  # type: ignore[attr-defined]
    return r


def test_the_two_actions_map_to_fixed_commands_and_nothing_else():
    assert power_control.action_argv("poweroff") == ["systemctl", "poweroff"]
    assert power_control.action_argv("reboot") == ["systemctl", "reboot"]
    for bad in ("", "halt", "poweroff; reboot", "../reboot", None, "REBOOT"):
        with pytest.raises(ValueError):
            power_control.action_argv(bad)  # type: ignore[arg-type]


def test_the_page_needs_a_session_and_offers_both_actions_with_a_confirmation(case, runner):  # noqa: F811
    status, location, _ = req(case, "GET", "/power", cookie=False)
    assert status == 303 and location.endswith("/login")
    status, _, page = req(case, "GET", "/power")
    assert status == 200
    assert 'action="/power/poweroff"' in page and 'action="/power/reboot"' in page
    assert page.count('name="confirm"') == 2
    assert runner.calls == []                       # looking at the page never runs anything


def test_without_a_session_nothing_runs(case, runner):  # noqa: F811
    assert req(case, "POST", "/power/poweroff", {"confirm": "yes"}, cookie=False)[0] in (303, 401)
    assert runner.calls == []


def test_without_the_confirmation_nothing_runs_and_the_page_says_so(case, runner):  # noqa: F811
    for action in ("poweroff", "reboot"):
        status, location, _ = req(case, "POST", f"/power/{action}", {})
        assert status == 303 and location.startswith("/power?notice=")
    assert not any(c[0] == "systemctl" for c in runner.calls)


def test_confirmed_shutdown_and_restart_run_exactly_the_fixed_command_and_are_audited(case, runner):  # noqa: F811
    status, _, page = req(case, "POST", "/power/poweroff", {"confirm": "yes"})
    assert status == 200 and "shutting down" in page.lower()
    status, _, page = req(case, "POST", "/power/reboot", {"confirm": "yes"})
    assert status == 200 and "restarting" in page.lower()
    assert ["systemctl", "poweroff"] in runner.calls and ["systemctl", "reboot"] in runner.calls
    assert ["audit", "power_action", "poweroff"] in runner.calls and ["audit", "power_action", "reboot"] in runner.calls


def test_an_unknown_action_is_refused_and_runs_nothing(case, runner):  # noqa: F811
    status, _, _ = req(case, "POST", "/power/halt", {"confirm": "yes"})
    assert status in (303, 404)
    assert not any(c[0] == "systemctl" for c in runner.calls)


def test_a_failing_command_is_reported_not_claimed_done(case, runner):  # noqa: F811
    class Failed(Done):
        returncode = 1
        stderr = "Failed to connect to bus"
    runner.run = lambda argv, **kw: Failed()         # type: ignore[method-assign]
    status, location, _ = req(case, "POST", "/power/reboot", {"confirm": "yes"})
    assert status == 303 and "Failed" in location.replace("+", " ")


def test_power_is_in_the_navigation_and_on_the_home_page(case):  # noqa: F811
    _, _, page = req(case, "GET", "/hardware")
    assert 'href="/power"' in page
    _, _, home = req(case, "GET", "/home")
    assert 'href="/power"' in home
