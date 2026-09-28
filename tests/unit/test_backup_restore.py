"""Unit tests for backup_restore.py - real, tar-based backup/restore of
the persistence volumes and/or the exported config, selectively.
No real tar is ever invoked - the FakeRunner records every argv.

Direct instruction covered here: "if the targeted drive is detected to
have a Baseline build... it should request to make a backup of the
being replaced persistence partitions / containers and wired in to
successful be able to do so... Backup can be selected to backup only
selected partition / containers or all and can be selected to only
back config. Restore options should align in the same way."
"""
from fake_runner import FakeProc, FakeRunner

import backup_restore as br


def test_backup_required_true_when_any_volume_found():
    assert br.backup_required({"found_volumes": ["baseline_user_persistence"], "missing_volumes": []}) is True


def test_backup_required_false_when_nothing_found():
    assert br.backup_required({"found_volumes": [], "missing_volumes": ["a", "b", "c"]}) is False


def test_backup_required_true_even_for_a_partial_existing_install():
    """A partial existing install still has real data worth
    protecting, not just a fully-provisioned one."""
    assert br.backup_required({"found_volumes": ["baseline_user_persistence"], "missing_volumes": ["x"]}) is True


def test_create_backup_argv_is_real_tar():
    argv = br.create_backup_argv("/mnt/INSTALLER_CACHE/backups/x.tar.gz", ["/mnt/USER_PERSISTENCE"])
    assert argv == ["tar", "-czf", "/mnt/INSTALLER_CACHE/backups/x.tar.gz", "/mnt/USER_PERSISTENCE"]


def test_create_backup_selected_targets_only():
    runner = FakeRunner()
    result = br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=["/mnt/USER_PERSISTENCE"])
    assert result.ok is True
    assert runner.calls[0] == ["tar", "-czf", "/tmp/x.tar.gz", "/mnt/USER_PERSISTENCE"]


def test_create_backup_all_persistence_targets():
    runner = FakeRunner()
    result = br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=br.all_persistence_targets())
    assert result.ok is True
    assert set(runner.calls[0][3:]) == {"/mnt/BASELINE", "/mnt/USER_PERSISTENCE_ADMIN", "/mnt/USER_PERSISTENCE_PERSONAL",
                                         "/mnt/INSTALLER_CACHE", "/mnt/SESSION_TEMP"}


def test_create_backup_config_only_ignores_any_targets_passed():
    runner = FakeRunner()
    result = br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=["/mnt/USER_PERSISTENCE"], config_only=True)
    assert result.ok is True
    assert runner.calls[0] == ["tar", "-czf", "/tmp/x.tar.gz"] + list(br.DEFAULT_CONFIG_PATHS)


def test_create_backup_refuses_when_no_targets_and_not_config_only():
    runner = FakeRunner()
    result = br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=[])
    assert result.ok is False
    assert runner.calls == []


def test_create_backup_reports_a_real_tar_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["tar"] and a[1] == "-czf", FakeProc(1, "", "tar: disk full")),
    ])
    result = br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=["/mnt/USER_PERSISTENCE"])
    assert result.ok is False
    assert "disk full" in result.detail


def test_list_backup_contents_parses_real_tar_listing():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["tar", "-tzf"], FakeProc(0, "USER_PERSISTENCE/\nUSER_PERSISTENCE/docs/\n", "")),
    ])
    contents = br.list_backup_contents(runner, "/tmp/x.tar.gz")
    assert contents == ["USER_PERSISTENCE/", "USER_PERSISTENCE/docs/"]


def test_list_backup_contents_empty_on_a_real_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["tar", "-tzf"], FakeProc(1, "", "not a tar archive")),
    ])
    assert br.list_backup_contents(runner, "/tmp/bad.tar.gz") == []


