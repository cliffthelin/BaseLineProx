import pytest

import rebuild_authority as ra

DRIVES = {"ONE": "SYNTH-1", "TWO": "SYNTH-2"}


@pytest.fixture
def clock():
    t = {"now": 1000.0}
    return t


@pytest.fixture
def auth(tmp_path, clock):
    return ra.Authority(tmp_path, DRIVES, now=lambda: clock["now"])


def test_unknown_target_is_refused(auth):
    assert not auth.request("NOPE")["ok"]


def test_right_code_approves_once(auth):
    req = auth.request("ONE")
    assert auth.approve(req["id"], req["code"])["ok"]
    assert not auth.approve(req["id"], req["code"])["ok"]
    assert auth.take_approved()["target"] == "ONE" and auth.take_approved() is None


def test_wrong_code_never_approves_and_closes_after_three(auth):
    req = auth.request("ONE")
    for _ in range(3):
        assert not auth.approve(req["id"], "00000000x")["ok"]
    assert not auth.approve(req["id"], req["code"])["ok"] and auth.take_approved() is None


def test_expired_request_cannot_be_approved(auth, clock):
    req = auth.request("ONE")
    clock["now"] += ra.TTL_SECONDS + 1
    assert "expired" in auth.approve(req["id"], req["code"])["error"]


def test_code_of_one_request_does_not_approve_another(auth):
    a, b = auth.request("ONE"), auth.request("TWO")
    assert not auth.approve(b["id"], a["code"])["ok"]


def test_second_request_for_a_running_target_is_refused(auth):
    req = auth.request("ONE")
    auth.approve(req["id"], req["code"])
    assert not auth.request("ONE")["ok"]


def test_code_is_not_stored_in_clear(auth, tmp_path):
    req = auth.request("ONE")
    assert req["code"] not in "".join(p.read_text() for p in tmp_path.glob("*.json"))


def test_bad_id_is_rejected(auth):
    assert not auth.approve("../../etc/passwd", "1")["ok"]
