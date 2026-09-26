"""Unit tests for gui_session.py (Track B3) - Runner-injectable lifecycle
for a compositor+app session (start/stop/restart/is_running). Mirrors
drive_setup_install.py's already-proven InstallRunner/process pattern -
a FakeSessionRunner/FakeSessionProcess pair, no real subprocess."""
import gui_session as gs


class FakeSessionProcess:
    def __init__(self):
        self.alive = True
        self.killed = False

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.killed = True
        self.alive = False


class FakeSessionRunner(gs.SessionRunner):
    def __init__(self):
        self.spawned = []  # (argv, env)
        self.processes = []

    def spawn(self, argv, env=None):
        self.spawned.append((list(argv), dict(env or {})))
        proc = FakeSessionProcess()
        self.processes.append(proc)
        return proc


def test_start_spawns_the_given_command():
    runner = FakeSessionRunner()
    handle = gs.start(runner, name="kiosk", command=["cage", "--", "chromium"])
    assert runner.spawned == [(["cage", "--", "chromium"], {})]
    assert handle.name == "kiosk"


def test_start_passes_env_through():
    runner = FakeSessionRunner()
    gs.start(runner, name="kiosk", command=["cage"], env={"XDG_RUNTIME_DIR": "/run/cage-kiosk"})
    assert runner.spawned[0][1] == {"XDG_RUNTIME_DIR": "/run/cage-kiosk"}


def test_is_running_true_for_live_process():
    runner = FakeSessionRunner()
    handle = gs.start(runner, name="kiosk", command=["cage"])
    assert gs.is_running(handle) is True


def test_is_running_false_after_process_exits():
    runner = FakeSessionRunner()
    handle = gs.start(runner, name="kiosk", command=["cage"])
    handle.process.alive = False
    assert gs.is_running(handle) is False


def test_stop_kills_the_process():
    runner = FakeSessionRunner()
    handle = gs.start(runner, name="kiosk", command=["cage"])
    assert gs.stop(handle) is True
    assert handle.process.killed is True
    assert gs.is_running(handle) is False


def test_restart_stops_old_process_and_spawns_a_new_one():
    runner = FakeSessionRunner()
    handle = gs.start(runner, name="kiosk", command=["cage"])
    old_process = handle.process
    new_handle = gs.restart(runner, handle, command=["cage"])
    assert old_process.killed is True
    assert new_handle.process is not old_process
    assert gs.is_running(new_handle) is True
    assert len(runner.spawned) == 2
