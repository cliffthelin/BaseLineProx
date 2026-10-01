"""Unit tests for sensors_collect.py (Track A5) - the oneshot collection
cycle invoked every 30s by baseline-sensors-collect.timer. Flattens
diagnostics.py's real collectors into sensors_history samples and prunes
old data. FakeRunner for the subprocess boundary, a real in-memory
sqlite3 connection for the history store (matching both modules' own
testing style)."""
import json

from fake_runner import FakeRunner, FakeProc

import sensors_collect as sc
import sensors_history as sh


def make_db():
    return sh.open_db(":memory:")


def script_no_hardware(runner):
    runner.command_responses = [
        (lambda a: a[:1] == ["sensors"], FakeProc(0, "{}", "")),
        (lambda a: a[:2] == ["nvme", "list"], FakeProc(0, json.dumps({"Devices": []}), "")),
        (lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, json.dumps({"devices": []}), "")),
    ]


def test_collect_once_records_zero_samples_when_no_hardware_present():
    runner = FakeRunner()
    script_no_hardware(runner)
    conn = make_db()
    count = sc.collect_once(runner, conn, now=1700000000.0)
    assert count == 0


def test_collect_once_records_real_sensor_reading():
    runner = FakeRunner()
    sensors_payload = json.dumps({
        "coretemp-isa-0000": {
            "Adapter": "ISA adapter",
            "Package id 0": {"temp1_input": 45.0},
        }
    })
    runner.command_responses = [
        (lambda a: a[:1] == ["sensors"], FakeProc(0, sensors_payload, "")),
        (lambda a: a[:2] == ["nvme", "list"], FakeProc(0, json.dumps({"Devices": []}), "")),
        (lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, json.dumps({"devices": []}), "")),
    ]
    conn = make_db()
    count = sc.collect_once(runner, conn, now=1700000000.0)
    assert count == 1
    rows = sh.query_history(conn, source="sensors", key="coretemp-isa-0000/Package id 0 temp1_input", since_ts=0)
    assert rows == [(1700000000.0, 45.0)]


def test_collect_once_records_nvme_temperature_and_wear():
    runner = FakeRunner()
    list_payload = json.dumps({"Devices": [{"DevicePath": "/dev/nvme0n1", "ModelNumber": "X", "Firmware": "1.0"}]})
    smart_payload = json.dumps({"temperature": 38, "percentage_used": 5})
    runner.command_responses = [
        (lambda a: a[:1] == ["sensors"], FakeProc(0, "{}", "")),
        (lambda a: a[:2] == ["nvme", "list"], FakeProc(0, list_payload, "")),
        (lambda a: a[:2] == ["nvme", "smart-log"], FakeProc(0, smart_payload, "")),
        (lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, json.dumps({"devices": []}), "")),
    ]
    conn = make_db()
    count = sc.collect_once(runner, conn, now=1700000000.0)
    assert count == 2
    temp_rows = sh.query_history(conn, source="nvme", key="/dev/nvme0n1/temperature", since_ts=0)
    assert temp_rows == [(1700000000.0, 38.0)]
    wear_rows = sh.query_history(conn, source="nvme", key="/dev/nvme0n1/percentage_used", since_ts=0)
    assert wear_rows == [(1700000000.0, 5.0)]


def test_collect_once_records_smart_temperature():
    runner = FakeRunner()
    scan_payload = json.dumps({"devices": [{"name": "/dev/sda", "type": "sat"}]})
    detail_payload = json.dumps({"model_name": "ST1000", "temperature": {"current": 32}})
    runner.command_responses = [
        (lambda a: a[:1] == ["sensors"], FakeProc(0, "{}", "")),
        (lambda a: a[:2] == ["nvme", "list"], FakeProc(0, json.dumps({"Devices": []}), "")),
        (lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, scan_payload, "")),
        (lambda a: a[:2] == ["smartctl", "-a"], FakeProc(0, detail_payload, "")),
    ]
    conn = make_db()
    count = sc.collect_once(runner, conn, now=1700000000.0)
    assert count == 1
    rows = sh.query_history(conn, source="smart", key="/dev/sda/temperature", since_ts=0)
    assert rows == [(1700000000.0, 32.0)]


def test_collect_once_prunes_samples_older_than_retention():
    runner = FakeRunner()
    script_no_hardware(runner)
    conn = make_db()
    sh.record_sample(conn, ts=0.0, source="sensors", key="stale", value=1.0, unit="C")
    sc.collect_once(runner, conn, now=1_000_000.0, retention_s=10.0)
    rows = sh.query_history(conn, source="sensors", key="stale", since_ts=0)
    assert rows == []


def test_collect_once_never_raises_when_tools_missing():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: True, FakeProc(127, "", "not found"))]
    conn = make_db()
    count = sc.collect_once(runner, conn, now=1700000000.0)
    assert count == 0


# --------------------------------------------------------------------------
# Per-volume telemetry (real follow-up work, decision record 71) - feeds
# the same 30s collection cycle/store, no new moving parts.
# --------------------------------------------------------------------------

