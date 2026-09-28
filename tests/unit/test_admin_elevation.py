"""Tests for admin_elevation.py - the real cross-persona "sudo" gate
for the admin persona (decision record 76). Per direct instruction:
"Admin has open access to each and an additional passphrase. This is
to add an extra guard from it being primary target to get access to
all accounts. it's essentially sudo or root." Deliberately short-lived
(default 15 minutes, settings_store's own admin_elevation_ttl_minutes)
- separate from and much shorter than admin's own base session, so a
compromised admin session alone still can't reach another persona's
data without the passphrase having been entered recently."""
from fake_runner import FakeRunner

import admin_elevation as ae
import settings_store as ss


def test_is_elevated_false_when_never_granted():
    runner = FakeRunner()
    store = ae.ElevationStore()
    assert store.is_elevated(runner, now=1000.0) is False


def test_attempt_elevation_fails_with_the_wrong_passphrase():
    runner = FakeRunner()
    store = ae.ElevationStore()
    ok = ae.attempt_elevation(store, lambda p: p == "correct", "wrong", now=1000.0)
    assert ok is False
    assert store.is_elevated(runner, now=1000.0) is False


def test_attempt_elevation_succeeds_and_grants_a_ticket():
    runner = FakeRunner()
    store = ae.ElevationStore()
    ok = ae.attempt_elevation(store, lambda p: p == "correct", "correct", now=1000.0)
    assert ok is True
    assert store.is_elevated(runner, now=1000.0) is True


def test_elevation_ticket_is_valid_within_the_default_15_minute_window():
    runner = FakeRunner()
    store = ae.ElevationStore()
    ae.attempt_elevation(store, lambda p: True, "x", now=1000.0)
    assert store.is_elevated(runner, now=1000.0 + 14 * 60) is True


def test_elevation_ticket_expires_after_the_default_15_minute_window():
    runner = FakeRunner()
    store = ae.ElevationStore()
    ae.attempt_elevation(store, lambda p: True, "x", now=1000.0)
    assert store.is_elevated(runner, now=1000.0 + 16 * 60) is False


def test_elevation_ticket_respects_a_configured_ttl_override():
    runner = FakeRunner()
    ss.set_setting("sessions", "admin_elevation_ttl_minutes", 5)
    store = ae.ElevationStore()
    ae.attempt_elevation(store, lambda p: True, "x", now=1000.0)
    assert store.is_elevated(runner, now=1000.0 + 6 * 60) is False


def test_revoke_clears_an_active_ticket_immediately():
    runner = FakeRunner()
    store = ae.ElevationStore()
    ae.attempt_elevation(store, lambda p: True, "x", now=1000.0)
    store.revoke()
    assert store.is_elevated(runner, now=1000.0) is False


def test_expired_ticket_does_not_silently_linger_in_the_store():
    """A real, checked implementation detail: once expired, the
    ticket is actually removed, not just reported as invalid."""
    runner = FakeRunner()
    store = ae.ElevationStore()
    ae.attempt_elevation(store, lambda p: True, "x", now=1000.0)
    store.is_elevated(runner, now=1000.0 + 16 * 60)
    assert "elevated" not in store.tickets


def test_require_elevation_matches_is_elevated():
    runner = FakeRunner()
    store = ae.ElevationStore()
    assert ae.require_elevation(store, runner, now=1000.0) is False
    ae.attempt_elevation(store, lambda p: True, "x", now=1000.0)
    assert ae.require_elevation(store, runner, now=1000.0) is True
