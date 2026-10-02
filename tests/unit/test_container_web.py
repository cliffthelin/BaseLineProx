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
    return _RealServerCase(deps),host


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
