import time

import console_charts as cc
import proxmox_vm_metrics as pvm
import sensors_history
import sensors_view as sv
import vm_page


def test_sparkline_draws_range_and_latest_in_words():
    out = cc.sparkline_svg([40, 45, 50], label="cpu", unit="C")
    assert "<polyline" in out and "now 50C, lowest 40C, highest 50C over 3 readings" in out


def test_empty_and_constant_series_are_safe():
    assert "no history yet" in cc.sparkline_svg([], label="x")
    assert "<polyline" in cc.sparkline_svg([7, 7, 7], label="x")


def test_hottest_history_reads_the_collectors_store(tmp_path):
    db = tmp_path / "h.db"
    conn = sensors_history.open_db(str(db))
    now = time.time()
    for i, v in enumerate([50, 60, 70]):
        sensors_history.record_sample(conn, ts=now - 30 + i, source="nvme", key="d/temperature", value=v, unit="C")
    conn.close()
    rows = [("nvme", "d/temperature", 70, "C"), ("sensors", "x/fan", 900, "RPM")]
    label, values = sv.hottest_history(rows, db_path=db, window_s=3600)
    assert label == "d/temperature temperature" and values == [50, 60, 70]


def test_missing_store_is_no_history_not_an_error(tmp_path):
    assert sv.hottest_history([("nvme", "d/t", 70, "C")], db_path=tmp_path / "none", window_s=60)[1] == []
    assert sv.hottest_history([], db_path=tmp_path / "none", window_s=60) == ("", [])


def test_sensors_page_shows_the_chart_when_given_history():
    assert b"<figure" in sv.render([("nvme", "d/t", 70, "C")], ("d/t temperature", [1, 2, 3]))
    assert b"<figure" not in sv.render([("nvme", "d/t", 70, "C")])


def test_running_cpu_history_uses_the_first_running_machine():
    vm = type("V", (), {"status": "running", "vmid": 100, "type": "qemu", "name": "demo"})()
    seen = {}

    class R:
        def run(self, argv, timeout=10):
            import subprocess
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, '[{"time": 1000, "cpu": 0.2}, {"time": 1010, "cpu": 0.4}, {"time": 1020}]', "")
    name, values, error = pvm.running_cpu_history(R(), [vm], window_s=100, now=1030)
    assert (name, values, error) == ("demo", [0.2, 0.4], "") and "100" in " ".join(seen["argv"])
    assert pvm.running_cpu_history(R(), [], window_s=100) == ("", [], "")


def test_vm_page_gains_the_usage_graph_above_its_closing_tag():
    page = vm_page.with_usage(b"<html><body>x</body></html>", "demo", [0.1, 0.2])
    assert b"vm-usage" in page and page.index(b"vm-usage") < page.index(b"</body>")
    assert b"no data" in vm_page.with_usage(b"<body></body>", "", [], "no data")
