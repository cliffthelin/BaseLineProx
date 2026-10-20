"""The Wiki and proposals tied to a (fake) running Kasm: intake, trial with the old values kept, verdicts, the archive, and the web page."""
import json

import pytest

import kasm_advice as ka
import kasm_proposals as kp
import kasm_telemetry as kt
from test_baseline_web import _RealServerCase, _base_deps
from test_kasm_settings_ui import Vm, running  # noqa: F401
from test_kasm_setup import world  # noqa: F401
from test_new_web_routes import req

NOW = 1_800_000_000.0
FPRINT = kt.fingerprint("kernel", "disk is filling up")


def proposal(**kw):
    base = {"title": "Keep debug logs shorter", "concerns": [FPRINT], "rationale": "Debug logs fill the disk.", "settings": {"debug_retention": "3"},
            "expect": {"metric": "disk_opt_kasm_used_pct", "direction": "down"}, "rollback": "Set it back to 1."}
    base.update(kw)
    return base


@pytest.fixture
def adv(world):
    setup, fake = running(world)
    conn = setup.telemetry_db()
    conn.execute("INSERT INTO events VALUES (?,?,?,?,?)", (NOW - 3600, "kernel", "error", FPRINT, "disk is filling up"))
    conn.execute("INSERT INTO samples VALUES (?,?,?)", (NOW - 3600, "disk_opt_kasm_used_pct", 80.0))
    conn.commit()
    conn.close()
    return ka.Advice(setup, clock=lambda: NOW), setup, fake


def leave(advice, name, body):
    (advice.store.folder("inbox") / f"{name}.json").write_text(json.dumps(body))


def values(fake):
    return {r["name"]: r["value"] for r in fake.live}


def test_refresh_writes_the_wiki_and_takes_in_a_proposal_checked_against_kasms_own_settings(adv):
    advice, setup, fake = adv
    leave(advice, "shorter", proposal())
    leave(advice, "bad", proposal(settings={"hec_token": "x"}))
    done = advice.refresh()
    assert done["wiki"]["concerns"] == 1 and done["proposals"]["accepted"] == ["shorter"] and [r["id"] for r in done["proposals"]["rejected"]] == ["bad"]
    assert (advice.root / "wiki" / "brief.md").is_file() and "hec_token" not in (advice.root / "wiki" / "settings.json").read_text()
    pending = advice.overview()["pending"][0]
    assert pending["changes"] == [{"name": "debug_retention", "title": "Debug retention (hours)", "current": "1", "new": "3", "restart": ["kasm_api"]}]


def test_a_proposal_is_not_judged_without_kasm_answering_and_waits_in_the_inbox(adv):
    advice, setup, fake = adv
    fake.state = "stopped"
    leave(advice, "shorter", proposal())
    done = advice.refresh()
    assert done["proposals"]["accepted"] == [] and done["proposals"]["waiting"] == 1                          # nothing is rejected just because Kasm was off


def test_trying_it_changes_the_setting_keeps_the_old_value_and_allows_only_one_trial(adv):
    advice, setup, fake = adv
    leave(advice, "shorter", proposal())
    leave(advice, "second", proposal(title="Other", settings={"log_retention": "30"}))
    advice.refresh()
    got = advice.try_it("shorter")
    assert values(fake)["debug_retention"] == "3" and got["restart"] == ["kasm_api"]
    trial = advice.store.get("trial", "shorter")
    assert trial["before"] == {"debug_retention": "1"} and trial["applied"] == {"debug_retention": "3"} and trial["started"] == NOW
    with pytest.raises(kp.ProposalError, match="Finish the trial"):
        advice.try_it("second")
    assert values(fake)["log_retention"] == "7"


def test_worse_or_the_same_puts_the_old_value_back_and_archives_with_baselines_own_check(adv):
    advice, setup, fake = adv
    leave(advice, "shorter", proposal())
    advice.refresh()
    advice.try_it("shorter")
    done = advice.finish("shorter", "worse", "disk got fuller", now=NOW + 600)
    assert values(fake)["debug_retention"] == "1" and done["kept"] is False and done["check"]["status"] == "too-early"
    archived = advice.store.get("archive", "shorter")
    assert archived["verdict"] == "worse" and archived["note"] == "disk got fuller" and advice.store.list("trial") == []
    assert "Result: **worse**" in (advice.refresh(now=NOW + 700) and (advice.root / "wiki" / "tried.md").read_text())          # the next brief shows it was tried


def test_better_keeps_the_change_and_offers_it_for_the_recipe(adv):
    advice, setup, fake = adv
    leave(advice, "shorter", proposal())
    advice.refresh()
    advice.try_it("shorter")
    done = advice.finish("shorter", "better", now=NOW + 7200)
    assert values(fake)["debug_retention"] == "3" and done["kept"] and done["recipe_settings"] == {"debug_retention": "3"}


def test_a_setting_changed_again_since_the_trial_is_not_overwritten_by_the_put_back(adv):
    advice, setup, fake = adv
    leave(advice, "shorter", proposal())
    advice.refresh()
    advice.try_it("shorter")
    setup.apply_settings({"debug_retention": "9"})                                  # someone changed it again during the trial
    done = advice.finish("shorter", "same", now=NOW + 7200)
    assert values(fake)["debug_retention"] == "9" and done["left_as_found"] == ["debug_retention"]


