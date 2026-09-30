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
    assert labels == {"BASELINE", "USER_PERSISTENCE_ADMIN", "USER_PERSISTENCE_PERSONAL",
                       "INSTALLER_CACHE", "SESSION_TEMP", "SUBSTRATE_PERSISTENCE"}
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


# -- collect_volume_details (real LV name + real allocated size) -----------
# Direct feedback: the web page's volume table showed raw byte counts
# with no partition/LV name at all, "makes no sense" - every volume
# needs its own real LV name and real allocated size shown, not just
# whatever happens to be mounted right now.

def test_collect_volume_details_reports_lv_name_and_real_size_for_an_existing_volume():
    runner = FakeRunner(command_responses=[
        (lambda a: "lvs" in a and "-o" in a and a[a.index("-o") + 1] == "vg_name,lv_name",
         FakeProc(0, "  pve   baseline_app_state\n", "")),
        (lambda a: "lvs" in a and "-o" in a and a[a.index("-o") + 1] == "lv_name,lv_size",
         FakeProc(0, "  baseline_app_state  5368709120\n", "")),
        (lambda a: a[:1] == ["df"] and a[-1] == "/mnt/BASELINE", FakeProc(
            0, "         1B-blocks         Used    Avail Use%\n"
               " 5368709120  1073741824 4294967296  20%\n", "")),
        (lambda a: a[:1] == ["df"], FakeProc(1, "", "not mounted")),
    ])
    details = di.collect_volume_details(runner, vg_name="pve", personas=())
    baseline = next(d for d in details if d.label == "BASELINE")
    assert baseline.lv_name == "baseline_app_state"
    assert baseline.lv_exists is True
    assert baseline.lv_size_bytes == 5368709120
    assert baseline.used_bytes == 1073741824
    assert baseline.total_bytes == 5368709120
    assert baseline.percent_used == 20.0


def test_collect_volume_details_reports_a_volume_that_does_not_exist_yet_honestly():
    runner = FakeRunner(command_responses=[
        (lambda a: "lvs" in a, FakeProc(0, "  pve   root\n", "")),  # none of the real volumes exist
        (lambda a: a[:1] == ["df"], FakeProc(1, "", "not mounted")),
    ])
    details = di.collect_volume_details(runner, vg_name="pve", personas=())
    baseline = next(d for d in details if d.label == "BASELINE")
    assert baseline.lv_exists is False
    assert baseline.lv_size_bytes is None
    assert baseline.total_bytes is None
    assert baseline.used_bytes is None
    assert baseline.percent_used is None


def test_collect_volume_details_returns_one_entry_per_planned_volume_regardless_of_mount_state():
    runner = FakeRunner(command_responses=[
        (lambda a: "lvs" in a, FakeProc(0, "", "")),
        (lambda a: a[:1] == ["df"], FakeProc(1, "", "not mounted")),
    ])
    details = di.collect_volume_details(runner, vg_name="pve")
    assert len(details) == len(di.BASELINE_VOLUMES)


def test_parse_logical_volume_sizes():
    text = "  baseline_app_state  5368709120\n  baseline_installer_cache  53687091200\n"
    sizes = di.parse_logical_volume_sizes(text)
    assert sizes == {"baseline_app_state": 5368709120, "baseline_installer_cache": 53687091200}


def test_parse_logical_volume_sizes_ignores_malformed_lines():
    assert di.parse_logical_volume_sizes("garbage\n") == {}
    assert di.parse_logical_volume_sizes("") == {}
