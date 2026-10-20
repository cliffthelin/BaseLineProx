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
from pathlib import Path

import pytest
from fake_runner import FakeProc, FakeRunner

import baseline_web as bw
import drive_admin as da


# -- render_nav / _with_nav ---------------------------------------------------

def test_render_nav_marks_the_active_tab():
    nav = bw.render_nav("/drive-admin")
    assert 'href="/drive-admin" class="active"' in nav and "Drive Administration" in nav


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
    def __init__(self, serials_by_path=None, drive_table="sdb disk  11111111-2222-3333-4444-555555555555 \n"):
        self.drive_table = drive_table
        self.serials_by_path = serials_by_path or {
            "/dev/sdb": "SYNTHDRIVEA00001", "/dev/sdd": "SYNTHDRIVEA00001",
        }

    def run(self, argv):
        if argv[0] == "udevadm":
            name_arg = next(a for a in argv if a.startswith("--name="))
            path = name_arg.split("=", 1)[1]
            serial = "BootSerial-999" if path.endswith("nvme0n1") else self.serials_by_path.get(path, "unknown")
            return f"ID_SERIAL_SHORT={serial}\n"
        if argv[0] == "findmnt":
            return "/dev/nvme0n1p2\n"
        if argv[0] == "lsblk" and "NAME,TYPE,FSTYPE,PTUUID,LABEL" in argv:
            return self.drive_table          # what is ON the drive: blank unless a test says otherwise
        if argv[0] == "lsblk":
            return "nvme0n1\n" if argv[-1] == "/dev/nvme0n1p2" else ""
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
    'SERIAL="SYNTHDRIVEA00001" TYPE="disk"\n'
    'NAME="sdz" SIZE="4.5T" MODEL="ST5000DM003-2FH18L" TRAN="sata" ROTA="1" '
    'SERIAL="OtherRealSerial-1" TYPE="disk"\n'
)


def test_real_drive_state_lists_every_real_candidate_drive_via_drive_admin():
    from fake_runner import FakeProc
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, _LSBLK_PAIRS, ""))])
    drives = bw.real_drive_state(runner, pds_runner=FakePdsRunner())
    paths = {d["path"] for d in drives}
    assert paths == {"/dev/sdb"}          # only the allowed SK hynix drive; /dev/sdz is never offered
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["is_default"] is True
    assert by_path["/dev/sdb"]["drive_type"] == "NVMe"


def test_real_drive_state_reports_missing_runner_instead_of_empty_inventory():
    with pytest.raises(bw.DriveInventoryError, match="runner unavailable"):
        bw.real_drive_state(None, pds_runner=FakePdsRunner())


def test_real_volume_state_returns_the_full_planned_volume_list_even_when_nothing_exists_yet():
    """collect_volume_details always returns one entry per planned
    volume, existing or not - a bare FakeRunner (nothing created, real
    lvs/df calls returning empty output) is a real, honest "not
    provisioned yet" state, not a failure."""
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["findmnt"], FakeProc(0, '{"filesystems": []}', "")),
    ])
    details = bw.real_volume_state(runner)
    assert len(details) == 8
    assert all(d["lv_exists"] is False for d in details)


def test_real_volume_state_reports_missing_runner_instead_of_empty_inventory():
    with pytest.raises(bw.VolumeInventoryError, match="runner unavailable"):
        bw.real_volume_state(None)


def test_real_volume_state_preserves_real_probe_error_instead_of_empty_inventory():
    class ExplodingRunner:
        def run(self, *a, **k):
            raise RuntimeError("real subprocess failure")
    with pytest.raises(bw.VolumeInventoryError, match="real subprocess failure"):
        bw.real_volume_state(ExplodingRunner())


def test_drive_admin_page_displays_volume_inventory_error():
    page = bw.render_drive_admin_page(drives=[], volumes=[], volume_error="lvs permission denied",
                                      actions=[], daily_ok=True)
    assert b"Volume inventory failed" in page
    assert b"lvs permission denied" in page


def test_drive_admin_page_displays_drive_inventory_error():
    page = bw.render_drive_admin_page(drives=[], volumes=[], drive_error="lsblk permission denied",
                                      actions=[], daily_ok=True)
    assert b"Drive inventory failed" in page
    assert b"lsblk permission denied" in page
    assert b"No eligible drives were found" not in page


def test_drive_admin_route_shows_failed_drive_probe_as_unknown_inventory():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lsblk"], FakeProc(1, "", "lsblk permission denied")),
    ])
    case = _RealServerCase(_base_deps(runner=runner))
    try:
        status, body = case.get("/drive-admin")
        assert status == 200
        assert b"Drive inventory failed" in body
        assert b"lsblk permission denied" in body
        assert b"No eligible drives were found" not in body
    finally:
        case.close()


# -- render_drive_admin_page ---------------------------------------------------

def test_render_drive_admin_page_groups_baseline_drives_at_the_top():
    """Direct instruction, 2026-09-29: a real Baseline-installed drive
    goes at the top of the drive list, under a "Baseline Installed"
    heading."""
    body = bw.render_drive_admin_page(
        drives=[
            {"path": "/dev/sda", "model": "Other Drive", "drive_type": "HDD", "size": "1T",
             "is_default": False, "is_baseline_drive": False},
            {"path": "/dev/sdd", "model": "Baseline Drive", "drive_type": "NVMe", "size": "476.9G",
             "is_default": True, "is_baseline_drive": True, "missing_baseline_volumes": []},
        ],
        volumes=[], actions=[],
    ).decode()
    assert "Baseline Installed" in body
    baseline_heading_pos = body.index("Baseline Installed")
    sdd_pos = body.index("/dev/sdd")
    sda_pos = body.index("/dev/sda")
    assert baseline_heading_pos < sdd_pos < sda_pos


def test_render_drive_admin_page_shows_a_baseline_pill_and_missing_volumes():
    body = bw.render_drive_admin_page(
        drives=[{"path": "/dev/sdd", "model": "Baseline Drive", "drive_type": "NVMe", "size": "476.9G",
                 "is_default": True, "is_baseline_drive": True,
                 "missing_baseline_volumes": ["baseline_installer_cache", "baseline_session_temp"]}],
        volumes=[], actions=[],
    ).decode()
    assert "Baseline drive" in body
    assert "baseline_installer_cache" in body
    assert "baseline_session_temp" in body


def test_render_drive_admin_page_does_not_group_when_no_drive_is_a_baseline_drive():
    body = bw.render_drive_admin_page(
        drives=[{"path": "/dev/sda", "model": "Other Drive", "drive_type": "HDD", "size": "1T",
                 "is_default": True, "is_baseline_drive": False}],
        volumes=[], actions=[],
    ).decode()
    assert "Baseline Installed" not in body


def test_render_drive_admin_page_hides_update_selected_action_card_by_default():
    """Direct instruction, 2026-09-29: "Update options are only shown
    when a Baseline drive is selected" - hidden server-side by default,
    JS reveals it only when the selected drive is a real Baseline
    drive."""
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=da.describe_actions()).decode()
    card_start = body.index('data-action-card-id="update_selected"')
    # the `hidden` attribute must appear on the same opening tag
    tag = body[body.rindex("<div", 0, card_start):body.index(">", card_start)]
    assert "hidden" in tag


