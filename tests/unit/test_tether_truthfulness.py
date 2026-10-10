import subprocess

import pytest

import tether


def test_driver_lookup_failure_is_not_an_unbound_device(monkeypatch):
    class DriverPath:
        def __truediv__(self, _part):
            return self

        def resolve(self, **_kwargs):
            raise PermissionError("driver link denied")

    monkeypatch.setattr(tether, "Path", lambda _path: DriverPath())
    with pytest.raises(tether.TetherProbeError, match="driver link denied"):
        tether._driver_name("usb0")


def test_missing_sysfs_network_inventory_is_not_reported_as_no_tether(monkeypatch):
    monkeypatch.setattr(tether,'_path_exists',lambda _path:False)
    result=tether.auto_tether()
    assert result['stage']=='probe_error'
    assert 'network interface inventory' in result['detail']


def test_failed_ip_link_command_does_not_continue_to_dhcp(monkeypatch):
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "operation not permitted")

    monkeypatch.setattr(tether.subprocess, "run", run)
    monkeypatch.setattr(tether.time, "sleep", lambda _seconds: None)

    result = tether.bring_up_tether("usb0")

    assert result["ok"] is False
    assert result["stage"] == "command_error"
    assert "operation not permitted" in result["detail"]
    assert calls == [["ip", "link", "set", "usb0", "up"]]


def test_carrier_read_failure_is_not_reported_as_no_carrier(monkeypatch):
    monkeypatch.setattr(tether.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    monkeypatch.setattr(tether.time, "sleep", lambda _seconds: None)

    class CarrierPath:
        def __truediv__(self, _part):
            return self

        def read_text(self):
            raise PermissionError("carrier read denied")

    monkeypatch.setattr(tether, "Path", lambda _path: CarrierPath())
    result = tether.bring_up_tether("usb0")
    assert result["stage"] == "probe_error"
    assert "carrier read denied" in result["detail"]


def test_tether_inventory_failure_is_not_reported_as_no_candidate(monkeypatch):
    monkeypatch.setattr(tether, "find_tether_candidates", lambda *_a: (_ for _ in ()).throw(
        tether.TetherProbeError("sysfs inventory denied")))
    result = tether.auto_tether()
    assert result["stage"] == "probe_error"
    assert result["candidates"] == []
    assert "sysfs inventory denied" in result["detail"]


def test_failed_ip_address_query_is_not_reported_as_no_dhcp_offer(monkeypatch):
    monkeypatch.setattr(tether.subprocess, "run", lambda argv, **_kwargs: subprocess.CompletedProcess(
        argv, 1, "", "address query denied"))
    with pytest.raises(tether.TetherProbeError, match="address query denied"):
        tether._current_v4_address("usb0")


def test_missing_dhcp_command_is_not_reported_as_a_missing_offer(monkeypatch):
    calls = []

    class CarrierPath:
        def __truediv__(self, _part):
            return self

        def read_text(self):
            return "1\n"

    monkeypatch.setattr(tether, "Path", lambda _path: CarrierPath())
    monkeypatch.setattr(tether.time, "sleep", lambda _seconds: None)

    def run(argv, **_kwargs):
        calls.append(argv)
        code = 0 if argv[0] == "ip" or argv[:2] == ["dhclient", "-r"] else 127
        return subprocess.CompletedProcess(argv, code, "", "command not found" if code else "")

    monkeypatch.setattr(tether.subprocess, "run", run)
    result = tether.bring_up_tether("usb0", attempts=1)

    assert result["stage"] == "command_error"
    assert "command not found" in result["detail"]
    assert calls[-1][0] == "timeout"
