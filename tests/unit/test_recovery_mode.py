"""Unit tests for recovery_mode.py - real entry, userless discovery,
and the hard exit condition for Baseline Recovery Mode (work-queue
item 26, decision record 81). Not blocked on the withdrawn USB
recovery mechanism (decision record 77) - nothing here touches it.
"""
from fake_runner import FakeRunner

import recovery_mode as rm


# -- should_enter ------------------------------------------------------------

def test_should_enter_true_when_cascade_failed():
    assert rm.should_enter(cascade_applied=False) is True


def test_should_enter_false_when_cascade_succeeded():
    assert rm.should_enter(cascade_applied=True) is False


# -- discover (guest-tier, no credential needed) -----------------------------

def test_discover_reports_a_found_persona():
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    report = rm.discover(runner, personas=("admin", "personal"))
    assert report.personas_found == ["admin"]
    assert report.personas_missing == ["personal"]


def test_discover_reports_the_active_persona_when_something_is_found():
    import persist_bind_mounts as pbm
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts, pbm.ACTIVE_PERSONA_MARKER_PATH: "admin"})
    report = rm.discover(runner, personas=("admin",))
    assert report.active_persona == "admin"


def test_discover_active_persona_is_none_when_nothing_is_found():
    runner = FakeRunner()
    report = rm.discover(runner, personas=("admin", "personal"))
    assert report.personas_found == []
    assert report.personas_missing == ["admin", "personal"]
    assert report.active_persona is None


# -- can_exit: the hard exit condition ---------------------------------------

def test_can_exit_true_when_a_persona_is_confirmed_read_write():
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    ok, reason = rm.can_exit(runner, personas=("admin", "personal"))
    assert ok is True
    assert "admin" in reason


def test_can_exit_false_when_the_only_mounted_persona_is_read_only():
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 ro,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    ok, reason = rm.can_exit(runner, personas=("admin",))
    assert ok is False
    assert "read-write" in reason


def test_can_exit_false_when_nothing_is_mounted_at_all():
    runner = FakeRunner()
    ok, reason = rm.can_exit(runner, personas=("admin", "personal"))
    assert ok is False


# -- record_entry / read_state / is_active -----------------------------------

def test_record_entry_writes_real_state_to_session_temp():
    runner = FakeRunner()
    rm.record_entry(runner, now=1700000000.0, reason="cascade_failed")
    assert rm.STATE_PATH.startswith("/mnt/SESSION_TEMP/")
    state = rm.read_state(runner)
    assert state["active"] is True
    assert state["reason"] == "cascade_failed"
    assert state["entered_at"] == 1700000000.0
    assert state["exited_at"] is None


def test_read_state_returns_none_when_never_recorded():
    runner = FakeRunner()
    assert rm.read_state(runner) is None


def test_is_active_true_after_a_real_entry():
    runner = FakeRunner()
    rm.record_entry(runner, now=1700000000.0, reason="on_demand")
    assert rm.is_active(runner) is True


def test_is_active_false_before_any_entry():
    runner = FakeRunner()
    assert rm.is_active(runner) is False


# -- attempt_exit -------------------------------------------------------------

def test_attempt_exit_refuses_and_never_clears_active_without_a_real_rw_persona():
    runner = FakeRunner()
    rm.record_entry(runner, now=1700000000.0, reason="cascade_failed")
    result = rm.attempt_exit(runner, personas=("admin",), now=1700000060.0)
    assert result.applied is False
    assert rm.is_active(runner) is True


def test_attempt_exit_succeeds_and_clears_active_once_a_persona_is_read_write():
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    rm.record_entry(runner, now=1700000000.0, reason="cascade_failed")
    result = rm.attempt_exit(runner, personas=("admin",), now=1700000060.0)
    assert result.applied is True
    state = rm.read_state(runner)
    assert state["active"] is False
    assert state["exited_at"] == 1700000060.0
    assert rm.is_active(runner) is False


def test_attempt_exit_when_never_entered_still_refuses_cleanly_without_a_persona():
    runner = FakeRunner()
    result = rm.attempt_exit(runner, personas=("admin",), now=1700000000.0)
    assert result.applied is False
