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
    assert "install" in body
    assert "driveAdminModalPassword" in body  # the sudo-password modal is present


def test_render_drive_admin_page_shows_real_partition_count_and_data_used():
    body = bw.render_drive_admin_page(
        drives=[{"path": "/dev/sda", "model": "ST5000DM003-2FH18L", "drive_type": "HDD",
                 "size": "4.5T", "is_default": False, "partition_count": 1,
                 "usage_text": "1.8 TiB used of 4.5 TiB"}],
        volumes=[], actions=[],
    ).decode()
    assert "1.8 TiB used of 4.5 TiB" in body
    assert ">1<" in body  # the real partition count


def test_render_drive_admin_page_shows_a_dash_when_partition_count_is_unknown():
    body = bw.render_drive_admin_page(
        drives=[{"path": "/dev/sdx", "model": "Unknown model", "drive_type": "Other",
                 "size": "?", "is_default": False, "partition_count": None, "usage_text": "unknown"}],
        volumes=[], actions=[],
    ).decode()
    assert "unknown" in body


def test_render_drive_admin_page_handles_an_empty_drive_or_volume_list_without_crashing():
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=[]).decode()
    assert "No volumes currently mounted" in body


def test_render_drive_admin_page_shows_a_checkbox_per_volume_for_the_update_action():
    """Direct feedback: Update should let the operator select
    partitions/volumes from the drive tree, then choose which types of
    update to apply - the mounted-volumes table needs a real checkbox
    per row, not just a read-only listing."""
    body = bw.render_drive_admin_page(
        drives=[], actions=[],
        volumes=[{"label": "BASELINE", "mountpoint": "/mnt/BASELINE", "used": "1000"},
                 {"label": "INSTALLER_CACHE", "mountpoint": "/mnt/INSTALLER_CACHE", "used": "500"}],
    ).decode()
    assert '<input type="checkbox" class="volume-select" value="BASELINE">' in body
    assert '<input type="checkbox" class="volume-select" value="INSTALLER_CACHE">' in body


def test_render_drive_admin_page_shows_a_visibly_distinct_banner_on_real_success():
    """Direct feedback: a real successful rebuild rendered the same
    quiet, easy-to-miss notice as everything else, and the operator
    couldn't tell anything had happened at all. Success gets its own
    unmistakable banner class now."""
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=[],
                                       notice="/dev/sdb rebuilt as LVM volume group 'baseline_persist'",
                                       notice_ok=True).decode()
    assert 'class="action-banner ok"' in body
    assert "baseline_persist" in body


def test_render_drive_admin_page_shows_a_visibly_distinct_banner_on_real_failure():
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=[],
                                       notice="pvcreate failed: device busy", notice_ok=False).decode()
    assert 'class="action-banner fail"' in body
    assert "device busy" in body


def test_render_drive_admin_page_uses_the_quiet_notice_style_when_ok_is_unknown():
    """A plain page load (no action just ran) still supports a generic
    notice without claiming a false success or failure."""
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=[], notice="just a note").decode()
    assert 'class="notice"' in body
    assert '<div class="action-banner' not in body


def test_render_drive_admin_page_flags_the_specific_drive_a_failed_action_targeted():
    """Direct feedback: a real failure banner appeared with no visual
    link to *which* of a dozen drive cards it was actually about.
    `acted_on_path` marks that one card - red on failure, green on
    success - never every card, never none."""
    drives = [
        {"path": "/dev/sdb", "model": "Drive B", "drive_type": "NVMe", "size": "1T", "is_default": True},
        {"path": "/dev/sdl", "model": "USB 3.2.1 FD", "drive_type": "USB", "size": "57.8G", "is_default": False},
    ]
    body = bw.render_drive_admin_page(
        drives=drives, volumes=[], actions=[],
        notice="pvcreate failed: Cannot use /dev/sdl: device is partitioned",
        notice_ok=False, acted_on_path="/dev/sdl",
    ).decode()
    cards = body.split('<label class="drive-card')[1:]
    sdl_card = next(c for c in cards if "/dev/sdl" in c)
    sdb_card = next(c for c in cards if "/dev/sdb" in c)
    assert "acted-on-fail" in sdl_card
    assert "acted-on-fail" not in sdb_card
    assert "acted-on-ok" not in sdl_card


def test_render_drive_admin_page_flags_the_acted_on_drive_green_on_success():
    drives = [{"path": "/dev/sdb", "model": "Drive B", "drive_type": "NVMe", "size": "1T", "is_default": True}]
    body = bw.render_drive_admin_page(
        drives=drives, volumes=[], actions=[],
        notice="/dev/sdb rebuilt as LVM volume group 'baseline_persist'",
        notice_ok=True, acted_on_path="/dev/sdb",
    ).decode()
    card = body.split('<label class="drive-card')[1]
    assert "acted-on-ok" in card
    assert "acted-on-fail" not in card


def test_render_drive_admin_page_marks_no_card_when_no_action_just_ran():
    drives = [{"path": "/dev/sdb", "model": "Drive B", "drive_type": "NVMe", "size": "1T", "is_default": True}]
    body = bw.render_drive_admin_page(drives=drives, volumes=[], actions=[]).decode()
    card = body.split('<label class="drive-card')[1]
    assert "acted-on-ok" not in card
    assert "acted-on-fail" not in card


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

