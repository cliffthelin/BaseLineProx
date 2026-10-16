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
