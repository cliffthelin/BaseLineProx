"""Private native Claude Code history on APPDATA_ADMIN; never prints transcript text.

Conversation state is separate from credential profiles and installer-cache data.
Imports are additive. Different local files stay authoritative; parent conflicts
are kept separately for explicit review. No session path or transcript is rewritten.
"""
from pathlib import Path
import filecmp
import hashlib
import json
import os
import pwd
import shutil
import tempfile
import time

TREES = ('projects', 'file-history', 'plans')
FILES = ('history.jsonl',)
DEST = 'claude-code/.claude'

class HistoryError(RuntimeError):
    pass


def parent_dir():
    import operator_identity
    name = operator_identity.invoking_user()
    home = Path(pwd.getpwnam(name).pw_dir) if name else Path.home()
    return (home / '.claude').resolve()


def inventory(source):
    root = Path(source)
    if not root.is_dir() or root.is_symlink():
        raise HistoryError('parent Claude Code directory is absent or redirected')
    result = []
    for name in TREES + FILES:
        start = root / name
        if start.is_symlink():
            raise HistoryError('Claude history contains a link; no import performed')
        if not start.exists():
            continue
        if (name in TREES and not start.is_dir()) or (name in FILES and not start.is_file()):
            raise HistoryError('unexpected Claude history layout')
        paths = [start] if start.is_file() else start.rglob('*')
        for p in paths:
            if p.is_symlink() or not (p.is_dir() or p.is_file()):
                raise HistoryError('Claude history contains a link or special file')
            if p.is_file():
                result.append((p.relative_to(root), p.stat().st_size))
    if not result:
        raise HistoryError('no Claude Code conversation history was found')
    return result


def _private_folder(path, boundary):
    if path.is_symlink():
        raise HistoryError('Claude history destination is redirected')
    if path != boundary:
        _private_folder(path.parent, boundary)
    path.mkdir(exist_ok=True, mode=0o700)
    path.chmod(0o700)


def seed(source, user_admin):
    root, admin = Path(source), Path(user_admin)
    if admin.is_symlink() or not admin.is_dir():
        raise HistoryError('verified APPDATA mount is required')
    entries = inventory(root)  # inspect structure before any destination writes
    space = os.statvfs(admin)
    needed = sum(size for rel, size in entries if not (admin / DEST / rel).is_file())
    if needed + 64 * 1024**2 > space.f_bavail * space.f_frsize:
        raise HistoryError("APPDATA needs more free space for the conversation import")
    dest = admin / DEST
    _private_folder(dest, admin)
    report = {'state': 'imported', 'copied': 0, 'unchanged': 0, 'conflicts': 0, 'bytes_copied': 0}
    for rel, _size in entries:
        src, target = root / rel, dest / rel
        _private_folder(target.parent, admin)
        if target.is_symlink():
            raise HistoryError('Claude history destination file is redirected')
        if target.exists():
            if not target.is_file():
                raise HistoryError('Claude history destination is not a regular file')
            if filecmp.cmp(src, target, shallow=False):
                target.chmod(0o600);report['unchanged'] += 1
                continue
            # Preserve both versions, never overwrite the running build's work.
            target = admin / 'claude-history-conflicts' / rel
            _private_folder(target.parent, admin)
            if target.exists():
                raise HistoryError('a prior history conflict needs review before another import')
            report['conflicts'] += 1
            report['state'] = 'needs review'
        for attempt in range(3):
            before = src.stat()
            fd, temporary = tempfile.mkstemp(prefix='.history-', dir=target.parent)
            try:
                os.fchmod(fd, 0o600)
                with src.open('rb') as incoming, os.fdopen(fd, 'wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                    outgoing.flush();os.fsync(outgoing.fileno())
                after = src.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    if attempt == 2:
                        raise HistoryError('a parent history file is changing; retry after the session settles')
                    continue
                if target.exists() or target.is_symlink():
                    raise HistoryError('destination history appeared during transfer; retry')
                os.replace(temporary, target)
                report['copied'] += 1;report['bytes_copied'] += after.st_size
                break
            finally:
                Path(temporary).unlink(missing_ok=True)
    receipt = admin / 'claude-history-import.json'
    receipt.write_text(json.dumps(dict(report, checked=time.time())) + '\n');receipt.chmod(0o600)
    return report


def data_root(user_admin):
    root = Path(user_admin).parent / 'APPDATA_ADMIN'
    if root.is_symlink() or not root.is_dir():
        raise HistoryError('APPDATA_ADMIN is required for Claude history; no USER_ADMIN fallback')
    return root


def apply_plan(plan, user_admin, *, source=None):
    selected = plan.get('host_configuration', {}).get('ai_setup', {}).get('claude_history', False)
    if type(selected) is not bool:
        raise HistoryError('Claude Code history choice must be a boolean')
    if not selected:
        return {'state': 'not requested'}
    return seed(source or parent_dir(), data_root(user_admin))


def prepare_workspace(repo, user_admin):
    """A local editable checkout, including selected uncommitted source; no network or secrets."""
    import subprocess
    repo, admin = Path(repo), Path(user_admin)
    dest = admin / 'workspaces/BaselineOS'
    if dest.exists():
        if dest.is_symlink() or not (dest / '.git').is_dir():
            raise HistoryError('maintenance workspace exists but is not a plain checkout')
        return {'state': 'kept existing checkout', 'path': '/mnt/APPDATA_ADMIN/workspaces/BaselineOS'}
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.workspace-', dir=dest.parent) as work:
        stage = Path(work) / 'repo'
        trees = {'baseline', 'boot', 'automation', 'packaging', 'docs', 'tests', 'config', 'tools'}
        has_git = (repo / '.git').exists()
        if has_git:
            done = subprocess.run(['git', 'clone', '--local', '--no-hardlinks', str(repo), str(stage)], capture_output=True)
            if done.returncode:
                raise HistoryError('could not create the editable maintenance checkout')
            listed = subprocess.run(['git', '-C', str(repo), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], capture_output=True, check=True).stdout
            paths = [Path(os.fsdecode(raw)) for raw in listed.split(b'\0') if raw]
        else:
            stage.mkdir()
            subprocess.run(['git', 'init', '-q', str(stage)], check=True, capture_output=True)
            paths = [p.relative_to(repo) for name in trees for p in (repo / name).rglob('*') if p.is_file() or p.is_symlink()]
            paths += [p.relative_to(repo) for p in repo.iterdir() if p.is_file()]
        for rel in paths:
            if rel.is_absolute() or '..' in rel.parts:
                raise HistoryError('invalid maintenance source path')
            if len(rel.parts) > 1 and rel.parts[0] not in trees:
                continue
            if '__pycache__' in rel.parts or rel.suffix == '.pyc':
                continue
            source, target = repo / rel, stage / rel
            if not source.is_file() and not source.is_symlink():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                target.unlink()
            shutil.copy2(source, target, follow_symlinks=False)
        if not has_git:
            subprocess.run(['git', '-C', str(stage), 'add', '-A'], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(stage), '-c', 'user.name=BaselineOS', '-c', 'user.email=build@baseline.invalid', 'commit', '-qm', 'Installed source snapshot'], check=True, capture_output=True)
        # Keep every required source file even when this feature is not committed yet.
        if not (stage / 'baseline/lib/claude_history.py').is_file():
            raise HistoryError('maintenance checkout is missing the history feature source')
        os.replace(stage, dest)
    return {'state': 'created editable checkout', 'path': '/mnt/APPDATA_ADMIN/workspaces/BaselineOS'}
