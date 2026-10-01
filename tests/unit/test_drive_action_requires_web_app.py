"""A drive action needs two independent proofs: the web app asked (signed origin) AND a person confirmed."""
import pytest
from fake_runner import FakeRunner
from test_drive_admin import FakePdsRunner

import drive_admin as da
import web_origin_helper as woh
from hitl_helpers import authorize

PDS = lambda: FakePdsRunner(serial="MD89N41071210AP4E")  # noqa: E731
PARAMS = {"device_path": "/dev/sdb"}


def test_a_human_confirmation_alone_is_not_enough():
    woh.configured_gate()
    auth, store = authorize("repair", PARAMS, pds_runner=PDS())
    runner = FakeRunner()
    result = da.perform_action(runner, "repair", PARAMS, pds_runner=PDS(), authorization=auth, hitl_store=store)
    assert result.ok is False and "web application" in result.detail and runner.calls == []


def test_a_signed_origin_alone_is_not_enough():
    woh.configured_gate()
    prepared = da.prepare_action("repair", PARAMS, pds_runner=PDS())
    origin = woh.origin_for("drive_action", {"action_id": "repair", "params": prepared["params"]})
    runner = FakeRunner()
    result = da.perform_action(runner, "repair", PARAMS, pds_runner=PDS(), origin=origin)
    assert result.ok is False and "human confirmation" in result.detail and runner.calls == []


def test_an_origin_for_a_different_action_or_drive_is_refused():
    gate = woh.configured_gate()
    auth, store = authorize("repair", PARAMS, pds_runner=PDS())
    wrong = woh.origin_for("drive_action", {"action_id": "mount_volume", "params": {"device_path": "/dev/sdb"}}, gate=gate)
    runner = FakeRunner()
    result = da.perform_action(runner, "repair", PARAMS, pds_runner=PDS(), authorization=auth, hitl_store=store, origin=wrong)
    assert result.ok is False and runner.calls == []


def test_with_no_web_app_in_the_process_nothing_runs():
    import web_gate
    auth, store = authorize("repair", PARAMS, pds_runner=PDS())      # (this helper configures a test gate...)
    web_gate.configure(None)                                           # ...which a plain script would not have
    runner = FakeRunner()
    result = da.perform_action(runner, "repair", PARAMS, pds_runner=PDS(), authorization=auth, hitl_store=store, origin=None)
    assert result.ok is False and runner.calls == []


@pytest.mark.parametrize("call", [
    lambda cpw, r: cpw.handle_backup(r, dest="/mnt/INSTALLER_CACHE/backups/x.tar.gz", targets=["/mnt/BASELINE"], now=1.0),
    lambda cpw, r: cpw.handle_restore(r, archive="/mnt/INSTALLER_CACHE/backups/x.tar.gz", dest_root="/mnt", members=[], now=1.0),
    lambda cpw, r: cpw.handle_update(r, categories={}),
])
def test_the_control_panel_handlers_refuse_without_a_web_origin(call):
    import control_panel_web as cpw
    woh.configured_gate()
    runner = FakeRunner()
    result = call(cpw, runner)
    assert result.outcome == "refused" and result.status in (403, 422)
    assert not any(c[0] in ("tar", "gpg") for c in runner.calls)
