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
def test_single_drive_page_proposal_uses_explicit_enrolled_serial():
    import install_plan_page as page
    import test_install_plan as fixtures
    found = fixtures.discover(fixtures.disk("sda", fixtures.PVE))
    result = page.perform({"action": "single-drive", "serial": fixtures.PVE}, discovery_provider=lambda: found)
    assert result["valid"] is True
    assert result["executed"] is False
    assert result["plan"]["storage"]["baseline"]["serial"] == fixtures.PVE


def test_input_preparation_waits_for_saved_draft_and_exposes_real_job_report():
    import install_plan_page as page
    html=page.render().decode()
    assert 'Prepare installation inputs' in html
    assert 'await installerDraft.flush()' in html
    assert '/install-plan/prepare-inputs' in html
    assert '/install-plan/input-bundle' in html
    assert 'request_id' in html
    assert 'crypto.randomUUID()' not in html


def test_workspace_exposes_current_drives_and_supported_recipes_over_http():
    from test_baseline_web import _RealServerCase,_base_deps
    found=discover(proxmox_disk(),baseline_disk())
    case=_RealServerCase(_base_deps(install_plan_discovery=lambda:found))
    try:
        response=case.get('/install-plan/discovery')
        assert response[0]==200
        body=json.loads(response[2]) if len(response)>2 else json.loads(response[1])
        assert body['drives']==found['drives']
        assert body['os_choices']==['ubuntu-24.04']
        assert 'chrome' in body['applications']
    finally:case.close()


def test_application_catalog_can_be_extended_through_authenticated_installer(tmp_path,monkeypatch):
    import application_bundle as ab
    from test_baseline_web import _RealServerCase,_base_deps
    monkeypatch.setattr(ab,'APPS',tuple(ab.APPS))
    for name in ('PACKAGES','SOURCES','EXECUTABLES','APPLICATION_DEFINITIONS'):
        monkeypatch.setattr(ab,name,dict(getattr(ab,name)))
    source=tmp_path/'source';source.mkdir()
    definition={'id':'my-editor','name':'My editor','package':'my-editor','executable':'usr/bin/my-editor',
        'source_url':'https://packages.example.org/editors/my-editor_2.4.1_amd64.deb','sha256':'a'*64}
    catalog=source/'user-state/application-definitions'
    case=_RealServerCase(_base_deps(installer_repo_root=source,application_catalog_root=catalog,
        install_plan_discovery=lambda:discover(proxmox_disk(),baseline_disk())))
    try:
        status,result=case.post_json('/install-plan/catalog',{'definition':definition})
        assert status==201 and result['installed'] is False
        status,raw=case.get('/install-plan/discovery')
        assert status==200 and any(app['id']=='my-editor' for app in json.loads(raw)['application_entries'])
        assert (catalog/'my-editor.json').is_file()
    finally:case.close()


def test_shortcut_configuration_validates_before_it_can_be_saved():
    from test_baseline_web import _RealServerCase,_base_deps
    case=_RealServerCase(_base_deps())
    try:
        status,result=case.post_json('/install-plan/app-config',{'app':'chrome','configuration':{'scale':1.25,'homepage':'https://www.proxmox.com/'}})
        assert status==200 and result['configuration']['scale']==1.25 and result['applied'] is False
        status,_=case.post_json('/install-plan/app-config',{'app':'chrome','configuration':{'scale':99}})
        assert status==400
    finally:case.close()


def test_workspace_uses_desktop_wallpaper_and_phone_icon_groups():
    import install_plan_page as page
    html = page.render().decode()
    assert 'desktop-wallpaper' in html
    assert 'icon-folder' in html
    assert 'backdrop-filter:blur(' in html
    assert 'contextmenu' in html
    assert 'prefers-reduced-motion' in html


def test_application_shortcut_catalog_reads_custom_definitions_from_persistent_state(tmp_path,monkeypatch):
    import application_bundle as ab
    import install_plan_page as page
    monkeypatch.setattr(ab,'APPS',tuple(ab.APPS))
    for name in ('PACKAGES','SOURCES','EXECUTABLES','APPLICATION_DEFINITIONS'):
        monkeypatch.setattr(ab,name,dict(getattr(ab,name)))
    definition={'id':'catalog-editor','name':'Catalog editor','package':'catalog-editor',
        'executable':'usr/bin/catalog-editor',
        'source_url':'https://packages.example.org/catalog/catalog-editor_1.2_amd64.deb',
        'sha256':'b'*64}
    catalog=ab.application_catalog_directory(state_dir=tmp_path/'user-state')
    ab.save_application_definition(catalog,definition)
    entries=page.catalog_entries(catalog_directory=catalog)
    assert any(entry['id']=='catalog-editor' and entry['name']=='Catalog editor'
               for entry in entries)


def test_authenticated_web_catalog_writes_and_reads_configured_state_without_command_fakes(tmp_path):
    import threading,time,urllib.request,json
    import baseline_web as bw
    import settings_web as sw
    import application_bundle as ab
    state=tmp_path/'user-state';catalog=ab.application_catalog_directory(state_dir=state)
    now=time.time();sessions=sw.SessionStore();session=sessions.create('catalog-owner',now=now)
    server=bw.make_server(deps={'sessions':sessions,'clock':lambda:time.time(),
        'application_catalog_root':catalog,'installer_repo_root':None},host='127.0.0.1',port=0)
    port=server.server_address[1]
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    definition={'id':'web-editor','name':'Web editor','package':'web-editor',
        'executable':'usr/bin/web-editor',
        'source_url':'https://packages.example.org/web/web-editor_1.0_amd64.deb',
        'sha256':'c'*64}
    def post(path,payload):
        url=f'http://127.0.0.1:{port}{path}'
        request=urllib.request.Request(url,data=json.dumps(payload).encode(),method='POST',
            headers={'Content-Type':'application/json','Cookie':'session='+session.token,'Origin':f'http://127.0.0.1:{port}'})
        with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.loads(response.read())
    try:
        status,result=post('/install-plan/catalog',{'definition':definition})
        assert status==201 and result['registered'] is True and result['installed'] is False
        status,result=post('/install-plan/app-config',{'app':'web-editor','configuration':{'scale':1.25}})
        assert status==200 and result['configuration']=={'scale':1.25}
        assert (catalog/'web-editor.json').read_text()==json.dumps(definition,sort_keys=True,indent=2)+'\n'
        assert (catalog/'web-editor.json').stat().st_mode&0o777==0o600
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_installer_offers_saved_parent_bluetooth_choice_outside_advanced_controls():
    import install_plan_page as page
    html = page.render().decode()
    assert 'id="bluetooth-from-parent"' in html
    assert 'Copy parent Bluetooth devices and pairings' in html
    assert html.index('id="bluetooth-from-parent"') < html.index('id="advanced-installer"')
    assert 'plan.host_configuration.bluetooth_from_parent' in html
