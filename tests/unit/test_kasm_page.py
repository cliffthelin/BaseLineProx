"""The Workspaces page (Kasm on this machine): real HTTP server and session, Kasm's machine and systemctl replaced by small fakes."""
import pytest

import kasm_setup as ks
from test_baseline_web import _RealServerCase, _base_deps
from test_new_web_routes import req


class Machine:
    def __init__(self, status=None, error=None):
        self._status, self._error = status or {"present": False, "installed": False}, error

    def status(self):
        if self._error:
            raise self._error
        return self._status


class Runner:
    def __init__(self, returncode=0):
        self.calls, self.returncode = [], returncode

    def run(self, argv, **_kw):
        self.calls.append(argv)
        return type("R", (), {"returncode": self.returncode, "stdout": "", "stderr": "no unit"})()


def make(machine, runner=None):
    audit = []
    return _RealServerCase(_base_deps(kasm_machine=machine, kasm_runner=runner or Runner(), audit=audit.append)), audit


def test_a_machine_with_no_kasm_offers_to_set_it_up_and_says_where_things_live():
    case, _ = make(Machine())
    try:
        assert req(case, "GET", "/workspaces", cookie=False)[0] == 303
        status, _, page = req(case, "GET", "/workspaces")
        assert status == 200 and "Not set up yet" in page and "/workspaces/setup" in page
        for place in ("APPDATA_ADMIN", "APPDATA_PERSONAL", "SESSION_TEMP"):
            assert place in page
        assert "Browser (personal)" in page and "not fully open source" in page
    finally:
        case.close()


def test_a_running_kasm_links_to_its_address_and_no_longer_offers_to_build_it():
    case, _ = make(Machine({"present": True, "installed": True, "running": True, "url": "https://192.168.1.50"}))
    try:
        page = req(case, "GET", "/workspaces")[2]
        assert "Running" in page and 'href="https://192.168.1.50"' in page and "/workspaces/setup" not in page
    finally:
        case.close()


def test_a_vm_still_being_installed_says_so():
    case, _ = make(Machine({"present": True, "installed": False, "running": True, "url": None}))
    try:
        assert "Setting up" in req(case, "GET", "/workspaces")[2]
    finally:
        case.close()


def test_a_state_that_cannot_be_read_is_shown_not_a_crash():
    case, _ = make(Machine(error=ks.KasmSetupError("pvesh failed")))
    try:
        status, _, page = req(case, "GET", "/workspaces")
        assert status == 200 and "could not be read" in page
    finally:
        case.close()


def test_setting_up_starts_the_service_without_waiting_and_is_audited():
    runner = Runner()
    case, audit = make(Machine(), runner)
    try:
        status, location, _ = req(case, "POST", "/workspaces/setup", {})
        assert status == 303 and location.startswith("/workspaces?notice=")
        assert runner.calls == [["systemctl", "start", "--no-block", "baseline-kasm-setup.service"]]
        assert {"event": "kasm_setup_requested"} in audit
        assert req(case, "POST", "/workspaces/setup", {}, cookie=False)[0] in (303, 401)
    finally:
        case.close()


def test_the_page_is_linked_from_navigation_and_home():
    case, _ = make(Machine())
    try:
        assert 'href="/workspaces"' in req(case, "GET", "/hardware")[2] and 'href="/workspaces"' in req(case, "GET", "/home")[2]
    finally:
        case.close()


def test_the_page_lists_the_workspaces_the_base_carries_when_it_says_so():
    case, _ = make(Machine({"present": False, "installed": False, "workspaces": [{"friendly_name": "My Browser", "persistent": True}, {"friendly_name": "Scratch", "persistent": False}]}))
    try:
        page = req(case, "GET", "/workspaces")[2]
        assert "My Browser" in page and "its profile is kept" in page and "Scratch" in page and "nothing is kept" in page
        assert "Development desktop" not in page                                    # the default set is shown only when the base does not say
    finally:
        case.close()


STATUS = {"present": True, "installed": True, "running": True, "url": "https://10.0.0.5", "mode": "persist"}


def test_the_page_offers_the_run_mode_and_removing_the_vm_with_the_data_kept():
    case, _ = make(Machine(STATUS))
    try:
        page = req(case, "GET", "/workspaces")[2]
        assert 'value="persist" checked' in page and 'value="reset"' in page and "Keep everything" in page and "Reset at every start" in page
        assert "/workspaces/dehydrate" in page and "Nothing is deleted" in page
        assert "sits over all of these" in page
    finally:
        case.close()


