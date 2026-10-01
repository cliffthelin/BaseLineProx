"""Human-in-the-loop confirmation for drive actions (v0.2 row 65).

Every drive action needs a person to confirm that exact request, each time. A confirmation is bound to the
session that asked, the exact action, parameters and drive; it needs a typed phrase AND this machine's root
password or passphrase (which a script cannot read off the page); it is single-use, short-lived and slow
enough to read. The only exception is a standing approval a person grants: scoped to one action and one
drive, limited in time and uses, revocable, and also gated by the password. Nothing here touches a real
device: the 'drive' is just a serial and some text."""
import json

import pytest

import hitl

SERIAL = "MD89N41071210AP4E"
PARAMS = {"device_path": "/dev/sdb"}
SECRET = "correct-secret"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def events():
    return []


@pytest.fixture
def store(clock, events):
    return hitl.ConfirmationStore(verify_secret=lambda s: s == SECRET, clock=clock, audit=events.append)


def _challenge(store, action="repair", params=PARAMS, serial=SERIAL, session="sess-A"):
    return store.challenge(session, action, params, serial, "Repair the volumes on the PC401")


def _confirm(store, chal, typed=None, secret=SECRET, session="sess-A", clock=None, wait=5):
    if clock is not None:
        clock.advance(wait)
    return store.confirm(session, chal["id"], typed if typed is not None else chal["phrase"], secret)


# --- the challenge ----------------------------------------------------------

def test_a_challenge_describes_the_request_and_asks_for_a_phrase_tied_to_the_drive(store):
    chal = _challenge(store)
    assert chal["phrase"] == "REPAIR " + SERIAL[-6:].upper()
    assert "PC401" in chal["summary"] and chal["expires_in"] > 0 and chal["min_wait"] >= 1


def test_each_action_has_its_own_verb_so_the_phrase_cannot_be_reused_across_actions(store):
    phrases = {a: _challenge(store, action=a)["phrase"] for a in sorted(hitl.CONFIRMED_ACTIONS)}
    assert len(set(phrases.values())) == len(phrases)


def test_an_action_that_needs_no_confirmation_cannot_be_challenged(store):
    with pytest.raises(ValueError):
        _challenge(store, action="list_volumes")


def test_the_challenge_id_is_unguessable(store):
    ids = {_challenge(store)["id"] for _ in range(hitl.MAX_PENDING)}
    assert len(ids) == hitl.MAX_PENDING and all(len(i) >= 16 for i in ids)


# --- confirming ---------------------------------------------------------------

def test_a_correct_confirmation_yields_an_authorization_for_exactly_that_request(store, clock):
    chal = _challenge(store)
    auth = _confirm(store, chal, clock=clock)
    assert auth.valid_for("repair", PARAMS, SERIAL) is True


def test_an_authorization_does_not_cover_a_different_action_drive_or_parameters(store, clock):
    auth = _confirm(store, _challenge(store), clock=clock)
    assert auth.valid_for("mount_volume", PARAMS, SERIAL) is False
    assert auth.valid_for("repair", PARAMS, "FD01N6557110C271B") is False
    assert auth.valid_for("repair", {"device_path": "/dev/sdc"}, SERIAL) is False
    assert auth.valid_for("repair", {**PARAMS, "lv_name": "root"}, SERIAL) is False


def test_confirmation_is_refused_if_it_comes_too_fast_to_have_been_read(store, clock):
    chal = _challenge(store)
    clock.advance(0.2)
    with pytest.raises(hitl.ConfirmationError, match="wait"):
        store.confirm("sess-A", chal["id"], chal["phrase"], SECRET)


def test_a_wrong_phrase_is_refused_and_does_not_consume_the_challenge(store, clock):
    chal = _challenge(store)
    clock.advance(5)
    with pytest.raises(hitl.ConfirmationError, match="phrase"):
        store.confirm("sess-A", chal["id"], "REPAIR XXXXXX", SECRET)
    assert _confirm(store, chal).valid_for("repair", PARAMS, SERIAL)           # the right phrase still works


def test_the_phrase_check_ignores_case_and_extra_spaces_only(store, clock):
    chal = _challenge(store)
    clock.advance(5)
    assert store.confirm("sess-A", chal["id"], "  " + chal["phrase"].lower().replace(" ", "   ") + " ", SECRET)


