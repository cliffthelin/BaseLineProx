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
    assert set(runner.calls[0][3:]) == {"/mnt/BASELINE", "/mnt/USER_PERSISTENCE", "/mnt/INSTALLER_CACHE", "/mnt/SESSION_TEMP"}


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
    br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt/newdir")
    assert runner.calls[0] == ["mkdir", "-p", "/mnt/newdir"]
    assert runner.calls[1] == ["tar", "-xzf", "/tmp/x.tar.gz", "-C", "/mnt/newdir"]


def test_restore_backup_extracts_everything_by_default():
    runner = FakeRunner()
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt")
    assert result.ok is True
    assert runner.calls[-1] == ["tar", "-xzf", "/tmp/x.tar.gz", "-C", "/mnt"]


def test_restore_backup_supports_selective_members():
    runner = FakeRunner()
    br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt",
                       members=["USER_PERSISTENCE/docs/"])
    assert runner.calls[-1] == ["tar", "-xzf", "/tmp/x.tar.gz", "-C", "/mnt", "USER_PERSISTENCE/docs/"]


def test_restore_backup_reports_a_real_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["tar", "-xzf"], FakeProc(1, "", "unexpected end of file")),
    ])
    result = br.restore_backup(runner, archive_path="/tmp/x.tar.gz", dest_root="/mnt")
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
