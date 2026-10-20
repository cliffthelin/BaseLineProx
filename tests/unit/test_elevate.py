import elevate

ENV = {"PATH": "/bin", "HOME": "/home/u", "BASELINE_DRIVES_FILE": "/x/d.json", "SECRET": "no"}


def test_already_root_does_nothing():
    assert elevate.elevation_argv(["s", "--a"], ENV, euid=0) is None


def test_graphical_session_uses_pkexec_and_carries_only_baseline_settings():
    cmd = elevate.elevation_argv(["s", "--a"], dict(ENV, DISPLAY=":0"), which=lambda n: "/usr/bin/" + n, euid=1000, python="py")
    assert cmd[0] == "pkexec" and cmd[-3:] == ["py", "s", "--a"]
    assert "BASELINE_DRIVES_FILE=/x/d.json" in cmd and not any("SECRET" in c for c in cmd)


def test_terminal_session_uses_sudo():
    cmd = elevate.elevation_argv(["s"], ENV, which=lambda n: "/usr/bin/" + n, euid=1000, python="py")
    assert cmd[0] == "sudo"


def test_nothing_installed_returns_none():
    assert elevate.elevation_argv(["s"], ENV, which=lambda n: None, euid=1000) is None