def test_render_drive_admin_page_lists_real_drives_volumes_and_actions():
    body = bw.render_drive_admin_page(
        drives=[{"path": "/dev/sdb", "model": "PC401 NVMe SK hynix 512GB", "drive_type": "NVMe",
                 "size": "476.9G", "is_default": True}],
        volumes=[{"label": "BASELINE", "mountpoint": "/mnt/BASELINE", "lv_name": "baseline_app_state",
                   "lv_exists": True, "lv_size_bytes": 5368709120, "total_bytes": 5368709120,
                   "used_bytes": 1073741824, "percent_used": 20.0}],
        actions=da.describe_actions(),
    ).decode()
    assert "PC401 NVMe SK hynix 512GB" in body
    assert "/dev/sdb" in body
    assert "/mnt/BASELINE" in body
    assert "install" in body
    assert "driveAdminModalConfirm" in body  # the confirm modal is present
    assert "driveAdminModalPassword" not in body  # no password field - real pkexec native dialog instead


def test_render_drive_admin_page_offers_the_serial_checked_partition_unmount_action():
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=da.describe_actions()).decode()
    assert 'data-action-card-id="unmount_partition"' in body
    assert 'function partitionUnmountParamsHtml()' in body
    assert 'params.partition_mountpoint' in body
    assert 'function askForNativePolicyKit(challenge)' in body
    assert '"/drive-admin/execute-native"' in body


def test_render_drive_admin_page_exposes_a_collapsed_overrides_section_for_technicians():
    """Direct instruction: technical fields (serial, source ISO path,
    cert/key paths, server host, MAC/DMI override) "should not be
    invisible to a technician/developer but should be hidden away in
    an override tab" - a real, always-rendered <details> disclosure,
    collapsed by default (no `open` attribute), gated to
    build_self_installer specifically since that's the only action
    with technical params to override."""
    body = bw.render_drive_admin_page(
        drives=[{"path": "/dev/sdb", "model": "PC401 NVMe SK hynix 512GB", "drive_type": "NVMe",
                 "size": "476.9G", "is_default": True}],
        volumes=[], actions=da.describe_actions(),
    ).decode()
    assert "overridesHtml" in body
    assert '<details class="overrides">' in body  # the real markup overridesHtml() builds
    assert "<details class=\"overrides\" open>" not in body  # collapsed by default, not forced open
    assert 'if (pendingActionId === "build_self_installer") extra = overridesHtml();' in body
    assert "SELF_INSTALLER_OVERRIDE_FIELDS" in body
    for param in ("expected_serial", "proxmox_source_iso", "server_host", "cert_path", "key_path",
                  "target_mac", "target_dmi_product"):
        assert param in body


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
    assert "No volume records were returned" in body


def test_render_drive_admin_page_only_allows_the_volume_that_holds_updateable_packages():
    body = bw.render_drive_admin_page(
        drives=[], actions=[],
        volumes=[{"label": "BASELINE", "mountpoint": "/mnt/BASELINE", "lv_name": "baseline_app_state",
                  "lv_exists": True, "lv_size_bytes": 5368709120, "total_bytes": None,
                  "used_bytes": None, "percent_used": None},
                 {"label": "INSTALLER_CACHE", "mountpoint": "/mnt/INSTALLER_CACHE",
                  "lv_name": "baseline_installer_cache", "lv_exists": False, "lv_size_bytes": None,
                  "total_bytes": None, "used_bytes": None, "percent_used": None}],
    ).decode()
    assert '<input type="checkbox" class="volume-select" value="BASELINE" disabled' in body
    assert '<input type="checkbox" class="volume-select" value="INSTALLER_CACHE">' in body
    assert 'querySelectorAll(".volume-select:not(:disabled)")' in body
    assert "Only INSTALLER_CACHE stores updateable Debian package artifacts" in body
    assert "host&#x27;s configured repository trust policy" in body or "host's configured repository trust policy" in body


def test_render_drive_admin_page_shows_real_lv_name_and_size_in_the_detail_row():
    body = bw.render_drive_admin_page(
        drives=[], actions=[],
        volumes=[{"label": "BASELINE", "mountpoint": "/mnt/BASELINE", "lv_name": "baseline_app_state",
                  "lv_exists": True, "lv_size_bytes": 5368709120, "total_bytes": None,
                  "used_bytes": None, "percent_used": None}],
    ).decode()
    assert "baseline_app_state" in body
    assert "allocated" in body


