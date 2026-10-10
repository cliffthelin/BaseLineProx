import pytest
from fake_runner import FakeRunner, FakeProc
import hardware_configuration as hc


def device_runner():
    return FakeRunner(files={'/sys/bus/pci/devices/0000:01:00.0/uevent':
        'PCI_ID=1234:5678\nMODALIAS=pci:test\n'},command_responses=[
        (lambda a:a[:2]==['modprobe','--resolve-alias'],FakeProc(0,'test_driver\n'))])


def test_driver_choices_come_from_native_device_alias():
    choices=hc.driver_choices(device_runner(),'0000:01:00.0')
    assert choices['modules']==['test_driver']
    assert choices['driver'] is None


def test_loading_unlisted_driver_never_runs_modprobe():
    runner=device_runner()
    with pytest.raises(RuntimeError,match='compatible'):
        hc.load_driver(runner,address='0000:01:00.0',pci_id='1234:5678',module='unrelated')
    assert ['modprobe','unrelated'] not in runner.calls


def test_driver_load_requires_observed_binding():
    with pytest.raises(RuntimeError,match='not bound'):
        hc.load_driver(device_runner(),address='0000:01:00.0',pci_id='1234:5678',module='test_driver')


def test_changed_device_identity_refuses_loading():
    runner=device_runner()
    with pytest.raises(RuntimeError,match='identity changed'):
        hc.load_driver(runner,address='0000:01:00.0',pci_id='1111:2222',module='test_driver')
    assert ['modprobe','test_driver'] not in runner.calls


def test_module_package_comes_from_native_module_path_and_package_database():
    runner = FakeRunner(command_responses=[
        (lambda a:a[0]=='modinfo', FakeProc(0,'/lib/modules/6.8/kernel/net/test.ko\n')),
        (lambda a:a[0]=='dpkg-query',FakeProc(0,'linux-modules-6.8: /lib/modules/6.8/kernel/net/test.ko\n'))])
    assert hc.module_package(runner,'test_driver')['packages'] == ['linux-modules-6.8']


def test_unowned_module_is_not_assigned_a_guessed_package():
    runner = FakeRunner(command_responses=[
        (lambda a:a[0]=='modinfo',FakeProc(0,'/lib/modules/6.8/updates/dkms/nvidia.ko\n')),
        (lambda a:a[0]=='dpkg-query',FakeProc(1,'','no path found'))])
    state = hc.module_package(runner,'nvidia')
    assert state['packages'] == [] and 'no path found' in state['error']
