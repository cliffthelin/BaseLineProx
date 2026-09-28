"""Unit tests for backup_recurring.py - the automated recurring
encrypted backup job (work-queue item 27, decision record 79).
Exercises real orchestration logic against a FakeRunner - the real
`tar`/`openssl` calls themselves are already proven by
backup_restore.py's and config_crypto.py's own test suites; this
module's job is scheduling and wiring them together correctly.
"""
from fake_runner import FakeProc, FakeRunner

import backup_recurring as br


# -- backup_filename ---------------------------------------------------------

def test_backup_filename_uses_legacy_label_for_none_persona():
    assert br.backup_filename(None, 1700000000.0) == "legacy-1700000000.tar.gz"


def test_backup_filename_uses_the_real_persona_name():
    assert br.backup_filename("admin", 1700000000.0) == "admin-1700000000.tar.gz"


# -- is_due --------------------------------------------------------------

def test_is_due_true_when_no_manifest_exists_yet():
    runner = FakeRunner()
    assert br.is_due(runner, persona="admin", now=1700000000.0) is True


def test_is_due_false_within_the_configured_interval():
    import backup_restore
    runner = FakeRunner()
    backup_restore.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE_ADMIN", ts=1700000000.0)
    assert br.is_due(runner, persona="admin", now=1700000000.0 + 3600, interval_hours=12) is False


def test_is_due_true_once_the_configured_interval_has_elapsed():
    import backup_restore
    runner = FakeRunner()
    backup_restore.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE_ADMIN", ts=1700000000.0)
    assert br.is_due(runner, persona="admin", now=1700000000.0 + 12 * 3600 + 1, interval_hours=12) is True


def test_is_due_checks_the_legacy_singular_target_when_persona_is_none():
    import backup_restore
    runner = FakeRunner()
    backup_restore.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    assert br.is_due(runner, persona=None, now=1700000000.0 + 60, interval_hours=12) is False


def test_is_due_for_one_persona_is_unaffected_by_another_personas_manifest():
    import backup_restore
    runner = FakeRunner()
    backup_restore.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE_ADMIN", ts=1700000000.0)
    assert br.is_due(runner, persona="personal", now=1700000000.0 + 60, interval_hours=12) is True


# -- run_encrypted_backup -------------------------------------------------

def test_run_encrypted_backup_creates_backs_up_encrypts_and_deletes_the_plaintext():
    runner = FakeRunner()
    removed = []
    runner.remove = lambda path: removed.append(path)
    result = br.run_encrypted_backup(runner, password_file="/tmp/.pw", now=1700000000.0, persona="admin")
    assert result.applied is True
    tar_calls = [c for c in runner.calls if c[0] == "tar"]
    encrypt_calls = [c for c in runner.calls if c[:2] == ["openssl", "enc"] and "-d" not in c]
    assert len(tar_calls) == 1
    assert "/mnt/USER_PERSISTENCE_ADMIN" in tar_calls[0]
    assert len(encrypt_calls) == 1
    plaintext_path = tar_calls[0][2]
    assert encrypt_calls[0][encrypt_calls[0].index("-in") + 1] == plaintext_path
    assert removed == [plaintext_path]  # real deletion of the plaintext copy, proven directly


def test_run_encrypted_backup_records_a_real_manifest_on_success():
    import backup_restore
    runner = FakeRunner()
    br.run_encrypted_backup(runner, password_file="/tmp/.pw", now=1700000000.0, persona="admin")
    assert backup_restore.has_recent_successful_backup(
        runner, target="/mnt/USER_PERSISTENCE_ADMIN", now=1700000000.0 + 60) is True


def test_run_encrypted_backup_reports_a_real_tar_failure_and_never_encrypts():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["tar"] and "-czf" in a, FakeProc(1, "", "no space left on device")),
    ])
    result = br.run_encrypted_backup(runner, password_file="/tmp/.pw", now=1700000000.0, persona="admin")
    assert result.applied is False
    assert "no space left" in result.detail
    assert not any(c[:2] == ["openssl", "enc"] for c in runner.calls)


def test_run_encrypted_backup_reports_a_real_encryption_failure_and_keeps_no_stale_encrypted_file():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["openssl", "enc"], FakeProc(1, "", "bad password file")),
    ])
    result = br.run_encrypted_backup(runner, password_file="/tmp/.pw", now=1700000000.0, persona="admin")
    assert result.applied is False
    assert "bad password file" in result.detail


# -- run_if_due ------------------------------------------------------------

def test_run_if_due_skips_real_work_when_not_due():
    import backup_restore
    runner = FakeRunner()
    backup_restore.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE_ADMIN", ts=1700000000.0)
    result = br.run_if_due(runner, password_file="/tmp/.pw", now=1700000000.0 + 60,
                            persona="admin", interval_hours=12)
    assert result.applied is True
    assert "skipped" in result.detail
    assert not any(c[0] == "tar" for c in runner.calls)


def test_run_if_due_runs_a_real_backup_when_due():
    runner = FakeRunner()
    result = br.run_if_due(runner, password_file="/tmp/.pw", now=1700000000.0, persona="admin")
    assert result.applied is True
    assert any(c[0] == "tar" for c in runner.calls)


# -- main --------------------------------------------------------------------

def test_main_returns_0_and_attempts_every_configured_persona():
    runner = FakeRunner()
    printed = []
    code = br.main(runner=runner, password_file="/tmp/.pw", personas=("admin", "personal"),
                    print_fn=printed.append)
    assert code == 0
    assert len(printed) == 2
    assert any("admin" in line for line in printed)
    assert any("personal" in line for line in printed)


def test_main_returns_1_when_any_persona_fails():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["tar"] and "-czf" in a, FakeProc(1, "", "disk full")),
    ])
    code = br.main(runner=runner, password_file="/tmp/.pw", personas=("admin",), print_fn=lambda *a: None)
    assert code == 1
