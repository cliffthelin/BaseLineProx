"""Real SQLite/settings contracts, without FakeRunner or mocked subprocesses."""
from pathlib import Path
from html.parser import HTMLParser

import config_pipeline
from repair import RealRunner
from settings_web import LocalAppStore, SystemSectionApplier
import settings_web


def test_saving_diagnostic_options_persists_without_running_a_network_test(tmp_path):
    store = LocalAppStore(Path(tmp_path) / "settings.sqlite")
    values = {"iperf3": {"role": "server", "port": 49152}}
    result = SystemSectionApplier(store, RealRunner()).apply("diagnostics", values)
    assert result.applied, result.detail
    assert "no network test" in result.detail.lower()
    assert store.settings()["diagnostics"]["iperf3"] == values["iperf3"]


def test_firstboot_skips_optional_network_test_without_an_explicit_run_request():
    summary = config_pipeline.apply_stored_config(
        RealRunner(), {"diagnostics": {"iperf3": {"role": "client", "peer_address": "", "port": 49152}}},
        network_interface="eno1")
    assert "iperf3" in summary["skipped"]
    assert "iperf3" not in summary["failed"]
    assert "iperf3" not in summary["applied"]


def test_explicit_client_run_without_a_peer_is_refused_instead_of_claiming_a_test(tmp_path):
    store = LocalAppStore(Path(tmp_path) / "settings.sqlite")
    result = SystemSectionApplier(store, RealRunner()).run_iperf3({"role": "client", "peer_address": "", "port": 49152})
    assert not result.applied
    assert "peer" in result.detail.lower()


def test_network_test_has_an_explicit_form_separate_from_option_autosave():
    class Forms(HTMLParser):
        forms = []
        def handle_starttag(self, tag, attrs):
            if tag == "form":
                self.forms.append(dict(attrs))
    page = settings_web.render_settings_page({"diagnostics": {"iperf3": {"role": "client", "port": 49993}}})
    parser = Forms()
    parser.feed(page.decode())
    run_forms = [form for form in parser.forms if form.get("action") == "/diagnostics/iperf3/run"]
    assert len(run_forms) == 1
    assert "data-autosave" not in run_forms[0]
    assert run_forms[0]["method"] == "post"


def test_network_test_action_refuses_an_unauthenticated_request(tmp_path):
    store = LocalAppStore(Path(tmp_path) / "settings.sqlite")
    result = settings_web.handle_iperf3_run(
        settings_web.SessionStore(), SystemSectionApplier(store, RealRunner()), "",
        {"role": "server", "port": 49152}, 0)
    assert result.status == 401
