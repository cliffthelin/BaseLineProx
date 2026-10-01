"""Each Bot<Action> account is authorized for exactly one action. These tests log in as each bot over a real socket
and exercise it against a temporary RAM-backed stand-in drive only: the bot's own action works (and a drive action
still needs a human confirmation), every other action is refused, and the RAM drive shows nothing else happened.
No real drive, device node, or backup destination is touched."""
import pytest

import drive_admin as da
import hitl
import operations as ops
import settings_web as sw
from ram_drive import RamDrive
from test_action_bots import ACTIONS, bot_name
from test_baseline_web import FakeSudoExecutor, _RealServerCase, _base_deps, _poll_job
from test_hitl_web import SECRET, Clock, _req

PARAMS = {"device_path": "/dev/sdb"}


def run_ops():
    return [a for a in ACTIONS if a in ops.OPERATIONS]


@pytest.fixture
def ram(tmp_path, monkeypatch):
    drive = RamDrive(tmp_path / "ram-cache-drive")
    drive.install_fake_actions(monkeypatch)
    drive.install_fake_backups(monkeypatch)
    return drive


def bot_case(role, tmp_path):
    clock = Clock()
    store = hitl.ConfirmationStore(verify_secret=lambda s: s == SECRET, clock=clock, min_wait_s=0)
    sessions = sw.SessionStore()
    sessions.create("bot", now=clock(), role=role)
    deps = _base_deps(sessions=sessions, hitl=store, clock=clock, pkexec_executor=FakeSudoExecutor(returncode=0),
                      recovery_verify_fn=lambda s: s == SECRET)
    deps["scheduler"] = ops.Scheduler(deps["web_gate"], ops.ScheduleStore(tmp_path / "sched.json"),
                                      lambda op, params, origin: None, clock=clock)
    return _RealServerCase(deps)


def attempt(case, action):
    """Ask for `action` the way its page does. Returns the HTTP status, the body, and the job if one started."""
    if action in ops.OPERATIONS:
        status, body = _req(case, "POST", "/operations/run", {"op": action})
    else:
        params = {} if action == "update_selected" else PARAMS
        if action == "update_selected":
            params = {"selected": ["BASELINE"]}
        status, body = _req(case, "POST", "/drive-admin/action", {"action_id": action, "params": params})
        if status == 200 and body.get("outcome") == "confirmation_required":
            chal = body["challenge"]
            status, body = _req(case, "POST", "/drive-admin/confirm",
                                {"challenge_id": chal["id"], "typed": chal["phrase"], "secret": SECRET})
    job = _poll_job(case, body["job_id"]) if isinstance(body, dict) and body.get("job_id") else None
    return status, body, job


@pytest.mark.parametrize("action", ACTIONS, ids=[bot_name(a) for a in ACTIONS])
def test_the_bot_can_do_its_own_action_on_the_ram_drive(action, ram, tmp_path):
    case = bot_case(f"bot:{action}", tmp_path)
    try:
        status, body, job = attempt(case, action)
        assert status == 200 and job is not None and job["outcome"] == "applied", (status, body, job)
        if action in ops.OPERATIONS:
            assert ram.calls == []                      # an operation never runs a drive action
        elif action == "build_self_installer":
            assert ram.installs == 1
        elif action == "lay_out_baseline_drive":
            assert getattr(ram, "layouts", 0) == 1 and not ram.intact()
        elif action in ("mount_volume", "unmount_volume"):
            assert ram.calls == [] and ram.installs == 0
        else:
            assert [c[0] for c in ram.calls] == [action]
    finally:
        case.close()


@pytest.mark.parametrize("action", [a for a in ACTIONS if a not in ops.OPERATIONS],
                         ids=[bot_name(a) for a in ACTIONS if a not in ops.OPERATIONS])
def test_a_drive_bot_cannot_run_its_action_without_a_human_confirmation(action, ram, tmp_path):
    case = bot_case(f"bot:{action}", tmp_path)
    try:
        params = {"selected": ["BASELINE"]} if action == "update_selected" else PARAMS
        status, body = _req(case, "POST", "/drive-admin/action", {"action_id": action, "params": params})
        assert body["outcome"] == "confirmation_required" and "job_id" not in body
        assert ram.installs == 0 and ram.calls == [] and ram.intact()
    finally:
        case.close()


@pytest.mark.parametrize("action", ACTIONS, ids=[bot_name(a) for a in ACTIONS])
def test_the_bot_is_refused_every_other_action_and_the_ram_drive_is_untouched(action, ram, tmp_path):
    case = bot_case(f"bot:{action}", tmp_path)
    try:
        for other in ACTIONS:
            if other == action:
                continue
            status, body, job = attempt(case, other)
            assert status in (400, 403) and job is None, (other, status, body)
        assert ram.installs == 0 and ram.calls == [] and ram.backups == [] and ram.intact() and ram.mounted == {}
    finally:
        case.close()


