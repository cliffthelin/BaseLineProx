"""Unit tests for config_pipeline.py - the real bridge between the
Baseline Install Configurator's exported JSON and the apply functions
already proven in config_apply.py (decision record 50). No real
smartd/ethtool/apt is ever invoked - the FakeRunner records everything.

Scope, matching the module's own docstring: this pipeline only ever
runs post-install, at firstboot, against the already-installed system.
It never reads, writes, or otherwise touches the ISO in any way - that
invariant is asserted directly in one of these tests, not just claimed
in a comment.
"""
import json

from fake_runner import FakeRunner

import config_pipeline as cp

FULL_CONFIG = {
    "network": {"hostname": "myhost", "dhcp": True},
    "firewall": {"allow_lan_only": True},
    "ssh": {"password_auth": False},
    "tether": {"enabled": False},
    "handoff": {"restored_categories": ["network", "ssh"]},
    "proxmox": {
        "smartd_health_check": True,
        "smartd_monitor_all": True,
        "smartd_auto_offline": "on",
        "smartd_attribute_autosave": "on",
        "smartd_selftest_schedule": "L/../../7/03",
        "smartd_email": "",
        "smartd_email_frequency": "daily",
        "ethtool_autoneg": "on",
        "ethtool_speed": "",
        "ethtool_duplex": "full",
        "ethtool_wol": "g",
        "ethtool_rx_checksum": True,
        "ethtool_tx_checksum": True,
        "ethtool_tso": True,
        "ethtool_gro": True,
        "ethtool_pause_autoneg": True,
    },
    "diagnostics": {
        "iperf3": {"role": "server", "peer_address": "192.168.1.10", "port": 5201},
    },
    "drivers": {
        "cpu_microcode": True,
        "nic_wifi_firmware": True,
    },
}
CONFIG_JSON = json.dumps(FULL_CONFIG)


def test_load_config_returns_none_when_no_file_exists():
    runner = FakeRunner()
    assert cp.load_config(runner, "/etc/baseline/install-config.json") is None


def test_load_config_parses_the_real_exported_json():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    assert config["proxmox"]["smartd_health_check"] is True
    assert config["drivers"]["cpu_microcode"] is True


def test_apply_stored_config_uses_the_configs_own_ethtool_interface_over_the_fallback():
    """Real bug found on audit: the configurator's own ethtool_interface
    field was never read - the pipeline always used whatever the caller
    passed as network_interface, silently discarding the operator's
    actual choice. This asserts the config's own value wins."""
    config = {"proxmox": dict(json.loads(CONFIG_JSON)["proxmox"], ethtool_interface="wlp9s0"), "drivers": {}}
    runner = FakeRunner()
    cp.apply_stored_config(runner, config, network_interface="eno1")
    assert any(c[:3] == ["ethtool", "-s", "wlp9s0"] for c in runner.calls)
    assert not any(c[:3] == ["ethtool", "-s", "eno1"] for c in runner.calls)


def test_apply_stored_config_uses_a_driver_package_override_for_different_target_hardware():
    """Real bug found on audit: the drivers toggles were hardwired to
    THIS session's own detected packages (amd64-microcode,
    firmware-mediatek) with no way to target different hardware - the
    exported config's own cpu_microcode_package/wifi_firmware_package
    must be honored when the operator sets them for a different
    target machine."""
    runner = FakeRunner()
    config = {"proxmox": {}, "drivers": {
        "cpu_microcode": True, "cpu_microcode_package": "intel-microcode",
        "nic_wifi_firmware": True, "wifi_firmware_package": "firmware-realtek",
    }}
    cp.apply_stored_config(runner, config, network_interface="eno1")
    assert any("intel-microcode" in c for c in runner.calls)
    assert not any("amd64-microcode" in c for c in runner.calls)
    assert any("firmware-realtek" in c for c in runner.calls)
    assert not any("firmware-mediatek" in c for c in runner.calls)


