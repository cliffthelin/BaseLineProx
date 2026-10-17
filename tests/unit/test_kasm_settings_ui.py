"""The Kasm settings screens: the plain-language and the full view over Kasm's own live list, and the change path through Kasm's admin API.
Kasm's list comes from a stateful fake of the VM; the web server and session are real."""
import json

import pytest

import kasm_settings_ui as ui
import kasm_setup as ks
from test_baseline_web import _RealServerCase, _base_deps
from test_kasm_setup import Fake, build, installed, world  # noqa: F401  (world is a fixture)
from test_new_web_routes import req


def row(name, value, type_="int", title=None, category="auth", restart=None, ident=None, secret=False, description="Kasm's own words"):
    return {"name": name, "title": title or name.replace("_", " ").title(), "category": category, "description": description, "type": type_,
            "restart": restart or "", "id": ident or f"id-{name}", "secret": secret, "value": None if secret else value}


LIVE = [row("log_retention", "7", title="Log retention (days)"), row("debug_retention", "1", title="Debug retention (hours)", restart="kasm_api"),
        row("session_lifetime", "43200", title="Session lifetime"), row("max_login_attempts", "5"), row("password_min_length", "8"),
        row("password_require_uppercase", "True", "bool"), row("notice_title", "", "string"), row("notice_message", "", "multiline_string"),
        row("hec_token", None, "password", secret=True), row("auto_agent", "False", "bool"), row("update_check", "True", "bool"),
        row("max_sessions_note", "3", "int", title="Sessions note limit", description="Kasm's own words about sessions"), row("odd_flag", "False", "bool", title="Odd flag")]


