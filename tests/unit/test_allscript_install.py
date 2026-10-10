"""baseline-allscript-install: the script's own decisions (stage order, confirmation, drive refusal, NIC naming).

Everything else it does is sequencing existing, separately tested modules; their behaviour is not re-tested here.
"""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "baseline" / "bin" / "baseline-allscript-install"
_loader = importlib.machinery.SourceFileLoader("allscript", str(_PATH))
_spec = importlib.util.spec_from_loader("allscript", _loader)
allscript = importlib.util.module_from_spec(_spec)
_loader.exec_module(allscript)


def test_stages_run_in_the_fixed_order_and_from_resumes_there():
    assert allscript.select_stages(None, None) == list(allscript.STAGES)
    assert allscript.select_stages(None, "cache") == list(allscript.STAGES)[allscript.STAGES.index("cache"):]
    assert allscript.select_stages("kiosk", None) == ["kiosk"]
    # the rehearsal is never part of the real run, and continues through first boot in its own session
    assert "rehearse" not in allscript.select_stages(None, None)
    assert allscript.select_stages("rehearse", None) == ["rehearse", "firstboot", "kiosk"]


def test_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        allscript.select_stages("format-everything", None)
    with pytest.raises(ValueError):
        allscript.select_stages(None, "nope")


def test_wipe_needs_the_exact_typed_phrase_for_that_serial():
    assert allscript.confirmation_ok("WIPE MD89N41071210AP4E", "MD89N41071210AP4E")
    assert allscript.confirmation_ok("  WIPE MD89N41071210AP4E\n", "MD89N41071210AP4E")
    for typed in ("wipe MD89N41071210AP4E", "WIPE", "yes", "", "WIPE FD01N6557110C271B", "WIPE MD89N41071210AP4"):
        assert not allscript.confirmation_ok(typed, "MD89N41071210AP4E")


def test_the_wipe_flag_must_name_pc401_exactly():
    assert allscript.wipe_authorized("MD89N41071210AP4E")
    for value in ("", "FD01N6557110C271B", "md89n41071210ap4e", "MD89N41071210AP4E ", "yes"):
        assert not allscript.wipe_authorized(value)


def test_the_protected_drive_can_never_be_the_target():
    with pytest.raises(RuntimeError):
        allscript.refuse_protected({"path": "/dev/sdb", "serial": "X"}, {"path": "/dev/sdb", "serial": "Y"})
    with pytest.raises(RuntimeError):
        allscript.refuse_protected({"path": "/dev/sdc", "serial": "FD01N6557110C271B"}, None)
    allscript.refuse_protected({"path": "/dev/sdc", "serial": "MD89N41071210AP4E"}, {"path": "/dev/sdb", "serial": "FD01N6557110C271B"})


def test_package_proxy_is_from_the_maintained_source_tree():
    repo = _PATH.parents[2]
    assert allscript.PROXY == repo / "baseline" / "lib" / "installer_package_proxy.py"
    assert allscript.PROXY.is_file()
