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


def test_apply_cpu_microcode_installs_the_real_amd_package_noninteractively():
    runner = FakeRunner()
    result = ca.apply_cpu_microcode(runner)
    assert result.ok is True
    assert runner.calls[0] == ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "amd64-microcode"]


def test_apply_cpu_microcode_accepts_a_different_package_name():
    """The configurator's default package is only correct for a target
    with this session's own AMD CPU - a different target (Intel) must
    be able to override it, found missing on audit."""
    runner = FakeRunner()
    ca.apply_cpu_microcode(runner, package="intel-microcode")
    assert runner.calls[0] == ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "intel-microcode"]


def test_apply_cpu_microcode_reports_a_real_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: "apt-get" in a and "install" in a, FakeProc(1, "", "unable to locate package")),
    ])
    result = ca.apply_cpu_microcode(runner)
    assert result.ok is False
    assert "unable to locate package" in result.detail


def test_apply_wifi_firmware_installs_the_real_mediatek_package_by_default_noninteractively():
    runner = FakeRunner()
    result = ca.apply_wifi_firmware(runner)
    assert result.ok is True
    assert runner.calls[0] == ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "firmware-mediatek"]


def test_apply_wifi_firmware_accepts_a_different_package_name():
    runner = FakeRunner()
    ca.apply_wifi_firmware(runner, package="firmware-realtek")
    assert runner.calls[0] == ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "firmware-realtek"]


def test_firewall_configuration_does_not_claim_unperformed_enforcement():
    runner = FakeRunner()
    result = ca.apply_firewall_config(runner, {"allow_lan_only": True})
    assert result.ok is False
    assert "not applied" in result.detail


def test_tether_does_not_claim_an_interface_was_configured():
    assert ca.apply_tether_config(FakeRunner(), {"enabled": True}).ok is False


def test_handoff_does_not_claim_categories_were_restored():
    assert ca.apply_handoff_config(FakeRunner(), {"restored_categories": ["network"]}).ok is False


def test_iperf_does_not_claim_a_configured_service_without_starting_one():
    assert ca.apply_iperf3_config(FakeRunner(), {"role": "server"}).ok is False


def test_ssh_reports_service_restart_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a == ["systemctl", "restart", "ssh"], FakeProc(1, "", "service failed")),
    ])
    assert ca.apply_ssh_config(runner, {"password_auth": False}).ok is False


def test_network_default_config_applies_hostname_and_accepts_dhcp_true():
    # settings_web's own default is {"hostname": "baseline", "dhcp": True}; DHCP is
    # the existing behaviour, so it must not block setting the hostname.
    runner = FakeRunner()
    assert ca.apply_network_config(runner, {"hostname": "baseline", "dhcp": True}).ok is True
    assert runner.calls == [["hostnamectl", "set-hostname", "baseline"]]


def test_network_unsupported_link_change_is_refused_before_any_write():
    for config in ({"hostname": "target", "dhcp": False},
                   {"hostname": "target", "address": "10.0.0.5/24"}):
        runner = FakeRunner()
        assert ca.apply_network_config(runner, config).ok is False
        assert runner.calls == []