def test_apply_stored_config_falls_back_to_this_machines_own_packages_when_omitted():
    runner = FakeRunner()
    config = {"proxmox": {}, "drivers": {"cpu_microcode": True, "nic_wifi_firmware": True}}
    cp.apply_stored_config(runner, config, network_interface="eno1")
    assert any("amd64-microcode" in c for c in runner.calls)
    assert any("firmware-mediatek" in c for c in runner.calls)


def test_apply_stored_config_falls_back_to_network_interface_when_config_omits_it():
    config = {"proxmox": json.loads(CONFIG_JSON)["proxmox"], "drivers": {}}
    runner = FakeRunner()
    cp.apply_stored_config(runner, config, network_interface="eno1")
    assert any(c[:3] == ["ethtool", "-s", "eno1"] for c in runner.calls)


def test_apply_stored_config_applies_smartd_and_ethtool_and_drivers():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "smartd" in summary["applied"]
    assert "ethtool" in summary["applied"]
    assert "cpu_microcode" in summary["applied"]
    assert "wifi_firmware" in summary["applied"]
    assert "/etc/smartd.conf" in runner.writes
    assert any(c[:3] == ["ethtool", "-s", "eno1"] for c in runner.calls)
    assert any("apt-get" in c and "install" in c and "amd64-microcode" in c for c in runner.calls)
    assert any("apt-get" in c and "install" in c and "firmware-mediatek" in c for c in runner.calls)


def test_apply_stored_config_skips_a_subsystem_with_no_relevant_keys():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": json.dumps({"proxmox": {}, "drivers": {}})})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert summary["applied"] == []
    assert "smartd" in summary["skipped"]
    assert "ethtool" in summary["skipped"]
    assert "cpu_microcode" in summary["skipped"]
    assert "wifi_firmware" in summary["skipped"]


def test_apply_stored_config_records_a_real_failure_without_stopping_other_subsystems():
    runner = FakeRunner(
        files={"/etc/baseline/install-config.json": CONFIG_JSON},
        command_responses=[
            (lambda a: a[:2] == ["ethtool", "-s"], __import__("fake_runner").FakeProc(1, "", "no such device")),
        ],
    )
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "ethtool" in summary["failed"]
    # smartd/drivers are independent subsystems - ethtool failing must not skip them
    assert "smartd" in summary["applied"]
    assert "cpu_microcode" in summary["applied"]


def test_apply_stored_config_never_touches_anything_iso_shaped():
    """The pipeline runs post-install, at firstboot, against the live
    installed system only - it must never read or write any path whose
    name suggests an ISO/image build artifact (drive_setup_acquire.py's
    domain), regardless of what a config file contains."""
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    cp.apply_stored_config(runner, config, network_interface="eno1")
    iso_shaped = lambda p: p.lower().endswith(".iso") or "/iso/" in p.lower()
    assert not any(iso_shaped(p) for p in runner.writes)
    assert not any(iso_shaped(a) for call in runner.calls for a in call if isinstance(a, str))


def test_apply_stored_config_applies_network_hostname():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    config["network"] = {"hostname": "myhost"}
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "network" in summary["applied"]
    assert any(c == ["hostnamectl", "set-hostname", "myhost"] for c in runner.calls)


def test_apply_stored_config_firewall_fails_when_the_ruleset_cannot_be_verified():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "firewall" in summary["failed"]      # the fake nft listing proves nothing, so it must not pass
    assert "firewall" not in summary["applied"]


def test_apply_stored_config_firewall_applies_when_the_live_ruleset_verifies():
    import lan_firewall as lf
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    runner.script_prefix("nft", "list", "table",
                         stdout="chain input { hook input; policy drop; " + " ".join(lf.DEFAULT_LAN_SUBNETS) + " }")
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "firewall" in summary["applied"]


def test_apply_stored_config_applies_ssh():
    runner = FakeRunner(files={
        "/etc/baseline/install-config.json": CONFIG_JSON,
        "/etc/ssh/sshd_config": "# default\nPasswordAuthentication yes\n",
    })
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "ssh" in summary["applied"]
    assert "/etc/ssh/sshd_config" in runner.writes


