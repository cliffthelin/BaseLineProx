import json
from pathlib import Path
import pytest
import environment_recipes as er


def _suite():
    import application_bundle as ab
    return ab.compose([ab.bind('chrome',{}, {'url':'https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1.0_amd64.deb','sha256':'a'*64,'version':'1.0','package':'google-chrome-stable','medium':'deb'},{'os':'debian','release':'13','arch':'amd64'})])


def test_template_is_standard_ansible_and_uses_typed_registered_components(tmp_path):
    import tasker
    recipe=tasker.template(_suite(),cache='/cache',generation='/os/build1',data='/private',run_as='baseline-admin')
    assert isinstance(recipe,list) and recipe[0]['hosts']=='baseline_target'
    assert recipe[0]['roles'][0]['role']=='baseline.environment.native_suite'
    assert recipe[0]['vars']['baseline_suite']==_suite()
    assert tasker.validate_playbook(recipe)==recipe
    with pytest.raises(er.RecipeError):tasker.template(_suite(),cache='/same',generation='/same/child',data='/private')
    with pytest.raises(er.RecipeError):tasker.template(_suite(),cache='/cache',generation='/os',data='/private',run_as='root')
    bad=json.loads(json.dumps(recipe));bad[0]['tasks']=[{'ansible.builtin.shell':'arbitrary'}]
    with pytest.raises(er.RecipeError):tasker.validate_playbook(bad)
    bad=json.loads(json.dumps(recipe));bad[0]['roles'][0]['role']='unknown.collection.role'
    with pytest.raises(er.RecipeError):tasker.validate_playbook(bad)


def test_registry_expected_support_does_not_mean_proven_and_fake_run_stays_unit(tmp_path):
    import tasker
    registry=tmp_path/'registry.sqlite';tasker.register_catalog(registry)
    rows=tasker.compatibility(registry)
    assert rows['components'] and not rows['observations']
    recipe=tasker.template(_suite(),cache='/cache',generation='/os',data='/private')
    class Result:
        status='successful';rc=0
        events=[{'event':'runner_on_ok','event_data':{'res':{'compatibility':{'component':'baseline.environment.native_suite','platform':_suite()['platform'],'suite_digest':_suite()['digest'],'applications':{'chrome':{'version':'1.0','medium':'deb','source_sha256':'a'*64}},'capability':'materialized','runtime_verified':False}}}}]
    result=tasker.execute(recipe,'inventory',registry,tmp_path/'work',runner=lambda **kw:Result())
    rows=tasker.compatibility(registry)
    assert result['status']=='successful' and rows['observations'][0]['level']=='unit-test'
    assert rows['observations'][0]['runtime_verified'] is False
    assert not rows['proven'] and not rows['proven_current']


def test_failed_or_mismatched_run_never_promotes_expected_support(tmp_path):
    import tasker
    recipe=tasker.template(_suite(),cache='/cache',generation='/os',data='/private')
    class Result:
        status='failed';rc=2
        events=[{'event':'runner_on_ok','event_data':{'res':{'compatibility':{'component':'baseline.environment.native_suite','platform':_suite()['platform'],'suite_digest':'wrong','applications':{},'capability':'materialized','runtime_verified':False}}}}]
    registry=tmp_path/'registry.sqlite'
    result=tasker.execute(recipe,'inventory',registry,tmp_path/'work',runner=lambda **kw:Result())
    assert result['status']=='failed' and not tasker.compatibility(registry)['proven']
    assert not tasker.compatibility(registry)['observations']
    with pytest.raises(er.RecipeError):tasker.execute(recipe,'inventory',registry,tmp_path/'work',runner=lambda **kw:Result())


