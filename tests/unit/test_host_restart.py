import pytest
from fake_runner import FakeRunner, FakeProc
import host_restart


def runner_for(session='User=1000\nName=cane\nActive=yes\nRemote=no\nType=wayland\n'):
    return FakeRunner(command_responses=[
        (lambda a: a[:2] == ['loginctl', 'list-sessions'], FakeProc(0, '2 1000 cane seat0 tty2\n')),
        (lambda a: a[:2] == ['loginctl', 'show-session'], FakeProc(0, session)),
        (lambda a: a == ['id', '-u'], FakeProc(0, '0\n')),
    ])


def test_restart_requests_native_confirmation_in_active_desktop():
    runner = runner_for()
    result = host_restart.request_restart(runner)
    assert result['outcome'] == 'confirmation_requested'
    assert runner.calls[-1] == ['runuser', '-u', 'cane', '--', 'env',
        'XDG_RUNTIME_DIR=/run/user/1000',
        'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus',
        'gnome-session-quit', '--reboot']
    assert not any('--force' in call or '--no-prompt' in call for call in runner.calls)


def test_missing_desktop_refuses_without_reboot_fallback():
    runner = runner_for('User=1000\nName=cane\nActive=yes\nRemote=yes\nType=tty\n')
    with pytest.raises(RuntimeError, match='one active local graphical session'):
        host_restart.request_restart(runner)
    assert not any('gnome-session-quit' in call or 'systemctl' in call for call in runner.calls)


def test_desktop_request_failure_is_an_error():
    runner = runner_for()
    runner.script(lambda a: a[0] == 'runuser', FakeProc(1, '', 'session bus unavailable'))
    with pytest.raises(RuntimeError, match='session bus unavailable'):
        host_restart.request_restart(runner)


def test_navigation_exposes_restart_request():
    import baseline_web
    nav = baseline_web.render_nav('/drive-admin')
    assert 'action="/host/restart"' in nav
    assert 'Restart host' in nav
    assert "referrerPolicy: 'same-origin'" in nav
    assert "credentials: 'same-origin'" in nav
