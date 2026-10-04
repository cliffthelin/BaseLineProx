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


def _listing_ok():
    import lan_firewall as lf
    return "chain input { type filter hook input priority filter; policy drop; " + " ".join(lf.DEFAULT_LAN_SUBNETS) + " }"


def test_firewall_applies_lan_only_through_the_lan_firewall_module():
    runner = FakeRunner()
    runner.script_prefix("nft", "list", "table", stdout=_listing_ok())
    result = ca.apply_firewall_config(runner, {"allow_lan_only": True})
    assert result.ok is True
    assert ["nft", "-f", "/etc/baseline/lan-only.nft.new"] in runner.calls


def test_firewall_open_mode_is_refused_not_applied():
    runner = FakeRunner()
    result = ca.apply_firewall_config(runner, {"allow_lan_only": False})
    assert result.ok is False and runner.calls == []


def test_firewall_unverifiable_ruleset_reports_failure():
    runner = FakeRunner()
    runner.script_prefix("nft", "list", "table", stdout="nothing useful")
    assert ca.apply_firewall_config(runner, {"allow_lan_only": True}).ok is False


# -- tether ------------------------------------------------------------------

def test_tether_disabled_has_nothing_to_apply_and_does_not_probe_hardware():
    def boom():
        raise AssertionError("must not touch tether hardware when disabled")
    assert ca.apply_tether_config(FakeRunner(), {"enabled": False}, tether_fn=boom).ok is True


def test_tether_enabled_succeeds_only_when_an_interface_really_got_an_address():
    up = lambda: {"ok": True, "stage": "ok", "interface": "usb0", "address": "192.168.42.10", "detail": "lease"}
    result = ca.apply_tether_config(FakeRunner(), {"enabled": True}, tether_fn=up)
    assert result.ok is True and "usb0" in result.detail and "192.168.42.10" in result.detail


def test_tether_enabled_reports_the_stage_it_stopped_at():
    down = lambda: {"ok": False, "stage": "no_dhcp_offer", "interface": "usb0", "address": None, "detail": "hotspot off?"}
    result = ca.apply_tether_config(FakeRunner(), {"enabled": True}, tether_fn=down)
    assert result.ok is False and "no_dhcp_offer" in result.detail


def test_tether_probe_crash_is_a_failure_not_an_exception():
    def crash():
        raise OSError("sysfs gone")
    assert ca.apply_tether_config(FakeRunner(), {"enabled": True}, tether_fn=crash).ok is False


# -- handoff -----------------------------------------------------------------

ARCHIVE = "/mnt/INSTALLER_CACHE/backups/handoff.tar.gz"


def test_handoff_with_nothing_to_restore_is_a_no_op_success():
    result = ca.apply_handoff_config(FakeRunner(), {"restored_categories": []})
    assert result.ok is True


def test_handoff_categories_without_an_archive_are_refused():
    runner = FakeRunner()
    assert ca.apply_handoff_config(runner, {"restored_categories": ["network"]}).ok is False
    assert runner.calls == []


def test_handoff_archive_outside_the_backup_folder_is_refused_before_any_command():
    runner = FakeRunner(files={"/tmp/x.tar.gz": ""})
    config = {"restored_categories": ["network"], "archive_path": "/tmp/x.tar.gz", "restore_root": "/mnt"}
    assert ca.apply_handoff_config(runner, config).ok is False
    assert runner.calls == []


def test_handoff_restore_is_gated_on_a_fresh_backup_of_user_data():
    runner = FakeRunner(files={ARCHIVE: ""})
    config = {"restored_categories": ["network"], "archive_path": ARCHIVE, "restore_root": "/mnt"}
    result = ca.apply_handoff_config(runner, config)
    assert result.ok is False and "backup" in result.detail
    assert not any(c[0] == "tar" and "-xzf" in c for c in runner.calls)   # tar never ran


def test_handoff_restores_when_the_archive_is_valid_and_user_data_is_freshly_backed_up():
    import backup_restore as br
    runner = FakeRunner(files={ARCHIVE: ""})
    for target in br.user_targets():
        br.record_backup_manifest(runner, target=target, ts=runner.now())
    config = {"restored_categories": ["network"], "archive_path": ARCHIVE, "restore_root": "/mnt"}
    result = ca.apply_handoff_config(runner, config)
    assert result.ok is True, result.detail
    assert ["tar", "-xzf", ARCHIVE, "-C", "/mnt"] in runner.calls


# -- iperf3 ------------------------------------------------------------------

IPERF_JSON = '{"end": {"sum_received": {"bits_per_second": 941000000.0}}}'


def test_iperf_client_runs_a_bounded_test_against_a_lan_peer_and_reports_the_result():
    runner = FakeRunner()
    runner.script_prefix("iperf3", "-c", stdout=IPERF_JSON)
    result = ca.apply_iperf3_config(runner, {"role": "client", "peer_address": "192.168.1.20", "port": 5201})
    assert result.ok is True and "941" in result.detail
    assert ["iperf3", "-c", "192.168.1.20", "-p", "5201", "-t", "5", "-J"] in runner.calls


def test_iperf_client_failure_is_a_failure():
    runner = FakeRunner()
    runner.script_prefix("iperf3", "-c", returncode=1, stderr="connection refused")
    assert ca.apply_iperf3_config(runner, {"role": "client", "peer_address": "192.168.1.20", "port": 5201}).ok is False


def test_iperf_peer_must_be_a_lan_address():
    for peer in ("8.8.8.8", "example.com", "-oProxyCommand=x", "192.168.1.20; reboot", "127.0.0.1", "0.0.0.0", 5):
        runner = FakeRunner()
        assert ca.apply_iperf3_config(runner, {"role": "client", "peer_address": peer, "port": 5201}).ok is False
        assert runner.calls == []


def test_iperf_port_from_a_settings_form_may_be_a_digit_string():
    runner = FakeRunner()
    runner.script_prefix("iperf3", "-c", stdout=IPERF_JSON)
    assert ca.apply_iperf3_config(runner, {"role": "client", "peer_address": "10.0.0.2", "port": "5201"}).ok is True
    assert ["iperf3", "-c", "10.0.0.2", "-p", "5201", "-t", "5", "-J"] in runner.calls


def test_iperf_bad_port_is_refused():
    runner = FakeRunner()
    assert ca.apply_iperf3_config(runner, {"role": "client", "peer_address": "10.0.0.2", "port": 70000}).ok is False
    assert ca.apply_iperf3_config(runner, {"role": "client", "peer_address": "10.0.0.2", "port": "5201; id"}).ok is False
    assert runner.calls == []


def test_iperf_server_starts_a_single_bounded_transient_unit():
    runner = FakeRunner()
    result = ca.apply_iperf3_config(runner, {"role": "server", "peer_address": "", "port": 5201})
    assert result.ok is True
    assert ["systemd-run", "--unit=baseline-iperf3", "--collect", "--property=RuntimeMaxSec=600",
            "iperf3", "-s", "-1", "-p", "5201"] in runner.calls


def test_iperf_without_a_peer_only_checks_the_tool_is_installed():
    runner = FakeRunner()
    assert ca.apply_iperf3_config(runner, {"role": "client", "peer_address": "", "port": 5201}).ok is True
    assert runner.calls == [["iperf3", "--version"]]
    missing = FakeRunner()
    missing.script_prefix("iperf3", "--version", returncode=127, stderr="not found")
    assert ca.apply_iperf3_config(missing, {"role": "client", "peer_address": "", "port": 5201}).ok is False


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
