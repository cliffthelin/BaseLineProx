"""Unit tests for diagnostics.py (PRD SS5.9a) - capability detection and
normalized collectors for the 5 diagnostic tools. Every collector must
produce a clean available:false (or available:true, empty) result on a
minimal/no-hardware host, matching what decision record 22 found for
real against an actual automated-install QEMU target."""
import json

from fake_runner import FakeRunner, FakeProc

import diagnostics as diag


# --------------------------------------------------------------------------
# lm-sensors
# --------------------------------------------------------------------------

def test_sensors_not_available_when_binary_missing():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["sensors"], FakeProc(127, "", "not found"))]
    result = diag.collect_sensors(runner)
    assert result.available is False
    assert "non-zero" in result.reason


def test_sensors_not_available_when_no_chips_found():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["sensors"], FakeProc(0, "{}", ""))]
    result = diag.collect_sensors(runner)
    assert result.available is False
    assert result.chips == []


def test_sensors_available_with_real_populated_output():
    payload = json.dumps({
        "coretemp-isa-0000": {
            "Adapter": "ISA adapter",
            "Package id 0": {"temp1_input": 45.0, "temp1_crit": 100.0},
        }
    })
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["sensors"], FakeProc(0, payload, ""))]
    result = diag.collect_sensors(runner)
    assert result.available is True
    assert result.chips[0]["chip"] == "coretemp-isa-0000"
    labels = [f["label"] for f in result.chips[0]["features"]]
    assert "Package id 0 temp1_input" in labels


# --------------------------------------------------------------------------
# nvme-cli
# --------------------------------------------------------------------------

def test_nvme_available_true_with_zero_devices():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:2] == ["nvme", "list"], FakeProc(0, json.dumps({"Devices": []}), ""))]
    result = diag.collect_nvme(runner)
    assert result.available is True
    assert result.devices == []


def test_nvme_not_available_when_binary_missing():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:2] == ["nvme", "list"], FakeProc(127, "", "not found"))]
    result = diag.collect_nvme(runner)
    assert result.available is False


def test_nvme_discovers_then_queries_only_discovered_device():
    list_payload = json.dumps({"Devices": [{"DevicePath": "/dev/nvme0n1", "ModelNumber": "Samsung X", "Firmware": "1.0"}]})
    smart_payload = json.dumps({"percentage_used": 3, "media_errors": 0})
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:2] == ["nvme", "list"], FakeProc(0, list_payload, "")),
        (lambda a: a[:2] == ["nvme", "smart-log"], FakeProc(0, smart_payload, "")),
    ]
    result = diag.collect_nvme(runner)
    assert result.available is True
    assert len(result.devices) == 1
    assert result.devices[0]["path"] == "/dev/nvme0n1"
    assert result.devices[0]["health"]["percentage_used"] == 3
    # never queries a device it didn't discover
    smart_calls = [c for c in runner.calls if c[:2] == ["nvme", "smart-log"]]
    assert smart_calls == [["nvme", "smart-log", "/dev/nvme0n1", "-o", "json"]]


# --------------------------------------------------------------------------
# smartmontools
# --------------------------------------------------------------------------

def test_smart_available_true_with_zero_devices():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, json.dumps({"devices": []}), ""))]
    result = diag.collect_smart(runner)
    assert result.available is True
    assert result.devices == []


def test_smart_discovers_then_queries_only_discovered_device():
    scan_payload = json.dumps({"devices": [{"name": "/dev/sda", "type": "sat"}]})
    detail_payload = json.dumps({"model_name": "ST1000", "temperature": {"current": 32},
                                  "power_on_time": {"hours": 100}, "smart_status": {"passed": True}})
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, scan_payload, "")),
        (lambda a: a[:2] == ["smartctl", "-a"], FakeProc(0, detail_payload, "")),
    ]
    result = diag.collect_smart(runner)
    assert result.devices[0]["model"] == "ST1000"
    assert result.devices[0]["temperature"] == 32
    assert result.devices[0]["smart_passed"] is True


def test_initiate_self_test_never_called_by_collect_smart():
    scan_payload = json.dumps({"devices": [{"name": "/dev/sda", "type": "sat"}]})
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:2] == ["smartctl", "--scan-open"], FakeProc(0, scan_payload, "")),
        (lambda a: a[:2] == ["smartctl", "-a"], FakeProc(0, "{}", "")),
    ]
    diag.collect_smart(runner)
    assert not any("-t" in c for c in runner.calls)


def test_initiate_self_test_rejects_invalid_type():
    runner = FakeRunner()
    result = diag.initiate_self_test(runner, "/dev/sda", "ultra-long")
    assert result["started"] is False
    assert runner.calls == []  # never touches the subprocess boundary


def test_initiate_self_test_runs_for_valid_type():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: "-t" in a, FakeProc(0, "", ""))]
    result = diag.initiate_self_test(runner, "/dev/sda", "short")
    assert result["started"] is True


# --------------------------------------------------------------------------
# ethtool
# --------------------------------------------------------------------------

def test_ethtool_available_true_with_zero_interfaces():
    runner = FakeRunner()
    result = diag.collect_ethtool(runner, list_interfaces_fn=lambda: [])
    assert result.available is True
    assert result.interfaces == []


def test_ethtool_never_assumes_interface_name_queries_only_discovered():
    output = "Settings for eth0:\n\tSpeed: 1000Mb/s\n\tDuplex: Full\n\tAuto-negotiation: on\n\tLink detected: yes\n"
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["ethtool"], FakeProc(0, output, ""))]
    result = diag.collect_ethtool(runner, list_interfaces_fn=lambda: [{"name": "eth0"}])
    assert result.available is True
    assert result.interfaces[0]["name"] == "eth0"
    assert result.interfaces[0]["link_detected"] is True
    assert result.interfaces[0]["speed"] == "1000Mb/s"
    assert runner.calls == [["ethtool", "eth0"]]


def test_ethtool_skips_interface_that_fails():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["ethtool"], FakeProc(1, "", "no such device"))]
    result = diag.collect_ethtool(runner, list_interfaces_fn=lambda: [{"name": "ghost0"}])
    assert result.interfaces == []
    assert result.available is False


# --------------------------------------------------------------------------
# iperf3 - never automatic, always both endpoints explicit
# --------------------------------------------------------------------------

def test_iperf3_requires_valid_role():
    runner = FakeRunner()
    result = diag.iperf3_client_server_test(runner, role="listener", peer_address="1.2.3.4")
    assert result.ran is False
    assert runner.calls == []


def test_iperf3_client_requires_peer_address():
    runner = FakeRunner()
    result = diag.iperf3_client_server_test(runner, role="client", peer_address="")
    assert result.ran is False
    assert runner.calls == []


def test_iperf3_client_runs_with_explicit_peer():
    payload = json.dumps({"end": {"sum_sent": {"bits_per_second": 941000000}}})
    runner = FakeRunner()
    runner.command_responses = [(lambda a: "-c" in a, FakeProc(0, payload, ""))]
    result = diag.iperf3_client_server_test(runner, role="client", peer_address="10.0.0.5")
    assert result.ran is True
    assert "10.0.0.5" in runner.calls[0]


def test_iperf3_server_runs_one_shot():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: "-s" in a, FakeProc(0, "{}", ""))]
    result = diag.iperf3_client_server_test(runner, role="server", peer_address="")
    assert result.ran is True
    assert "-1" in runner.calls[0]  # one-shot, never a persistent listener
