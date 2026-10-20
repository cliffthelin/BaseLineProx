"""Request Ubuntu/GNOME's native restart confirmation; never force a restart."""


def _run(runner, argv):
    proc = runner.run(argv, timeout=15)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or 'Restart request command failed')
    return proc.stdout.strip()


def request_restart(runner):
    sessions = _run(runner, ['loginctl', 'list-sessions', '--no-legend', '--no-pager'])
    desktops = []
    for line in sessions.splitlines():
        session_id = line.split()[0]
        properties = _run(runner, ['loginctl', 'show-session', session_id,
            '--property=User,Name,Active,Remote,Type'])
        values = dict(line.split('=', 1) for line in properties.splitlines() if '=' in line)
        if values.get('Active') == 'yes' and values.get('Remote') == 'no' and values.get('Type') in ('wayland', 'x11'):
            desktops.append(values)
    if len(desktops) != 1:
        raise RuntimeError('Restart requires exactly one active local graphical session; no restart was issued')
    desktop = desktops[0]
    uid, name = desktop.get('User', ''), desktop.get('Name', '')
    if not uid.isdecimal() or not name or name.startswith('-'):
        raise RuntimeError('Desktop session identity is invalid; no restart was issued')
    caller = _run(runner, ['id', '-u'])
    if caller not in ('0', uid):
        raise RuntimeError('The web service cannot reach the active desktop session; no restart was issued')
    command = ['env', 'XDG_RUNTIME_DIR=/run/user/' + uid,
        'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/' + uid + '/bus',
        'gnome-session-quit', '--reboot']
    if caller == '0':
        command = ['runuser', '-u', name, '--'] + command
    _run(runner, command)
    return {'outcome': 'confirmation_requested',
        'detail': 'Restart requested. Confirm or cancel in the Ubuntu desktop dialog.'}