def test_a_wrong_secret_is_refused_even_with_the_right_phrase(store, clock):
    chal = _challenge(store)
    clock.advance(5)
    with pytest.raises(hitl.ConfirmationError, match="credential"):
        store.confirm("sess-A", chal["id"], chal["phrase"], "guess")


def test_an_empty_secret_is_refused(store, clock):
    chal = _challenge(store)
    clock.advance(5)
    with pytest.raises(hitl.ConfirmationError):
        store.confirm("sess-A", chal["id"], chal["phrase"], "")


def test_another_session_cannot_confirm_someone_elses_challenge(store, clock):
    chal = _challenge(store, session="sess-A")
    clock.advance(5)
    with pytest.raises(hitl.ConfirmationError, match="session"):
        store.confirm("sess-B", chal["id"], chal["phrase"], SECRET)


def test_a_challenge_expires(store, clock):
    chal = _challenge(store)
    clock.advance(hitl.DEFAULT_TTL_S + 1)
    with pytest.raises(hitl.ConfirmationError, match="expired|unknown"):
        store.confirm("sess-A", chal["id"], chal["phrase"], SECRET)


def test_a_challenge_can_only_be_confirmed_once(store, clock):
    chal = _challenge(store)
    _confirm(store, chal, clock=clock)
    with pytest.raises(hitl.ConfirmationError):
        store.confirm("sess-A", chal["id"], chal["phrase"], SECRET)


def test_an_unknown_challenge_id_is_refused(store):
    with pytest.raises(hitl.ConfirmationError):
        store.confirm("sess-A", "no-such-id", "REPAIR X", SECRET)


# --- using the authorization: single use --------------------------------------

def test_an_authorization_can_be_used_exactly_once(store, clock):
    auth = _confirm(store, _challenge(store), clock=clock)
    assert hitl.require(auth, "repair", PARAMS, SERIAL) is None            # first use passes
    with pytest.raises(hitl.ConfirmationRequired):
        hitl.require(auth, "repair", PARAMS, SERIAL)                        # a second use is refused


def test_an_authorization_expires_if_not_used_promptly(store, clock):
    auth = _confirm(store, _challenge(store), clock=clock)
    clock.advance(hitl.AUTHORIZATION_USE_WINDOW_S + 1)
    with pytest.raises(hitl.ConfirmationRequired):
        hitl.require(auth, "repair", PARAMS, SERIAL)


def test_no_authorization_means_refused_for_every_confirmed_action():
    for action in hitl.CONFIRMED_ACTIONS:
        with pytest.raises(hitl.ConfirmationRequired):
            hitl.require(None, action, PARAMS, SERIAL)


@pytest.mark.parametrize("fake", ["yes", True, 1, {"valid": True}, object(), "approved"])
def test_a_forged_authorization_is_refused(fake):
    with pytest.raises(hitl.ConfirmationRequired):
        hitl.require(fake, "repair", PARAMS, SERIAL)


def test_an_authorization_copied_from_another_store_is_refused(clock):
    other = hitl.ConfirmationStore(verify_secret=lambda s: True, clock=clock)
    chal = other.challenge("s", "repair", PARAMS, SERIAL, "x")
    clock.advance(5)
    auth = other.confirm("s", chal["id"], chal["phrase"], "anything")
    mine = hitl.ConfirmationStore(verify_secret=lambda s: True, clock=clock)
    assert auth.valid_for("repair", PARAMS, SERIAL) is True                 # valid where it was minted
    assert mine.owns(auth) is False


def test_an_unconfirmed_action_name_passes_through_require(store):
    assert hitl.require(None, "list_volumes", PARAMS, SERIAL) is None


# --- standing approvals (the only exception) -----------------------------------

def _grant(store, **kw):
    args = dict(action_id="mount_volume", serial=SERIAL, minutes=10, max_uses=2, secret=SECRET, session="sess-A")
    args.update(kw)
    typed = args.pop("typed", f"I AUTHORIZE MOUNT {SERIAL[-6:].upper()} FOR {args['minutes']} MINUTES")
    return store.grant(args.pop("session"), typed=typed, **args)


def test_a_standing_approval_needs_the_password_and_a_typed_sentence(store):
    with pytest.raises(hitl.ConfirmationError):
        _grant(store, secret="wrong")
    with pytest.raises(hitl.ConfirmationError):
        _grant(store, typed="yes please")
    assert _grant(store)["uses_left"] == 2