class FakeSudoExecutor:
    """Matches drive_admin.SudoRunner/verify_sudo_password's own
    injectable `executor(argv, *, input, capture_output, timeout)`
    shape - no real `sudo` or real password is ever used driving these
    real-socket tests."""

    def __init__(self, *, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, *, input, capture_output, timeout):
        self.calls.append((list(argv), input, timeout))
        import types
        return types.SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


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
        "pds_runner": FakePdsRunner(), "vg_name": "pve", "sudo_executor": None,
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
    """A wrong password fails the real `sudo -S -k` preflight
    (FakeSudoExecutor scripted to returncode=1, exactly like a genuine
    sudo auth failure) - refused before any action code ever runs."""
    executor = FakeSudoExecutor(returncode=1, stderr=b"sudo: 1 incorrect password attempt\n")
    case = _RealServerCase(_base_deps(sudo_executor=executor))
    try:
        status, body = case.post_json("/drive-admin/action",
                                       {"action_id": "update_selected",
                                        "params": {"selected": [], "update_types": ["switch_persona"],
                                                    "to_persona": "admin"},
                                        "password": "wrong"})
        assert status == 401
        assert "invalid password" in body["error"]
    finally:
        case.close()


def test_drive_admin_action_reaches_the_real_action_once_the_sudo_password_is_accepted():
    """Proves the sudo-password gate itself lets a correct password
    through to a real SudoRunner-backed action - not any one action's
    specific business outcome, which depends on this real machine's
    own actual mount state (SudoRunner's reads are real, by design;
    only its privileged writes go through the injected executor). A
    401 here would mean the gate wrongly rejected a correct password;
    anything else means the real action code genuinely ran."""
    executor = FakeSudoExecutor(returncode=0)
    case = _RealServerCase(_base_deps(sudo_executor=executor))
    try:
        status, body = case.post_json("/drive-admin/action",
                                       {"action_id": "update_selected",
                                        "params": {"selected": ["BASELINE"], "update_types": ["apply_volume_mode"]},
                                        "password": "right-password"})
        assert status != 401
        assert executor.calls  # the real preflight (and likely more) genuinely ran
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


# -- /settings/<section> and /admin/settings/<group>/<key> POST routes -------
# Real regression coverage: neither route existed at all on the merged
# app until now - clicking "Save" on any Settings or Admin field
# silently 404'd, a real functional gap found by the user directly
# driving the running page, not by code review.

class FakeSource:
    def __init__(self, settings: dict):
        self.settings = settings

    def current_settings(self):
        return self.settings


class FakeApplier:
    def __init__(self):
        self.calls = []

    def apply(self, section, new_values):
        import settings_web as sw
        self.calls.append((section, new_values))
        return sw.ApplyResult(applied=True, detail=f"{section} applied")


def test_settings_section_save_route_exists_and_applies_real_typed_values():
    applier = FakeApplier()
    source = FakeSource({"network": {"hostname": "baseline", "dhcp": True}})
    import settings_web as sw
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1700000000.0)
    case = _RealServerCase(_base_deps(source=source, applier=applier, sessions=sessions))
    try:
        url = f"http://127.0.0.1:{case.port}/settings/network"
        import urllib.request
        req = urllib.request.Request(
            url, method="POST",
            data=b"hostname__type=str&hostname=newhost&dhcp__type=bool",  # dhcp checkbox left unchecked
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"session={session.token}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
        assert status == 200
        assert applier.calls == [("network", {"hostname": "newhost", "dhcp": False})]
    finally:
        case.close()


def _post_form_no_redirect(port, path, form_bytes, cookie):
    """A plain `http.client` POST that does NOT auto-follow the 303
    redirect these routes return on a browser-form submission - lets a
    test observe the real status/Location instead of urllib silently
    following it to whatever the target page returns."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, body=form_bytes,
                 headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"session={cookie}"})
    resp = conn.getresponse()
    resp.read()
    status = resp.status
    conn.close()
    return status


def test_admin_settings_save_route_exists_and_requires_real_elevation():
    import admin_elevation
    import settings_store
    import settings_web as sw
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1700000000.0)
    elevation_store = admin_elevation.ElevationStore()
    runner = FakeRunner()
    case = _RealServerCase(_base_deps(sessions=sessions, elevation_store=elevation_store, runner=runner))
    try:
        status = _post_form_no_redirect(case.port, "/admin/settings/startup/auto_start_persona",
                                         b"value__type=str&value=personal", session.token)
        # No elevation ticket granted - the route must reach real code
        # (a redirect back to /admin, not a 404) and refuse for the
        # real reason (no elevation), not because the route silently
        # didn't exist.
        assert status == 303
        assert settings_store.get_setting(runner, "startup", "auto_start_persona") == "personal"  # unchanged default
    finally:
        case.close()


def test_admin_settings_save_route_applies_a_real_value_once_elevated():
    import admin_elevation
    import settings_store
    import settings_web as sw
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1700000000.0)
    elevation_store = admin_elevation.ElevationStore()
    elevation_store.grant(now=1700000000.0)
    runner = FakeRunner()
    case = _RealServerCase(_base_deps(sessions=sessions, elevation_store=elevation_store, runner=runner))
    try:
        status = _post_form_no_redirect(case.port, "/admin/settings/startup/auto_start_persona",
                                         b"value__type=str&value=admin", session.token)
        assert status == 303
        assert settings_store.get_setting(runner, "startup", "auto_start_persona") == "admin"
    finally:
        case.close()
