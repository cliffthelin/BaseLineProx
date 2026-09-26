"""Unit tests for the Track B3 GUI brokers (notification, clipboard,
file_picker) - see docs/design/milestone-2-gui-plan.md. Each is a small,
separately testable, Runner-injectable module - no real wl-copy/wl-paste,
no real filesystem, matching this project's established FakeRunner style."""
import json

from fake_runner import FakeRunner, FakeProc

from gui_brokers import notification, clipboard, file_picker


# --------------------------------------------------------------------------
# notification
# --------------------------------------------------------------------------

def test_notify_returns_true():
    runner = FakeRunner()
    result = notification.notify(runner, app_id="chromium", summary="Download complete", body="report.pdf")
    assert result is True


def test_notify_durably_logs_the_event():
    runner = FakeRunner()
    notification.notify(runner, app_id="chromium", summary="Download complete", body="report.pdf")
    assert len(runner.appends) == 1
    logged = runner.files[runner.appends[0]]
    rec = json.loads(logged.strip().splitlines()[-1])
    assert rec["app_id"] == "chromium"
    assert rec["summary"] == "Download complete"
    assert rec["body"] == "report.pdf"


def test_notify_appends_multiple_events_without_overwriting():
    runner = FakeRunner()
    notification.notify(runner, app_id="a", summary="one", body="")
    notification.notify(runner, app_id="b", summary="two", body="")
    log_path = runner.appends[0]
    lines = runner.files[log_path].strip().splitlines()
    assert len(lines) == 2


# --------------------------------------------------------------------------
# clipboard
# --------------------------------------------------------------------------

def test_read_clipboard_returns_stdout_on_success():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["wl-paste"], FakeProc(0, "hello clipboard", ""))]
    assert clipboard.read_clipboard(runner) == "hello clipboard"


def test_read_clipboard_returns_empty_string_when_command_fails():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["wl-paste"], FakeProc(1, "", "no clipboard content"))]
    assert clipboard.read_clipboard(runner) == ""


def test_write_clipboard_returns_true_on_success():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["wl-copy"], FakeProc(0, "", ""))]
    assert clipboard.write_clipboard(runner, "new text") is True
    assert runner.calls[-1] == ["wl-copy", "new text"]


def test_write_clipboard_returns_false_on_failure():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["wl-copy"], FakeProc(1, "", "no wayland display"))]
    assert clipboard.write_clipboard(runner, "new text") is False


# --------------------------------------------------------------------------
# file_picker
# --------------------------------------------------------------------------

def test_list_exchange_files_empty_when_dir_empty():
    runner = FakeRunner()
    assert file_picker.list_exchange_files(runner, exchange_dir="/var/lib/baseline/gui-exchange") == []


def test_list_exchange_files_returns_basenames():
    runner = FakeRunner(files={
        "/var/lib/baseline/gui-exchange/report.pdf": "x",
        "/var/lib/baseline/gui-exchange/notes.txt": "y",
    })
    result = file_picker.list_exchange_files(runner, exchange_dir="/var/lib/baseline/gui-exchange")
    assert result == ["notes.txt", "report.pdf"]


def test_pick_exchange_file_returns_path_for_real_listed_file():
    runner = FakeRunner(files={"/var/lib/baseline/gui-exchange/report.pdf": "x"})
    result = file_picker.pick_exchange_file(runner, "report.pdf", exchange_dir="/var/lib/baseline/gui-exchange")
    assert result == "/var/lib/baseline/gui-exchange/report.pdf"


def test_pick_exchange_file_refuses_unlisted_name():
    runner = FakeRunner(files={"/var/lib/baseline/gui-exchange/report.pdf": "x"})
    result = file_picker.pick_exchange_file(runner, "not-there.pdf", exchange_dir="/var/lib/baseline/gui-exchange")
    assert result is None


def test_pick_exchange_file_refuses_path_traversal():
    runner = FakeRunner(files={"/var/lib/baseline/gui-exchange/report.pdf": "x", "/etc/shadow": "secret"})
    result = file_picker.pick_exchange_file(runner, "../../etc/shadow", exchange_dir="/var/lib/baseline/gui-exchange")
    assert result is None
