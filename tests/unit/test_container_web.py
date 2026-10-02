"""HTTP tests use fake Proxmox; live boot checks are separate."""
import json

import settings_web as sw
from test_baseline_web import _RealServerCase, _base_deps
from test_distro_containers import NativeRunner
import distro_containers as dc


def case(tmp_path, role='admin'):
    run = NativeRunner()
    host = dc.DistroContainers(tmp_path/'protected',run=run,run_input=run.input,
                              password_factory=lambda: b'fresh-test-only',password_hasher=lambda _: '$6$salt$hash')
    sessions = sw.SessionStore()
    sessions.create('someone',1_800_000_000.0,role=role)
    deps = _base_deps(sessions=sessions,container_host=host,vm_config_path=tmp_path/'paths.json')
    c = _RealServerCase(deps)
    post = c.post_json
    def completed_post(path,body):
        status,result=post(path,body)
        if status==202:
            c.server.deps['workload_jobs'].wait(result['job_id'],3)
            return post('/workloads/result',{'job_id':result['job_id']})
        return status,result
    c.post_json=completed_post
    return c,host


def test_admin_can_choose_host_distros_create_a_linked_container_and_rebuild_its_os(tmp_path):
    c,h = case(tmp_path)
    try:
        status,page=c.get('/containers')
        assert status==200 and b'alpine-3.23' in page and b'host kernel' in page
        _,r=c.post_json('/containers/action',{'action':'create','name':'alpine-work',
                  'template':h.catalog()[0]['name'],'cache_storage':'source-cache','os_storage':'os-thin',
                  'disk_gb':4,'memory_mb':512,'cpus':1})
        assert r['ok'] and r['password']=='fresh-test-only'
        assert b'fresh-test-only' not in c.get('/containers')[1]
        (h.data_path('alpine-work','home')/'saved').write_text('document')
        assert c.post_json('/containers/action',{'action':'shutdown','name':'alpine-work'})[1]['ok']
        assert not c.post_json('/containers/action',{'action':'rebuild','name':'alpine-work'})[1]['ok']
        assert c.post_json('/containers/action',{'action':'rebuild','name':'alpine-work','confirm':'yes'})[1]['ok']
        assert (h.data_path('alpine-work','home')/'saved').read_text()=='document'
    finally:
        c.close()


def test_limited_login_cannot_manage_distro_containers(tmp_path):
    c,h=case(tmp_path,role='operator')
    try:
        assert c.get('/containers')[0]==403
        assert c.post_json('/containers/action',{'action':'create','name':'x'})[0]==403
    finally:
        c.close()


def test_missing_os_is_visible_and_explicit_recovery_runs_through_durable_web_job(tmp_path):
    c,h=case(tmp_path)
    try:
        c.post_json('/containers/action',{'action':'create','name':'work','template':h.catalog()[0]['name'],
                                        'cache_storage':'source-cache','os_storage':'os-thin'})
        c.post_json('/containers/action',{'action':'shutdown','name':'work'})
        original=h.run
        def interrupted(args):
            if args[:2]==['pct','clone']: return 1,'','injected failure'
            return original(args)
        h.run=interrupted
        assert not c.post_json('/containers/action',{'action':'rebuild','name':'work','confirm':'yes'})[1]['ok']
        h.run=original
        status,page=c.get('/containers')
        assert status==200 and b'Recover rebuild' in page and b'absent' in page
        assert not c.post_json('/containers/action',{'action':'recover','name':'work'})[1]['ok']
        result=c.post_json('/containers/action',{'action':'recover','name':'work','confirm':'yes'})[1]
        assert result['ok'] and h.status('work')['running']
    finally:
        c.close()


def test_retained_backup_and_new_name_restore_are_available_through_durable_jobs(tmp_path):
    from test_container_backup import ScriptedRun
    c,h=case(tmp_path)
    dest=tmp_path/'separate';dest.mkdir()
    c.server.deps['container_backup_run']=ScriptedRun(dest)
    try:
        c.post_json('/containers/action',{'action':'create','name':'work','template':h.catalog()[0]['name'],
                                        'cache_storage':'source-cache','os_storage':'os-thin'})
        c.post_json('/containers/action',{'action':'shutdown','name':'work'})
        (h.data_path('work','data')/'saved').write_text('keep')
        assert b'Back up retained data' in c.get('/containers')[1]
        status,result=c.post_json('/containers/action',{'action':'backup','name':'work','destination':str(dest)})
        assert result['ok'] and result['backup_id']
        status,page=c.get('/containers/backups?destination='+str(dest))
        assert status==200 and result['backup_id'].encode() in page and b'OS packages' in page
        body={'action':'restore','name':'restored','destination':str(dest),'backup_id':result['backup_id']}
        assert not c.post_json('/containers/action',body)[1]['ok']
        body['confirm']='yes'
        assert c.post_json('/containers/action',body)[1]['ok']
        assert (h.data_path('restored','data')/'saved').read_text()=='keep'
        assert (h.data_path('work','data')/'saved').read_text()=='keep'
    finally:c.close()
