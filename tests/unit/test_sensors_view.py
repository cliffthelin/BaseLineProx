"""One source of rows for the TUI's Sensors tab and the web /sensors page, so the two can never disagree."""
from types import SimpleNamespace as NS

import sensors_view as sv


class Diagnostics:
    def collect_sensors(self, runner):
        return NS(chips=[{"chip": "coretemp", "features": [{"label": "Package", "value": 51.0, "unit": "C"}, {"label": "Fan", "value": 900}]}])

    def collect_nvme(self, runner):
        return NS(devices=[{"path": "/dev/nvme0", "health": {"temperature": 38, "percentage_used": 3, "other": "x"}}])

    def collect_smart(self, runner):
        return NS(devices=[{"device": "/dev/sda", "temperature": 33}, {"device": "/dev/sdb", "temperature": None}])


def test_rows_are_the_same_shape_the_tui_always_showed():
    rows = sv.collect_rows(None, Diagnostics())
    assert rows == [("sensors", "coretemp/Package", 51.0, "C"), ("sensors", "coretemp/Fan", 900, ""),
                    ("nvme", "/dev/nvme0/temperature", 38, "C"), ("nvme", "/dev/nvme0/percentage_used", 3, "%"),
                    ("smart", "/dev/sda/temperature", 33, "C")]


def test_the_page_lists_every_row_and_says_so_when_there_is_nothing():
    html = sv.render([("sensors", "coretemp/Package", 51.0, "C")]).decode()
    assert "coretemp/Package" in html and "51.0" in html
    assert "no sensors/NVMe/SMART data available" in sv.render([]).decode()


def test_values_from_the_hardware_are_escaped():
    assert "<script>" not in sv.render([("sensors", "<script>x</script>", 1, "C")]).decode()
