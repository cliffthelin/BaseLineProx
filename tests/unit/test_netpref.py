"""Tests for netpref.py's preference storage (decision record 91) -
moved off its own flat JSON file onto settings_store.py's registry.
conftest.py's autouse fixture isolates the underlying database per
test, same as every other settings_store-backed module."""
import netpref


def test_load_preference_defaults_to_both_none_when_never_set():
    assert netpref.load_preference() == {"primary": None, "fallback": None}


def test_save_preference_sets_primary_only():
    result = netpref.save_preference(primary="eth0")
    assert result == {"primary": "eth0", "fallback": None}


def test_save_preference_sets_fallback_only():
    result = netpref.save_preference(fallback="wlan0")
    assert result == {"primary": None, "fallback": "wlan0"}


def test_save_preference_leaves_the_other_field_untouched_across_calls():
    netpref.save_preference(primary="eth0")
    result = netpref.save_preference(fallback="wlan0")
    assert result == {"primary": "eth0", "fallback": "wlan0"}


def test_load_preference_reflects_a_real_prior_save():
    netpref.save_preference(primary="eth0", fallback="wlan0")
    assert netpref.load_preference() == {"primary": "eth0", "fallback": "wlan0"}
