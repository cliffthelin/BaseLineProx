import subprocess

import pytest

import network


def test_route_lookup_failure_raises_instead_of_claiming_no_route(monkeypatch):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], 127, '', 'ip missing'))
    with pytest.raises(network.NetworkProbeError, match='ip missing'):
        network._route_default([])


def test_route_lookup_keeps_a_gatewayless_default_route(monkeypatch):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, 'default dev enp1s0 scope link metric 100\n', ''))
    assert network._route_default(['enp1s0']) == (None, 'enp1s0')


def test_lifeline_reports_route_probe_unavailable_distinctly(monkeypatch):
    monkeypatch.setattr(network, '_physical_nics', lambda: ['enp1s0'])
    monkeypatch.setattr(network, '_carrier', lambda _name: True)
    monkeypatch.setattr(network, '_driver_name', lambda _name: 'r8169')
    monkeypatch.setattr(network, '_route_default', lambda _up: (_ for _ in ()).throw(
        network.NetworkProbeError('ip route query failed: permission denied')))
    monkeypatch.setattr(network, '_log_event', lambda *args: None)

    facts = network.check_lifeline()

    assert facts[-1] == {
        'fact': 'address_assigned', 'ok': False,
        'detail': 'default route query unavailable: ip route query failed: permission denied',
    }


def test_physical_nic_inventory_io_failure_raises(monkeypatch):
    class NetRoot:
        def iterdir(self):
            raise PermissionError('sysfs denied')

    monkeypatch.setattr(network, 'Path', lambda _path: NetRoot())
    with pytest.raises(network.NetworkProbeError, match='sysfs denied'):
        network._physical_nics()


def test_lifeline_reports_physical_nic_inventory_unavailable(monkeypatch):
    monkeypatch.setattr(network, '_physical_nics', lambda: (_ for _ in ()).throw(
        network.NetworkProbeError('sysfs denied')))
    monkeypatch.setattr(network, '_log_event', lambda *args: None)
    facts = network.check_lifeline()
    assert facts == [{'fact': 'nic_detected', 'ok': False,
                      'detail': 'physical NIC inventory unavailable: sysfs denied'}]


def test_carrier_read_failure_raises(monkeypatch):
    class CarrierPath:
        def __truediv__(self, _part):
            return self

        def read_text(self):
            raise PermissionError('carrier denied')

    monkeypatch.setattr(network, 'Path', lambda _path: CarrierPath())
    with pytest.raises(network.NetworkProbeError, match='carrier denied'):
        network._carrier('enp1s0')


def test_driver_lookup_failure_raises_instead_of_claiming_non_wired(monkeypatch):
    class DriverPath:
        def __truediv__(self, _part):
            return self

        def resolve(self, strict=False):
            raise PermissionError('driver denied')

    monkeypatch.setattr(network, 'Path', lambda _path: DriverPath())
    with pytest.raises(network.NetworkProbeError, match='driver denied'):
        network.is_wired('enp1s0')


def test_interface_stats_read_failure_is_not_reported_as_no_traffic(monkeypatch):
    class StatsPath:
        def __init__(self, path):
            self.path = path

        def __truediv__(self, part):
            return StatsPath(self.path + '/' + part)

        def read_text(self):
            raise PermissionError('statistics denied')

    monkeypatch.setattr(network, 'Path', StatsPath)
    with pytest.raises(network.NetworkProbeError, match='statistics denied'):
        network.interface_traffic_label('enp1s0')


def test_malformed_interface_stats_are_not_reported_as_no_traffic(monkeypatch):
    class StatsPath:
        def __init__(self, path):
            self.path = path

        def __truediv__(self, part):
            return StatsPath(self.path + '/' + part)

        def read_text(self):
            return 'invalid counter'

    monkeypatch.setattr(network, 'Path', StatsPath)
    with pytest.raises(network.NetworkProbeError, match='malformed traffic counters'):
        network.interface_traffic_label('enp1s0')


def test_confirmed_zero_interface_counters_still_render_as_no_traffic(monkeypatch):
    class StatsPath:
        def __init__(self, path):
            self.path = path

        def __truediv__(self, part):
            return StatsPath(self.path + '/' + part)

        def read_text(self):
            return '0\n'

    monkeypatch.setattr(network, 'Path', StatsPath)
    assert network.interface_traffic_label('enp1s0') == ''


def test_admin_state_read_failure_is_not_reported_as_enabled(monkeypatch):
    class FlagsPath:
        def __init__(self, _path):
            pass

        def read_text(self):
            raise PermissionError('flags denied')

    monkeypatch.setattr(network, 'Path', FlagsPath)
    with pytest.raises(network.NetworkProbeError, match='flags denied'):
        network.is_admin_up('enp1s0')


def test_admin_state_parse_failure_is_explicit(monkeypatch):
    class FlagsPath:
        def __init__(self, _path):
            pass

        def read_text(self):
            return 'not hex flags'

    monkeypatch.setattr(network, 'Path', FlagsPath)
    with pytest.raises(network.NetworkProbeError, match='malformed admin state'):
        network.is_admin_up('enp1s0')


def test_set_admin_state_command_exception_returns_failure(monkeypatch):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(
        FileNotFoundError('ip command missing')))
    ok, detail = network.set_admin_state('enp1s0', True)
    assert ok is False
    assert 'ip command missing' in detail


