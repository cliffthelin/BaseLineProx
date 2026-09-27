"""Tests for scripts_inbox_gate.py - refuses to start the scripts
inbox CRUD server until USER_PERSISTENCE is actually mounted, so a
script pushed before that lands on the real persistent volume rather
than silently writing through to the disposable substrate
(persist_bind_mounts.ensure_redirect's own established concern,
applied here to the scripts-inbox server's own dependency on the same
mountpoint)."""
import scripts_inbox_gate as sig


class FakeGateRunner:
    def __init__(self, mounts_text=""):
        self.mounts_text = mounts_text

    def read_text(self, path):
        assert path == "/proc/self/mounts"
        return self.mounts_text


def test_check_refuses_when_user_persistence_not_mounted():
    runner = FakeGateRunner(mounts_text="/dev/sda1 / ext4 rw 0 0\n")
    assert sig.check(runner) == 1


def test_check_allows_when_user_persistence_is_mounted():
    runner = FakeGateRunner(mounts_text="/dev/sdd2 /mnt/USER_PERSISTENCE ext4 rw,relatime 0 0\n")
    assert sig.check(runner) == 0


def test_main_prints_a_clear_reason_when_refusing(capsys):
    runner = FakeGateRunner(mounts_text="/dev/sda1 / ext4 rw 0 0\n")
    rc = sig.main(runner)
    assert rc == 1
    captured = capsys.readouterr()
    assert "USER_PERSISTENCE" in captured.err
    assert "not mounted" in captured.err


def test_main_prints_nothing_when_allowing(capsys):
    runner = FakeGateRunner(mounts_text="/dev/sdd2 /mnt/USER_PERSISTENCE ext4 rw,relatime 0 0\n")
    rc = sig.main(runner)
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
