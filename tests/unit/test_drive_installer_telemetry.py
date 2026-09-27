"""Tests for drive_installer.py's real per-volume usage telemetry
(collect_volume_usage) - real follow-up work, decision record 71.
Reuses `df` rather than parsing /proc or lvs output a second way,
matching diagnostics.py's own preference for real, standard tools.
An unmounted/missing volume is skipped, never crashes - the same
tolerance diagnostics.py's collectors already hold themselves to."""
from fake_runner import FakeProc, FakeRunner

import drive_installer as di


def test_df_argv_shape():
    assert di.df_argv("/mnt/SESSION_TEMP") == ["df", "-B1", "--output=size,used,avail,pcent", "/mnt/SESSION_TEMP"]


def test_parse_df_output_real_shape():
    text = (
        "         1B-blocks         Used    Avail Use%\n"
        " 53687091200  10737418240 42949672960  20%\n"
    )
    parsed = di.parse_df_output(text)
    assert parsed == {
        "total_bytes": 53687091200,
        "used_bytes": 10737418240,
        "available_bytes": 42949672960,
        "percent_used": 20.0,
    }


def test_parse_df_output_returns_none_for_empty_text():
    assert di.parse_df_output("") is None


def test_parse_df_output_returns_none_for_malformed_text():
    assert di.parse_df_output("garbage\nmore garbage\n") is None


def test_collect_volume_usage_returns_one_entry_per_real_mounted_volume():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["df"], FakeProc(
            0,
            "         1B-blocks         Used    Avail Use%\n"
            " 53687091200  10737418240 42949672960  20%\n",
            "")),
    ])
    usages = di.collect_volume_usage(runner)
    assert len(usages) == len(di.BASELINE_VOLUMES)
    labels = {u.label for u in usages}
    assert labels == {"BASELINE", "USER_PERSISTENCE", "INSTALLER_CACHE", "SESSION_TEMP"}
    first = usages[0]
    assert first.percent_used == 20.0
    assert first.total_bytes == 53687091200


def test_collect_volume_usage_skips_a_volume_that_isnt_mounted():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["df"] and a[-1] == "/mnt/BASELINE", FakeProc(1, "", "df: /mnt/BASELINE: No such file or directory")),
        (lambda a: a[:1] == ["df"], FakeProc(
            0,
            "         1B-blocks         Used    Avail Use%\n"
            " 53687091200  10737418240 42949672960  20%\n",
            "")),
    ])
    usages = di.collect_volume_usage(runner)
    labels = {u.label for u in usages}
    assert "BASELINE" not in labels
    assert len(usages) == len(di.BASELINE_VOLUMES) - 1


def test_collect_volume_usage_returns_empty_list_when_nothing_is_mounted():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["df"], FakeProc(1, "", "not mounted")),
    ])
    assert di.collect_volume_usage(runner) == []
