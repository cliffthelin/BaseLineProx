"""Tests for network.py's interface-alias storage (decision record 91)
- moved off its own flat JSON file onto registry.py directly (a
dynamic, hardware-dependent key space, not settings_store.py's fixed
schema). conftest.py's autouse fixture isolates the underlying
database per test."""
import network


def test_load_aliases_is_empty_when_none_ever_set():
    assert network.load_aliases() == {}


def test_save_alias_then_load_aliases_reflects_it():
    network.save_alias("eth0", "Office Uplink")
    assert network.load_aliases() == {"eth0": "Office Uplink"}


def test_save_alias_strips_whitespace():
    network.save_alias("eth0", "  Office Uplink  ")
    assert network.load_aliases() == {"eth0": "Office Uplink"}


def test_save_alias_with_empty_string_clears_an_existing_alias():
    network.save_alias("eth0", "Office Uplink")
    network.save_alias("eth0", "")
    assert network.load_aliases() == {}


def test_save_alias_with_empty_string_on_a_never_set_interface_is_a_no_op():
    network.save_alias("eth0", "")
    assert network.load_aliases() == {}


def test_multiple_interface_aliases_coexist_independently():
    network.save_alias("eth0", "Office Uplink")
    network.save_alias("wlan0", "Guest Wi-Fi")
    assert network.load_aliases() == {"eth0": "Office Uplink", "wlan0": "Guest Wi-Fi"}


def test_friendly_name_uses_a_real_saved_alias_over_the_driver_default():
    network.save_alias("eth0", "Office Uplink")
    assert network.friendly_name("eth0") == "Office Uplink"