def test_apply_stored_config_disabled_tether_is_applied_as_nothing_to_do():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "tether" in summary["applied"]


def test_apply_stored_config_reports_unwired_handoff_as_failed():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "handoff" in summary["failed"]
    assert "handoff" not in summary["applied"]


def test_apply_stored_config_iperf3_server_is_applied_when_the_unit_starts():
    import lan_firewall as lf
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    runner.script_prefix("nft", "list", "table",
                         stdout="chain input { hook input; policy drop; " + " ".join(lf.DEFAULT_LAN_SUBNETS) + " }")
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "iperf3" in summary["applied"]


def test_apply_stored_config_all_sections_accounted_for():
    """Every subsystem the pipeline knows about must appear in exactly
    one of applied/skipped/failed - nothing silently dropped."""
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    all_named = set(summary["applied"] + summary["skipped"] + summary["failed"])
    expected = {"network", "firewall", "ssh", "tether", "handoff",
                "smartd", "ethtool", "iperf3", "cpu_microcode", "wifi_firmware"}
    assert expected == all_named


def test_no_config_skips_every_subsystem_and_a_partial_apply_never_runs_the_firewall():
    runner = FakeRunner()
    summary = cp.apply_stored_config(runner, None, network_interface="eno1")
    assert summary["failed"] == [] and "firewall" in summary["skipped"] and runner.calls == []


def test_no_config_with_enforcement_still_attempts_the_firewall():
    runner = FakeRunner()
    summary = cp.apply_stored_config(runner, None, network_interface="eno1", enforce_lan_only=True)
    assert summary["applied"] == []
    assert summary["failed"] == ["firewall"]          # attempted; the fake nft listing proves nothing
    expected = {"network", "ssh", "tether", "handoff",
                "smartd", "ethtool", "iperf3", "cpu_microcode", "wifi_firmware"}
    assert expected == set(summary["skipped"])


def test_firewall_is_enforced_even_when_the_config_has_no_firewall_section():
    import lan_firewall as lf
    runner = FakeRunner()
    runner.script_prefix("nft", "list", "table",
                         stdout="chain input { hook input; policy drop; " + " ".join(lf.DEFAULT_LAN_SUBNETS) + " }")
    summary = cp.apply_stored_config(runner, {"ssh": {"password_auth": False}}, network_interface="eno1",
                                     enforce_lan_only=True)
    assert "firewall" in summary["applied"]
    assert ["nft", "-f", lf.RULESET_PATH + ".new"] in runner.calls


def test_a_partial_settings_apply_does_not_run_the_firewall_for_an_unrelated_section():
    runner = FakeRunner()
    summary = cp.apply_stored_config(runner, {"network": {"hostname": "h", "dhcp": True}}, network_interface="eno1")
    assert "firewall" in summary["skipped"] and not any(c[0] == "nft" for c in runner.calls)


def test_iperf3_server_is_not_started_when_the_firewall_did_not_apply():
    config = {"diagnostics": {"iperf3": {"role": "server", "peer_address": "", "port": 5201}}}
    runner = FakeRunner()          # fake nft listing proves nothing, so the firewall fails
    summary = cp.apply_stored_config(runner, config, network_interface="eno1", enforce_lan_only=True)
    assert "firewall" in summary["failed"]
    assert "iperf3" in summary["failed"]
    assert not any(c[0] == "systemd-run" for c in runner.calls)


def test_a_subsystem_that_raises_is_reported_failed_and_does_not_stop_the_others():
    config = {"diagnostics": {"iperf3": {"role": "client", "peer_address": ["not", "a", "string"], "port": 5201}},
              "ssh": {"password_auth": False}}
    runner = FakeRunner(files={"/etc/ssh/sshd_config": "# x\n"})
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")
    assert "iperf3" in summary["failed"] and "ssh" in summary["applied"]
