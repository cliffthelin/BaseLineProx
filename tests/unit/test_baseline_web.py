"""Unit + light integration tests for baseline_web.py - the merged
Baseline web app (decision record 83). Reuses settings_web.py/
control_panel_web.py/drive_admin.py's own already-tested handle_*
functions; this module's own logic under test is the composition
(routing, nav, the Drive Administration page, the sudo-password action
gate) - a handful of real-socket tests prove the dispatch itself
actually works, matching this project's "thin wiring, verified
separately" precedent for its other *_web.py modules.
"""
import json
import threading
import urllib.error
import urllib.request

import pytest
from fake_runner import FakeRunner

import baseline_web as bw
import drive_admin as da


# -- render_nav / _with_nav ---------------------------------------------------

def test_render_nav_marks_the_active_tab():
    nav = bw.render_nav("/drive-admin")
    assert 'class="active">Drive Administration' in nav


def test_with_nav_inserts_right_after_body_tag():
    page = b"<html><body><h1>hi</h1></body></html>"
    result = bw._with_nav(page, "/settings")
    assert result.startswith(b"<html><body><nav")
    assert b"<h1>hi</h1>" in result


def test_with_nav_returns_unchanged_when_no_body_tag_found():
    page = b"not html at all"
    assert bw._with_nav(page, "/settings") == page


# -- real_drive_state / real_volume_state -------------------------------------

class FakePdsRunner:
    def __init__(self, serials_by_path=None):
        self.serials_by_path = serials_by_path or {
            "/dev/sdb": "MD89N41071210AP4E", "/dev/sdd": "FD01N6557110C271B",
        }

    def run(self, argv):
        if argv[0] == "udevadm":
            name_arg = next(a for a in argv if a.startswith("--name="))
            path = name_arg.split("=", 1)[1]
            serial = "BootSerial-999" if path.endswith("nvme0n1") else self.serials_by_path.get(path, "unknown")
            return f"ID_SERIAL_SHORT={serial}\n"
        if argv[0] == "findmnt":
            return "/dev/nvme0n1p2\n"
        if argv[0] == "lsblk":
            return "nvme0n1\n"
        raise AssertionError(f"unexpected: {argv}")

    def lstat(self, path):
        class _Stat:
            st_mode = 0o60000
        return _Stat()

    def realpath(self, path):
        return path

    def read_size_file(self, dev_name):
        return str(500_000_000_000 // 512)


_LSBLK_PAIRS = (
    'NAME="sdb" SIZE="476.9G" MODEL="PC401 NVMe SK hynix 512GB" TRAN="usb" ROTA="1" '
    'SERIAL="MD89N41071210AP4E" TYPE="disk"\n'
    'NAME="sdz" SIZE="4.5T" MODEL="ST5000DM003-2FH18L" TRAN="sata" ROTA="1" '
    'SERIAL="OtherRealSerial-1" TYPE="disk"\n'
)


def test_real_drive_state_lists_every_real_candidate_drive_via_drive_admin():
    from fake_runner import FakeProc
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, _LSBLK_PAIRS, ""))])
    drives = bw.real_drive_state(runner, pds_runner=FakePdsRunner())
    paths = {d["path"] for d in drives}
    assert paths == {"/dev/sdb", "/dev/sdz"}
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["is_default"] is True
    assert by_path["/dev/sdb"]["drive_type"] == "NVMe"
    assert by_path["/dev/sdz"]["is_default"] is False


def test_real_drive_state_returns_empty_list_when_no_runner_is_configured():
    assert bw.real_drive_state(None, pds_runner=FakePdsRunner()) == []


def test_real_volume_state_returns_empty_list_on_a_real_failure_rather_than_crashing():
    assert bw.real_volume_state(FakeRunner()) == []


# -- render_drive_admin_page ---------------------------------------------------

def test_render_drive_admin_page_lists_real_drives_volumes_and_actions():
    body = bw.render_drive_admin_page(
        drives=[{"path": "/dev/sdb", "model": "PC401 NVMe SK hynix 512GB", "drive_type": "NVMe",
                 "size": "476.9G", "is_default": True}],
        volumes=[{"label": "BASELINE", "mountpoint": "/mnt/BASELINE", "used": "1000"}],
        actions=da.describe_actions(),
    ).decode()
    assert "PC401 NVMe SK hynix 512GB" in body
    assert "/dev/sdb" in body
    assert "/mnt/BASELINE" in body
    assert "rebuild_persistence_lvm" in body
    assert "driveAdminModalPassword" in body  # the sudo-password modal is present


def test_render_drive_admin_page_handles_an_empty_drive_or_volume_list_without_crashing():
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=[]).decode()
    assert "No volumes currently mounted" in body