def test_restore_backup_creates_the_destination_root_first():
    """Real finding from an end-to-end smoke test: `tar -C dest`
    requires dest to already exist - it will not create it, and fails
    outright if it doesn't."""
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt/newdir", now=1700000000.0 + 60)
    assert runner.calls[0] == ["mkdir", "-p", "/mnt/newdir"]
    assert runner.calls[1] == ["tar", "-xzf", "/tmp/x.tar.gz", "-C", "/mnt/newdir"]


def test_restore_backup_extracts_everything_by_default():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=1700000000.0 + 60)
    assert result.ok is True
    assert runner.calls[-1] == ["tar", "-xzf", "/tmp/x.tar.gz", "-C", "/mnt"]


def test_restore_backup_supports_selective_members():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt",
                       members=["USER_PERSISTENCE/docs/"], now=1700000000.0 + 60)
    assert runner.calls[-1] == ["tar", "-xzf", "/tmp/x.tar.gz", "-C", "/mnt", "USER_PERSISTENCE/docs/"]


def test_restore_backup_reports_a_real_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["tar", "-xzf"], FakeProc(1, "", "unexpected end of file")),
    ])
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=1700000000.0 + 60)
    assert result.ok is False
    assert "unexpected end of file" in result.detail


def test_restore_never_invokes_any_decryption_mechanism():
    """Structural proof, not just a convention: restore_backup's
    module never imports config_crypto - decryption can only ever be
    a separate, explicit, password-gated step, never bundled into
    restore where it could bypass a real password/encryption. Checks
    the module's real code, with its own docstring (which discusses
    this design in prose) excluded from the check."""
    import ast
    import inspect

    import backup_restore
    assert not hasattr(backup_restore, "config_crypto")

    source = inspect.getsource(backup_restore)
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree) or ""
    code_without_module_docstring = source.replace(docstring, "", 1)
    assert "import config_crypto" not in code_without_module_docstring
    assert "password" not in code_without_module_docstring.lower()


# --------------------------------------------------------------------------
# Backup-freshness proof and the restore hard gate (decision record 74) -
# "never overwriting the user persistence unless there is valid proof
# of it being backed up successfully within 24 hours." Unconditional,
# not a caller-opt-in flag: any restore that would touch
# USER_PERSISTENCE (named in members, or an unconstrained restore-
# everything) refuses outright without a fresh manifest.
# --------------------------------------------------------------------------

def test_record_backup_manifest_then_read_returns_it():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    manifest = br.read_backup_manifest(runner, target="/mnt/USER_PERSISTENCE")
    assert manifest == {"target": "/mnt/USER_PERSISTENCE", "ts": 1700000000.0}


def test_read_backup_manifest_returns_none_when_never_recorded():
    runner = FakeRunner()
    assert br.read_backup_manifest(runner, target="/mnt/USER_PERSISTENCE") is None


def test_has_recent_successful_backup_true_within_window():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    assert br.has_recent_successful_backup(runner, target="/mnt/USER_PERSISTENCE", now=1700000000.0 + 3600) is True


def test_has_recent_successful_backup_false_once_older_than_24h():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    now = 1700000000.0 + 86400 + 1
    assert br.has_recent_successful_backup(runner, target="/mnt/USER_PERSISTENCE", now=now) is False


def test_has_recent_successful_backup_false_when_never_recorded():
    runner = FakeRunner()
    assert br.has_recent_successful_backup(runner, target="/mnt/USER_PERSISTENCE", now=1700000000.0) is False


def test_has_recent_successful_backup_false_for_a_different_targets_manifest():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/BASELINE", ts=1700000000.0)
    assert br.has_recent_successful_backup(runner, target="/mnt/USER_PERSISTENCE", now=1700000000.0 + 60) is False


def test_create_backup_records_a_manifest_per_target_when_now_is_given():
    runner = FakeRunner()
    br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=["/mnt/USER_PERSISTENCE", "/mnt/BASELINE"], now=1700000000.0)
    assert br.has_recent_successful_backup(runner, target="/mnt/USER_PERSISTENCE", now=1700000000.0) is True
    assert br.has_recent_successful_backup(runner, target="/mnt/BASELINE", now=1700000000.0) is True


