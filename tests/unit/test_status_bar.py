"""Unit tests for status_bar.py - the pure formatting behind the
app-wide condensed header bar (SESSION_HANDOFF.md's still-open "Chat
tab quality" ask). Textual's own Header already shows the app title
and clock (datetime); its own tab strip already highlights the active
tab (see `Tab.-active` in bin/baseline's CSS) - this bar exists for
the parts nothing else already shows: live session/access-scope state
and the copy-action hint.

Also enforces the 80x24 layout floor (item 4,
docs/design/v0.1-work-queue.md): a long write-grant scope path must
never push this always-visible line past the target floor width -
per this project's own "no non-ASCII characters anywhere in rendered
output" standing rule (see docs/SESSION_HANDOFF.md), truncation uses
plain ASCII "...", never an ellipsis glyph.
"""
import status_bar as sb


def test_format_status_bar_combines_session_description_and_copy_hint():
    assert sb.format_status_bar("session: cold (no memory yet) | write: none") == (
        "BaselineOS | session: cold (no memory yet) | write: none | c=copy"
    )


def test_format_status_bar_with_an_active_write_grant_that_fits():
    desc = "session: warm | write: /srv/util (this session only)"
    assert sb.format_status_bar(desc) == f"BaselineOS | {desc} | c=copy"


def test_format_status_bar_stays_within_the_80x24_floor_width():
    long_desc = ("session: warm (multi-turn memory active) | write: "
                 "/var/lib/baseline/some/deeply/nested/example/grant/directory/name "
                 "(this session only)")
    line = sb.format_status_bar(long_desc, max_width=80)
    assert len(line) <= 80
    assert line.startswith("BaselineOS | ")
    assert line.endswith(" | c=copy")


def test_format_status_bar_truncation_uses_only_ascii():
    long_desc = "write: " + ("x" * 200)
    line = sb.format_status_bar(long_desc, max_width=80)
    assert line.isascii()
    assert "..." in line


def test_format_status_bar_default_max_width_is_80():
    long_desc = "write: " + ("y" * 200)
    default_line = sb.format_status_bar(long_desc)
    explicit_line = sb.format_status_bar(long_desc, max_width=80)
    assert default_line == explicit_line


def test_elide_middle_leaves_short_text_untouched():
    assert sb.elide_middle("short", 20) == "short"


def test_elide_middle_truncates_long_text_with_ascii_ellipsis():
    result = sb.elide_middle("a" * 50, 20)
    assert len(result) <= 20
    assert "..." in result
    assert result.isascii()


def test_elide_middle_never_exceeds_max_len():
    for max_len in (1, 2, 3, 4, 5, 10, 30):
        result = sb.elide_middle("x" * 100, max_len)
        assert len(result) <= max_len
