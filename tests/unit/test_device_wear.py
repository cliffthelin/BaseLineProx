import device_wear as dw


def test_reads_sectors_written_as_bytes(tmp_path):
    (tmp_path / "sdx").mkdir()
    (tmp_path / "sdx" / "stat").write_text("1 2 3 4 5 6 2048 8 9 10 11")
    assert dw.written_bytes("sdx", sys_block=tmp_path) == 2048 * 512


def test_unreadable_device_is_none(tmp_path):
    assert dw.written_bytes("nope", sys_block=tmp_path) is None


def test_spent_and_describe():
    assert dw.spent(10, 25) == 15 and dw.spent(None, 5) is None and dw.spent(9, 3) == 0
    assert dw.describe(2 * dw.GIB) == "2.0 GiB" and dw.describe(None) == "unknown"
