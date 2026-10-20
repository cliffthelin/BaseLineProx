"""Opaque conversation transfer using synthetic transcripts, never live accounts."""
import json
import pytest


def test_import_preserves_native_session_layout_and_private_permissions(tmp_path):
    import claude_history as h
    parent = tmp_path / 'parent/.claude'
    session = parent / 'projects/-synthetic-repo/session.jsonl'
    session.parent.mkdir(parents=True)
    session.write_text('{"message":"synthetic conversation"}\n')
    (parent / 'history.jsonl').write_text('{"display":"synthetic prompt"}\n')
    admin = tmp_path / 'USER_ADMIN'
    admin.mkdir()
    report = h.seed(parent, admin)
    dest = admin / 'claude-code/.claude'
    assert (dest / session.relative_to(parent)).read_bytes() == session.read_bytes()
    assert (dest / 'history.jsonl').exists()
    assert (dest / 'history.jsonl').stat().st_mode & 0o077 == 0
    assert report['copied'] == 2 and report['conflicts'] == 0
    assert 'synthetic conversation' not in json.dumps(report)
    assert h.seed(parent, admin)['unchanged'] == 2


def test_import_never_replaces_child_conversations_or_copies_credentials(tmp_path):
    import claude_history as h
    parent = tmp_path / 'parent'
    (parent / 'projects/project').mkdir(parents=True)
    (parent / 'projects/project/s.jsonl').write_text('parent\n')
    (parent / '.credentials.json').write_text('synthetic credential not for import')
    child = tmp_path / 'admin/claude-code/.claude/projects/project'
    child.mkdir(parents=True)
    (child / 's.jsonl').write_text('child\n')
    report = h.seed(parent, tmp_path / 'admin')
    assert report['conflicts'] == 1 and report['state'] == 'needs review'
    assert (child / 's.jsonl').read_text() == 'child\n'
    assert not (tmp_path / 'admin/claude-code/.claude/.credentials.json').exists()


def test_installed_source_without_git_becomes_editable_versioned_checkout(tmp_path):
    import claude_history as h
    source = tmp_path / 'payload'
    (source / 'baseline/lib').mkdir(parents=True)
    (source / 'baseline/lib/claude_history.py').write_text('# synthetic installed source\n')
    (source / 'boot').mkdir()
    (source / 'boot/provision.sh').write_text('#!/bin/sh\n')
    admin = tmp_path / 'admin'
    admin.mkdir()
    result = h.prepare_workspace(source, admin)
    dest = admin / 'workspaces/BaselineOS'
    assert result['state'] == 'created editable checkout'
    assert (dest / '.git').is_dir()
    (dest / 'baseline/lib/claude_history.py').write_text('# local fix\n')
    assert h.prepare_workspace(source, admin)['state'] == 'kept existing checkout'
    assert 'local fix' in (dest / 'baseline/lib/claude_history.py').read_text()


def test_runtime_claude_keeps_new_conversations_on_persistent_history(tmp_path):
    import ai_runtime
    root = tmp_path / 'runtime'
    root.mkdir()
    persistent = tmp_path / 'USER_ADMIN/root/.claude'
    persistent.mkdir(parents=True)
    (persistent / 'projects').mkdir()
    (root / 'history-location.json').write_text(json.dumps({'claude-code': str(persistent)}))
    profile = {'providers': {'claude-code': {'env': {'ANTHROPIC_API_KEY': 'synthetic-only-key'}, 'files': {}}}, 'mcp': {}}
    env = ai_runtime.environment(profile, 'claude-code', root)
    active = __import__('pathlib').Path(env['HOME']) / '.claude/projects'
    assert active.is_symlink()
    (active / 'synthetic-new.jsonl').write_text('new conversation\n')
    assert (persistent / 'projects/synthetic-new.jsonl').exists()


def test_plan_keeps_conversations_off_user_admin(tmp_path, monkeypatch):
    import claude_history as h
    parent = tmp_path / 'parent'
    (parent / 'projects').mkdir(parents=True)
    (parent / 'projects/session.jsonl').write_text('synthetic\n')
    admin = tmp_path / 'mnt/USER_ADMIN'
    app = tmp_path / 'mnt/APPDATA_ADMIN'
    admin.mkdir(parents=True)
    app.mkdir()
    h.apply_plan({'host_configuration': {'ai_setup': {'claude_history': True}}}, admin, source=parent)
    assert (app / 'claude-code/.claude/projects/session.jsonl').is_file()
    assert not (admin / 'root').exists()
