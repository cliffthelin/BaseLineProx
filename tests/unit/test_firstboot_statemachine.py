"""Unit tests for firstboot_statemachine.py (Gate E) - the durable
completion-marker/journal wrapper around firstboot_network_repair.py's
already-real, already-tested discover/propose/CONFIRM/apply/verify flow.
Stubs firstboot_network_repair.run_first_boot_network_repair directly
(monkeypatch) so these tests exercise only this module's own logic -
the wrapped flow's own behavior is covered by
test_phase0_additive_repair.py's dedicated first-boot-wiring section."""
import json

import pytest

import firstboot_network_repair as fbnr
import firstboot_statemachine as fsm
from repair import RepairResult


class FakeRealRunner:
    """A minimal stand-in - this module never touches the Runner
    directly, it only passes it through to fbnr.run_first_boot_network_repair,
    which is stubbed in every test below."""
    pass


def test_first_run_with_nothing_to_do_commits_and_writes_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(fbnr, "run_first_boot_network_repair",
                         lambda *a, **k: {"action": "none", "reason": "lifeline already healthy",
                                           "package_install_allowed": True})
    result = fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["package_install_allowed"] is True
    assert (tmp_path / "complete").exists()
    assert (tmp_path / "journal.json").exists()


def test_confirmed_repair_commits_and_writes_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(fbnr, "run_first_boot_network_repair",
                         lambda *a, **k: {"action": "additive", "target": "vmbr0",
                                           "result": RepairResult(ok=True, attempt_id="x", outcome="success"),
                                           "package_install_allowed": True})
    result = fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["package_install_allowed"] is True
    assert (tmp_path / "complete").exists()


def test_declined_confirmation_does_not_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(fbnr, "run_first_boot_network_repair",
                         lambda *a, **k: {"action": "declined", "package_install_allowed": False})
    result = fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["package_install_allowed"] is False
    assert not (tmp_path / "complete").exists()


def test_refused_diagnosis_does_not_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(fbnr, "run_first_boot_network_repair",
                         lambda *a, **k: {"action": "refused", "reason": "ambiguous topology",
                                           "package_install_allowed": False})
    result = fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["package_install_allowed"] is False
    assert not (tmp_path / "complete").exists()


def test_verification_failure_does_not_commit_even_though_confirmed(tmp_path, monkeypatch):
    # A confirmed repair whose independent verification failed must not
    # be treated as a success - package_install_allowed is False, so no
    # marker is written, matching repair.py's own "verification is a
    # precondition, not confirmation alone" discipline.
    monkeypatch.setattr(fbnr, "run_first_boot_network_repair",
                         lambda *a, **k: {"action": "additive", "target": "vmbr0",
                                           "result": RepairResult(ok=False, attempt_id="x", outcome="refused"),
                                           "package_install_allowed": False})
    result = fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["package_install_allowed"] is False
    assert not (tmp_path / "complete").exists()


def test_completion_marker_prevents_rerun_without_calling_the_real_flow_again(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fbnr, "run_first_boot_network_repair",
                         lambda *a, **k: calls.append(1) or {"action": "none", "package_install_allowed": True})

    fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    assert len(calls) == 1

    result2 = fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    assert len(calls) == 1  # never called a second time
    assert result2["action"] == "already_completed"
    assert result2["package_install_allowed"] is True


def test_journal_accumulates_history_across_multiple_non_committing_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(fbnr, "run_first_boot_network_repair",
                         lambda *a, **k: {"action": "declined", "package_install_allowed": False})
    fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    fsm.run(FakeRealRunner(), state_dir=tmp_path, print_fn=lambda *a: None)
    history = json.loads((tmp_path / "journal.json").read_text())["history"]
    assert len(history) == 2


def test_already_completed_returns_none_when_no_marker(tmp_path):
    assert fsm.already_completed(tmp_path) is None


def test_already_completed_returns_timestamp_when_marker_present(tmp_path):
    fsm.mark_complete(tmp_path)
    completed_at = fsm.already_completed(tmp_path)
    assert completed_at is not None
    assert completed_at != ""


def test_mark_complete_is_durable_atomic_rename_no_stray_tmp_file(tmp_path):
    fsm.mark_complete(tmp_path)
    entries = list(tmp_path.iterdir())
    names = [e.name for e in entries]
    assert "complete" in names
    assert not any(n.startswith(".tmp-") for n in names)
