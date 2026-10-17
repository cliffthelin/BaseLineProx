"""Proposals: what is accepted, what is refused and why, how a trial is judged."""
import json

import pytest

import kasm_proposals as kp
import kasm_telemetry as kt
from test_kasm_settings_ui import live_rows

NOW = 1_800_000_000.0
FP = {"abc123abc123"}
METRICS = {"mem_avail_pct", "disk_opt_kasm_used_pct"}


def good(**kw):
    base = {"title": "Keep debug logs shorter", "concerns": ["abc123abc123"], "rationale": "The disk fills with debug logs.", "settings": {"debug_retention": "2"},
            "expect": {"metric": "disk_opt_kasm_used_pct", "direction": "down"}, "rollback": "Set it back to 1."}
    base.update(kw)
    return base


def check(raw):
    return kp.validate(raw, live_rows(), FP, METRICS)


def test_a_good_proposal_is_accepted_in_its_stored_shape():
    p = check(good())
    assert p["settings"] == {"debug_retention": "2"} and p["expect"] == {"metric": "disk_opt_kasm_used_pct", "direction": "down"} and p["sizes"] == {}


@pytest.mark.parametrize("change,why", [
    ({"settings": {"no_such_setting": "1"}}, "not a setting"),
    ({"settings": {"hec_token": "x"}}, "secret"),
    ({"settings": {"max_login_attempts": "many"}}, "whole number"),
    ({"settings": {"debug_retention": "1"}}, "already has"),
    ({"settings": {}}, "no setting and no size"),
    ({"concerns": ["feedfeedfeed"]}, "does not exist"),
    ({"expect": None}, "how success is measured"),
    ({"expect": {"metric": "mem_avail_pct", "direction": "sideways"}}, "how success is measured"),
    ({"expect": {"metric": "never_measured", "direction": "up"}}, "no data"),
    ({"expect": {"metric": "mem_avail_pct", "concern": "abc123abc123", "direction": "down"}}, "either a metric or a concern"),
    ({"expect": {"concern": "abc123abc123", "direction": "up"}}, "go down"),
    ({"settings": {}, "sizes": {"memory_mb": 1}}, "out of range"),
    ({"settings": {}, "sizes": {"disk_gb": 4}}, "memory_mb, cpus"),
    ({"title": ""}, "title"),
    ({"rationale": 5}, "rationale"),
])
def test_what_does_not_fit_is_refused_with_the_reason(change, why):
    with pytest.raises(kp.ProposalError, match=why):
        check(good(**change))


def test_a_secret_pasted_into_the_words_is_removed_before_it_is_kept():
    p = check(good(rationale="It was password=hunter2 in the log", title="Bearer abcdef.ghijkl.mnopqr"))
    assert "hunter2" not in p["rationale"] and "abcdef" not in p["title"]


def test_a_size_recommendation_alone_is_a_valid_proposal_but_a_wrong_type_is_not():
    assert check(good(settings={}, sizes={"memory_mb": 12288, "cpus": 4}))["sizes"] == {"memory_mb": 12288, "cpus": 4}
    with pytest.raises(kp.ProposalError):
        check(good(settings={}, sizes={"memory_mb": "lots"}))
    with pytest.raises(kp.ProposalError):
        check(good(settings={}, sizes={"cpus": True}))


# ---- the inbox -------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    return kp.ProposalStore(tmp_path / "proposals")


def drop(store, name, body):
    (store.folder("inbox") / name).write_text(body if isinstance(body, str) else json.dumps(body))


def intake(store):
    return store.ingest(live_rows(), FP, METRICS, NOW)


def test_a_good_file_becomes_a_pending_proposal_and_the_inbox_is_emptied(store):
    drop(store, "shorter-debug.json", good())
    got = intake(store)
    assert got["accepted"] == ["shorter-debug"] and got["rejected"] == [] and list(store.folder("inbox").iterdir()) == []
    assert store.get("pending", "shorter-debug")["state"] == "pending"