def test_a_grant_covers_only_its_action_and_drive_and_counts_down(store):
    _grant(store)
    a1 = store.authorization_from_grant("sess-A", "mount_volume", PARAMS, SERIAL)
    assert a1 is not None and a1.valid_for("mount_volume", PARAMS, SERIAL)
    assert store.authorization_from_grant("sess-A", "repair", PARAMS, SERIAL) is None
    assert store.authorization_from_grant("sess-A", "mount_volume", PARAMS, "FD01N6557110C271B") is None
    assert store.authorization_from_grant("sess-A", "mount_volume", PARAMS, SERIAL) is not None   # second use
    assert store.authorization_from_grant("sess-A", "mount_volume", PARAMS, SERIAL) is None       # used up


def test_a_grant_expires(store, clock):
    _grant(store, minutes=5)
    clock.advance(5 * 60 + 1)
    assert store.authorization_from_grant("sess-A", "mount_volume", PARAMS, SERIAL) is None


def test_a_grant_is_tied_to_the_session_that_made_it(store):
    _grant(store)
    assert store.authorization_from_grant("sess-B", "mount_volume", PARAMS, SERIAL) is None


def test_a_grant_can_be_revoked(store):
    g = _grant(store)
    assert store.revoke(g["id"]) is True
    assert store.authorization_from_grant("sess-A", "mount_volume", PARAMS, SERIAL) is None


@pytest.mark.parametrize("kw", [{"minutes": 0}, {"minutes": 61}, {"minutes": -5}, {"max_uses": 0}, {"max_uses": 6}])
def test_a_grant_is_limited_in_time_and_uses(store, kw):
    with pytest.raises(hitl.ConfirmationError):
        _grant(store, **kw)


def test_the_most_destructive_action_can_never_be_granted_ahead_of_time(store):
    """Installing over a drive is confirmed by a person every single time, with no standing approval."""
    with pytest.raises(hitl.ConfirmationError, match="every time"):
        _grant(store, action_id="build_self_installer", typed=f"I AUTHORIZE INSTALL {SERIAL[-6:]} FOR 10 MINUTES")


def test_a_grant_never_exceeds_the_authorized_serial(store):
    _grant(store)
    assert store.authorization_from_grant("sess-A", "mount_volume", {"device_path": "/dev/anything"}, "SOMEOTHER") is None


# --- limits and audit ------------------------------------------------------------

def test_too_many_pending_challenges_are_refused(store):
    for _ in range(hitl.MAX_PENDING):
        _challenge(store)
    with pytest.raises(ValueError, match="pending"):
        _challenge(store)


def test_every_step_is_audited_and_the_secret_never_is(store, clock, events):
    chal = _challenge(store)
    clock.advance(5)
    with pytest.raises(hitl.ConfirmationError):
        store.confirm("sess-A", chal["id"], chal["phrase"], "wrong-secret-xyz")
    auth = store.confirm("sess-A", chal["id"], chal["phrase"], SECRET)
    hitl.require(auth, "repair", PARAMS, SERIAL)
    kinds = [e["event"] for e in events]
    assert kinds == ["challenge", "confirm_failed", "confirmed", "authorization_used"]
    blob = json.dumps(events)
    assert "wrong-secret-xyz" not in blob and SECRET not in blob


def test_the_audit_file_is_append_only_and_private(tmp_path):
    path = tmp_path / "audit" / "hitl.jsonl"
    sink = hitl.AuditFile(path)
    sink({"event": "a"})
    sink({"event": "b"})
    assert [json.loads(l)["event"] for l in path.read_text().splitlines()] == ["a", "b"]
    assert path.stat().st_mode & 0o777 == 0o600
    sink({"event": "c"})
    assert path.read_text().splitlines()[0] and len(path.read_text().splitlines()) == 3        # earlier lines untouched


@pytest.mark.parametrize("action,params,serial", [
    ("mount_volume", PARAMS, SERIAL), ("repair", PARAMS, "FD01N6557110C271B"), ("repair", {"device_path": "/dev/sdc"}, SERIAL),
    ("repair", {**PARAMS, "lv_name": "root"}, SERIAL),
])
def test_require_refuses_an_authorization_used_for_a_different_request_and_it_stays_usable_for_the_right_one(
        store, clock, action, params, serial):
    auth = _confirm(store, _challenge(store), clock=clock)
    with pytest.raises(hitl.ConfirmationRequired):
        hitl.require(auth, action, params, serial)
    assert hitl.require(auth, "repair", PARAMS, SERIAL) is None            # a wrong attempt does not burn it
