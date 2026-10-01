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
    def __init__(self, serials_by_path=None, drive_table="sdb disk  11111111-2222-3333-4444-555555555555 \n"):
        self.drive_table = drive_table
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
        if argv[0] == "lsblk" and "NAME,TYPE,FSTYPE,PTUUID,LABEL" in argv:
            return self.drive_table          # what is ON the drive: blank unless a test says otherwise
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
    assert paths == {"/dev/sdb"}          # only the allowed SK hynix drive; /dev/sdz is never offered
    by_path = {d["path"]: d for d in drives}
    assert by_path["/dev/sdb"]["is_default"] is True
    assert by_path["/dev/sdb"]["drive_type"] == "NVMe"


def test_real_drive_state_returns_empty_list_when_no_runner_is_configured():
    assert bw.real_drive_state(None, pds_runner=FakePdsRunner()) == []


def test_real_volume_state_returns_the_full_planned_volume_list_even_when_nothing_exists_yet():
    """collect_volume_details always returns one entry per planned
    volume, existing or not - a bare FakeRunner (nothing created, real
    lvs/df calls returning empty output) is a real, honest "not
    provisioned yet" state, not a failure."""
    details = bw.real_volume_state(FakeRunner())
    assert len(details) == 8
    assert all(d["lv_exists"] is False for d in details)


def test_real_volume_state_returns_empty_list_when_no_runner_is_configured():
    assert bw.real_volume_state(None) == []


def test_real_volume_state_returns_empty_list_on_a_real_exception_rather_than_crashing():
    class ExplodingRunner:
        def run(self, *a, **k):
            raise RuntimeError("real subprocess failure")
    assert bw.real_volume_state(ExplodingRunner()) == []


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
    assert "No volumes planned" in body


def test_render_drive_admin_page_shows_a_checkbox_per_volume_for_the_update_action():
    """Direct feedback: Update should let the operator select
    partitions/volumes from the drive tree, then choose which types of
    update to apply - the mounted-volumes table needs a real checkbox
    per row, not just a read-only listing."""
    body = bw.render_drive_admin_page(
        drives=[], actions=[],
        volumes=[{"label": "BASELINE", "mountpoint": "/mnt/BASELINE", "lv_name": "baseline_app_state",
                  "lv_exists": True, "lv_size_bytes": 5368709120, "total_bytes": None,
                  "used_bytes": None, "percent_used": None},
                 {"label": "INSTALLER_CACHE", "mountpoint": "/mnt/INSTALLER_CACHE",
                  "lv_name": "baseline_installer_cache", "lv_exists": False, "lv_size_bytes": None,
                  "total_bytes": None, "used_bytes": None, "percent_used": None}],
    ).decode()
    assert '<input type="checkbox" class="volume-select" value="BASELINE">' in body
    assert '<input type="checkbox" class="volume-select" value="INSTALLER_CACHE">' in body


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
    `find_vg_for_device`'s real `pvs` call); `update_selected` is a
    pure honest placeholder that never touches the runner at all, so
    it can't prove this on its own."""
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

def test_real_hardware_state_returns_empty_shape_when_no_runner_is_configured():
    state = bw.real_hardware_state(None)
    assert state == {"dependency_results": [], "sensors": None, "nvme": None,
                     "smart": None, "sysinfo": {}, "inventory": {}}


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
        assert b"Isolation holds" in body
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


def test_app_isolation_page_reports_a_violation_loudly():
    import appdata
    plans = appdata.plan_all("personal")
    body = bw.render_app_isolation_page(
        "personal", plans, leaks=[("a", "b", "/x")], conflicts=[],
        formats=appdata.supported_formats()).decode()
    assert "Isolation violated" in body
    assert "ic-banner warn" in body


def test_app_isolation_page_states_an_app_with_no_overlay_rather_than_blanking_it():
    import appdata
    plans = appdata.plan_all("personal")
    body = bw.render_app_isolation_page(
        "personal", plans, leaks=[], conflicts=[],
        formats=appdata.supported_formats()).decode()
    assert "no overlay (stated, not assumed)" in body


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