def test_collect_once_records_real_volume_usage_samples():
    runner = FakeRunner()
    df_payload = (
        "         1B-blocks         Used    Avail Use%\n"
        " 53687091200  10737418240 42949672960  20%\n"
    )
    runner.command_responses = [
        (lambda a: a[:1] == ["sensors"], FakeProc(0, "{}", "")),
        (lambda a: a[:2] == ["nvme", "list"], FakeProc(0, json.dumps({"Devices": []}), "")),
        (lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, json.dumps({"devices": []}), "")),
        (lambda a: a[:1] == ["df"], FakeProc(0, df_payload, "")),
    ]
    conn = make_db()
    count = sc.collect_once(runner, conn, now=1700000000.0)
    # 8 volumes (BASELINE, USER_ADMIN, USER_PERSONAL,
    # APPDATA_ADMIN, APPDATA_PERSONAL, INSTALLER_CACHE, SESSION_TEMP,
    # SUBSTRATE) x 2 samples each (percent_used, used_bytes)
    assert count == 16
    rows = sh.query_history(conn, source="volume", key="SESSION_TEMP/percent_used", since_ts=0)
    assert rows == [(1700000000.0, 20.0)]
    rows = sh.query_history(conn, source="volume", key="USER_ADMIN/used_bytes", since_ts=0)
    assert rows == [(1700000000.0, 10737418240.0)]


def test_collect_once_records_no_volume_samples_when_nothing_mounted():
    runner = FakeRunner()
    script_no_hardware(runner)  # default fake response for unmatched df is (0, "", "") -> no valid rows
    conn = make_db()
    count = sc.collect_once(runner, conn, now=1700000000.0)
    assert count == 0


# --------------------------------------------------------------------------
# Per-source collection cadence (decision record 72) - "a parameter
# available to be set as needed as often as needed... check every
# second until a condition changes... should not change places that
# are not of high concern": each source's own interval independently
# gates whether its real collector even runs this cycle.
# --------------------------------------------------------------------------

def test_collect_once_skips_a_source_whose_interval_has_not_yet_elapsed():
    runner = FakeRunner()
    script_no_hardware(runner)
    conn = make_db()
    sc.collect_once(runner, conn, now=1700000000.0)  # first call: everything due (never attempted)
    calls_after_first = len(runner.calls)
    sc.collect_once(runner, conn, now=1700000005.0)  # 5s later - well under the 30s default
    # no new real subprocess calls should have been made for any source
    assert len(runner.calls) == calls_after_first


def test_collect_once_recollects_a_source_once_its_interval_has_elapsed():
    runner = FakeRunner()
    script_no_hardware(runner)
    conn = make_db()
    sc.collect_once(runner, conn, now=1700000000.0)
    calls_after_first = len(runner.calls)
    sc.collect_once(runner, conn, now=1700000031.0)  # 31s later - past the 30s default
    assert len(runner.calls) > calls_after_first


def test_collect_once_respects_a_real_time_override_escalated_to_one_second():
    runner = FakeRunner()
    script_no_hardware(runner)
    conn = make_db()
    sh.set_interval(conn, "nvme", 1.0)  # a time of high concern for nvme specifically
    sc.collect_once(runner, conn, now=1700000000.0)
    nvme_calls_after_first = sum(1 for c in runner.calls if c[:2] == ["nvme", "list"])
    sc.collect_once(runner, conn, now=1700000002.0)  # 2s later - past the 1s override
    nvme_calls_after_second = sum(1 for c in runner.calls if c[:2] == ["nvme", "list"])
    assert nvme_calls_after_second > nvme_calls_after_first


def test_collect_once_escalating_one_source_does_not_speed_up_another():
    """The direct instruction's own core requirement: escalating nvme
    to 1s must not also re-poll sensors/smart/volume early."""
    runner = FakeRunner()
    script_no_hardware(runner)
    conn = make_db()
    sh.set_interval(conn, "nvme", 1.0)
    sc.collect_once(runner, conn, now=1700000000.0)
    sensors_calls_after_first = sum(1 for c in runner.calls if c[:1] == ["sensors"])
    sc.collect_once(runner, conn, now=1700000002.0)  # nvme is due again, sensors (still 30s) is not
    sensors_calls_after_second = sum(1 for c in runner.calls if c[:1] == ["sensors"])
    assert sensors_calls_after_second == sensors_calls_after_first


def test_collect_once_records_an_attempt_even_when_no_samples_result():
    runner = FakeRunner()
    script_no_hardware(runner)
    conn = make_db()
    sc.collect_once(runner, conn, now=1700000000.0)
    assert sh.get_last_attempt(conn, "sensors") == 1700000000.0
    assert sh.get_last_attempt(conn, "nvme") == 1700000000.0
    assert sh.get_last_attempt(conn, "smart") == 1700000000.0
    assert sh.get_last_attempt(conn, "volume") == 1700000000.0