def test_a_bot_backup_writes_only_to_the_ram_drive(ram, tmp_path):
    case = bot_case("bot:backup_offdrive", tmp_path)
    try:
        _req(case, "POST", "/operations/run", {"op": "backup_offdrive", "params": {"dry_run": True}})
        import time
        time.sleep(0.2)
        assert ram.backups == []                        # a dry run writes nothing
        _, body = _req(case, "POST", "/operations/run", {"op": "backup_offdrive"})
        _poll_job(case, body["job_id"])
        assert ram.backups == ["set-1"] and (ram.root / "set-1").exists() and ram.intact()
    finally:
        case.close()


# -- the root password once a day per target ---------------------------------------------

def _ask_repair(case, device="/dev/sdb"):
    return _req(case, "POST", "/drive-admin/action", {"action_id": "repair", "params": {"device_path": device}})


def _confirm_daily(case, chal, daily=True):
    return _req(case, "POST", "/drive-admin/confirm",
                {"challenge_id": chal["id"], "typed": chal["phrase"], "secret": SECRET, "daily": daily})


def test_a_bot_needs_the_root_password_once_a_day_per_drive(ram, tmp_path):
    case = bot_case("bot:repair", tmp_path)
    try:
        _, body = _ask_repair(case)
        assert body["outcome"] == "confirmation_required"
        _, started = _confirm_daily(case, body["challenge"])
        assert _poll_job(case, started["job_id"])["outcome"] == "applied"
        # Same drive, same day: no challenge, it runs (even from a brand new login of the same account).
        for _ in range(3):
            status, again = _ask_repair(case)
            assert status == 200 and again["outcome"] == "started", again
            assert _poll_job(case, again["job_id"])["outcome"] == "applied"
        assert len([c for c in ram.calls if c[0] == "repair"]) == 4
    finally:
        case.close()


def test_without_ticking_the_daily_box_every_run_still_needs_the_password(ram, tmp_path):
    case = bot_case("bot:repair", tmp_path)
    try:
        _, body = _ask_repair(case)
        _, started = _confirm_daily(case, body["challenge"], daily=False)
        _poll_job(case, started["job_id"])
        assert _ask_repair(case)[1]["outcome"] == "confirmation_required"
    finally:
        case.close()


def test_a_new_day_needs_a_new_authorization(ram, tmp_path):
    case = bot_case("bot:repair", tmp_path)
    try:
        _, body = _ask_repair(case)
        _, started = _confirm_daily(case, body["challenge"])
        _poll_job(case, started["job_id"])
        assert _ask_repair(case)[1]["outcome"] == "started"
        clock = case.server.deps["clock"]
        clock.t += 26 * 3600
        case.server.deps["sessions"].sessions[case.token].created = clock.t      # the login itself is still live
        assert _ask_repair(case)[1]["outcome"] == "confirmation_required"
    finally:
        case.close()


def test_a_new_target_needs_a_new_authorization(ram, tmp_path):
    case = bot_case("bot:repair", tmp_path)
    try:
        _, body = _ask_repair(case)
        _, started = _confirm_daily(case, body["challenge"])
        _poll_job(case, started["job_id"])
        # A different serial would be a different target; the allowlist only admits the SK hynix drives, so prove the
        # scoping at the store: the authorization is bound to this exact serial.
        store = case.server.deps["hitl"]
        assert store.authorization_from_daily("bot", "repair", {}, "ANOTHERTARGET") is None
        assert store.authorization_from_daily("bot", "repair", {}, "MD89N41071210AP4E") is not None
    finally:
        case.close()


def test_the_daily_box_is_refused_for_non_bot_logins_and_never_applies_to_the_install(ram, tmp_path):
    admin = bot_case("admin", tmp_path)
    try:
        _, body = _ask_repair(admin)
        status, out = _confirm_daily(admin, body["challenge"])
        assert status == 403 and "job_id" not in out and ram.calls == []
    finally:
        admin.close()
    bot = bot_case("bot:build_self_installer", tmp_path)
    try:
        _, body = _req(bot, "POST", "/drive-admin/action", {"action_id": "build_self_installer", "params": PARAMS})
        status, out = _confirm_daily(bot, body["challenge"])
        assert status == 403 and out["reason"] == "never_granted" and ram.installs == 0
        assert _req(bot, "POST", "/drive-admin/action",
                    {"action_id": "build_self_installer", "params": PARAMS})[1]["outcome"] == "confirmation_required"
    finally:
        bot.close()


def test_the_daily_authorization_is_not_shared_with_another_bot_account(ram, tmp_path):
    case = bot_case("bot:repair", tmp_path)
    try:
        _, body = _ask_repair(case)
        _confirm_daily(case, body["challenge"])
        store = case.server.deps["hitl"]
        assert store.authorization_from_daily("some-other-bot", "repair", {}, "MD89N41071210AP4E") is None
    finally:
        case.close()
