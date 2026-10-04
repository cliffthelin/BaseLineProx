"""Read-only installer editor over fresh synthetic drive listings."""
import copy
import json
import pytest
import install_plan as ip
from test_install_plan import discover, proxmox_disk, baseline_disk


def test_autofill_then_compile_uses_fresh_discovery_and_runs_nothing():
    import install_plan_page as page
    calls=[]
    def provider():
        calls.append(True)
        return discover(proxmox_disk(),baseline_disk())
    result=page.perform({'action':'autofill'},discovery_provider=provider)
    assert result['valid'] and result['executed'] is False
    plan=result['plan'];plan['environment']['name']='my-desktop'
    compiled=page.perform({'action':'compile','plan':plan},discovery_provider=provider)
    assert compiled['stages']['environment']['name']=='my-desktop'
    assert compiled['stages']['executed'] is False and len(calls)==2


def test_invalid_actions_and_extra_fields_are_refused_before_discovery():
    import install_plan_page as page
    def provider():raise AssertionError('invalid request must not discover hardware')
    for body in (None,[],{'action':'execute'},{'action':'compile'},
                 {'action':'autofill','device':'/dev/sda'}, {'action':'validate','plan':{},'shell':'true'}):
        with pytest.raises(ip.PlanError):page.perform(body,discovery_provider=provider)


def test_changed_partition_and_missing_volumes_remain_editable_but_cannot_compile():
    import install_plan_page as page
    found=discover(proxmox_disk(),baseline_disk())
    plan=page.perform({'action':'autofill'},discovery_provider=lambda:found)['plan']
    changed=discover(proxmox_disk(),baseline_disk(prefix='z'))
    result=page.perform({'action':'validate','plan':plan},discovery_provider=lambda:changed)
    assert not result['valid'] and result['errors'] and result['executed'] is False
    with pytest.raises(ip.PlanError):page.perform({'action':'compile','plan':plan},discovery_provider=lambda:changed)
    incomplete=discover(proxmox_disk(),baseline_disk(names=['BASELINE']))
    result=page.perform({'action':'autofill'},discovery_provider=lambda:incomplete)
    assert result['plan'] and not result['valid'] and any('missing volumes' in e for e in result['errors'])


def test_plan_page_reaches_authenticated_http_and_refuses_cross_site_before_discovery():
    from test_baseline_web import _RealServerCase, _base_deps
    from test_baseline_web_auth_gate import _request
    import settings_web as sw
    calls=[]
    def provider():calls.append(True);return discover(proxmox_disk(),baseline_disk())
    sessions=sw.SessionStore();token=sessions.create('root',now=1700000000.0).token
    case=_RealServerCase(_base_deps(sessions=sessions,install_plan_discovery=provider))
    try:
        status,_,body=_request(case.port,'GET','/install-plan',cookie=token)
        assert status==200 and b'Installer plan' in body
        assert '/install-plan' in __import__('baseline_web').render_nav('/install-plan')
        assert not calls
        status,_,_=_request(case.port,'POST','/install-plan/action',body=b'{"action":"autofill"}')
        assert status in (303,401) and not calls
        import urllib.request
        def post(origin):
            req=urllib.request.Request(f'http://127.0.0.1:{case.port}/install-plan/action',
                data=b'{"action":"autofill"}',headers={'Content-Type':'application/json','Cookie':'session='+token,'Origin':origin})
            try:
                with urllib.request.urlopen(req) as response:return response.status,json.loads(response.read())
            except __import__('urllib.error').error.HTTPError as exc:return exc.code,exc.read()
        status,_=post('https://outside.example');assert status==403 and not calls
        status,result=post(f'http://127.0.0.1:{case.port}')
        assert status==200 and result['executed'] is False and len(calls)==1
    finally:case.close()


def test_editor_browser_script_is_valid_javascript(tmp_path):
    import subprocess
    import install_plan_page as page
    script=page.render().decode().split('<script>',1)[1].split('</script>',1)[0]
    path=tmp_path/'editor.js';path.write_text(script)
    result=subprocess.run(['node','--check',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_editor_rejects_large_plan_before_discovery():
    import install_plan_page as page
    def provider():raise AssertionError('oversized plan must not trigger discovery')
    with pytest.raises(ip.PlanError):page.perform({'action':'validate','plan':{'notes':'x'*65537}},discovery_provider=provider)


def test_editor_module_is_carried_in_installer_source():
    from pathlib import Path
    provision=(Path(__file__).resolve().parents[2]/'boot/provision.sh').read_text()
    assert 'cp "$SRC/baseline/lib/install_plan_page.py" /opt/baseline/lib/install_plan_page.py' in provision


@pytest.mark.parametrize('field,value',[('os',{}),('variant',[]),('apps',[{}])])
def test_malformed_edit_is_refused_without_an_http_server_error(field,value):
    import install_plan_page as page
    found=discover(proxmox_disk(),baseline_disk());plan=ip.autofill(found)
    plan['applications' if field=='apps' else 'environment'][field]=value
    with pytest.raises(ip.PlanError):page.perform({'action':'compile','plan':plan},discovery_provider=lambda:found)


def test_compiled_plan_no_longer_claims_its_editor_is_missing():
    import install_plan_page as page
    found=discover(proxmox_disk(),baseline_disk());plan=ip.autofill(found)
    result=page.perform({'action':'compile','plan':plan},discovery_provider=lambda:found)
    assert not any('web page for editing' in item for item in result['stages']['not_yet_connected'])


def test_real_discovery_adapter_refuses_unknown_boot_identity_before_listing(monkeypatch):
    import subprocess,physical_device_safety as pds
    import install_plan_page as page
    monkeypatch.setattr(pds,'get_boot_device_serial',lambda runner:None)
    def forbidden(*args,**kwargs):raise AssertionError('unknown boot identity must stop discovery')
    monkeypatch.setattr(subprocess,'run',forbidden)
    with pytest.raises(ip.PlanError):page.discover_current()
