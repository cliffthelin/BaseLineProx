from types import SimpleNamespace
import hardware_tabs as ht
from fake_runner import FakeRunner, FakeProc


def test_package_observation_requires_real_installed_status():
    runner = FakeRunner(command_responses=[(lambda a:a[0]=='dpkg-query',
        FakeProc(0,'ethtool\t6.0\tinstalled\nsmartmontools\t7.4\tconfig-files\n'))])
    state = ht.package_state(runner)
    assert state['installed'] == {'ethtool': '6.0'}
    assert state['available']


def test_failed_package_query_is_unavailable_not_missing_packages():
    runner = FakeRunner(command_responses=[(lambda a:a[0]=='dpkg-query',FakeProc(2,'','database error'))])
    state = ht.package_state(runner)
    assert not state['available'] and 'database error' in state['error']


def test_subtabs_associate_storage_network_and_cpu_packages():
    page = ht.render({},configuration_html='<p>config</p>',driver_sections={},packages={'available':True,'installed':{'ethtool':'6.0'}},render_inventory=lambda inventory:'inventory')
    assert 'role="tablist"' in page
    assert 'id="hardware-tab-drives"' in page
    assert 'id="hardware-tab-network"' in page
    assert '/drive-admin' in page
    assert '/installer-cache#cache-entry-ethtool' in page
    assert '6.0' in page and 'smartmontools' in page and 'intel-microcode' in page
    assert 'Not installed' in page


def test_vm_drive_panel_does_not_offer_host_disk_actions():
    page = ht.render({},configuration_html='',driver_sections={},packages={'available':False,'error':'no guest package adapter'},render_inventory=lambda inventory:'inventory',target='my-vm')
    assert '/drive-admin' not in page
    assert 'no guest package adapter' in page
    assert '/vms' in page