def test_render_drive_admin_page_reports_a_not_yet_created_volume_honestly():
    body = bw.render_drive_admin_page(
        drives=[], actions=[],
        volumes=[{"label": "INSTALLER_CACHE", "mountpoint": "/mnt/INSTALLER_CACHE",
                  "lv_name": "baseline_installer_cache", "lv_exists": False, "lv_size_bytes": None,
                  "total_bytes": None, "used_bytes": None, "percent_used": None}],
    ).decode()
    assert "not created yet" in body
    assert "not mounted" in body


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
    """Matches drive_admin.PkexecRunner's own injectable
    `executor(argv, *, input, capture_output, timeout)` shape - no real
    `pkexec` or real password is ever used driving these real-socket
    tests. Name kept as `FakeSudoExecutor` (a real pre-pkexec-migration
    name) since it's still exactly what `drive_admin.SudoRunner`
    (still real and in use by `settings_web.SudoPasswordVerifier` for
    login) needs too - one shape, two real callers."""

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
        # Every route but the login screen needs a session, so the harness
        # logs in by default; test_baseline_web_auth_gate.py covers the
        # unauthenticated side by sending its own requests.
        import hitl
        if "hitl" not in deps:
            # min_wait_s=0 here only so the many harness tests need not sleep; the real minimum wait is covered in
            # test_hitl_web.py. The secret is the one a person would type.
            deps["hitl"] = hitl.ConfirmationStore(verify_secret=lambda s: s == "test-secret", clock=deps["clock"], min_wait_s=0)
        sessions = deps["sessions"]
        if not sessions.sessions:
            sessions.create("root", now=deps["clock"]())
        self.token = next(iter(sessions.sessions))
        self.server = bw.make_server(deps=deps, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, headers={"Accept": "text/html", "Cookie": f"session={self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def post_json(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                      headers={"Content-Type": "application/json", "Cookie": f"session={self.token}",
                                              "Origin": f"http://127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def drive_action(self, action_id, params, secret="test-secret"):
        """Request a drive action and confirm it the way a person must: the request only produces a challenge;
        the confirm step (typed phrase + root password) is what starts it."""
        status, body = self.post_json("/drive-admin/action", {"action_id": action_id, "params": params})
        if body.get("outcome") != "confirmation_required":
            return status, body
        chal = body["challenge"]
        return self.post_json("/drive-admin/confirm",
                              {"challenge_id": chal["id"], "typed": chal["phrase"], "secret": secret})

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
        "pds_runner": FakePdsRunner(), "vg_name": "pve", "pkexec_executor": None,
        "recovery_store": None, "recovery_verify_fn": None,
    }
    import web_gate
    gate = web_gate.WebGate(b"b" * 32, clock=lambda: deps["clock"]())
    web_gate.configure(gate)
    deps["web_gate"] = gate
    deps.update(overrides)
    return deps


def test_host_restart_route_requests_desktop_confirmation():
    from test_host_restart import runner_for
    runner = runner_for()
    case = _RealServerCase(_base_deps(runner=runner))
    try:
        status, body = case.post_json('/host/restart', {})
        assert status == 200
        assert body['outcome'] == 'confirmation_requested'
        assert runner.calls[-1][-2:] == ['gnome-session-quit', '--reboot']
    finally:
        case.close()


def test_host_restart_route_requires_login():
    from test_host_restart import runner_for
    runner = runner_for()
    case = _RealServerCase(_base_deps(runner=runner))
    try:
        case.token = 'not-a-session'
        status, body = case.post_json('/host/restart', {})
        assert status == 401
        assert runner.calls == []
    finally:
        case.close()


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


def _poll_job(case, job_id, *, max_tries=100):
    import time as _time
    job = None
    for _ in range(max_tries):
        _, raw = case.get(f"/drive-admin/job-log?job_id={job_id}")
        job = json.loads(raw)
        if job["done"]:
            break
        _time.sleep(0.02)
    return job


def test_drive_admin_action_reports_a_real_refusal_when_pkexec_authentication_fails():
    """Direct instruction, 2026-09-29: "Make the application ask for
    the sudo password through Ubuntu best practices" - there's no
    separate password-verification HTTP step any more (`PkexecRunner`
    has no password to check at all; PolicyKit's own native agent
    handles that entirely outside this app). A cancelled/failed
    authentication surfaces as the underlying privileged command's own
    non-zero exit (simulated here via a scripted `FakeSudoExecutor`
    returncode), which the existing job/ActionResult machinery reports
    as a real refusal - never a special-cased 401 at the HTTP layer."""
    executor = FakeSudoExecutor(returncode=127, stderr=b"Not authorized\n")
    case = _RealServerCase(_base_deps(pkexec_executor=executor))
    try:
        status, body = case.drive_action("repair", {"device_path": "/dev/sdb"})
        assert status == 200  # the job itself always starts - the outcome comes later
        job = _poll_job(case, body["job_id"])
        assert job["outcome"] == "refused"
    finally:
        case.close()


def test_drive_admin_action_returns_a_job_id_immediately_instead_of_blocking():
    """Direct instruction, 2026-09-29: a long-running action used to
    block the whole request with zero feedback - now it starts in the
    background and the request returns immediately with a job_id."""
    executor = FakeSudoExecutor(returncode=0)
    case = _RealServerCase(_base_deps(pkexec_executor=executor))
    try:
        status, body = case.drive_action("update_selected", {"selected": []})
        assert status == 200
        assert body["outcome"] == "started"
        assert body["job_id"]
    finally:
        case.close()


def test_drive_admin_job_log_reports_real_completion_for_a_started_job():
    executor = FakeSudoExecutor(returncode=0)
    case = _RealServerCase(_base_deps(pkexec_executor=executor))
    try:
        status, body = case.drive_action("update_selected", {"selected": []})
        job = _poll_job(case, body["job_id"])
        assert job is not None and job["done"] is True
        assert job["outcome"] in ("applied", "refused")
        assert isinstance(job["lines"], list)
    finally:
        case.close()


def test_drive_admin_job_log_returns_404_for_an_unknown_job_id():
    case = _RealServerCase(_base_deps())
    try:
        status, _ = case.get("/drive-admin/job-log?job_id=totally-unknown")
        assert status == 404
    finally:
        case.close()


def test_drive_admin_screendump_returns_404_when_no_install_is_running(tmp_path):
    case = _RealServerCase(_base_deps())
    try:
        status, body = case.get(f"/drive-admin/screendump?workspace={tmp_path}")
        assert status == 404
        assert "no active install" in json.loads(body)["error"]
    finally:
        case.close()


def test_drive_admin_screendump_returns_a_real_png_when_an_install_is_running(tmp_path):
    """Direct instruction, 2026-09-29: "keep things improving" - the
    real fix for the manual `nc screendump ...\\nquit\\n` mistake that
    killed a real in-progress install. Real Unix socket server stands
    in for QEMU's own monitor, proving the full route only ever sends
    the one real `screendump` command."""
    import socket
    import threading

    monitor_socket = tmp_path / "monitor.sock"

    def _serve():
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(monitor_socket))
        srv.listen(1)
        conn, _ = srv.accept()
        conn.sendall(b"(qemu) ")
        data = conn.recv(4096)
        assert b"quit" not in data
        # The real command is "screendump <path>\n" - write the fake
        # PPM to whatever path the server actually requested, exactly
        # as real QEMU would.
        requested_path = data.decode().split(" ", 1)[1].strip()
        Path(requested_path).write_bytes(b"P6\n1 1\n255\n" + bytes((1, 2, 3)))
        conn.sendall(b"\r\n(qemu) ")
        conn.close()
        srv.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    import time as _time
    _time.sleep(0.1)
    case = _RealServerCase(_base_deps())
    try:
        status, body = case.get(f"/drive-admin/screendump?workspace={tmp_path}")
        assert status == 200
        assert body.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        case.close()
        t.join(timeout=2.0)


def test_drive_admin_action_reaches_the_real_action_via_a_real_pkexec_runner():
    """Proves the server actually constructs a real `PkexecRunner` and
    dispatches to it - not any one action's specific business outcome.
    `repair` is used since it genuinely calls `runner.run()` (via
    `find_vg_for_device`'s real `pvs` call). The cache update action
    also reaches the runner now, but this test isolates the drive-action
    dispatch path from APT/cache behavior."""
    executor = FakeSudoExecutor(returncode=0, stdout="")
    case = _RealServerCase(_base_deps(pkexec_executor=executor))
    try:
        status, body = case.drive_action("repair", {"device_path": "/dev/sdb"})
        assert status == 200
        job = _poll_job(case, body["job_id"])
        assert job["done"] is True
        assert executor.calls  # the real pkexec-wrapped call genuinely ran
        assert executor.calls[0][0][0] == "pkexec"  # via pkexec, never a piped password
    finally:
        case.close()


# -- build_real_server ---------------------------------------------------------

def test_build_real_server_defaults_to_port_8100(tmp_path):
    import inspect
    assert inspect.signature(bw.build_real_server).parameters["port"].default == 8100


def test_build_real_server_wires_a_real_system_elevation_verifier(tmp_path):
    import settings_web as sw
    real_server = bw.build_real_server(host="127.0.0.1", port=0, data_path=tmp_path / "store.json", state_dir=tmp_path / "state")
    try:
        assert isinstance(real_server.deps["elevation_verify_fn"], sw.SystemElevationVerifier)
        assert real_server.deps["elevation_verify_fn"].username == "root"
    finally:
        real_server.server_close()


def test_build_real_server_honors_a_custom_elevation_username(tmp_path):
    real_server = bw.build_real_server(host="127.0.0.1", port=0, data_path=tmp_path / "store.json", state_dir=tmp_path / "state",
                                        elevation_username="cane")
    try:
        assert real_server.deps["elevation_verify_fn"].username == "cane"
    finally:
        real_server.server_close()


