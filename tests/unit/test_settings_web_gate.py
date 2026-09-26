"""Unit tests for settings_web_gate.py - the ExecStartPre check that
refuses to launch the settings web UI until baseline-firstboot.service
has genuinely committed. Reuses firstboot_statemachine.already_completed()'s
existence-based, fail-closed discipline unchanged - never re-implements
its own notion of "done"."""
import settings_web_gate


def test_refuses_when_not_completed(tmp_path):
    rc = settings_web_gate.check(state_dir=tmp_path)
    assert rc == 1


def test_allows_when_completed(tmp_path):
    marker = tmp_path / "complete"
    marker.write_text("2026-01-01T00:00:00\n")
    rc = settings_web_gate.check(state_dir=tmp_path)
    assert rc == 0
