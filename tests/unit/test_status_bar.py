"""Unit tests for status_bar.py - the pure formatting behind the
app-wide condensed header bar (SESSION_HANDOFF.md's still-open "Chat
tab quality" ask). Textual's own Header already shows the app title
and clock (datetime); its own tab strip already highlights the active
tab (see `Tab.-active` in bin/baseline's CSS) - this bar exists for
the parts nothing else already shows: live session/access-scope state
and the copy-action hint."""
import status_bar as sb


def test_format_status_bar_combines_session_description_and_copy_hint():
    assert sb.format_status_bar("session: cold (no memory yet) | write: none") == (
        "BaselineOS | session: cold (no memory yet) | write: none | c=copy"
    )


def test_format_status_bar_with_an_active_write_grant():
    desc = "session: warm (multi-turn memory active) | write: /srv/util (this session only)"
    assert sb.format_status_bar(desc) == f"BaselineOS | {desc} | c=copy"