def test_build_real_server_wires_the_drive_admin_pds_runner(tmp_path):
    import physical_device_safety as pds
    real_server = bw.build_real_server(host="127.0.0.1", port=0, data_path=tmp_path / "store.json", state_dir=tmp_path / "state")
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
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"session={session.token}",
                     "Origin": f"http://127.0.0.1:{case.port}"},
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
                 headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"session={cookie}",
                          "Origin": f"http://127.0.0.1:{port}"})
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
        assert settings_store.get_setting("startup", "auto_start_persona") == "personal"  # unchanged default
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
        assert settings_store.get_setting("startup", "auto_start_persona") == "admin"
    finally:
        case.close()


# -- Hardware tab (direct instruction, 2026-09-29: health check moves out of ---
# -- Drive Administration into its own tab that just shows current state) -----

def test_real_hardware_state_uses_the_real_runner_when_none_is_injected(monkeypatch):
    import repair
    runner = FakeRunner()
    monkeypatch.setattr(repair, "RealRunner", lambda: runner)
    state = bw.real_hardware_state(None)
    assert "errors" in state
    assert state["sysinfo"].get("kernel") is None
    assert any(item["source"] == "kernel" for item in state["errors"])
    assert any(call[0] == "uname" for call in runner.calls)


def test_real_hardware_state_preserves_collector_failures_and_renders_them(monkeypatch):
    import dependencies
    import diagnostics
    import hardware_inventory
    monkeypatch.setattr(dependencies, "run_checks", lambda **kw: (_ for _ in ()).throw(OSError("dependency probe")))
    monkeypatch.setattr(diagnostics, "collect_sensors", lambda runner: (_ for _ in ()).throw(OSError("sensor probe")))
    monkeypatch.setattr(diagnostics, "collect_nvme", lambda runner: (_ for _ in ()).throw(OSError("nvme probe")))
    monkeypatch.setattr(diagnostics, "collect_smart", lambda runner: (_ for _ in ()).throw(OSError("smart probe")))
    monkeypatch.setattr(hardware_inventory, "collect_all", lambda runner: (_ for _ in ()).throw(OSError("inventory probe")))
    state = bw.real_hardware_state(FakeRunner())
    sources = {item["source"] for item in state["errors"]}
    assert {"dependencies", "sensors", "nvme", "smart", "hardware inventory"} <= sources
    assert state["sensors"] is None and state["nvme"] is None and state["smart"] is None
    body = bw.render_hardware_page(**state).decode()
    for name in sources:
        assert name in body
    assert "probe failed" in body


def test_real_hardware_state_reports_real_dependency_results():
    state = bw.real_hardware_state(FakeRunner())
    assert isinstance(state["dependency_results"], list)
    assert any(r["id"] == "system.sqlite3_importable" for r in state["dependency_results"])


def test_render_hardware_page_shows_a_failing_dependency_as_a_danger_card():
    body = bw.render_hardware_page(
        dependency_results=[{"id": "self_installer.lvm_size_preset_valid", "ok": False, "detail": "bad value"}],
        sensors=None, nvme=None, smart=None,
    ).decode()
    assert "self_installer.lvm_size_preset_valid" in body
    assert "bad value" in body
    assert "danger" in body


def test_render_hardware_page_reports_an_unavailable_collector_honestly():
    body = bw.render_hardware_page(dependency_results=[], sensors=None, nvme=None, smart=None).decode()
    assert "Not available" in body


def test_render_hardware_page_has_no_run_button_it_just_shows():
    body = bw.render_hardware_page(dependency_results=[], sensors=None, nvme=None, smart=None).decode()
    assert "Run&hellip;" not in body


def test_render_drive_admin_page_css_actually_hides_a_hidden_action_card():
    """Real bug found live: `.action-card { display: flex }` overrode
    the native `[hidden]` attribute's default `display: none` (equal
    CSS specificity, author style wins over the UA default regardless
    of the attribute) - the update_selected card had `hidden=true` in
    the DOM but was still visually showing. An explicit
    `.action-card[hidden] { display: none; }` rule is required."""
    body = bw.render_drive_admin_page(drives=[], volumes=[], actions=[]).decode()
    assert ".action-card[hidden]" in body


# -- Installer Cache tab (direct instruction, 2026-09-30: show all -----
# -- software/packages/OS distros/drivers with their original installer,
# -- what is on the volume now, and a Refresh-with-Root button) --------

def _cache_report(*, mounted=True, present_ids=()):
    import installer_cache as ic
    report = ic.CacheReport(
        root="/mnt/INSTALLER_CACHE", mounted=mounted,
        mount_detail="mounted from /dev/sdd2 ext4" if mounted else
                     "/mnt/INSTALLER_CACHE is NOT a mount point - it is a plain directory",
    )
    for entry in ic.catalog():
        hit = entry.entry_id in present_ids
        report.rows.append(ic.Presence(entry, hit, entry.cache_path if hit else "",
                                       1024 if hit else 0,
                                       "on the volume" if hit else "not on the volume"))
    return report


def test_installer_cache_tab_is_in_the_nav():
    assert any(path == "/installer-cache" for path, _ in bw.NAV_TABS)


def test_installer_cache_page_shows_a_present_and_a_missing_artifact():
    body = bw.render_installer_cache_page(
        _cache_report(present_ids={"proxmox-ve-source"})).decode()
    assert "on volume" in body
    assert "missing" in body
    assert "Proxmox VE" in body


def test_installer_cache_page_names_each_artifacts_original_installer():
    """The instruction asked for the original installer, the install
    helper and the configuration - all three must reach the page."""
    body = bw.render_installer_cache_page(_cache_report()).decode()
    assert "Original installer / source" in body
    assert "Install helper" in body
    assert "Configuration" in body
    assert "enterprise.proxmox.com" in body


def test_installer_cache_page_warns_loudly_when_the_volume_is_not_mounted():
    body = bw.render_installer_cache_page(_cache_report(mounted=False)).decode()
    assert "Not a mount point" in body
    assert "ic-banner warn" in body


def test_installer_cache_page_shows_scan_failure_without_claiming_everything_missing():
    import installer_cache as ic
    report = ic.CacheReport(root="/mnt/INSTALLER_CACHE", mounted=True,
                            mount_detail="mounted from /dev/cache", scanned_ok=False,
                            scan_detail="permission denied while listing packages")
    body = bw.render_installer_cache_page(report).decode()
    assert "Cache inventory failed" in body
    assert "permission denied while listing packages" in body
    assert "required for a build" not in body
    assert "not on the volume" not in body


def test_installer_cache_page_confirms_a_real_mount():
    body = bw.render_installer_cache_page(_cache_report(mounted=True)).decode()
    assert "ic-banner ok" in body
    assert "/dev/sdd2" in body


def test_installer_cache_page_has_a_refresh_with_root_button():
    body = bw.render_installer_cache_page(_cache_report()).decode()
    assert "Refresh with Root" in body
    assert "/installer-cache?root=1" in body


def test_installer_cache_page_lists_uncatalogued_files_rather_than_hiding_them():
    import installer_cache as ic
    report = _cache_report()
    report.extras.append(ic.Uncatalogued("isos/omarchy-4.0.4.iso", 6185304064))
    body = bw.render_installer_cache_page(report).decode()
    assert "omarchy-4.0.4.iso" in body
    assert "not in the catalog" in body


