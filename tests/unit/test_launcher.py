"""The single Baseline launcher: opens the web application, starting its service first if needed. It never runs
anything but 'start the Baseline web service' and 'open the page'; every action happens inside the web application."""
import launcher as lc


class Env:
    def __init__(self, up=(False,), installed=True, start_ok=True):
        self.up, self.installed, self.start_ok = list(up), installed, start_ok
        self.started, self.opened, self.messages, self.sleeps = 0, [], [], []
        self.t = 0.0

    def probe(self, url):
        return self.up.pop(0) if len(self.up) > 1 else self.up[0]

    def is_installed(self):
        return self.installed

    def start(self):
        self.started += 1
        return self.start_ok

    def opener(self, url):
        self.opened.append(url)

    def notify(self, text):
        self.messages.append(text)

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s

    def clock(self):
        return self.t


def go(env, **kw):
    return lc.launch(probe=env.probe, is_installed=env.is_installed, start_service=env.start, open_page=env.opener,
                     notify=env.notify, sleep=env.sleep, clock=env.clock, **kw)


def test_when_the_app_is_already_up_it_just_opens_the_page():
    env = Env(up=(True,))
    assert go(env) == 0
    assert env.started == 0 and env.opened == [lc.URL]


def test_when_it_is_down_the_service_is_started_then_the_page_opens_once_it_answers():
    env = Env(up=(False, False, True))
    assert go(env) == 0
    assert env.started == 1 and env.opened == [lc.URL]


def test_it_gives_up_with_a_message_if_the_app_never_answers():
    env = Env(up=(False,))
    assert go(env) == 1
    assert env.opened == [] and env.messages and "did not start" in env.messages[-1]
    assert env.t <= lc.WAIT_S + 5


def test_if_the_service_is_not_installed_the_app_is_still_started_and_opened():
    env = Env(up=(False, True), installed=False)
    assert go(env) == 0
    assert env.started == 1 and env.opened == [lc.URL]


def test_a_refused_start_is_reported():
    env = Env(up=(False,), start_ok=False)
    assert go(env) == 1 and env.opened == [] and env.messages


def test_the_url_is_the_local_web_app_only():
    assert lc.URL == "http://127.0.0.1:8100/"


def test_the_entry_point_the_desktop_file_and_provisioning_agree():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    desktop = (root / "packaging" / "baseline-launcher" / "baseline.desktop").read_text()
    assert "Exec=/opt/baseline/bin/baseline-launcher" in desktop and "Icon=baseline" in desktop
    assert (root / "packaging" / "baseline-launcher" / "baseline.svg").exists()
    assert (root / "baseline" / "bin" / "baseline-launcher").stat().st_mode & 0o111
    provision = (root / "boot" / "provision.sh").read_text()
    for needle in ("baseline/bin/baseline-launcher", "baseline/lib/launcher.py", "baseline.desktop", "baseline.svg"):
        assert needle in provision


def test_the_launcher_only_starts_the_service_and_opens_the_page():
    import inspect
    source = inspect.getsource(lc)
    assert source.count("subprocess.run([pkexec") == 1 and 'systemctl", "start", SERVICE' in source
    for banned in ("stop", "restart", "enable", "mkfs", "wipefs", "rm "):
        assert f'"{banned}"' not in source


def test_state_dir_falls_back_to_the_users_own_directory_when_the_system_one_is_not_writable(tmp_path):
    import baseline_web as bw
    system = tmp_path / "sys"
    system.mkdir()
    home_env = {"HOME": str(tmp_path / "home")}
    assert bw.resolve_state_dir(home_env, system_dir=system, writable=lambda p: True) == system
    got = bw.resolve_state_dir(home_env, system_dir=system, writable=lambda p: False)
    assert got == tmp_path / "home" / ".local" / "share" / "baseline"
    assert bw.resolve_state_dir({**home_env, "BASELINE_STATE_DIR": "/x/y"}, system_dir=system,
                                writable=lambda p: True) == __import__("pathlib").Path("/x/y")
