"""Sign-ins carried from one machine to the others: capture the small files where an application keeps its sign-in, keep them sealed with the person's other secrets, and place them on
another machine that is not signed in yet. A machine that already has a sign-in is never overwritten."""
import base64
import json

import pytest

import signin_share as ss


class Guest:
    """A pretend machine: files by path under its home; `exec` understands the few commands signin_share runs."""
    def __init__(self, files=None, installed=("google-chrome-stable",)):
        self.files = dict(files or {})
        self.installed = set(installed)
        self.log = []

    def exec(self, argv, data=b""):
        self.log.append((argv, data))
        text = " ".join(argv)
        if argv[:2] == ["sh", "-c"] and "command -v" in argv[2] and "echo" in argv[2]:
            return "deb\n" if any(p in argv[2] for p in self.installed) else "flatpak\n"
        if argv[:2] == ["base64", "-w0"]:
            path = argv[3]
            if path not in self.files:
                raise RuntimeError("missing")
            return base64.b64encode(self.files[path]).decode()
        if argv[:2] == ["test", "-e"]:
            if argv[2] not in self.files:
                raise RuntimeError("missing")
            return ""
        if argv[:4] == ["runuser", "-u", "cliff", "--"] and "cat >" in argv[6]:
            self.files[argv[8]] = data
            return ""
        raise AssertionError(text)


HOME = "/home/cliff"
CHROME = ".config/google-chrome"


def signed_in_chrome():
    return Guest({f"{HOME}/{CHROME}/Default/Cookies": b"cookie-bytes", f"{HOME}/{CHROME}/Default/Login Data": b"logins", f"{HOME}/{CHROME}/Local State": b"{}"})


def test_capture_takes_the_signin_files_that_exist_and_names_where_it_came_from():
    bundle = ss.capture(signed_in_chrome().exec, "cliff", "chrome", source="debian")
    names = {f["path"] for f in bundle["files"]}
    assert names == {"Default/Cookies", "Default/Login Data", "Local State"} and bundle["from"] == "debian" and bundle["app"] == "chrome"
    assert base64.b64decode(next(f for f in bundle["files"] if f["path"] == "Default/Cookies")["b64"]) == b"cookie-bytes"


def test_a_machine_that_is_not_signed_in_gives_nothing_to_capture():
    with pytest.raises(ss.SigninError):
        ss.capture(Guest().exec, "cliff", "chrome", source="debian")


def test_apply_places_the_files_for_the_owner_and_leaves_a_signed_in_machine_alone():
    bundle = ss.capture(signed_in_chrome().exec, "cliff", "chrome", source="debian")
    target = Guest()
    report = ss.apply(target.exec, "cliff", bundle)
    assert report["applied"] and target.files[f"{HOME}/{CHROME}/Default/Cookies"] == b"cookie-bytes"
    again = ss.apply(target.exec, "cliff", bundle)
    assert again["applied"] == [] and "already signed in" in again["skipped"]


def test_apply_goes_to_the_flatpak_folder_when_that_is_how_chrome_is_installed_there():
    bundle = ss.capture(signed_in_chrome().exec, "cliff", "chrome", source="debian")
    target = Guest(installed=())
    ss.apply(target.exec, "cliff", bundle)
    assert f"{HOME}/.var/app/com.google.Chrome/config/google-chrome/Default/Cookies" in target.files


def test_file_names_in_a_bundle_cannot_leave_the_applications_folder():
    bad = {"app": "chrome", "from": "x", "at": "t", "files": [{"path": "../../.ssh/authorized_keys", "b64": base64.b64encode(b"x").decode()}]}
    with pytest.raises(ss.SigninError):
        ss.apply(Guest().exec, "cliff", bad)
    with pytest.raises(ss.SigninError):
        ss.apply(Guest().exec, "cliff", {"app": "nothing", "files": []})


def test_the_owner_name_is_a_plain_account_name():
    with pytest.raises(ss.SigninError):
        ss.capture(Guest().exec, "../root", "chrome", source="x")


def test_the_store_seals_with_the_passphrase_and_refuses_to_keep_plain_when_a_passphrase_is_set(tmp_path):
    bundle = ss.capture(signed_in_chrome().exec, "cliff", "chrome", source="debian")
    plain = ss.Store(tmp_path / "plain")
    plain.save(bundle)
    assert plain.load("chrome")["from"] == "debian" and plain.apps() == ["chrome"]
    sealed = ss.Store(tmp_path / "sealed", passphrase="correct horse battery")
    sealed.save(bundle)
    raw = next((tmp_path / "sealed").iterdir()).read_bytes()
    assert b"cookie" not in raw and base64.b64encode(b"cookie-bytes") not in raw
    assert ss.Store(tmp_path / "sealed", passphrase="correct horse battery").load("chrome")["app"] == "chrome"
    with pytest.raises(ss.Locked):
        ss.Store(tmp_path / "sealed").load("chrome")
    assert oct((tmp_path / "sealed").stat().st_mode & 0o777) == "0o700"


def test_chrome_and_claude_start_with_a_store_every_machine_shares():
    files = {f["path"]: f for f in ss.wrapper_files("chrome")}
    assert "--password-store=basic" in files["/usr/local/bin/google-chrome-stable"]["content"]
    assert files["/usr/local/bin/google-chrome-stable"]["permissions"] == "0755"
    assert "/usr/local/bin/google-chrome-stable" in files["/usr/local/share/applications/google-chrome.desktop"]["content"]
    assert ss.wrapper_files("vscode") == []


class FakeHost:
    def __init__(self, guests, running=None):
        self.guests, self.running = guests, running or set(guests)

    def list_vms(self):
        return [{"name": n, "running": n in self.running} for n in self.guests]

    def guest_exec(self, name, argv, data=b""):
        if name not in self.running:
            raise RuntimeError("not running")
        return {"out-data": self.guests[name].exec(argv, data)}


def test_a_saved_signin_reaches_every_running_machine_that_has_none(tmp_path):
    src, a, b, off = signed_in_chrome(), Guest(), signed_in_chrome(), Guest()
    host = FakeHost({"src": src, "a": a, "b": b, "off": off}, running={"src", "a", "b"})
    store = ss.Store(tmp_path / "s")
    assert ss.capture_from(host, store, "cliff", "chrome", "src")["files"] == 3
    report = ss.apply_to_running(host, store, "cliff")
    assert report["a"]["chrome"]["applied"] and "already signed in" in report["b"]["chrome"]["skipped"] and "off" not in report
    assert a.files[f"{HOME}/{CHROME}/Default/Cookies"] == b"cookie-bytes" and off.files == {}


def test_one_machine_failing_is_reported_and_the_rest_still_get_theirs(tmp_path):
    src, good = signed_in_chrome(), Guest()
    class Bad(Guest):
        def exec(self, argv, data=b""):
            raise RuntimeError("guest agent did not answer")
    host = FakeHost({"src": src, "bad": Bad(), "good": good})
    store = ss.Store(tmp_path / "s")
    ss.capture_from(host, store, "cliff", "chrome", "src")
    report = ss.apply_to_running(host, store, "cliff")
    assert "error" in report["bad"]["chrome"] and report["good"]["chrome"]["applied"]