def test_installer_cache_route_renders_without_a_runner_instead_of_crashing():
    deps = _base_deps(runner=None)
    case = _RealServerCase(deps)
    try:
        status, body = case.get("/installer-cache")
        assert status == 200
        assert b"Installer Cache" in body
    finally:
        case.close()


def test_installer_cache_route_renders_failed_scan_as_unknown_inventory():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["findmnt"], FakeProc(0, "/dev/cache ext4\n", "")),
        (lambda a: a[:1] == ["ls"] and a[-1].endswith("/isos"), FakeProc(2, "", "Permission denied")),
    ])
    case = _RealServerCase(_base_deps(runner=runner))
    try:
        status, body = case.get("/installer-cache")
        assert status == 200
        assert b"Cache inventory failed" in body
        assert b"no artifacts are marked present or missing" in body
        assert b"required for a build" not in body
    finally:
        case.close()


def test_installer_cache_route_uses_pkexec_only_when_root_is_requested():
    """?root=1 must go through PkexecRunner (PolicyKit's own agent),
    and a plain refresh must not escalate at all."""
    escalated = []

    class _Spy:
        def __init__(self, *a, **kw):
            escalated.append(True)

        def run(self, argv, timeout=10):
            import subprocess
            return subprocess.CompletedProcess(argv, 1, "", "")

    deps = _base_deps()
    case = _RealServerCase(deps)
    original = da.PkexecRunner
    da.PkexecRunner = _Spy
    try:
        case.get("/installer-cache")
        assert escalated == [], "a plain refresh must not escalate"
        case.get("/installer-cache?root=1")
        assert escalated == [True], "Refresh with Root must go through PkexecRunner"
    finally:
        da.PkexecRunner = original
        case.close()


# -- App Isolation tab (appdata.py surfaced) ---------------------------

def test_app_isolation_tab_is_in_the_nav():
    assert any(path == "/app-isolation" for path, _ in bw.NAV_TABS)


def test_app_isolation_route_renders_for_a_real_persona():
    case = _RealServerCase(_base_deps())
    try:
        status, body = case.get("/app-isolation?persona=admin")
        assert status == 200
        assert b"APPDATA_ADMIN" in body
        assert b"Plan checks passed" in body
    finally:
        case.close()


def test_app_isolation_route_falls_back_for_an_unknown_persona():
    """A persona from a query string is untrusted input; it must not
    reach a path on disk."""
    case = _RealServerCase(_base_deps())
    try:
        status, body = case.get("/app-isolation?persona=../../etc")
        assert status == 200
        assert b"APPDATA_PERSONAL" in body
        assert b"etc" not in body.split(b"APPDATA_PERSONAL")[0][-80:]
    finally:
        case.close()


def test_app_isolation_page_shows_the_package_format_matrix():
    import appdata
    plans = appdata.plan_all("personal")
    body = bw.render_app_isolation_page(
        "personal", plans, leaks=[], conflicts=[],
        formats=appdata.supported_formats()).decode()
    assert "Flatpak" in body and "AppImage" in body and "Snap" in body
    assert "~/.var/app/{app}" in body


def test_app_isolation_page_verifies_live_persona_volume_identity():
    import appdata
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["blkid", "-L"], FakeProc(0, "/dev/mapper/baseline_appdata_personal\n", "")),
        (lambda a: a[:2] == ["findmnt", "--noheadings"], FakeProc(0, "/dev/mapper/baseline_appdata_personal ext4\n", "")),
        (lambda a: a[:2] == ["readlink", "-e"], FakeProc(0, "/dev/mapper/baseline_appdata_personal\n", "")),
    ])
    body = bw.render_app_isolation_page(
        "personal", appdata.plan_all("personal"), leaks=[], conflicts=[],
        formats=appdata.supported_formats(), runner=runner).decode()
    assert "APPDATA_PERSONAL mount verified" in body
    assert "/mnt/APPDATA_PERSONAL is backed by APPDATA_PERSONAL" in body


def test_app_isolation_page_shows_wrong_mounted_volume_as_an_error():
    import appdata
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["blkid", "-L"], FakeProc(0, "/dev/mapper/baseline_appdata_personal\n", "")),
        (lambda a: a[:2] == ["findmnt", "--noheadings"], FakeProc(0, "/dev/nvme0n1p2 ext4\n", "")),
        (lambda a: a[:2] == ["readlink", "-e"] and a[-1] == "/dev/mapper/baseline_appdata_personal",
         FakeProc(0, "/dev/mapper/baseline_appdata_personal\n", "")),
        (lambda a: a[:2] == ["readlink", "-e"], FakeProc(0, "/dev/nvme0n1p2\n", "")),
    ])
    body = bw.render_app_isolation_page(
        "personal", appdata.plan_all("personal"), leaks=[], conflicts=[],
        formats=appdata.supported_formats(), runner=runner).decode()
    assert 'role="alert"' in body
    assert "does not match labeled volume" in body
    assert "APPDATA_PERSONAL mount verified" not in body


def test_app_isolation_page_reports_a_violation_loudly():
    import appdata
    plans = appdata.plan_all("personal")
    body = bw.render_app_isolation_page(
        "personal", plans, leaks=[("a", "b", "/x")], conflicts=[],
        formats=appdata.supported_formats()).decode()
    assert "Plan checks failed" in body
    assert "ic-banner warn" in body


def test_app_isolation_page_states_an_app_with_no_overlay_rather_than_blanking_it():
    import appdata
    plans = appdata.plan_all("personal")
    body = bw.render_app_isolation_page(
        "personal", plans, leaks=[], conflicts=[],
        formats=appdata.supported_formats()).decode()
    assert "no overlay (stated, not assumed)" in body
    assert 'id="isolation-search"' in body
    assert 'role="tablist"' in body
    assert 'id="application-tree"' in body
    assert 'pageSize=50' in body


def test_a_drive_action_on_a_drive_outside_the_allowlist_never_reaches_pkexec():
    """Over the real socket: the job is refused and the privileged runner is never invoked."""
    executor = FakeSudoExecutor(returncode=0, stdout="")
    case = _RealServerCase(_base_deps(pkexec_executor=executor))
    try:
        status, body = case.drive_action("repair", {"device_path": "/dev/sdz"})
        assert status == 400 and body["outcome"] == "refused" and "allowed drives" in body["detail"]
        assert executor.calls == []
    finally:
        case.close()


def test_app_isolation_preview_never_claims_runtime_confinement():
    import appdata
    plans = appdata.plan_all('personal')
    body = bw.render_app_isolation_page('personal', plans, leaks=[], conflicts=[],
                                       formats=appdata.supported_formats()).decode()
    assert 'Plan checks passed' in body
    assert 'Runtime isolation has not been applied or verified' in body
    assert 'Isolation holds' not in body
    assert 'Unlisted data paths are not audited' in body