def test_set_admin_state_verifies_the_requested_state(monkeypatch):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], 0, '', ''))
    monkeypatch.setattr(network, 'is_admin_up', lambda _name: True)
    ok, detail = network.set_admin_state('enp1s0', True)
    assert ok is True
    assert detail == 'enp1s0 is enabled (readback verified)'


def test_set_admin_state_does_not_claim_success_when_readback_disagrees(monkeypatch):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], 0, '', ''))
    monkeypatch.setattr(network, 'is_admin_up', lambda _name: False)
    ok, detail = network.set_admin_state('enp1s0', True)
    assert ok is False
    assert 'readback mismatch' in detail


def test_device_details_preserves_udev_command_failure(monkeypatch):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 127, '', 'udevadm unavailable'))
    result = network.device_details('no-such-iface')
    assert result['manufacturer'] == 'unknown'
    assert any('udevadm unavailable' in error for error in result['errors'])


def test_interface_list_preserves_unknown_carrier_instead_of_coercing_false(monkeypatch):
    monkeypatch.setattr(network, '_physical_nics', lambda: ['enp1s0'])
    monkeypatch.setattr(network, '_carrier', lambda _name: (_ for _ in ()).throw(
        network.NetworkProbeError('carrier denied')))
    monkeypatch.setattr(network, 'friendly_name', lambda name: name)
    monkeypatch.setattr(network, '_driver_name', lambda _name: 'r8169')
    assert network.list_interfaces() == [{
        'name': 'enp1s0', 'friendly': 'enp1s0', 'driver_bound': True,
        'driver_error': None, 'carrier': None, 'carrier_error': 'carrier denied', 'wired': True,
    }]


def test_interface_list_preserves_unknown_driver_and_medium(monkeypatch):
    monkeypatch.setattr(network, '_physical_nics', lambda: ['enp1s0'])
    monkeypatch.setattr(network, '_carrier', lambda _name: False)
    monkeypatch.setattr(network, '_driver_name', lambda _name: (_ for _ in ()).throw(
        network.NetworkProbeError('driver denied')))
    monkeypatch.setattr(network, 'friendly_name', lambda name: name)
    assert network.list_interfaces() == [{
        'name': 'enp1s0', 'friendly': 'enp1s0', 'driver_bound': None,
        'driver_error': 'driver denied', 'carrier': False, 'carrier_error': None,
        'wired': None,
    }]


def test_lifeline_reports_carrier_probe_unavailable(monkeypatch):
    monkeypatch.setattr(network, '_physical_nics', lambda: ['enp1s0'])
    monkeypatch.setattr(network, '_carrier', lambda _name: (_ for _ in ()).throw(
        network.NetworkProbeError('carrier denied')))
    monkeypatch.setattr(network, '_log_event', lambda *args: None)
    facts = network.check_lifeline()
    assert facts[-1] == {'fact': 'carrier_present', 'ok': False,
                         'detail': 'carrier observation unavailable: carrier denied'}


def test_lifeline_reports_driver_probe_unavailable(monkeypatch):
    monkeypatch.setattr(network, '_physical_nics', lambda: ['enp1s0'])
    monkeypatch.setattr(network, '_carrier', lambda _name: True)
    monkeypatch.setattr(network, '_driver_name', lambda _name: (_ for _ in ()).throw(
        network.NetworkProbeError('driver denied')))
    monkeypatch.setattr(network, '_log_event', lambda *args: None)
    facts = network.check_lifeline()
    assert facts[-1] == {'fact': 'driver_bound', 'ok': False,
                         'detail': 'driver observation unavailable: enp1s0: driver denied'}


def test_address_lookup_failure_raises_instead_of_claiming_no_address(monkeypatch):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], 1, '', 'permission denied'))
    with pytest.raises(network.NetworkProbeError, match='permission denied'):
        network._addr_for('enp1s0')


@pytest.mark.parametrize('output', [
    '2: enp1s0 inet definitely-not-an-ip/24 scope global\n',
    '2: enp1s0 inet scope global\n',
])
def test_malformed_address_output_raises_instead_of_claiming_no_address(monkeypatch, output):
    monkeypatch.setattr(network.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, output, ''))
    with pytest.raises(network.NetworkProbeError, match='malformed IPv4 address'):
        network._addr_for('enp1s0')


def test_lifeline_reports_address_probe_unavailable_distinctly(monkeypatch):
    monkeypatch.setattr(network, '_physical_nics', lambda: ['enp1s0'])
    monkeypatch.setattr(network, '_carrier', lambda _name: True)
    monkeypatch.setattr(network, '_driver_name', lambda _name: 'r8169')
    monkeypatch.setattr(network, '_route_default', lambda _up: ('192.0.2.1', 'enp1s0'))
    monkeypatch.setattr(network, '_addr_for', lambda _dev: (_ for _ in ()).throw(
        network.NetworkProbeError('address query failed: permission denied')))
    monkeypatch.setattr(network, '_log_event', lambda *args: None)

    facts = network.check_lifeline()

    assert facts[-1] == {
        'fact': 'address_assigned', 'ok': False,
        'detail': 'address query unavailable: address query failed: permission denied',
    }