class Vm(Fake):
    """A fake that keeps Kasm's settings and applies update requests the way the admin API does."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.live = [dict(r) for r in LIVE]
        self.updates, self.refuse = [], set()

    def __call__(self, argv, data=None, timeout=120):
        if argv[:2] == ["qm", "guest"] and "update_setting" in argv[-1]:
            self.calls.append(list(argv))
            lines = data.decode().splitlines()
            self.updates.append(json.loads(lines[1]))
            out = ""
            for change in json.loads(lines[1]):
                if change["id"] in self.refuse:
                    out += f"{change['id']} error: refused\n"
                    continue
                for r in self.live:
                    if r["id"] == change["id"]:
                        r["value"] = change["value"]
                out += f"{change['id']} ok\n"
            return 0, json.dumps({"exited": 1, "exitcode": 0, "out-data": out}), ""
        if argv[:2] == ["qm", "guest"] and "Reads one line" in argv[-1]:
            self.settings_stdin = data
            self.settings_output = json.dumps([{**r, "restart": r["restart"] or None} for r in self.live])
        return super().__call__(argv, data, timeout)


def running(world):
    setup, fake = installed(world, fake=Vm())                 # a real set-up, so the admin password is in the vault as it would be
    fake.state = "running"
    return setup, fake


# ---- the pure part ---------------------------------------------------------------------------------------------------------------------
def live_rows():
    import kasm_telemetry as kt
    return kt.parse_settings_full(json.dumps([{**r, "restart": r["restart"] or None} for r in LIVE]))


def test_a_plain_value_is_shown_and_stored_in_the_unit_a_person_thinks_in():
    rows = live_rows()
    page = ui.render_simple(rows).decode()
    assert 'name="c:session_lifetime" value="12"' in page.replace("'", '"') and "hours" in page          # 43200 seconds is 12 hours
    changed = ui.simple_requested(rows, {"c:session_lifetime": "8", "c:log_retention": "30"})
    assert changed == {"session_lifetime": "28800", "log_retention": "30"}


def test_numbers_outside_the_stated_range_or_not_numbers_are_refused():
    rows = live_rows()
    for form in ({"c:log_retention": "0"}, {"c:log_retention": "9999"}, {"c:log_retention": "lots"}, {"c:session_lifetime": "-1"}):
        with pytest.raises(ui.SettingsError):
            ui.simple_requested(rows, form)


def test_a_secret_is_never_shown_or_offered_for_change_and_a_forged_field_for_it_is_refused():
    rows = live_rows()
    for page in (ui.render_simple(rows).decode(), ui.render_advanced(rows).decode()):
        assert ":hec_token" not in page                                                                  # no input exists for it
    assert "s:hec_token" not in ui.render_advanced(rows).decode()
    with pytest.raises(ui.SettingsError, match="secret"):
        ui.plan(rows, {"hec_token": "x"})
    assert ui.simple_requested(rows, {"c:hec_token": "x"}) == {}


def test_an_unknown_setting_or_an_ill_typed_value_is_refused_and_an_unchanged_value_is_not_a_change():
    rows = live_rows()
    with pytest.raises(ui.SettingsError, match="not a setting"):
        ui.plan(rows, {"nope": "1"})
    with pytest.raises(ui.SettingsError):
        ui.plan(rows, {"max_login_attempts": "five"})
    assert ui.plan(rows, {"max_login_attempts": "5"}) == []
    change = ui.plan(rows, {"debug_retention": "2"})[0]
    assert (change["old"], change["new"], change["restart"]) == ("1", "2", ["kasm_api"])


def test_the_advanced_view_lists_every_setting_searchable_and_marks_restarts():
    rows = live_rows()
    page = ui.render_advanced(rows).decode()
    assert f"{len(rows)} of {len(rows)} settings" in page and "restarts kasm_api" in page
    narrowed = ui.render_advanced(rows, query="debug").decode()
    assert "1 of" in narrowed and "debug_retention" in narrowed and "max_login_attempts" not in narrowed


def test_a_value_with_markup_is_escaped_on_both_screens():
    rows = live_rows()
    rows[6]["value"] = "<script>alert(1)</script>"
    for page in (ui.render_simple(rows).decode(), ui.render_advanced(rows).decode()):
        assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_a_kasm_without_a_setting_simply_does_not_offer_it():
    rows = [r for r in live_rows() if r["name"] != "log_retention"]
    assert "Normal logs" not in ui.render_simple(rows).decode()


# ---- through the machine ---------------------------------------------------------------------------------------------------------------
def test_a_change_goes_through_kasms_admin_api_is_read_back_and_kept_with_its_real_values(world):
    import kasm_telemetry as kt
    setup, fake = running(world)
    result = setup.apply_settings({"log_retention": "14", "debug_retention": "2", "max_login_attempts": "5"})
    assert [(a["name"], a["old"], a["new"], a["verified"]) for a in result["applied"]] == [("log_retention", "7", "14", True), ("debug_retention", "1", "2", True)]
    assert result["failed"] == [] and result["restart"] == ["kasm_api"]
    assert fake.updates == [[{"id": "id-log_retention", "value": "14"}, {"id": "id-debug_retention", "value": "2"}]]
    password = setup.vault.get("KASM_ADMIN_PASSWORD")
    assert not [c for c in fake.calls if password in " ".join(c) or '"14"' in " ".join(c)]            # neither the password nor a value is on a command line
    report = {r["name"]: r for r in kt.setting_report(setup.telemetry_db(), 0)}
    assert (report["log_retention"]["last_old"], report["log_retention"]["last_new"]) == ("7", "14")


def test_a_refusal_by_kasm_is_reported_not_recorded_and_nothing_is_claimed_applied(world):
    setup, fake = running(world)
    fake.refuse = {"id-log_retention"}
    result = setup.apply_settings({"log_retention": "14", "debug_retention": "2"})
    assert [f["title"] for f in result["failed"]] == ["Log retention (days)"] and [a["name"] for a in result["applied"]] == ["debug_retention"]
    import kasm_telemetry as kt
    assert [r["name"] for r in kt.setting_report(setup.telemetry_db(), 0)] == ["debug_retention"]


def test_nothing_is_sent_for_a_refused_request_or_when_nothing_differs(world):
    setup, fake = running(world)
    with pytest.raises(ui.SettingsError):
        setup.apply_settings({"log_retention": "14", "hec_token": "x"})
    assert fake.updates == []                                                                          # one bad entry stops the whole request
    assert setup.apply_settings({"log_retention": "7"}) == {"applied": [], "failed": [], "restart": []} and fake.updates == []


def test_settings_cannot_be_read_or_changed_while_the_vm_is_not_running(world):
    setup, fake = running(world)
    fake.state = "stopped"
    assert setup.read_settings()["ok"] is False
    with pytest.raises(ks.KasmSetupError, match="not running"):
        setup.apply_settings({"log_retention": "14"})


# ---- through the web app ---------------------------------------------------------------------------------------------------------------
class Machine:
    def __init__(self):
        self.applied, self.ok, self.view = [], True, None

    def read_view(self):
        return self.view

    def write_view(self, names):
        self.view = names

    def status(self):
        return {"present": True, "installed": True, "running": True, "url": "https://x"}

    def read_settings(self):
        return {"ok": True, "settings": live_rows()} if self.ok else {"ok": False, "reason": "The Kasm VM is not running."}

    def apply_settings(self, requested):
        self.applied.append(requested)
        changes = ui.plan(live_rows(), requested)
        return {"applied": [{"name": c["name"], "title": c["title"], "old": c["old"], "new": c["new"], "verified": True} for c in changes], "failed": [], "restart": ["kasm_api"] if changes else []}


@pytest.fixture
def web():
    machine, audit = Machine(), []
    case = _RealServerCase(_base_deps(kasm_machine=machine, audit=audit.append))
    yield case, machine, audit
    case.close()


def test_both_screens_need_a_login_and_show_the_live_settings(web):
    case, _, _ = web
    for path in ("/workspaces/settings", "/workspaces/settings/advanced"):
        assert req(case, "GET", path, cookie=False)[0] == 303
        status, _, page = req(case, "GET", path)
        assert status == 200 and "Kasm settings" in page
    assert "How long a sign-in lasts" in req(case, "GET", "/workspaces/settings")[2]
    assert "max_login_attempts" in req(case, "GET", "/workspaces/settings/advanced")[2]


def test_when_the_vm_is_not_running_the_screen_says_so_instead_of_failing(web):
    case, machine, _ = web
    machine.ok = False
    status, _, page = req(case, "GET", "/workspaces/settings")
    assert status == 200 and "not running" in page


def test_applying_needs_the_box_ticked_and_a_login_and_changes_only_what_was_changed(web):
    case, machine, audit = web
    assert req(case, "POST", "/workspaces/settings/apply", {"mode": "simple", "c:log_retention": "30"}, cookie=False)[0] in (303, 401) and machine.applied == []
    status, location, _ = req(case, "POST", "/workspaces/settings/apply", {"mode": "simple", "c:log_retention": "30"})
    assert status == 303 and "Tick" in location.replace("+", " ") and machine.applied == []
    status, _, page = req(case, "POST", "/workspaces/settings/apply", {"mode": "simple", "confirm": "yes", "c:log_retention": "30", "c:max_login_attempts": "5"})
    assert status == 200 and "Changed" in page and "30" in page
    assert machine.applied == [{"log_retention": "30", "max_login_attempts": "5"}]
    assert audit[-1] == {"event": "kasm_settings_changed", "settings": ["log_retention"], "failed": 0}   # the audit names the settings, never their values


def test_the_advanced_form_changes_any_setting_and_a_bad_value_goes_back_with_the_reason(web):
    case, machine, _ = web
    status, _, page = req(case, "POST", "/workspaces/settings/apply", {"mode": "advanced", "confirm": "yes", "s:debug_retention": "3"})
    assert status == 200 and "restarted" in page
    status, location, _ = req(case, "POST", "/workspaces/settings/apply", {"mode": "advanced", "confirm": "yes", "s:max_login_attempts": "many"})
    assert status == 303 and location.startswith("/workspaces/settings/advanced?notice=")
    status, location, _ = req(case, "POST", "/workspaces/settings/apply", {"mode": "advanced", "confirm": "yes", "s:hec_token": "x"})
    assert status == 303 and "secret" in location


def test_the_workspaces_page_links_to_the_settings_only_when_kasm_is_running(web):
    case, _, _ = web
    assert "/workspaces/settings" in req(case, "GET", "/workspaces")[2]


def test_the_scripts_run_inside_the_vm_are_valid_bash():
    import subprocess
    import kasm_telemetry as kt
    for script in (kt.SETTINGS_SCRIPT, kt.UPDATE_SETTINGS_SCRIPT):
        assert subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True).returncode == 0


# ---- choosing what the everyday screen shows -------------------------------------------------------------------------------------------
def test_the_shipped_everyday_list_is_what_shows_until_the_person_chooses():
    rows = live_rows()
    assert [c["setting"] for _g, c in ui.ordered_controls(rows)] == [n for n in ui.default_shown() if n in {r["name"] for r in rows}]


def test_any_setting_can_be_put_on_the_everyday_screen_with_a_control_made_from_its_type_and_kasms_own_words():
    rows = live_rows()
    page = ui.render_simple(rows, shown=["max_sessions_note", "odd_flag", "notice_message"]).decode()
    assert "Sessions note limit" in page and "Kasm&#x27;s own words about sessions" in page                           # Kasm's own title and description
    assert 'name="c:odd_flag"' in page.replace("'", '"') and "<select" in page and "<textarea" in page               # a switch for a bool, a box for multiline text
    assert "password_min_length" not in page and "How long a sign-in lasts" not in page                                 # what was not chosen is not there
    assert ui.simple_requested(rows, {"c:max_login_attempts": "7", "c:log_retention": "30"}, shown=["max_login_attempts"]) == {"max_login_attempts": "7"}   # only what is in the view can be sent from it


def test_the_order_chosen_is_the_order_shown_and_settings_that_belong_together_still_share_a_box():
    rows = live_rows()
    page = ui.render_simple(rows, shown=["debug_retention", "update_check", "log_retention"]).decode()
    assert page.index("Debug logs") < page.index("Update check") < page.index("Normal logs")
    assert page.count("<fieldset>") == 3                                                                                # the log group is split by the one between


def test_the_customise_form_keeps_ticked_settings_in_list_order_and_never_a_secret_or_an_unknown_name():
    rows = live_rows()
    form = {"order": "update_check,log_retention,max_login_attempts,hec_token,ghost", "show:log_retention": "on", "show:update_check": "on", "show:hec_token": "on",
            "show:ghost": "on", "show:auto_agent": "on"}
    assert ui.shown_from_form(rows, form) == ["update_check", "log_retention", "auto_agent"]                            # unticked dropped, a tick without a place last
    page = ui.render_customize(rows, ["log_retention"]).decode()
    assert 'name="show:log_retention"' in page.replace("'", '"') and "show:hec_token" not in page and "checked" in page
    assert page.count("type='checkbox'") == len(rows) - 1                                                              # one switch per setting, none for the secret


def test_the_customise_page_and_save_work_through_the_web_app_and_persist_the_choice(web):
    case, machine, audit = web
    assert "Choose what appears" in req(case, "GET", "/workspaces/settings/customize")[2]
    assert req(case, "POST", "/workspaces/settings/customize", {"order": "update_check", "show:update_check": "on"}, cookie=False)[0] in (303, 401) and machine.view is None
    status, location, _ = req(case, "POST", "/workspaces/settings/customize", {"order": "update_check", "show:update_check": "on"})
    assert status == 303 and machine.view == ["update_check"]
    page = req(case, "GET", "/workspaces/settings")[2]
    assert 'name="c:update_check"' in page.replace("'", '"') and "How long a sign-in lasts" not in page
    req(case, "POST", "/workspaces/settings/customize", {"reset": "yes"})
    assert machine.view is None and "How long a sign-in lasts" in req(case, "GET", "/workspaces/settings")[2]
    assert [a["event"] for a in audit].count("kasm_settings_view_changed") == 2


def test_the_choice_is_kept_on_the_admin_volume_and_does_not_touch_kasm(world):
    setup, fake = running(world)
    assert setup.read_view() is None
    before = len(fake.calls)
    setup.write_view(["update_check", "log_retention"])
    assert setup.read_view() == ["update_check", "log_retention"] and len(fake.calls) == before                         # a file only; nothing sent to Kasm
    setup.view_path.write_text("not json")
    assert setup.read_view() is None                                                                                    # damaged: the shipped list, not a failure
    setup.write_view(None)
    assert not setup.view_path.exists()
