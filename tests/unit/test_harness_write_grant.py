"""Unit tests for harness.py's write-scope grant (decision record 32):
explicit, scoped, session-only. No write tool is ever enabled without a
grant made in that specific session; a grant made in one session grants
nothing in a fresh one; a grant for one scope path never covers a path
outside it."""
import pytest

import harness


def test_grant_write_scope_requires_an_existing_directory(tmp_path):
    session = harness.HarnessSession(session_id="s1")
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError):
        harness.grant_write_scope(session, str(missing), authorized_by="operator", now=1.0)
    assert session.write_grant is None


def test_grant_write_scope_records_who_and_when(tmp_path):
    session = harness.HarnessSession(session_id="s1")
    grant = harness.grant_write_scope(session, str(tmp_path), authorized_by="operator via console", now=42.0)
    assert grant.scope_path == str(tmp_path.resolve())
    assert grant.authorized_by == "operator via console"
    assert grant.granted_at == 42.0
    assert session.write_grant is grant


def test_revoke_write_scope_clears_it(tmp_path):
    session = harness.HarnessSession(session_id="s1")
    harness.grant_write_scope(session, str(tmp_path), authorized_by="operator", now=1.0)
    harness.revoke_write_scope(session)
    assert session.write_grant is None


def test_a_fresh_session_never_inherits_another_sessions_grant(tmp_path):
    granted = harness.HarnessSession(session_id="s1")
    harness.grant_write_scope(granted, str(tmp_path), authorized_by="operator", now=1.0)
    fresh = harness.HarnessSession(session_id="s2")
    assert fresh.write_grant is None


def test_is_path_within_grant_accepts_the_scope_directory_itself(tmp_path):
    session = harness.HarnessSession(session_id="s1")
    harness.grant_write_scope(session, str(tmp_path), authorized_by="operator", now=1.0)
    assert harness.is_path_within_grant(session, str(tmp_path)) is True


def test_is_path_within_grant_accepts_a_file_inside_the_scope(tmp_path):
    session = harness.HarnessSession(session_id="s1")
    harness.grant_write_scope(session, str(tmp_path), authorized_by="operator", now=1.0)
    inside = tmp_path / "notes.txt"
    inside.write_text("x")
    assert harness.is_path_within_grant(session, str(inside)) is True


def test_is_path_within_grant_refuses_a_sibling_directory(tmp_path):
    scope = tmp_path / "scope"
    scope.mkdir()
    sibling = tmp_path / "scope-but-not-really"
    sibling.mkdir()
    session = harness.HarnessSession(session_id="s1")
    harness.grant_write_scope(session, str(scope), authorized_by="operator", now=1.0)
    assert harness.is_path_within_grant(session, str(sibling / "x.txt")) is False


def test_is_path_within_grant_refuses_traversal_out_of_scope(tmp_path):
    scope = tmp_path / "scope"
    scope.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    session = harness.HarnessSession(session_id="s1")
    harness.grant_write_scope(session, str(scope), authorized_by="operator", now=1.0)
    escaping = str(scope / ".." / "outside.txt")
    assert harness.is_path_within_grant(session, escaping) is False


def test_is_path_within_grant_is_false_with_no_grant_at_all(tmp_path):
    session = harness.HarnessSession(session_id="s1")
    assert harness.is_path_within_grant(session, str(tmp_path / "anything")) is False


# -- build_ask_argv: the grant must actually change what's sent to the CLI --

def test_build_ask_argv_with_no_grant_stays_fully_tool_disabled():
    session = harness.HarnessSession(session_id="fixed-id")
    argv = harness.build_ask_argv("hello", session)
    assert argv == ["claude", "-p", "hello", "--session-id", "fixed-id", "--tools", ""]


def test_build_ask_argv_with_an_active_grant_scopes_write_instead_of_disabling_everything(tmp_path):
    session = harness.HarnessSession(session_id="fixed-id")
    harness.grant_write_scope(session, str(tmp_path), authorized_by="operator", now=1.0)
    argv = harness.build_ask_argv("hello", session)
    assert argv == ["claude", "-p", "hello", "--session-id", "fixed-id",
                     "--allowedTools", f"Write({tmp_path.resolve()}/**)"]
    assert "--tools" not in argv