def test_render_drive_admin_page_only_checks_one_radio_when_multiple_drives_are_default():
    """A radio group can only have one genuinely checked option -
    proves only the first is_default drive gets `checked`, even when
    more than one candidate (this project's own two pre-authorized
    drives) both carry is_default=True."""
    body = bw.render_drive_admin_page(
        drives=[
            {"path": "/dev/sdb", "model": "Drive B", "drive_type": "NVMe", "size": "1T", "is_default": True},
            {"path": "/dev/sdd", "model": "Drive D", "drive_type": "NVMe", "size": "1T", "is_default": True},
        ],
        volumes=[], actions=[],
    ).decode()
    assert 'value="/dev/sdb" checked' in body
    assert 'value="/dev/sdd" checked' not in body


# -- a real end-to-end dispatch, over an actual socket ------------------------

class FakeElevationVerifier:
    def __init__(self, correct_password="right-password"):
        self.correct_password = correct_password
        self.calls = []

    def __call__(self, password):
        self.calls.append(password)
        return password == self.correct_password


class _RealServerCase:
    def __init__(self, deps):
        self.server = bw.make_server(deps=deps, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, headers={"Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def post_json(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                      headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _base_deps(**overrides):
    import settings_web as sw
    deps = {
        "verifier": sw.FileBackedPasswordVerifier.__new__(sw.FileBackedPasswordVerifier),
        "source": None, "applier": None, "eligibility": None, "trigger": None, "hasher": None,
        "clock": lambda: 1700000000.0, "sessions": sw.SessionStore(), "store": None,
        "persona_provider": None, "runner": FakeRunner(), "elevation_store": None,
        "elevation_verify_fn": None, "personas": ("admin", "personal"),
        "pds_runner": FakePdsRunner(), "vg_name": "pve",
    }
    deps.update(overrides)
    return deps


def test_drive_admin_page_reachable_over_a_real_socket():
    from fake_runner import FakeProc
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, _LSBLK_PAIRS, ""))])
    case = _RealServerCase(_base_deps(runner=runner))
    try:
        status, body = case.get("/drive-admin")
        assert status == 200
        assert b"/dev/sdb" in body
    finally:
        case.close()


def test_drive_admin_actions_endpoint_returns_real_json():
    case = _RealServerCase(_base_deps())
    try:
        status, body = case.get("/drive-admin/actions")
        assert status == 200
        payload = json.loads(body)
        assert {a["action_id"] for a in payload["actions"]} == set(da.ACTIONS)
    finally:
        case.close()


def test_drive_admin_action_refuses_with_the_wrong_password_over_a_real_socket():
    verifier = FakeElevationVerifier(correct_password="right-password")
    case = _RealServerCase(_base_deps(elevation_verify_fn=verifier))
    try:
        status, body = case.post_json("/drive-admin/action",
                                       {"action_id": "switch_persona", "params": {"to_persona": "admin"},
                                        "password": "wrong"})
        assert status == 401
        assert "invalid password" in body["error"]
    finally:
        case.close()


def test_drive_admin_action_runs_the_real_action_with_the_correct_password():
    verifier = FakeElevationVerifier(correct_password="right-password")
    mounts = "/dev/sdb2 /mnt/USER_PERSISTENCE_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    case = _RealServerCase(_base_deps(elevation_verify_fn=verifier, runner=runner))
    try:
        status, body = case.post_json("/drive-admin/action",
                                       {"action_id": "switch_persona", "params": {"to_persona": "admin"},
                                        "password": "right-password"})
        assert status == 200
        assert body["outcome"] == "applied"
    finally:
        case.close()


# -- build_real_server ---------------------------------------------------------

def test_build_real_server_defaults_to_port_8100(tmp_path):
    import inspect
    assert inspect.signature(bw.build_real_server).parameters["port"].default == 8100


def test_build_real_server_wires_a_real_system_elevation_verifier(tmp_path):
    import settings_web as sw
    real_server = bw.build_real_server(host="127.0.0.1", port=0, data_path=tmp_path / "store.json")
    try:
        assert isinstance(real_server.deps["elevation_verify_fn"], sw.SystemElevationVerifier)
        assert real_server.deps["elevation_verify_fn"].username == "root"
    finally:
        real_server.server_close()


def test_build_real_server_honors_a_custom_elevation_username(tmp_path):
    real_server = bw.build_real_server(host="127.0.0.1", port=0, data_path=tmp_path / "store.json",
                                        elevation_username="cane")
    try:
        assert real_server.deps["elevation_verify_fn"].username == "cane"
    finally:
        real_server.server_close()


def test_build_real_server_wires_the_drive_admin_pds_runner(tmp_path):
    import physical_device_safety as pds
    real_server = bw.build_real_server(host="127.0.0.1", port=0, data_path=tmp_path / "store.json")
    try:
        assert isinstance(real_server.deps["pds_runner"], pds.Runner)
    finally:
        real_server.server_close()
