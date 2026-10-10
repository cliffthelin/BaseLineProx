"""Tests for scripts_inbox_gate.py - refuses to start the scripts inbox CRUD
server until the ACTIVE persona's USER_<PERSONA> volume is actually mounted,
so a script pushed before that lands on the real persistent volume rather
than silently writing through to the disposable substrate.

These previously asserted that a mount at the singular /mnt/USER satisfied
the gate. No persona install has that volume, so the real gate refused on
every boot and the unit's Restart=on-failure retried every 5 seconds
forever (2026-10-10 offline rehearsal)."""
import persist_bind_mounts as pbm
import scripts_inbox as si
import scripts_inbox_gate as sig
import scripts_inbox_web as siw


class FakeGateRunner:
    def __init__(self, mounts_text="", active_persona=None):
        self.mounts_text = mounts_text
        self.active_persona = active_persona

    def path_exists(self, path):
        return path == pbm.ACTIVE_PERSONA_MARKER_PATH and self.active_persona is not None

    def read_text(self, path):
        if path == pbm.ACTIVE_PERSONA_MARKER_PATH:
            return self.active_persona + "\n"
        assert path == "/proc/self/mounts"
        return self.mounts_text


def _mounted(path):
    return f"/dev/mapper/vg-x {path} ext4 rw,relatime 0 0\n"


def test_check_refuses_when_the_active_personas_volume_is_not_mounted():
    assert sig.check(FakeGateRunner(mounts_text="/dev/sda1 / ext4 rw 0 0\n")) == 1


def test_check_allows_when_the_default_personas_volume_is_mounted():
    """No marker yet = the default persona (admin)."""
    assert sig.check(FakeGateRunner(mounts_text=_mounted("/mnt/USER_ADMIN"))) == 0


def test_check_follows_the_active_persona_marker():
    runner = FakeGateRunner(mounts_text=_mounted("/mnt/USER_PERSONAL"), active_persona="personal")
    assert sig.check(runner) == 0
    runner = FakeGateRunner(mounts_text=_mounted("/mnt/USER_ADMIN"), active_persona="personal")
    assert sig.check(runner) == 1


def test_the_old_singular_user_mount_no_longer_satisfies_the_gate():
    """The pre-persona volume. A persona install never has it."""
    assert sig.check(FakeGateRunner(mounts_text=_mounted("/mnt/USER"))) == 1


def test_main_names_the_volume_and_persona_when_refusing(capsys):
    rc = sig.main(FakeGateRunner(mounts_text="/dev/sda1 / ext4 rw 0 0\n", active_persona="personal"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "/mnt/USER_PERSONAL" in err and "'personal'" in err and "not mounted" in err


def test_main_prints_nothing_when_allowing(capsys):
    assert sig.main(FakeGateRunner(mounts_text=_mounted("/mnt/USER_ADMIN"))) == 0
    assert capsys.readouterr().err == ""


def test_the_server_uses_exactly_the_volume_the_gate_checked():
    """Gate and server resolve paths from one function, so they cannot drift
    apart again the way the unit's hardcoded /mnt/USER did."""
    runner = FakeGateRunner(active_persona="personal")
    gate = si.active_persona_paths(runner)
    data_path, inbox_dir = siw.resolve_paths({}, runner=runner)
    assert data_path.startswith(gate["mountpoint"] + "/")
    assert inbox_dir.startswith(gate["mountpoint"] + "/")
    assert data_path == "/mnt/USER_PERSONAL/scripts-inbox-auth/store.json"


def test_the_server_never_falls_back_to_tmp_without_configuration():
    data_path, _ = siw.resolve_paths({}, runner=FakeGateRunner())
    assert not data_path.startswith("/tmp")


def test_explicit_environment_still_wins_for_development():
    env = {"BASELINE_SCRIPTS_INBOX_DATA": "/tmp/x/store.json", "BASELINE_SCRIPTS_INBOX_DIR": "/tmp/x/inbox"}
    assert siw.resolve_paths(env, runner=FakeGateRunner()) == ("/tmp/x/store.json", "/tmp/x/inbox")