def test_master_config_aggregates_current_values_through_authenticated_http(tmp_path):
    import admin_elevation
    class Source:
        def current_settings(self):
            return {'diagnostics': {'ethtool_duplex': 'half'}}
    class Host:
        store = '/mnt/SUBSTRATE/vms'
        persistence_store = '/mnt/USER_PERSONAL/vms'
        def list_vms(self):
            return [{'name': 'actual-test-vm', 'cpus': 2, 'password': 'must-not-be-rendered'}]
    case = _RealServerCase(_base_deps(source=Source(), vm_host=Host(),
        elevation_store=admin_elevation.ElevationStore(), vm_config_path=tmp_path / 'vm.json'))
    try:
        status, body = case.get('/master-config')
        assert status == 200
        assert b'config-search' in body and b'actual-test-vm' in body
        assert b'must-not-be-rendered' not in body
        assert b'/settings/diagnostics' in body
        assert b'Installer Cache / declared sources' in body
    finally:
        case.close()


def test_draft_http_routes_save_reload_and_master_aggregate(tmp_path):
    import admin_elevation
    from configuration_drafts import DraftStore
    class Source:
        def current_settings(self): return {}
    case = _RealServerCase(_base_deps(source=Source(), draft_store=DraftStore(tmp_path / 'drafts.sqlite'),
                                     elevation_store=admin_elevation.ElevationStore()))
    try:
        status, payload = case.post_json('/install-plan/draft', {'document': {'environment': {'name': 'persisted-example'}}, 'revision': 0})
        assert status == 200 and payload['draft']['applied'] is False
        status, raw = case.get('/install-plan/draft')
        assert json.loads(raw)['draft']['revision'] == 1
        status, payload = case.post_json('/install-plan/draft', {'document': {'environment': {}}, 'revision': 0})
        assert status == 409
        status, raw = case.get('/master-config')
        assert status == 200 and b'persisted-example' in raw
        assert b'no saved draft source' not in raw
        status, payload = case.post_json('/recipes/draft', {'document': {'document': {'id': 'unfinished-recipe'}, 'app_document': None}, 'revision': 0})
        assert status == 200
        assert json.loads(case.get('/recipes/draft')[1])['draft']['document']['document']['id'] == 'unfinished-recipe'
    finally:
        case.close()


def test_draft_routes_enforce_user_ownership_and_existing_role_gate(tmp_path):
    from configuration_drafts import DraftStore
    store = DraftStore(tmp_path / 'drafts.sqlite')
    case = _RealServerCase(_base_deps(draft_store=store))
    try:
        assert case.post_json('/install-plan/draft', {'document': {'name': 'root-only'}, 'revision': 0})[0] == 200
        bob = case.server.deps['sessions'].create('other-admin', now=1700000000, role='admin')
        case.token = bob.token
        assert json.loads(case.get('/install-plan/draft')[1])['draft'] is None
        assert case.post_json('/install-plan/draft', {'owner':'root', 'document': {}, 'revision':0})[0] == 400
        assert store.get('root','installer')['document']['name'] == 'root-only'
        case.token = case.server.deps['sessions'].create('limited-operator', now=1700000000, role='operator').token
        assert case.post_json('/install-plan/draft', {'document': {}, 'revision':0})[0] == 403
        assert case.get('/recipes/draft')[0] == 403
    finally:
        case.close()


def test_hardware_drive_links_use_serial_and_escape_inventory():
    from hardware_inventory import BlockDevice
    page = bw._render_inventory({'block':[BlockDevice('sdd', serial='serial & one', model='<unsafe>') ]})
    assert '/drive-admin?serial=serial%20%26%20one' in page
    assert '&lt;unsafe&gt;' in page and '<unsafe>' not in page


def test_drive_admin_serial_link_selects_only_fresh_matching_candidate():
    drives = [{'path':'/dev/sdb','serial':'first','model':'one','is_default':True},
              {'path':'/dev/sdc','serial':'second','model':'two'}]
    page = bw.render_drive_admin_page(drives=drives, volumes=[], actions=[], selected_serial='second').decode()
    assert 'value="/dev/sdc" checked' in page
    assert 'value="/dev/sdb" checked' not in page
    missing = bw.render_drive_admin_page(drives=drives, volumes=[], actions=[], selected_serial='disconnected').decode()
    assert 'value="/dev/sdb" checked' not in missing
    assert 'no longer available' in missing


def test_installer_cache_provides_associated_package_anchors():
    import installer_cache as ic
    entry = next(item for item in ic.catalog() if item.entry_id == 'ethtool')
    report = ic.CacheReport(root=ic.DEFAULT_CACHE_ROOT, mounted=False, mount_detail='not mounted', rows=[ic.Presence(entry,False)])
    assert 'id="cache-entry-ethtool"' in bw.render_installer_cache_page(report).decode()


def test_hardware_host_page_still_works_when_vm_backend_is_unavailable(monkeypatch):
    class Host:
        def list_vms(self):
            raise bw.vh.VmError('VM store offline')
    monkeypatch.setattr(bw,'real_hardware_state',lambda runner:{'dependency_results':[],'inventory':{}})
    case = _RealServerCase(_base_deps(vm_host=Host()))
    try:
        status, page = case.get('/hardware')
        assert status == 200
        assert b'VM store offline' in page
        assert b'hardware-tab-drives' in page
    finally:
        case.close()


def test_installer_prepare_inputs_is_durable_and_uses_saved_owned_draft(tmp_path):
    from configuration_drafts import DraftStore
    import workload_jobs
    from test_installer_inputs import repository
    class Source:
        def current_settings(self):return {'drivers':{'cpu_microcode':True}}
    drafts=DraftStore(tmp_path/'drafts.sqlite')
    drafts.save('root','installer',{'environment':{'name':'saved-plan'}},expected_revision=0)
    jobs=workload_jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    case=_RealServerCase(_base_deps(source=Source(),draft_store=drafts,workload_jobs=jobs,
        installer_repo_root=repository(tmp_path/'repo'),installer_bundle_root=tmp_path/'bundles'))
    try:
        status,result=case.post_json('/install-plan/prepare-inputs',{'revision':0,'request_id':'stale-test'})
        assert status==409
        status,result=case.post_json('/install-plan/prepare-inputs',{'revision':1,'request_id':'prepare-test'})
        assert status==202
        job=jobs.wait(result['job_id'],5)
        assert job['state']=='completed'
        assert 'not ready' in job['result']['message'].lower()
        status,body=case.get('/install-plan/input-bundle?job_id='+job['id'])
        report=json.loads(body)
        assert status==200 and report['prepared'] and report['ready'] is False
        assert report['executed'] is False
        repeated,retry=case.post_json('/install-plan/prepare-inputs',{'revision':1,'request_id':'prepare-test'})
        assert repeated==202 and retry['job_id']==job['id']
        from pathlib import Path
        manifest=next((tmp_path/'bundles').rglob('MANIFEST.json'))
        manifest.unlink()
        status,result=case.post_json('/workloads/inspect',{'job_id':job['id']})
        assert status==409  # completed jobs do not need recovery
        import sqlite3
        with sqlite3.connect(tmp_path/'jobs.sqlite') as db:
            db.execute("UPDATE jobs SET state='interrupted' WHERE id=?",(job['id'],))
        status,result=case.post_json('/workloads/inspect',{'job_id':job['id']})
        assert status==200
        assert 'source preparation' in str(result).lower()
        status,result=case.post_json('/workloads/acknowledge',{'job_id':job['id'],'name':job['name']})
        assert status==200 and result['state']=='reviewed'
    finally:
        case.close()


