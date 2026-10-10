import http.server
import threading
from types import SimpleNamespace

import pytest
import baseline_web as bw
import hardware_configuration as hc
from fake_runner import FakeRunner, FakeProc


def test_web_server_dispatches_requests_concurrently(monkeypatch):
    monkeypatch.setattr(http.server.HTTPServer, '__init__', lambda *a, **k: None)
    server = bw.make_server(deps={})
    assert isinstance(server, http.server.ThreadingHTTPServer)


@pytest.mark.parametrize('owner,code,applied', [('old_driver', 0, False), ('test_driver', 0, True), ('', 1, False)])
def test_driver_application_requires_selected_owning_module(owner, code, applied):
    runner = FakeRunner(files={'/sys/bus/pci/devices/0000:01:00.0/uevent':
        'PCI_ID=1234:5678\nMODALIAS=pci:test\nDRIVER=driver-name\n'}, command_responses=[
        (lambda a: a[:2] == ['modprobe', '--resolve-alias'], FakeProc(0, 'test_driver\n')),
        (lambda a: a[0] == 'readlink', FakeProc(code, '/sys/module/'+owner+'\n' if owner else ''))])
    if applied:
        assert hc.load_driver(runner, address='0000:01:00.0', pci_id='1234:5678', module='test_driver')['outcome'] == 'applied'
    else:
        with pytest.raises(RuntimeError, match='requested module|ownership'):
            hc.load_driver(runner, address='0000:01:00.0', pci_id='1234:5678', module='test_driver')


def test_stalled_request_does_not_block_another_handler(monkeypatch):
    monkeypatch.setattr(http.server.HTTPServer, '__init__', lambda *a, **k: None)
    server = bw.make_server(deps={})
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def handle(request, address):
        if request == 'slow':
            started.set()
            assert release.wait(3)
        else:
            completed.set()

    server.finish_request = handle
    server.shutdown_request = lambda request: None
    server.socket = SimpleNamespace(close=lambda: None)
    try:
        server.process_request('slow', None)
        assert started.wait(1)
        server.process_request('poll', None)
        assert completed.wait(1)
    finally:
        release.set()
        server.server_close()
