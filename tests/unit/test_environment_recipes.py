import copy
import json
import pytest
import environment_recipes as er


def os_recipe():
    return {'format':'baseline.recipe/v1','kind':'os','id':'ubuntu-desktop',
            'platform':{'os':'ubuntu','release':'24.04','arch':'amd64'},
            'source':{'sha256':'a'*64}, 'configuration':{'locale':'en_US.UTF-8'},
            'state':[{'path':'/home','role':'documents','retention':'retained'}]}


def app_recipe():
    return {'format':'baseline.recipe/v1','kind':'app','id':'chromium',
            'platform':{'os':'ubuntu','release':'24.04','arch':'amd64'},
            'source':{'sha256':'b'*64}, 'configuration':{'homepage_role':'environment_console'},
            'state':[{'path':'~/.config/chromium','role':'app_private','retention':'retained'}]}


def test_recipe_roundtrip_and_locked_stack_have_no_local_deployment_data():
    osr,app=os_recipe(),app_recipe()
    bundle=er.compose(osr,[app])
    assert bundle['format']=='baseline.stack/v1'
    assert bundle['os']['digest']==er.digest(osr)
    assert bundle['apps'][0]['digest']==er.digest(app)
    assert er.load(er.export(osr))==osr
    assert er.digest(osr)==er.digest(json.loads(json.dumps(osr,sort_keys=True)))
    assert bundle['runtime_applied'] is False


@pytest.mark.parametrize('change',[
    lambda r:r.update(vmid=100),
    lambda r:r['configuration'].update(password='private'),
    lambda r:r['source'].update(path='/mnt/private/image'),
    lambda r:r['platform'].update(host='local'),
    lambda r:r.update(id='unknown-app'),
    lambda r:r['state'][0].update(path='/etc'),
    lambda r:r['source'].update(sha256='not-pinned'),
])
def test_unknown_private_or_unsupported_fields_are_refused(change):
    r=app_recipe();change(r)
    with pytest.raises(er.RecipeError):er.export(r)


def test_stack_refuses_duplicate_apps_wrong_kinds_and_tampered_lock():
    osr,app=os_recipe(),app_recipe()
    with pytest.raises(er.RecipeError):er.compose(osr,[app,copy.deepcopy(app)])
    with pytest.raises(er.RecipeError):er.compose(app,[osr])
    lock=er.compose(osr,[app]);lock['apps'][0]['recipe']['configuration']['homepage_role']='private-url'
    with pytest.raises(er.RecipeError):er.verify_stack(lock)
    assert er.verify_stack(er.compose(osr,[app]))['runtime_applied'] is False


def test_import_refuses_duplicate_json_keys_and_reports_malformed_documents():
    text=er.export(os_recipe()).replace('"kind":"os"','"kind":"app","kind":"os"')
    with pytest.raises(er.RecipeError):er.load(text)
    for text in ('{broken', '[]', 'null', '"text"'):
        with pytest.raises(er.RecipeError):er.load(text)


def test_cli_validates_and_composes_without_claiming_installation(tmp_path):
    import subprocess
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    osfile=tmp_path/'os.json';appfile=tmp_path/'app.json'
    osfile.write_text(er.export(os_recipe()));appfile.write_text(er.export(app_recipe()))
    cli=root/'baseline/bin/baseline-recipes'
    result=subprocess.run(['python3',str(cli),'compose',str(osfile),str(appfile)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert er.verify_stack(json.loads(result.stdout))['runtime_applied'] is False
    appfile.write_text('{bad')
    refused=subprocess.run(['python3',str(cli),'compose',str(osfile),str(appfile)],capture_output=True,text=True)
    assert refused.returncode!=0 and not refused.stdout