def test_web_source_acquisition_publishes_verified_cache_and_feeds_preparation(tmp_path,monkeypatch):
    import hashlib
    import installer_sources as sources
    import workload_jobs
    from test_installer_sources import CacheRunner
    from test_installer_inputs import repository
    from configuration_drafts import DraftStore
    monkeypatch.setattr(sources.ue,'IMAGE_SHA256',hashlib.sha256(b'vanilla').hexdigest())
    root=tmp_path/'cache';root.mkdir()
    runner=CacheRunner(root)
    drafts=DraftStore(tmp_path/'drafts.sqlite')
    drafts.save('root','installer',{'environment':{'name':'test-plan'}},expected_revision=0)
    jobs=workload_jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    case=_RealServerCase(_base_deps(runner=runner,draft_store=drafts,workload_jobs=jobs,installer_cache_root=root,
        installer_repo_root=repository(tmp_path/'repo'),installer_bundle_root=tmp_path/'bundles'))
    try:
        status,body=case.post_json('/installer-cache/acquire',{'source':'ubuntu_base','request_id':'source-test'})
        assert status==202
        job=jobs.wait(body['job_id'],5);assert job['state']=='completed'
        status,page=case.get('/installer-cache/source?source=ubuntu_base')
        assert status==200 and page==b'vanilla'
        status,body=case.post_json('/install-plan/prepare-inputs',{'revision':1,'request_id':'snapshot-test'})
        assert status==202
        prepared=jobs.wait(body['job_id'],5)
        status,body=case.get('/install-plan/input-bundle?job_id='+prepared['id'])
        checks=json.loads(body)
        assert checks['artifacts'][2]['verified'] is True
        assert checks['ready'] is False  # unrelated source/dependency gaps remain real
        status,body=case.post_json('/installer-cache/acquire',{'source':'unsupported','request_id':'bad'})
        assert status==400
    finally:case.close()


def test_cache_page_offers_typed_native_source_acquisition_and_actual_file_link():
    import installer_cache as ic
    report=ic.CacheReport(root=ic.DEFAULT_CACHE_ROOT,mounted=False,mount_detail='not mounted')
    html=bw.render_installer_cache_page(report).decode()
    assert '<select id="source-choice">' in html
    assert '/installer-cache/acquire' in html
    assert '/installer-cache/source?source=ubuntu_base' in html
    assert 'crypto.randomUUID' not in html


def test_managed_mode_page_defaults_to_standalone_and_saves_a_change(tmp_path):
    f = tmp_path / "managed.json"
    case = _RealServerCase(_base_deps(managed_file=f, fs_roots=[str(tmp_path)]))
    try:
        status, body = case.get('/managed-mode')
        assert status == 200 and b"On its own" in body and b"nothing ever connects to a parent" in body
        assert any(p == "/managed-mode" for p, _ in bw.NAV_TABS)
        assert case.post_json('/managed-mode', {'mode': 'managed', 'mirror_root': None, 'remote_rebuild': False})[0] == 400
        assert case.post_json('/managed-mode', {'mode': 'managed', 'mirror_root': '/etc/not-allowed', 'remote_rebuild': False})[0] == 400      # validated again on the server
        assert case.post_json('/managed-mode', {'mode': 'managed', 'mirror_root': str(tmp_path / 'v'), 'remote_rebuild': False})[0] == 200
        assert json.loads(f.read_text())["mode"] == "managed"
        assert case.post_json('/managed-mode', {'mode': 'standalone', 'mirror_root': None})[0] == 200
        assert json.loads(f.read_text())["mode"] == "standalone"
    finally:
        case.close()


def test_managed_mode_needs_an_operator_account(tmp_path):
    case = _RealServerCase(_base_deps(managed_file=tmp_path / "m.json"))
    try:
        case.token = case.server.deps['sessions'].create('viewer', now=1700000000, role='viewer').token
        assert case.post_json('/managed-mode', {'mode': 'standalone', 'mirror_root': None})[0] == 403
    finally:
        case.close()


def test_web_address_page_and_save(tmp_path):
    f = tmp_path / "web.env"
    case = _RealServerCase(_base_deps(web_env_file=f))
    try:
        status, body = case.get('/web-address')
        assert status == 200 and b"Proxmox host itself" in body and b"0.0.0.0" in body
        assert case.post_json('/web-address', {'bind_host': 'not-an-ip', 'port': 8100})[0] == 400
        assert case.post_json('/web-address', {'bind_host': '0.0.0.0', 'port': 9100})[0] == 200
        assert "BASELINE_WEB_PORT=9100" in f.read_text()
    finally:
        case.close()


def test_network_connection_page_and_save_use_the_shared_logic(monkeypatch):
    import network
    import netpref
    calls = []
    monkeypatch.setattr(network, "list_interfaces", lambda: [{"name": "eth9", "friendly": "Ethernet"}])
    monkeypatch.setattr(network, "device_details", lambda n: {"driver": "e1000"})
    monkeypatch.setattr(network, "is_admin_up", lambda n: True)
    monkeypatch.setattr(network, "load_aliases", lambda: {})
    monkeypatch.setattr(network, "check_lifeline", lambda: [{"fact": "nic_detected", "ok": True, "detail": "other0"}])
    monkeypatch.setattr(network, "save_alias", lambda n, a: calls.append(("alias", n, a)))
    monkeypatch.setattr(network, "set_admin_state", lambda n, up: calls.append(("power", n, up)) or (True, "ok"))
    monkeypatch.setattr(netpref, "load_preference", lambda: {})
    monkeypatch.setattr(netpref, "apply_primary", lambda d: calls.append(("primary", d)) or (True, "primary set"))
    case = _RealServerCase(_base_deps())
    try:
        status, body = case.get('/network/connection?dev=eth9')
        assert status == 200 and b'name="alias"' in body
        assert case.get('/network/connection?dev=nope')[0] == 404
        assert case.post_json('/network/connection', {'dev': 'nope', 'alias': '', 'power': True})[0] == 404
        status, out = case.post_json('/network/connection', {'dev': 'eth9', 'alias': 'Office', 'power': False, 'role': 'primary'})
        assert status == 200 and ("alias", "eth9", "Office") in calls and ("power", "eth9", False) in calls and ("primary", "eth9") in calls
    finally:
        case.close()


def test_a_bare_fragment_page_still_gets_the_menu():
    out = bw._with_nav(b"<h1>Installation readiness</h1><table></table>", "/installation-readiness").decode()
    assert out.startswith("<!doctype html>") and 'class="baseline-nav"' in out and "<h1>Installation readiness</h1>" in out


def test_memory_page_says_so_when_the_volume_group_cannot_be_read(monkeypatch):
    import volume_growth
    monkeypatch.setattr(bw, "_swap_runner", lambda deps: (_ for _ in ()).throw(volume_growth.GrowthError("lvs could not be read")))
    case = _RealServerCase(_base_deps())
    try:
        status, body = case.get('/memory')
        assert status == 200 and b"Swap could not be read" in body
    finally:
        case.close()