def test_cli_emits_a_real_ansible_template_with_editable_defaults(tmp_path):
    import subprocess
    suite=tmp_path/'suite.json';suite.write_text(json.dumps(_suite()))
    cli=Path(__file__).resolve().parents[2]/'baseline/bin/baseline-tasker'
    result=subprocess.run(['python3',str(cli),'template',str(suite)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    play=json.loads(result.stdout)[0]
    assert play['vars']['baseline_cache']=='/var/lib/baseline-app-cache'
    assert play['vars']['baseline_data']=='/home/baseline-admin/baseline-managed-apps'
    assert play['vars']['baseline_generation'].startswith('/var/lib/baseline-apps/generations/build-')


def test_runner_uses_its_python_environment_binaries(tmp_path,monkeypatch):
    import tasker,sys
    bindir=tmp_path/'venv/bin';bindir.mkdir(parents=True)
    binary=bindir/'ansible-playbook';binary.write_text('#!/bin/sh\n');binary.chmod(0o755)
    monkeypatch.setattr(sys,'executable',str(bindir/'python'))
    seen=[]
    class Result:
        status='successful';rc=0;events=[]
    tasker.execute(tasker.template(_suite(),cache='/cache',generation='/os',data='/private'),
        'inventory',tmp_path/'registry.sqlite',tmp_path/'work',runner=lambda **kw:seen.append(kw) or Result(),check=True)
    assert seen[0]['envvars']['PATH'].split(':')[0]==str(bindir)


def test_prerequisites_and_native_install_are_separate_registered_tasks():
    import tasker
    recipe=tasker.template(_suite(),cache='/cache',generation='/os',data='/private',with_runtime=True)
    assert len(recipe)==2
    assert recipe[0]['roles']==[{'role':'baseline.environment.native_runtime'}]
    assert recipe[0]['become_user']=='root'
    assert recipe[1]['become_user']=='baseline-admin'
    assert tasker.validate_playbook(recipe)==recipe
    assert len(tasker.catalog()['components'])==2
    malformed=json.loads(json.dumps(recipe));malformed[0]['become_user']='baseline-admin'
    with pytest.raises(er.RecipeError):tasker.validate_playbook(malformed)


def test_ansible_check_mode_refuses_wrong_target_os_before_a_build(monkeypatch,tmp_path):
    import importlib.util,types,sys
    class Refused(Exception):pass
    class Success(Exception):pass
    class Module:
        params={'backend_sha256':{},'suite':_suite(),'cache':'/cache','generation':'/not-created','data':'/private'}
        check_mode=True
        tmpdir=str(tmp_path)
        def __init__(self,**kwargs):pass
        def run_command(self,argv):
            if argv[1]=='runtime-plan':return 0,json.dumps({'platform':{'os':'ubuntu','release':'24.04','arch':'amd64'}}),''
            return 0,json.dumps(_suite()),''
        def fail_json(self,**kwargs):raise Refused(kwargs)
        def exit_json(self,**kwargs):raise Success(kwargs)
    basic=types.ModuleType('ansible.module_utils.basic');basic.AnsibleModule=Module
    monkeypatch.setitem(sys.modules,'ansible.module_utils.basic',basic)
    backend=types.ModuleType('ansible_collections.baseline.environment.plugins.module_utils.backend');backend.verify_backend=lambda *args:{}
    monkeypatch.setitem(sys.modules,backend.__name__,backend)
    file=Path(__file__).resolve().parents[2]/'automation/ansible_collections/baseline/environment/plugins/modules/native_suite.py'
    spec=importlib.util.spec_from_file_location('native_suite_test',file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module.os.path,'isfile',lambda path:True)
    monkeypatch.setattr(module.os,'access',lambda *args:True)
    monkeypatch.setattr(module.os.path,'lexists',lambda path:False)
    with pytest.raises(Refused,match='target'):module.main()


def test_backend_fingerprints_refuse_changed_or_redirected_files(tmp_path):
    import importlib.util,hashlib
    path=Path(__file__).resolve().parents[2]/'automation/ansible_collections/baseline/environment/plugins/module_utils/backend.py'
    spec=importlib.util.spec_from_file_location('backend_test',path);backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
    class Refused(Exception):pass
    class Module:
        def fail_json(self,**kwargs):raise Refused(kwargs)
    file=tmp_path/'cli';file.write_bytes(b'original');expected={'cli':hashlib.sha256(b'original').hexdigest()}
    assert backend.verify_backend(Module(),expected,paths={'cli':file},require_root=False)==expected
    file.write_bytes(b'changed')
    with pytest.raises(Refused):backend.verify_backend(Module(),expected,paths={'cli':file},require_root=False)
    link=tmp_path/'link';link.symlink_to(file)
    with pytest.raises(Refused):backend.verify_backend(Module(),expected,paths={'cli':link},require_root=False)


def test_component_revision_change_during_execution_refuses_attestation(tmp_path,monkeypatch):
    import tasker
    original=tasker.catalog()
    class Result:
        status='successful';rc=0
        events=[{'event':'runner_on_ok','event_data':{'res':{'compatibility':{'component':'baseline.environment.native_suite','platform':_suite()['platform'],'suite_digest':_suite()['digest'],'applications':{'chrome':{'version':'1.0','source_sha256':'a'*64}},'capability':'materialized','runtime_verified':False}}}}]
    def runner(**kwargs):
        changed=json.loads(json.dumps(original));changed['components'][0]['revision']='f'*64
        monkeypatch.setattr(tasker,'catalog',lambda:changed)
        return Result()
    registry=tmp_path/'registry.sqlite'
    with pytest.raises(er.RecipeError,match='revision'):
        tasker.execute(tasker.template(_suite(),cache='/cache',generation='/os',data='/private'),
            'inventory',registry,tmp_path/'work',runner=runner)
    assert tasker.compatibility(registry)['runs'][0]['status']=='failed'
    assert not tasker.compatibility(registry)['observations']


def test_recipe_values_are_literal_and_cannot_inject_ansible_lookup_tasks():
    import tasker,application_bundle as ab
    with pytest.raises(er.RecipeError):
        tasker.template(_suite(),cache='/cache',generation='/os',data="/private/{{lookup('pipe','command')}}")
    with pytest.raises(er.RecipeError):
        tasker.template(_suite(),cache='/cache',generation='/other/../cache/build',data='/private')
    recipe=_suite()['applications'][0]
    injected=ab.bind('chrome',{'homepage':"https://example.com/{{lookup('pipe','command')}}"},recipe['source'],recipe['platform'])
    with pytest.raises(er.RecipeError):tasker.template(ab.compose([injected]),cache='/cache',generation='/os',data='/private')