def test_a_removed_vm_is_shown_as_removed_with_its_data_kept_and_can_be_rebuilt():
    case, _ = make(Machine({"present": False, "installed": True, "dehydrated": True, "mode": "reset"}))
    try:
        page = req(case, "GET", "/workspaces")[2]
        assert "Removed (its data is kept)" in page and "Rebuild the VM" in page and "same address" in page
        assert "/workspaces/mode" not in page                                     # nothing to change while there is no VM
    finally:
        case.close()


def test_changing_the_mode_runs_the_command_as_its_own_unit_only_with_a_valid_mode_and_confirmation():
    runner = Runner()
    case, audit = make(Machine(STATUS), runner)
    try:
        assert req(case, "POST", "/workspaces/mode", {"mode": "reset"})[0] == 303 and runner.calls == []              # no confirmation: nothing runs
        req(case, "POST", "/workspaces/mode", {"mode": "snapshot", "confirm": "yes"})
        assert runner.calls == []                                                                                    # not a mode: nothing runs
        status, location, _ = req(case, "POST", "/workspaces/mode", {"mode": "reset", "confirm": "yes"})
        assert status == 303 and location.startswith("/workspaces?notice=")
        assert runner.calls == [["systemd-run", "--no-block", "--unit=baseline-kasm-action", "/opt/baseline/bin/baseline-kasm", "mode", "reset"]]
        assert {"event": "kasm_mode_requested", "mode": "reset"} in audit
        assert req(case, "POST", "/workspaces/mode", {"mode": "reset", "confirm": "yes"}, cookie=False)[0] in (303, 401) and len(runner.calls) == 1
    finally:
        case.close()


def test_removal_needs_the_confirmation_and_passes_the_yes_the_command_requires():
    runner = Runner()
    case, audit = make(Machine(STATUS), runner)
    try:
        req(case, "POST", "/workspaces/dehydrate", {})
        assert runner.calls == []
        req(case, "POST", "/workspaces/dehydrate", {"confirm": "yes"})
        assert runner.calls == [["systemd-run", "--no-block", "--unit=baseline-kasm-action", "/opt/baseline/bin/baseline-kasm", "dehydrate", "--yes"]]
        assert {"event": "kasm_dehydrate_requested"} in audit
    finally:
        case.close()


def test_the_page_says_which_components_are_in_the_base_and_which_nothing_here_uses():
    import kasm_recipe
    import kasm_build
    recipe = kasm_recipe.summary(kasm_recipe.default(kasm_build.WORKSPACES))
    case, _ = make(Machine({"present": False, "installed": False, "recipe": recipe}))
    try:
        page = req(case, "GET", "/workspaces")[2]
        assert "What this Kasm is built from" in page and "server-connections</b> (carried, not used)" in page and "database</b> (required)" in page
        assert "network</b> plugin (carried, not used)" in page
    finally:
        case.close()


def test_the_page_shows_what_the_history_suggests_and_the_settings_that_changed_with_their_values():
    report = {"suggestions": [{"id": "more-memory", "severity": "warning", "title": "Give the VM more memory (6144 MB to 9216 MB)", "evidence": ["memory stalls reached 30%"],
                               "benefit": "fewer stalls", "action": {"memory_mb": 9216}}],
              "errors": [], "launches": {}, "setting_changes": [{"name": "log_retention", "changes": 2, "last_old": "7", "last_new": "14", "secret": False},
                                                              {"name": "hec_token", "changes": 1, "last_old": None, "last_new": None, "secret": True}]}

    class WithReport(Machine):
        def telemetry_report(self):
            return report
    case, _ = make(WithReport(STATUS))
    try:
        page = req(case, "GET", "/workspaces")[2]
        assert "What the history suggests" in page and "6144 MB to 9216 MB" in page and "Benefit: fewer stalls" in page
        assert "log_retention</b> changed 2 time(s); last: 7 to 14" in page and "a secret (its value is not kept)" in page
    finally:
        case.close()


def test_a_machine_with_no_history_shows_no_report_section():
    case, _ = make(Machine(STATUS))
    try:
        assert "What the history suggests" not in req(case, "GET", "/workspaces")[2]
    finally:
        case.close()


def test_the_open_link_appears_only_when_kasm_itself_answers():
    import kasm_page
    base = {"present": True, "installed": True, "running": True, "url": "https://10.0.0.9", "mode": "persist"}
    starting = kasm_page.render(dict(base, ready=False)).decode()
    assert "Open Kasm" not in starting and "not answering yet" in starting and "http-equiv='refresh'" in starting
    ready = kasm_page.render(dict(base, ready=True)).decode()
    assert 'href="https://10.0.0.9"' in ready and "Kasm is ready" in ready and "http-equiv='refresh'" not in ready
    assert "Open Kasm" in kasm_page.render(base).decode()                    # a status that does not say keeps the earlier behaviour
