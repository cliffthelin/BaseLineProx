"""The watchdog verdicts: a dead or paused VM, a moved drive, a stalled screen and a time limit are all noticed on the tick they appear."""
import time

import install_watch as w


def watch(**kw):
    return w.StageWatch(stage="firstboot-screen", opened_path="/dev/sdb", started=0.0, limit_seconds=kw.pop("limit", 3600), **kw)


def test_status_is_read_from_the_monitors_reply_and_a_missing_reply_is_none():
    assert w.parse_status("(qemu) info status\r\nVM status: paused (io-error)\r\n(qemu) ") == "paused (io-error)"
    assert w.parse_status("VM status: running") == "running" and w.parse_status("") is None


def test_a_paused_io_error_is_fatal_at_once_not_after_an_hour():
    v = watch().tick(5.0, status="paused (io-error)", device_path="/dev/sdb", digest="a")
    assert v.fatal and "paused (io-error)" in v.fatal


def test_a_drive_that_moved_or_vanished_is_fatal_and_says_where_it_went():
    moved = watch().tick(5.0, status="running", device_path="/dev/sdl", digest="a")
    assert moved.fatal and "/dev/sdb" in moved.fatal and "/dev/sdl" in moved.fatal
    assert "no longer attached" in watch().tick(5.0, status="running", device_path=None, digest="a").fatal


def test_a_healthy_changing_screen_raises_nothing():
    s = watch()
    for t, d in ((10, "0" * 20), (200, "1" * 20), (400, "0" * 10 + "1" * 10)):
        v = s.tick(float(t), status="running", device_path="/dev/sdb", digest=d)
        assert v.fatal is None and v.alerts == []


def test_an_unchanging_screen_is_reported_after_the_stall_time_and_then_at_intervals_not_every_tick():
    s = watch(stall_seconds=300, alert_every=120)
    assert s.tick(1.0, status="running", device_path="/dev/sdb", digest="a").alerts == []
    first = s.tick(301.0, status="running", device_path="/dev/sdb", digest="a")
    assert first.fatal is None and "not changed for 5 min" in first.alerts[0]
    assert s.tick(330.0, status="running", device_path="/dev/sdb", digest="a").alerts == []
    assert s.tick(430.0, status="running", device_path="/dev/sdb", digest="a").alerts
    assert s.tick(500.0, status="running", device_path="/dev/sdb", digest="b").alerts == []      # it changed: quiet again


def test_the_stage_fails_at_its_time_limit():
    assert "exceeded its 1 minute limit" in watch(limit=60).tick(61.0, status="running", device_path="/dev/sdb", digest="a").fatal


def test_an_unreadable_monitor_is_an_alert_not_silence():
    assert watch().tick(5.0, status=None, device_path="/dev/sdb", digest="a").alerts


def test_recent_usb_disconnects_are_counted_inside_the_window_only():
    now = time.mktime(time.strptime("2026 Oct 11 12:40:00", "%Y %b %d %H:%M:%S"))
    text = ("Oct 11 12:32:17 host kernel: usb 2-1: USB disconnect, device number 3\n"
            "Oct 11 12:33:28 host kernel: usb 2-1: new SuperSpeed USB device\n"
            "Oct 11 09:00:00 host kernel: usb 2-1: USB disconnect, device number 2\n")
    assert w.usb_disconnects(text, year=2026, now_epoch=now, window_seconds=600) == 1
    assert w.usb_disconnects(text, year=2026, now_epoch=now, window_seconds=86400) == 2


def _ppm(path, width=64, height=32, lit_blocks=(), cursor=False):
    px = bytearray(width * height * 3)
    for bx, by in lit_blocks:
        for y in range(by * 16, by * 16 + 16):
            for x in range(bx * 16, bx * 16 + 16):
                px[(y * width + x) * 3:(y * width + x) * 3 + 3] = b"\xff\xff\xff"
    if cursor:      # an 8x14 cursor in the bottom-left block
        for y in range(18, 32):
            for x in range(0, 8):
                px[(y * width + x) * 3:(y * width + x) * 3 + 3] = b"\xff\xff\xff"
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode() + bytes(px))
    return path


def test_a_blinking_cursor_is_not_a_change_but_new_text_is(tmp_path):
    idle = w.screen_digest(_ppm(tmp_path / "a.ppm", lit_blocks=[(1, 0)]))
    blink = w.screen_digest(_ppm(tmp_path / "b.ppm", lit_blocks=[(1, 0)], cursor=True))
    assert not w.differs(idle, blink)
    more = w.screen_digest(_ppm(tmp_path / "c.ppm", lit_blocks=[(1, 0), (2, 0), (3, 0), (0, 0)]))
    assert w.differs(idle, more) and w.screen_digest(tmp_path / "missing.ppm") is None


def test_a_cursor_blinking_on_an_idle_prompt_still_counts_as_a_stalled_screen(tmp_path):
    s = watch(stall_seconds=300)
    a = w.screen_digest(_ppm(tmp_path / "a.ppm", lit_blocks=[(1, 0)]))
    b = w.screen_digest(_ppm(tmp_path / "b.ppm", lit_blocks=[(1, 0)], cursor=True))
    s.tick(1.0, status="running", device_path="/dev/sdb", digest=a)
    s.tick(100.0, status="running", device_path="/dev/sdb", digest=b)
    assert "not changed" in s.tick(400.0, status="running", device_path="/dev/sdb", digest=a).alerts[0]


def test_bytes_written_reads_an_image_file_and_the_throughput_line_reports_rate(tmp_path):
    image = tmp_path / "disk.raw"
    with open(image, "wb") as f:
        f.truncate(1 << 30)                      # sparse: nothing allocated yet
        f.seek(0); f.write(b"x" * (8 << 20))
    assert 8 << 20 <= w.bytes_written(image) < 64 << 20
    assert w.bytes_written(tmp_path / "missing") is None
    assert w.throughput_line(0, 6_000_000_000, 60) == "written 5.6 GiB, 100 MB/s"
    assert w.throughput_line(None, 2 ** 30, 60) == "written 1.0 GiB" and w.throughput_line(1, None, 60) == "written: unknown"


def test_only_disconnects_on_the_drives_own_usb_bus_count():
    now = time.mktime(time.strptime("2026 Oct 12 15:50:00", "%Y %b %d %H:%M:%S"))
    text = ("Oct 12 15:47:03 host kernel: usb 2-5.1: USB disconnect, device number 116\n"      # a keyboard hub on another controller
            "Oct 12 15:48:00 host kernel: usb 4-2: USB disconnect, device number 2\n")          # the drive's own bridge
    assert w.usb_disconnects(text, year=2026, now_epoch=now, window_seconds=900) == 2
    assert w.usb_disconnects(text, year=2026, now_epoch=now, window_seconds=900, bus="4") == 1
    assert w.usb_disconnects(text, year=2026, now_epoch=now, window_seconds=900, bus="6") == 0
    assert w.usb_bus_of("/sys/devices/pci0000:00/0000:0d:00.3/usb4/4-2/4-2:1.0/host9/block/sdh") == "4"
    assert w.usb_bus_of("/sys/devices/pci0000:00/nvme/nvme0n1") is None
