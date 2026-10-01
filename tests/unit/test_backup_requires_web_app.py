"""The off-drive backup runs only when the web application asked for it."""
import pytest

import offdrive_backup as ob
import web_gate as wg
import web_origin_helper as woh


@pytest.fixture(autouse=True)
def _reset():
    wg.configure(None)
    yield
    wg.configure(None)


S = {("backups", "offdrive_destination"): "/mnt/x", ("backups", "offdrive_min_interval_hours"): 168}


def test_main_refuses_when_no_web_app_is_running_in_the_process():
    with pytest.raises(wg.NotFromWebApp):
        ob.main(get_setting=lambda g, k: S[(g, k)], print_fn=lambda l: None)


def test_run_backup_refuses_without_an_origin():
    woh.configured_gate()
    with pytest.raises(wg.NotFromWebApp):
        ob.run_backup(destination="/mnt/x", run=None, sources={}, now=1.0, allowed_serials=())


def test_an_origin_for_a_dry_run_cannot_make_a_real_backup():
    gate = woh.configured_gate()
    dry = woh.origin_for("backup_offdrive", {"dry_run": True, "force": False}, gate=gate)
    with pytest.raises(wg.NotFromWebApp):
        ob.run_backup(destination="/mnt/x", run=None, sources={}, now=1.0, allowed_serials=(),
                      dry_run=False, origin=dry)


def test_an_origin_for_another_operation_is_refused():
    gate = woh.configured_gate()
    other = woh.origin_for("backup_verify", {}, gate=gate)
    with pytest.raises(wg.NotFromWebApp):
        ob.main(get_setting=lambda g, k: S[(g, k)], print_fn=lambda l: None, origin=other)
