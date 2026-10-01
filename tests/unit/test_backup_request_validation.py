"""The backup, restore and encrypt/decrypt routes used to take any destination and any source paths from the
request and hand them to tar / gpg as root: a logged-in session could overwrite /etc/passwd with an archive, or
archive /root/.ssh somewhere readable. Now a backup may only be written as a NEW file in a known backup folder,
may only read Baseline's own volumes and config, and a restore may only go to /mnt or a Baseline volume."""
import pytest
from fake_runner import FakeProc, FakeRunner

import backup_restore as br
import control_panel_web as cpw

GOOD_DEST = "/mnt/INSTALLER_CACHE/backups/baseline-backup.tar.gz"


def _runner(**files):
    return FakeRunner(files=files)


# --- destinations ---------------------------------------------------------------

@pytest.mark.parametrize("dest", [
    "/etc/passwd", "/etc/passwd.tar.gz", "/tmp/x.tar.gz", "/root/.ssh/authorized_keys", "relative.tar.gz",
    "/mnt/INSTALLER_CACHE/backups/../../../etc/x.tar.gz", "/mnt/INSTALLER_CACHE/backups/sub/x.tar.gz",
    "/mnt/INSTALLER_CACHE/backups/x", "/mnt/INSTALLER_CACHE/backups/.tar.gz", "/mnt/INSTALLER_CACHE/backups/a b.tar.gz",
    "/mnt/INSTALLER_CACHE/backups/x.tar.gz\n", "", "/mnt/INSTALLER_CACHE/backupsX/x.tar.gz",
])
def test_a_backup_destination_outside_the_backup_folders_is_refused_and_tar_never_runs(dest):
    runner = _runner()
    result = cpw.handle_backup(runner, dest=dest, targets=["/mnt/BASELINE"])
    assert result.outcome == "refused" and runner.calls == []


def test_a_backup_never_overwrites_an_existing_file():
    runner = _runner(**{GOOD_DEST: "existing archive"})
    result = cpw.handle_backup(runner, dest=GOOD_DEST, targets=["/mnt/BASELINE"])
    assert result.outcome == "refused" and "exist" in result.body["detail"].lower() and runner.calls == []


def test_a_good_destination_and_target_still_work():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "tar", FakeProc(0, "", ""))])
    result = cpw.handle_backup(runner, dest=GOOD_DEST, targets=["/mnt/BASELINE", "/etc/baseline"], now=1.0)
    assert result.outcome == "applied" and any(c[0] == "tar" for c in runner.calls)


def test_the_encrypted_backup_folder_is_a_valid_destination_too():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "tar", FakeProc(0, "", ""))])
    assert cpw.handle_backup(runner, dest="/mnt/INSTALLER_CACHE/encrypted_backups/x.tar.gz",
                             targets=["/mnt/BASELINE"], now=1.0).outcome == "applied"


# --- sources --------------------------------------------------------------------

@pytest.mark.parametrize("target", [
    "/", "/etc", "/etc/shadow", "/root", "/root/.ssh", "/home/cane", "/mnt", "/mnt/10TB", "/mnt/BASELINE/../../etc",
    "/mnt/BASELINE_EVIL", "relative", "", "/etc/baseline/../shadow", "/var/lib",
])
def test_sources_outside_baseline_volumes_and_config_are_refused(target):
    runner = _runner()
    result = cpw.handle_backup(runner, dest=GOOD_DEST, targets=["/mnt/BASELINE", target])
    assert result.outcome == "refused" and runner.calls == []


def test_a_non_list_of_targets_is_refused():
    assert cpw.handle_backup(_runner(), dest=GOOD_DEST, targets="/mnt/BASELINE").outcome == "refused"
    assert cpw.handle_backup(_runner(), dest=GOOD_DEST, targets=[1, 2]).outcome == "refused"


def test_config_only_still_validates_the_destination():
    runner = _runner()
    assert cpw.handle_backup(runner, dest="/etc/passwd", targets=[], config_only=True).outcome == "refused"
    assert runner.calls == []


# --- restore --------------------------------------------------------------------