def test_a_bad_file_is_archived_as_rejected_with_its_reason_so_the_writer_can_see_why(store):
    drop(store, "bad-setting.json", good(settings={"hec_token": "x"}))
    drop(store, "not-json.json", "{ nope")
    drop(store, "Bad Name.json", good())
    drop(store, "notes.txt", "hello")
    got = intake(store)
    assert got["accepted"] == [] and {r["id"] for r in got["rejected"]} == {"bad-setting", "not-json", "Bad Name", "notes"}
    assert "secret" in store.get("archive", "bad-setting")["reason"] and store.get("archive", "bad-setting")["verdict"] == "rejected"
    assert store.get("archive", "not-json")["reason"] == "the file is not valid JSON"
    assert store.get("archive", "Bad Name") is None                                                      # an unsafe name is reported but never used as a file name
    assert list(store.folder("inbox").iterdir()) == []


def test_the_same_change_is_not_taken_in_twice_nor_again_after_it_was_tried(store):
    drop(store, "first.json", good())
    intake(store)
    drop(store, "second.json", good(title="Another try"))
    assert "already here as first" in intake(store)["rejected"][0]["reason"]
    store.move("first", "pending", "archive", verdict="worse", ended=NOW)
    drop(store, "third.json", good(title="And again"))
    assert "(worse)" in intake(store)["rejected"][0]["reason"]


def test_only_a_few_wait_for_a_decision_at_once_and_the_rest_wait_in_the_inbox(store):
    for i in range(kp.MAX_PENDING + 2):
        drop(store, f"p{i}.json", good(settings={"log_retention": str(10 + i)}))
    got = intake(store)
    assert len(got["accepted"]) == kp.MAX_PENDING and got["waiting"] == 2 and len(list(store.folder("inbox").iterdir())) == 2


def test_an_oversize_file_is_refused_without_being_read(store):
    drop(store, "huge.json", "x" * 30000)
    assert "too large" in intake(store)["rejected"][0]["reason"]


# ---- the check -------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def conn(tmp_path):
    c = kt.open_db(tmp_path / "t.sqlite")
    yield c
    c.close()


def fill(conn, metric, before, after, start, span):
    for i, v in enumerate(before):
        conn.execute("INSERT INTO samples VALUES (?,?,?)", (start - span + (i + 1) * span / (len(before) + 1), metric, v))
    for i, v in enumerate(after):
        conn.execute("INSERT INTO samples VALUES (?,?,?)", (start + (i + 1) * span / (len(after) + 1), metric, v))
    conn.commit()


def test_too_early_or_too_little_data_is_said_plainly_and_never_guessed(conn):
    expect = {"metric": "m", "direction": "down"}
    assert kp.evaluate(conn, expect, NOW - 600, NOW)["status"] == "too-early"
    assert kp.evaluate(conn, expect, NOW - 7200, NOW)["status"] == "no-data"


@pytest.mark.parametrize("before,after,direction,status", [
    ([80] * 6, [50] * 6, "down", "improved"), ([80] * 6, [81] * 6, "down", "no-clear-change"), ([80] * 6, [95] * 6, "down", "worse"),
    ([10] * 6, [20] * 6, "up", "improved"), ([10] * 6, [5] * 6, "up", "worse"),
])
def test_a_measure_is_compared_before_and_after_in_equal_spans(conn, before, after, direction, status):
    fill(conn, "m", before, after, NOW - 7200, 7200)
    got = kp.evaluate(conn, {"metric": "m", "direction": direction}, NOW - 7200, NOW)
    assert got["status"] == status and "before" in got["text"]


def test_a_concern_is_judged_by_how_often_it_was_seen_before_and_during(conn):
    for t in (NOW - 9000, NOW - 8500, NOW - 8000, NOW - 7500):
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?)", (t, "kernel", "error", "fp1", "x"))
    conn.commit()
    expect = {"concern": "fp1", "direction": "down"}
    assert kp.evaluate(conn, expect, NOW - 7200, NOW)["status"] == "improved"
    assert kp.evaluate(conn, {"concern": "never", "direction": "down"}, NOW - 7200, NOW)["status"] == "no-data"
