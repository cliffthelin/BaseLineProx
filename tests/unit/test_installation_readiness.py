import pytest
from fake_runner import FakeRunner, FakeProc
import firstboot_network_repair as network_repair


def test_address_and_gateway_do_not_prove_internet_or_firewall(monkeypatch):
    import installation_readiness as ir
    monkeypatch.setattr(ir.storage_policy,'verify_runtime',lambda runner:{'state':'storage_verified'})
    facts=[{'fact':'address_assigned','ok':True},{'fact':'gateway_reachable','ok':True}]
    runner=FakeRunner(command_responses=[(lambda a:a[0]=='systemctl',FakeProc(0,'active\n'))])
    report=ir.collect(runner,network_check=lambda:facts)
    assert not report['ready']
    assert any(row['id']=='internet' and not row['ready'] for row in report['checks'])
    assert any(row['id']=='firewall' and not row['ready'] for row in report['checks'])


def test_missing_network_observations_are_not_success():
    assert network_repair.facts_verification([]) == {'address': False, 'gateway': False}


def test_non_boolean_network_observations_are_not_success():
    assert network_repair.facts_verification([
        {'fact':'address_assigned','ok':'unknown'},
        {'fact':'gateway_reachable','ok':1}]) == {'address':False,'gateway':False}


def test_readiness_requires_storage_network_and_every_service(monkeypatch):
    import installation_readiness as ir
    monkeypatch.setattr(ir.storage_policy, 'verify_runtime', lambda runner: {'state':'storage_verified'})
    monkeypatch.setattr(ir.lan_firewall,'verify_active',lambda runner:(True,'Verified fixture firewall'))
    facts=[{'fact':'address_assigned','ok':True},{'fact':'gateway_reachable','ok':True}]
    runner=FakeRunner(command_responses=[(lambda a:a[0]=='curl',FakeProc(0,'200')),
        (lambda a:a[0]=='systemctl',FakeProc(0,'active\n'))])
    assert ir.collect(runner, network_check=lambda:facts)['ready']
    runner.command_responses=[(lambda a:a[-1]=='pveproxy.service',FakeProc(3,'failed\n')),
        (lambda a:a[0]=='curl',FakeProc(0,'200')),
        (lambda a:a[0]=='systemctl',FakeProc(0,'active\n'))]
    report=ir.collect(runner,network_check=lambda:facts)
    assert not report['ready']
    assert any(row['id']=='pveproxy.service' and not row['ready'] for row in report['checks'])


def test_unavailable_storage_and_network_are_reported(monkeypatch):
    import installation_readiness as ir
    def unavailable(*args):raise RuntimeError('observation unavailable')
    monkeypatch.setattr(ir.storage_policy,'verify_runtime',unavailable)
    report=ir.collect(FakeRunner(),network_check=unavailable)
    assert not report['ready']
    assert all(not row['ready'] for row in report['checks'])
    assert 'observation unavailable' in report['checks'][0]['detail']


def test_readiness_page_escapes_observation_errors():
    import installation_readiness as ir
    page=ir.render({'ready':False,'checks':[{'id':'storage','ready':False,'detail':'<script>failure</script>'}]})
    assert '<script>' not in page
    assert '&lt;script&gt;' in page


def test_readiness_route_requires_authentication_before_observation(monkeypatch):
    import baseline_web as bw
    import installation_readiness as ir
    from types import SimpleNamespace
    handler=object.__new__(bw.UnifiedHandler)
    handler.path='/installation-readiness'
    handler.server=SimpleNamespace(deps={'clock':lambda:0})
    monkeypatch.setattr(handler,'_refuse_unauthenticated',lambda *args:True)
    monkeypatch.setattr(ir,'collect',lambda *args:pytest.fail('Unauthenticated observation'))
    handler.do_GET()


def test_authenticated_readiness_route_renders_report(monkeypatch):
    import baseline_web as bw
    import installation_readiness as ir
    from types import SimpleNamespace
    handler=object.__new__(bw.UnifiedHandler)
    handler.path='/installation-readiness'
    runner=FakeRunner()
    handler.server=SimpleNamespace(deps={'clock':lambda:0,'runner':runner})
    monkeypatch.setattr(handler,'_refuse_unauthenticated',lambda *args:False)
    monkeypatch.setattr(ir,'collect',lambda observed: {'ready':False,'checks':[]})
    responses=[]
    monkeypatch.setattr(handler,'_html_response',lambda status,page:responses.append((status,page)))
    handler.do_GET()
    assert responses[0][0]==200
    assert b'Required checks have not passed' in responses[0][1]