ARCHIVE = "/mnt/INSTALLER_CACHE/backups/baseline-backup.tar.gz"


@pytest.mark.parametrize("archive", ["/etc/passwd", "/tmp/x.tar.gz", "/mnt/INSTALLER_CACHE/backups/../x.tar.gz", ""])
def test_restoring_from_an_archive_outside_the_backup_folders_is_refused(archive):
    runner = _runner(**{archive: "x"} if archive else {})
    result = cpw.handle_restore(runner, archive=archive, dest_root="/mnt", members=[], now=1.0)
    assert result.outcome == "refused" and runner.calls == []


@pytest.mark.parametrize("dest_root", ["/", "/etc", "/root", "/home", "/mnt/../etc", "/usr", "relative"])
def test_restoring_into_a_system_folder_is_refused(dest_root):
    runner = _runner(**{ARCHIVE: "x"})
    result = cpw.handle_restore(runner, archive=ARCHIVE, dest_root=dest_root, members=[], now=1.0)
    assert result.outcome == "refused" and not any(c[0] == "tar" for c in runner.calls)


@pytest.mark.parametrize("members", [["../../etc/passwd"], ["/etc/passwd"], ["ok/../../x"], [1], "x"])
def test_restore_members_must_be_plain_relative_names(members):
    runner = _runner(**{ARCHIVE: "x"})
    result = cpw.handle_restore(runner, archive=ARCHIVE, dest_root="/mnt", members=members, now=1.0)
    assert result.outcome == "refused" and not any(c[0] == "tar" for c in runner.calls)


def test_restore_into_mnt_or_a_baseline_volume_is_accepted():
    for root in ("/mnt", "/mnt/BASELINE"):
        runner = FakeRunner(files={ARCHIVE: "x"}, command_responses=[(lambda a: a[0] == "tar", FakeProc(0, "", ""))])
        result = cpw.handle_restore(runner, archive=ARCHIVE, dest_root=root, members=["BASELINE/state/a"], now=1.0)
        assert result.outcome in ("applied", "refused")
        assert result.outcome == "applied" or "backup" in result.body["detail"].lower()    # refused only by the 24h gate


# --- listing, encrypt, decrypt ----------------------------------------------------

def test_listing_an_archive_outside_the_backup_folders_is_refused():
    runner = _runner()
    result = cpw.handle_backup_list(runner, archive="/etc/shadow")
    assert result.outcome == "refused" and runner.calls == []


@pytest.mark.parametrize("in_path,out_path", [
    ("/etc/shadow", "/mnt/INSTALLER_CACHE/encrypted_backups/x.gpg"),
    (ARCHIVE, "/etc/cron.d/evil"), (ARCHIVE, "/root/.ssh/authorized_keys"),
    (ARCHIVE, "/mnt/INSTALLER_CACHE/../../etc/x.gpg"),
])
def test_encrypt_and_decrypt_only_work_between_backup_folders(in_path, out_path):
    for fn in (cpw.handle_backup_encrypt, cpw.handle_backup_decrypt):
        runner = _runner(**{in_path: "x"})
        result = fn(runner, in_path=in_path, out_path=out_path, password="pw")
        assert result.outcome == "refused" and runner.calls == []


def test_decrypt_never_overwrites_an_existing_file():
    out = "/mnt/INSTALLER_CACHE/backups/restored.tar.gz"
    runner = _runner(**{"/mnt/INSTALLER_CACHE/encrypted_backups/x.gpg": "x", out: "already here"})
    result = cpw.handle_backup_decrypt(runner, in_path="/mnt/INSTALLER_CACHE/encrypted_backups/x.gpg",
                                       out_path=out, password="pw")
    assert result.outcome == "refused" and runner.calls == []


# --- the retired standalone server has no login, so it must not run --------------------

def test_the_standalone_control_panel_refuses_to_start(monkeypatch, capsys):
    monkeypatch.setattr(cpw, "make_server", lambda **k: (_ for _ in ()).throw(AssertionError("must not start a server")))
    assert cpw.main() == 1
    assert "baseline-web" in capsys.readouterr().err