def test_folder_browser_and_paste_check_routes_stay_inside_the_allowed_places(tmp_path):
    (tmp_path / "drive" / "sub").mkdir(parents=True)
    case = _RealServerCase(_base_deps(fs_roots=[str(tmp_path)]))
    try:
        status, body = case.get(f"/fs/browse?path={tmp_path}/drive")
        assert status == 200 and [d["name"] for d in json.loads(body)["dirs"]] == ["sub"]
        assert json.loads(case.get("/fs/browse?path=/etc")[1])["dirs"] == []
        assert json.loads(case.get(f"/fs/validate?path={tmp_path}/drive")[1])["ok"] is True
        assert json.loads(case.get("/fs/validate?path=/etc")[1])["ok"] is False
        assert json.loads(case.get("/fs/validate?path=relative")[1])["ok"] is False
    finally:
        case.close()


def test_the_launcher_offers_the_systems_the_machine_carries_when_no_list_was_written(tmp_path):
    import launcher_model
    import os_list
    entries = os_list.derived({"ubuntu", "nixos"}, ["ubuntu-26.04.1-desktop-amd64.iso"])
    out = launcher_model.available_to_create(entries, ["ubuntu-26.04.1-desktop-amd64.iso"], [], 16384, bases={"ubuntu", "nixos"})
    assert {e["id"] for e in out} == {"ubuntu", "nixos"} and all(e["plan"]["prebuilt"] for e in out)


def test_files_page_downloads_uploads_and_stays_inside_the_drives(tmp_path):
    drive = tmp_path / "drive"; drive.mkdir(); (drive / "a.txt").write_text("hello")
    case = _RealServerCase(_base_deps(fs_roots=[str(tmp_path)]))
    try:
        status, body = case.get(f"/files?path={drive}")
        assert status == 200 and b"a.txt" in body
        assert case.get(f"/files/download?path={drive}/a.txt") == (200, b"hello")
        assert case.get("/files/download?path=/etc/hostname")[0] == 404
        assert case.post_json("/files/op", {"op": "mkdir", "path": str(drive), "name": "new"})[1]["ok"]
        assert (drive / "new").is_dir()
        assert not case.post_json("/files/op", {"op": "delete", "path": "/etc/hostname"})[1]["ok"]
        url = f"http://127.0.0.1:{case.port}/files/upload?path={drive}&name=up.bin"
        req = urllib.request.Request(url, data=b"abc", method="POST", headers={"Content-Type": "application/octet-stream", "Cookie": f"session={case.token}",
                                                                              "Origin": f"http://127.0.0.1:{case.port}"})
        assert json.loads(urllib.request.urlopen(req, timeout=5).read())["ok"] and (drive / "up.bin").read_bytes() == b"abc"
    finally:
        case.close()


def test_each_tool_has_its_own_address(tmp_path):
    case = _RealServerCase(_base_deps())
    try:
        for name in ("lm-sensors", "nvme-cli", "smartmontools", "iperf3", "ethtool"):
            status, body = case.get(f"/tools/{name}")
            assert status == 200 and name.encode() in body
        status, body = case.get("/tools/lm-sensors?action=readings")
        assert status == 200 and b"Result" in body
        assert case.get("/tools/nothing")[0] in (404,)
    finally:
        case.close()


def test_vault_page_lists_adds_shows_and_deletes_secrets(tmp_path):
    roots = (("USER_ADMIN", "admin", str(tmp_path / "a")), ("USER_PERSONAL", "personal", str(tmp_path / "p")))
    case = _RealServerCase(_base_deps(vault_roots=roots))
    try:
        assert case.post_json("/vault/put", {"scope": "personal", "name": "GOOGLE_LOGIN", "value": "hunter2hunter2"})[1]["ok"]
        page = case.get("/vault")[1]
        assert b"GOOGLE_LOGIN" in page and b"hunter2hunter2" not in page
        shown = case.post_json("/vault/reveal", {"scope": "personal", "name": "GOOGLE_LOGIN"})[1]
        assert shown["ok"] and shown["value"] == "hunter2hunter2"
        assert not case.post_json("/vault/put", {"scope": "personal", "name": "bad name", "value": "hunter2hunter2"})[1]["ok"]
        assert case.post_json("/vault/delete", {"scope": "personal", "name": "GOOGLE_LOGIN"})[1]["ok"]
        assert b"GOOGLE_LOGIN" not in case.get("/vault")[1]
    finally:
        case.close()


def test_vault_grants_and_delivery_reach_a_guest_through_stdin_only(tmp_path):
    roots = (("USER_ADMIN", "admin", str(tmp_path / "a")), ("USER_PERSONAL", "personal", str(tmp_path / "p")))
    sent = []
    case = _RealServerCase(_base_deps(vault_roots=roots, vault_grants_path=str(tmp_path / "grants.json"),
                                      vault_push=lambda target, argv, data: sent.append((target, argv, data))))
    try:
        case.post_json("/vault/put", {"scope": "personal", "name": "GOOGLE_LOGIN", "value": "hunter2hunter2"})
        assert case.post_json("/vault/grant", {"target": "kasm", "name": "GOOGLE_LOGIN"})[1]["ok"]
        assert not case.post_json("/vault/grant", {"target": "../x", "name": "GOOGLE_LOGIN"})[1]["ok"]
        report = case.post_json("/vault/deliver", {"target": "kasm"})[1]
        assert report["delivered"] == ["GOOGLE_LOGIN"]
        assert sent[0][0] == "kasm" and sent[0][2] == b"hunter2hunter2" and "hunter2" not in " ".join(sent[0][1])
        assert b"data-send='kasm'" in case.get("/vault")[1]
        assert case.post_json("/vault/revoke", {"target": "kasm", "name": "GOOGLE_LOGIN"})[1]["ok"]
    finally:
        case.close()


def test_setup_runs_for_the_signed_in_user_and_says_what_was_done(tmp_path, monkeypatch):
    import turnkey
    seen = []
    monkeypatch.setattr(turnkey, "run", lambda host, user, entries, carried, bases, **kw: seen.append((user, kw["vault_names"])) or
                        {"created": ["debian"], "already_there": [], "failed": {}, "not_carried": [], "apps_skipped": {}, "granted_to": ["kasm", "vm:debian"]})
    roots = (("USER_ADMIN", "admin", str(tmp_path / "a")), ("USER_PERSONAL", "personal", str(tmp_path / "p")))
    case = _RealServerCase(_base_deps(vault_roots=roots, vault_grants_path=str(tmp_path / "g.json"), turnkey_marker=str(tmp_path / "turnkey.json"), turnkey_inline=True))
    try:
        case.post_json("/vault/put", {"scope": "personal", "name": "GOOGLE_LOGIN", "value": "hunter2hunter2"})
        req = urllib.request.Request(f"http://127.0.0.1:{case.port}/turnkey/run", data=b"", method="POST",
                                     headers={"Cookie": f"session={case.token}", "Origin": f"http://127.0.0.1:{case.port}"})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            urllib.request.build_opener(NoRedirect).open(req, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 303 or exc.code == 302
        assert seen and seen[0][1] == ["GOOGLE_LOGIN"]
        page = case.get("/turnkey")[1]
        assert b"debian" in page and b"kasm" in page
        assert (tmp_path / "turnkey.json").exists()
    finally:
        case.close()