def test_a_partly_refused_trial_puts_back_what_did_change_and_starts_nothing(adv):
    advice, setup, fake = adv
    leave(advice, "two", proposal(settings={"log_retention": "30", "debug_retention": "3"}))
    advice.refresh()
    fake.refuse = {"id-debug_retention"}
    with pytest.raises(kp.ProposalError, match="Kasm refused"):
        advice.try_it("two")
    assert values(fake)["log_retention"] == "7" and advice.store.get("pending", "two") and advice.store.list("trial") == []


def test_a_size_only_proposal_can_be_archived_but_has_nothing_to_try(adv):
    advice, setup, fake = adv
    leave(advice, "bigger", proposal(settings={}, sizes={"memory_mb": 12288}))
    advice.refresh()
    with pytest.raises(kp.ProposalError, match="only recommends a size"):
        advice.try_it("bigger")
    assert advice.archive("bigger", "will do by hand")["verdict"] == "not tried"


def test_the_checks_before_and_after_use_the_telemetry_the_trial_ran_through(adv):
    advice, setup, fake = adv
    conn = setup.telemetry_db()
    start = NOW
    for i in range(8):
        conn.execute("INSERT INTO samples VALUES (?,?,?)", (start - 7000 + i * 800, "disk_opt_kasm_used_pct", 80.0))
        conn.execute("INSERT INTO samples VALUES (?,?,?)", (start + 100 + i * 800, "disk_opt_kasm_used_pct", 55.0))
    conn.commit()
    conn.close()
    leave(advice, "shorter", proposal())
    advice.refresh()
    advice.try_it("shorter")
    trial = advice.overview(now=NOW + 7000)["trials"][0]
    assert trial["check"]["status"] == "improved"


def test_telemetry_collection_keeps_the_wiki_current_and_a_failure_does_not_stop_it(adv, monkeypatch):
    advice, setup, fake = adv
    got = setup.collect_telemetry(now=NOW)
    assert got["collected"] and got["wiki"]["concerns"] == 1
    monkeypatch.setattr(ka.Advice, "refresh", lambda self, *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert setup.collect_telemetry(now=NOW + 60)["wiki"] == {"error": "disk full"}


# ---- the page ---------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def web(adv):
    advice, setup, fake = adv
    audit = []
    case = _RealServerCase(_base_deps(kasm_machine=setup, kasm_advice=advice, audit=audit.append))
    yield case, advice, fake, audit
    case.close()


def post(case, action, form, cookie=True):
    return req(case, "POST", f"/workspaces/suggestions/{action}", form, cookie=cookie)


def test_the_page_needs_a_login_shows_the_wiki_and_where_to_point_an_ai(web):
    case, advice, _, _ = web
    assert req(case, "GET", "/workspaces/suggestions", cookie=False)[0] == 303
    post(case, "refresh", {})
    page = req(case, "GET", "/workspaces/suggestions")[2]
    assert str(advice.root / "wiki" / "brief.md") in page and "Nothing is waiting." in page


def test_a_proposal_is_shown_as_text_even_when_it_is_written_to_look_like_markup(web):
    case, advice, _, _ = web
    leave(advice, "sneaky", proposal(title="<script>alert(1)</script>", rationale="<img src=x onerror=alert(2)>"))
    post(case, "refresh", {})
    page = req(case, "GET", "/workspaces/suggestions")[2]
    assert "<script>alert(1)" not in page and "<img src=x" not in page and "&lt;script&gt;" in page


def test_trying_ending_and_archiving_need_a_login_and_a_ticked_box_and_are_audited_without_values(web):
    case, advice, fake, audit = web
    leave(advice, "shorter", proposal())
    leave(advice, "other", proposal(title="Other", settings={"log_retention": "30"}))
    post(case, "refresh", {})
    assert post(case, "try", {"id": "shorter", "confirm": "yes"}, cookie=False)[0] in (303, 401) and values(fake)["debug_retention"] == "1"
    status, location, _ = post(case, "try", {"id": "shorter"})
    assert "Tick" in location.replace("+", " ") and values(fake)["debug_retention"] == "1"
    post(case, "try", {"id": "shorter", "confirm": "yes"})
    assert values(fake)["debug_retention"] == "3" and "On trial" in req(case, "GET", "/workspaces/suggestions")[2]
    status, location, _ = post(case, "try", {"id": "other", "confirm": "yes"})
    assert "Finish the trial" in location.replace("+", " ")
    post(case, "finish", {"id": "shorter", "verdict": "worse", "confirm": "yes"})
    assert values(fake)["debug_retention"] == "1"
    post(case, "archive", {"id": "other", "note": "no", "confirm": "yes"})
    page = req(case, "GET", "/workspaces/suggestions")[2]
    assert "Nothing is waiting." in page and "Keep debug logs shorter" in page and "(worse" in page and "(not tried" in page
    assert [a["event"] for a in audit if a["event"].startswith("kasm_suggestion")] == ["kasm_suggestion_refresh", "kasm_suggestion_try", "kasm_suggestion_finish", "kasm_suggestion_archive"]
    assert not any("debug_retention" in json.dumps(a) for a in audit)


def test_an_unknown_action_or_id_is_refused_not_acted_on(web):
    case, _, fake, _ = web
    assert "Unknown" in post(case, "explode", {"id": "x", "confirm": "yes"})[1]
    assert "not waiting" in post(case, "try", {"id": "../../etc/passwd", "confirm": "yes"})[1].replace("+", " ")
