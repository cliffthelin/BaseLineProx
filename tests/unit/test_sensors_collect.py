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
