import json
import pytest
import app_capture as ac
import vm_host as vh


class Guest:
    def __init__(self):self.calls=[]
    def guest_exec(self,name,command,data=b''):
        self.calls.append((name,command,data))
        return {'out-data':'installed\nbash\n5.2.21-2ubuntu4\namd64\nbase-files (>= 2.1), libc6 (>= 2.36)\n /etc/bash.bashrc aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'}


def test_inspection_extracts_package_identity_and_config_locations_without_content():
    guest=Guest();result=ac.inspect_vm(guest,'work','bash')
    report=result['capture_report']
    assert result['ok'] and report['package']=='bash' and report['version']=='5.2.21-2ubuntu4'
    assert report['configuration_paths']==['/etc/bash.bashrc']
    assert report['recipe_ready'] is False and report['test_install_verified'] is False
    assert report['sources_verified'] is False
    assert guest.calls[0][1][0]=='dpkg-query' and guest.calls[0][2]==b''
    assert 'aaaaaaaa' not in json.dumps(report)


@pytest.mark.parametrize('package',['--help','*','bash; touch /tmp/x','bash:amd64','',None])
def test_package_options_patterns_and_shell_text_are_refused_before_guest_execution(package):
    guest=Guest()
    with pytest.raises(vh.VmError):ac.inspect_vm(guest,'work',package)
    assert guest.calls==[]


def test_missing_native_package_and_malformed_metadata_do_not_create_a_recipe():
    guest=Guest()
    guest.guest_exec=lambda *args,**kwargs:{'out-data':'not-installed\nbash\nanything'}
    with pytest.raises(vh.VmError):ac.inspect_vm(guest,'work','bash')


def test_inspection_is_available_as_a_durable_human_web_action(tmp_path):
    from test_vm_web import _case
    c,f,_=_case(tmp_path,wait_jobs=False)
    f.host.guest_exec=Guest().guest_exec
    try:
        assert b'Inspect installed application' in c.get('/recipes')[1]
        status,result=c.post_json('/vms/action',{'action':'inspect_app','name':'work','package':'bash'})
        assert status==202,result
        jobs=c.server.deps['workload_jobs'];jobs.wait(result['job_id'],3)
        report=c.post_json('/workloads/result',{'job_id':result['job_id']})[1]['capture_report']
        assert report['package']=='bash' and not report['recipe_ready']
        assert jobs.get(result['job_id'])['result']['capture_report']==report
    finally:c.close()


def test_inspection_submit_works_on_http_lan_without_secure_context_crypto():
    import subprocess
    import recipe_page
    html=recipe_page.render().decode()
    # Exercise the actual inspection handler independently of unrelated editor initialization.
    script='async function inspectApp(){'+html.split('async function inspectApp(){',1)[1].split('function clear()',1)[0]
    harness="""const vm=require('vm');const fields={};let submitted=false;
const context={document:{getElementById:id=>fields[id]||(fields[id]={value:id==='capture_vm'?'work':'bash',addEventListener(){}})},
setTimeout,fetch:async(path,options)=>{submitted=JSON.parse(options.body).action==='inspect_app';return {ok:false,json:async()=>({message:'test refusal'})}}};
vm.createContext(context);vm.runInContext(SCRIPT,context);context.inspectApp().then(()=>{if(!submitted)process.exit(1)});
""".replace('SCRIPT',__import__('json').dumps(script))
    result=subprocess.run(['node','-e',harness],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_application_catalog_accepts_new_native_package_definition(monkeypatch):
    import application_bundle as ab
    monkeypatch.setattr(ab,'APPS',tuple(ab.APPS))
    for name in ('PACKAGES','SOURCES','EXECUTABLES','APPLICATION_DEFINITIONS'):
        monkeypatch.setattr(ab,name,dict(getattr(ab,name)))
    ab.register_application({'id':'gimp','name':'GIMP','package':'gimp','executable':'usr/bin/gimp',
        'source_url':'https://archive.ubuntu.com/ubuntu/pool/universe/g/gimp/gimp_3.0_amd64.deb','sha256':'a'*64})
    recipe=ab.bind('gimp',{}, {'url':'https://archive.ubuntu.com/ubuntu/pool/universe/g/gimp/gimp_3.0_amd64.deb',
        'sha256':'a'*64,'version':'3.0','package':'gimp','medium':'deb'}, {'os':'ubuntu','release':'24.04','arch':'amd64'})
    assert recipe['app']=='gimp' and 'gimp' in ab.APPS
