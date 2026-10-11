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
    for t, d in ((10, "a"), (200, "b"), (400, "c")):
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
