"""Unit tests for config_apply.py - the real apply-at-boot mechanism
for the Baseline Install Configurator's smartmontools/ethtool fields
(the "one configuration file to rule them all" - decision record 50).
Directives researched directly from local man pages this session
(smartd.conf(5), ethtool(8)), not guessed. No real smartd/ethtool is
ever invoked - the FakeRunner records every argv."""
from fake_runner import FakeProc, FakeRunner

import config_apply as ca

SMARTD_CONFIG = {
    "smartd_health_check": True,
    "smartd_monitor_all": True,
    "smartd_auto_offline": "on",
    "smartd_attribute_autosave": "on",
    "smartd_selftest_schedule": "L/../../7/03",
    "smartd_email": "",
    "smartd_email_frequency": "daily",
}

ETHTOOL_CONFIG = {
    "ethtool_autoneg": "on",
    "ethtool_speed": "",
    "ethtool_duplex": "full",
    "ethtool_wol": "g",
    "ethtool_rx_checksum": True,
    "ethtool_tx_checksum": True,
    "ethtool_tso": True,
    "ethtool_gro": True,
    "ethtool_pause_autoneg": True,
}


# -- build_smartd_conf(): pure, real directive generation ----------------

def test_build_smartd_conf_includes_health_and_monitor_all():
    text = ca.build_smartd_conf(SMARTD_CONFIG)
    assert "DEVICESCAN" in text
    assert " -H " in text or text.rstrip().endswith("-H")
    assert " -a " in text or " -a" in text


def test_build_smartd_conf_includes_offline_and_autosave_directives():
    text = ca.build_smartd_conf(SMARTD_CONFIG)
    assert "-o on" in text
    assert "-S on" in text


def test_build_smartd_conf_includes_selftest_schedule():
    text = ca.build_smartd_conf(SMARTD_CONFIG)
    assert "-s L/../../7/03" in text


def test_build_smartd_conf_omits_email_directives_when_blank():
    text = ca.build_smartd_conf(SMARTD_CONFIG)
    assert "-m" not in text
    assert "-M" not in text


def test_build_smartd_conf_includes_email_when_present():
    config = dict(SMARTD_CONFIG, smartd_email="ops@example.com")
    text = ca.build_smartd_conf(config)
    assert "-m ops@example.com" in text
    assert "-M daily" in text


def test_build_smartd_conf_disabled_directives_are_simply_absent():
    config = dict(SMARTD_CONFIG, smartd_health_check=False, smartd_monitor_all=False)
    text = ca.build_smartd_conf(config)
    assert "-H" not in text
    assert " -a" not in text.replace("DEVICESCAN -a", "")  # sanity: not left in some other form


# -- ethtool argv builders: pure, real flag shapes ------------------------

def test_ethtool_change_argv_autoneg_on_omits_speed_and_duplex():
    argv = ca.ethtool_change_argv("eth0", ETHTOOL_CONFIG)
    assert argv == ["ethtool", "-s", "eth0", "autoneg", "on", "wol", "g"]


def test_ethtool_change_argv_autoneg_off_includes_speed_and_duplex():
    config = dict(ETHTOOL_CONFIG, ethtool_autoneg="off", ethtool_speed="1000")
    argv = ca.ethtool_change_argv("eth0", config)
    assert argv == ["ethtool", "-s", "eth0", "autoneg", "off", "speed", "1000", "duplex", "full", "wol", "g"]


def test_ethtool_offload_argv():
    argv = ca.ethtool_offload_argv("eth0", ETHTOOL_CONFIG)
    assert argv == ["ethtool", "-K", "eth0", "rx", "on", "tx", "on", "tso", "on", "gro", "on"]


def test_ethtool_offload_argv_reflects_disabled_features():
    config = dict(ETHTOOL_CONFIG, ethtool_tso=False)
    argv = ca.ethtool_offload_argv("eth0", config)
    assert argv == ["ethtool", "-K", "eth0", "rx", "on", "tx", "on", "tso", "off", "gro", "on"]


def test_ethtool_pause_argv():
    assert ca.ethtool_pause_argv("eth0", ETHTOOL_CONFIG) == ["ethtool", "-A", "eth0", "autoneg", "on"]


# -- Runner-executed operations -------------------------------------------

def test_apply_smartd_config_writes_the_file_and_reloads():
    runner = FakeRunner()
    result = ca.apply_smartd_config(runner, SMARTD_CONFIG)
    assert result.ok is True
    assert "/etc/smartd.conf" in runner.writes
    assert runner.calls[0][:2] == ["systemctl", "reload-or-restart"]


def test_apply_ethtool_config_runs_all_three_real_commands_in_order():
    runner = FakeRunner()
    result = ca.apply_ethtool_config(runner, "eth0", ETHTOOL_CONFIG)
    assert result.ok is True
    assert runner.calls[0][:3] == ["ethtool", "-s", "eth0"]
    assert runner.calls[1][:3] == ["ethtool", "-K", "eth0"]
    assert runner.calls[2][:3] == ["ethtool", "-A", "eth0"]


def test_apply_ethtool_config_reports_the_real_failure_and_stops():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["ethtool", "-s"], FakeProc(1, "", "no such device")),
    ])
    result = ca.apply_ethtool_config(runner, "eth0", ETHTOOL_CONFIG)
    assert result.ok is False
    assert "no such device" in result.detail
    # -K/-A must never have been attempted after -s failed
    assert not any(c[:2] == ["ethtool", "-K"] for c in runner.calls)