def test_create_backup_records_no_manifest_when_now_is_omitted():
    runner = FakeRunner()
    br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=["/mnt/USER_PERSISTENCE"])
    assert br.read_backup_manifest(runner, target="/mnt/USER_PERSISTENCE") is None


def test_create_backup_records_no_manifest_when_tar_itself_fails():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["tar"], FakeProc(1, "", "disk full")),
    ])
    br.create_backup(runner, dest_path="/tmp/x.tar.gz", targets=["/mnt/USER_PERSISTENCE"], now=1700000000.0)
    assert br.read_backup_manifest(runner, target="/mnt/USER_PERSISTENCE") is None


def test_restore_refuses_unconstrained_restore_without_a_fresh_manifest():
    """Unconstrained restore (members=None) conservatively counts as
    touching USER_PERSISTENCE - fails safe, not open by default."""
    runner = FakeRunner()
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=1700000000.0)
    assert result.ok is False
    assert "no proof" in result.detail.lower() or "backup" in result.detail.lower()
    assert not any(c[0] == "tar" and c[1] == "-xzf" for c in runner.calls)


def test_restore_refuses_selective_user_persistence_members_without_a_fresh_manifest():
    runner = FakeRunner()
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt",
                                members=["USER_PERSISTENCE/docs/"], now=1700000000.0)
    assert result.ok is False
    assert not any(c[0] == "tar" and c[1] == "-xzf" for c in runner.calls)


def test_restore_refuses_when_now_is_not_given_at_all():
    """Never silently skip the freshness check because a caller forgot
    a parameter - fail closed."""
    runner = FakeRunner()
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt")
    assert result.ok is False
    assert not any(c[0] == "tar" and c[1] == "-xzf" for c in runner.calls)


def test_restore_allows_unconstrained_restore_with_a_fresh_manifest():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=1700000000.0 + 60)
    assert result.ok is True
    assert runner.calls[-1] == ["tar", "-xzf", "/tmp/x.tar.gz", "-C", "/mnt"]


def test_restore_allows_selective_user_persistence_members_with_a_fresh_manifest():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt",
                                members=["USER_PERSISTENCE/docs/"], now=1700000000.0 + 60)
    assert result.ok is True


def test_restore_refuses_with_a_stale_manifest_older_than_24h():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    stale_now = 1700000000.0 + 86400 + 1
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=stale_now)
    assert result.ok is False


def test_restore_with_explicit_persistence_targets_checks_that_targets_manifest_instead():
    """decision record 79: a persona-scoped backup's manifest is never
    recorded under the legacy singular USER_PERSISTENCE path - a
    caller restoring a real persona's archive must be able to point
    the freshness check at that persona's own mountpoint."""
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE_PERSONAL", ts=1700000000.0)
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=1700000000.0 + 60,
                                persistence_targets=["/mnt/USER_PERSISTENCE_PERSONAL"])
    assert result.ok is True


def test_restore_with_explicit_persistence_targets_still_refuses_without_a_fresh_one():
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)  # a different target's manifest
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=1700000000.0 + 60,
                                persistence_targets=["/mnt/USER_PERSISTENCE_PERSONAL"])
    assert result.ok is False


def test_restore_omitting_persistence_targets_still_checks_the_legacy_singular_target():
    """Backward compatibility: persistence_targets=None (the default)
    reproduces the pre-existing behavior byte-for-byte."""
    runner = FakeRunner()
    br.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt", now=1700000000.0 + 60)
    assert result.ok is True


def test_restore_of_non_user_persistence_members_does_not_require_a_manifest():
    """The hard gate is scoped to USER_PERSISTENCE specifically - a
    restore that only touches, say, BASELINE members is unaffected."""
    runner = FakeRunner()
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt",
                                members=["BASELINE/some-app-state"], now=1700000000.0)
    assert result.ok is True
