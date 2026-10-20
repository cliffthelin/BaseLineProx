"""Standalone RAM-only AI launcher; also installed inside granted guests."""
import base64
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import sys

RUNTIME = '/run/baseline-ai'


def install(profile, *, account=None, runtime=RUNTIME, launcher='/usr/local/bin/baseline-ai-run', source=None, history_root=None):
    """Receiver executes as guest root; credentials belong only to the selected guest user."""
    if account:
        owner = pwd.getpwnam(account)
    else:
        candidates = [p for p in pwd.getpwall() if p.pw_uid == 1100]
        if not candidates:
            candidates = [p for p in pwd.getpwall() if p.pw_name == 'kasm-user']
        if not candidates:
            candidates = [p for p in pwd.getpwall() if 1000 <= p.pw_uid < 65534 and p.pw_shell.endswith(('/bash', '/sh', '/zsh', '/fish'))]
        if not candidates:
            candidates = [pwd.getpwnam('root')]  # root-only system containers
        if len(candidates) != 1:
            raise ValueError('select a guest account: no unique managed owner was found')
        owner = candidates[0]
    base = Path(runtime)
    if base.is_symlink():
        raise ValueError('AI runtime directory is redirected')
    base.mkdir(mode=0o755, parents=True, exist_ok=True)
    root = base / str(owner.pw_uid)
    if root.is_symlink():
        raise ValueError('AI runtime account directory is redirected')
    root.mkdir(mode=0o700, exist_ok=True)
    # Only root or this account may refresh its runtime profile.
    if root.stat().st_uid not in (0, owner.pw_uid):
        raise ValueError('AI runtime account directory belongs to another account')
    os.chmod(root, 0o700)
    target = root / 'profile.json'
    if target.is_symlink():
        raise ValueError('AI runtime profile is redirected')
    temporary = root / 'profile.new'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    if os.geteuid() == 0:
        os.fchown(fd, owner.pw_uid, owner.pw_gid)
    with os.fdopen(fd, 'w') as stream:
        json.dump(profile, stream)
    os.replace(temporary, target)
    if os.geteuid() == 0:
        os.chown(root, owner.pw_uid, owner.pw_gid)
    if history_root is not None:
        location = root / 'history-location.json'
        if location.is_symlink():
            raise ValueError('history metadata is redirected')
        import tempfile
        fd, staged = tempfile.mkstemp(prefix='.history-location-', dir=root)
        try:
            os.fchmod(fd, 0o600)
            if os.geteuid() == 0:
                os.fchown(fd, owner.pw_uid, owner.pw_gid)
            with os.fdopen(fd, 'w') as stream:
                json.dump({'claude-code': str(history_root)}, stream)
            os.replace(staged, location)
        finally:
            Path(staged).unlink(missing_ok=True)
    if source is not None:
        path = Path(launcher)
        if path.is_symlink():
            raise ValueError('AI launcher is redirected')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/usr/bin/env python3\n' + source + '\nif __name__ == "__main__":\n    launch()\n')
        path.chmod(0o755)
    return {'installed': True, 'account': owner.pw_name, 'providers': sorted(profile['providers']), 'authenticated': False}


def receive():
    try:
        request = json.load(sys.stdin)
        install(request['profile'], account=request.get('account'), source=request['source'])
    except Exception:
        print('AI setup delivery failed; check target account, Python and runtime permissions', file=sys.stderr)
        raise SystemExit(1)


def environment(profile, provider, root):
    """Materialize exactly one provider into its private runtime HOME."""
    row = profile['providers'].get(provider)
    has_upstream = (provider == 'codex' and bool(profile['providers'].get('openai', {}).get('env'))) or (provider == 'opencode' and any(profile['providers'].get(p, {}).get('env') for p in ('openai', 'gemini', 'openrouter')))
    if row is None or not (row['env'] or row['files'] or has_upstream):
        raise ValueError('provider has no imported/custom configuration; complete its sign-in or settings')
    root = Path(root)
    home = root / provider / 'home'
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', provider):
        raise ValueError('invalid provider')
    for rel, encoded in row['files'].items():
        if Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise ValueError('invalid AI file')
        dest = home / rel
        if dest.is_symlink() or any(p.is_symlink() for p in dest.parents if p != root):
            raise ValueError('AI runtime path is redirected')
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Preserve native token refreshes in RAM until the next explicit delivery.
        if not dest.exists():
            dest.write_bytes(base64.b64decode(encoded, validate=True)); dest.chmod(0o600)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = dict(os.environ)
    if provider == 'claude-code':
        env.pop('CLAUDE_CONFIG_DIR', None)
        location = root / 'history-location.json'
        if location.is_file() and not location.is_symlink():
            persistent = Path(json.loads(location.read_text())['claude-code'])
            if not persistent.is_absolute() or persistent.is_symlink() or not persistent.is_dir():
                raise ValueError('persistent Claude history is unavailable')
            config_dir = home / '.claude'
            config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            for name in ('projects', 'file-history', 'plans', 'history.jsonl'):
                target = persistent / name
                if not target.exists():
                    if name.endswith('.jsonl'):
                        target.touch(mode=0o600)
                    else:
                        target.mkdir(mode=0o700)
                link = config_dir / name
                if link.is_symlink():
                    if link.resolve() != target.resolve():
                        raise ValueError('Claude history link points elsewhere')
                elif link.exists():
                    raise ValueError('runtime history already has work; preserve it before linking')
                else:
                    link.symlink_to(target, target_is_directory=target.is_dir())
    inherited = {}
    upstream = ['openai'] if provider == 'codex' else ['openai', 'gemini', 'openrouter'] if provider == 'opencode' else []
    for ident in upstream:
        for name, value in profile['providers'].get(ident, {}).get('env', {}).items():
            if name in inherited and inherited[name] != value:
                raise ValueError('conflicting provider endpoints or keys; configure the client explicitly')
            inherited[name] = value
    env.update(inherited)
    env.update(row['env'])
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'), CODEX_HOME=str(home / '.codex'))
    return env


def launch():
    try:
        args = sys.argv[1:]
        if len(args) < 3 or args[1] != '--':
            raise ValueError('usage: baseline-ai-run PROVIDER -- PROGRAM [ARGUMENTS]')
        root = Path(RUNTIME) / str(os.getuid())
        profile = json.loads((root / 'profile.json').read_text())
        env = environment(profile, args[0], root)
        os.execvpe(args[2], args[2:], env)
    except (OSError, ValueError, KeyError):
        print('AI launcher unavailable: unlock/deliver AI setup, select a configured provider and install its client.', file=sys.stderr)
        raise SystemExit(1)
