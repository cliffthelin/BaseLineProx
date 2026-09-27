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

CONFIG_JSON = json.dumps({
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
    "drivers": {
        "cpu_microcode": True,
        "nic_wifi_firmware": True,
    },
})


def test_load_config_returns_none_when_no_file_exists():
    runner = FakeRunner()
    assert cp.load_config(runner, "/etc/baseline/install-config.json") is None


def test_load_config_parses_the_real_exported_json():
    runner = FakeRunner(files={"/etc/baseline/install-config.json": CONFIG_JSON})
    config = cp.load_config(runner, "/etc/baseline/install-config.json")
    assert config["proxmox"]["smartd_health_check"] is True
    assert config["drivers"]["cpu_microcode"] is True


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
    assert any(c[:3] == ["apt-get", "install", "-y"] and "amd64-microcode" in c for c in runner.calls)
    assert any(c[:3] == ["apt-get", "install", "-y"] and "firmware-mediatek" in c for c in runner.calls)


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
