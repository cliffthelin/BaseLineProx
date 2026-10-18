"""Installer update contract; fake command execution is not physical proof."""
from fake_runner import FakeRunner, FakeProc
from test_drive_admin import FakePdsRunner
from hitl_helpers import perform_confirmed
import drive_admin as da


def test_web_confirmed_update_runs_helper_bound_to_selected_serial(tmp_path):
    runner = FakeRunner(command_responses=[(lambda a: True, FakeProc(0, '{"state":"updated","boot_verified":false}\n'))])
    result = perform_confirmed(
        runner, 'update_installed_drive',
        {'device_path':'/dev/sdb','input_bundle':str(tmp_path/'bundle'),
         'recovery_folder':str(tmp_path/'recovery')},
        pds_runner=FakePdsRunner())
    assert result.ok
    assert any('SYNTHDRIVEA00001' in call and 'baseline-drive-update' in ' '.join(call)
               for call in runner.calls)
    assert 'boot' in result.detail.lower()


def test_changed_captured_source_refuses_before_any_target_command(tmp_path):
    import pytest
    import installer_inputs as inputs
    import installed_drive_update as update
    from test_installer_inputs import repository
    source = repository(tmp_path/'source')
    bundle = tmp_path/'bundle'
    inputs.prepare(source,bundle,plan={},settings={},recipe=None,artifact_locks={},which=lambda name:'/bin/'+name)
    (bundle/'payload/baseline/lib/needed.py').write_text('changed')
    runner = FakeRunner()
    with pytest.raises(inputs.InputError,match='integrity'):
        update.update(runner,serial='SYNTHDRIVEA00001',input_bundle=bundle,
                      recovery_folder=tmp_path/'recovery',root=tmp_path/'target')
    assert runner.calls == []


def test_installed_web_updater_is_deployed_with_its_native_helper():
    from pathlib import Path
    provision=(Path(__file__).resolve().parents[2]/'boot/provision.sh').read_text()
    assert 'cp "$SRC/baseline/lib/installed_drive_update.py" /opt/baseline/lib/installed_drive_update.py' in provision
    assert 'cp "$SRC/baseline/bin/baseline-drive-update" /opt/baseline/bin/baseline-drive-update' in provision


def test_installer_update_reviews_owned_snapshot_without_executing(tmp_path):
    import hashlib
    import installer_inputs as inputs
    import workload_jobs
    from test_installer_inputs import repository
    from test_baseline_web import _RealServerCase, _base_deps
    jobs=workload_jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    name='captured-update'
    folder=tmp_path/'bundles'/hashlib.sha256(b'root').hexdigest()/name
    inputs.prepare(repository(tmp_path/'source'),folder,plan={},settings={},recipe=None,
                   artifact_locks={},which=lambda name:'/bin/'+name)
    job=jobs.submit('installer','prepare_inputs',{'name':name},lambda:{'ok':True})
    jobs.wait(job['id'],5)
    case=_RealServerCase(_base_deps(workload_jobs=jobs,installer_bundle_root=tmp_path/'bundles',
        installed_update_discovery=lambda serial:'/dev/sdb',
        installed_update_recovery=lambda serial:tmp_path/'recovery',pds_runner=FakePdsRunner()))
    try:
        status,result=case.post_json('/install-plan/update',{'serial':'SYNTHDRIVEA00001','job_id':job['id']})
        assert status==200
        assert result['outcome']=='confirmation_required'
        assert 'REDEPLOY' in str(result)
        assert all(item['action']=='prepare_inputs' for item in jobs.listing())
    finally:
        case.close()


def test_confirmed_installer_update_is_durable_and_not_replayed(tmp_path):
    import hashlib
    import installer_inputs as inputs
    import workload_jobs
    from test_installer_inputs import repository
    from test_baseline_web import _RealServerCase, _base_deps, FakeSudoExecutor
    jobs=workload_jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    name='captured-update'
    folder=tmp_path/'bundles'/hashlib.sha256(b'root').hexdigest()/name
    inputs.prepare(repository(tmp_path/'source'),folder,plan={},settings={},recipe=None,
                   artifact_locks={},which=lambda name:'/bin/'+name)
    prep=jobs.submit('installer','prepare_inputs',{'name':name},lambda:{'ok':True})
    jobs.wait(prep['id'],5)
    executor=FakeSudoExecutor(stdout=b'{"state":"updated","boot_verified":false}\n')
    case=_RealServerCase(_base_deps(workload_jobs=jobs,installer_bundle_root=tmp_path/'bundles',
        installed_update_discovery=lambda serial:'/dev/sdb',installed_update_recovery=lambda serial:tmp_path/'recovery',
        pds_runner=FakePdsRunner(),pkexec_executor=executor))
    try:
        _,review=case.post_json('/install-plan/update',{'serial':'SYNTHDRIVEA00001','job_id':prep['id']})
        challenge=review['challenge']
        status,refused=case.post_json('/drive-admin/confirm',{'challenge_id':challenge['id'],
            'typed':challenge['phrase'],'secret':'wrong-test-secret'})
        assert status==403 and not executor.calls
        body={'challenge_id':challenge['id'],'typed':challenge['phrase'],'secret':'test-secret'}
        status,result=case.post_json('/drive-admin/confirm',body)
        assert status==200 and result['durable']
        assert jobs.wait(result['job_id'],5)['state']=='completed'
        assert len(executor.calls)==1
        status,_=case.post_json('/drive-admin/confirm',body)
        assert status==404 and len(executor.calls)==1
    finally:
        case.close()
    reopened=workload_jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    try:
        assert reopened.get(result['job_id'])['state']=='completed'
        assert len(executor.calls)==1
    finally:
        reopened.close()


def test_open_physical_volume_refuses_before_mount_or_provision(tmp_path):
    import json
    import pytest
    import installed_drive_update as update
    import installer_inputs as inputs
    from test_installer_inputs import repository
    bundle=tmp_path/'bundle'
    inputs.prepare(repository(tmp_path/'source'),bundle,plan={},settings={},recipe=None,
                   artifact_locks={},which=lambda name:'/bin/'+name)
    disk={'name':'/dev/sdb','type':'disk','serial':'SYNTHDRIVEA00001',
          'size':500000000000,'mountpoints':[None],
          'children':[{'name':'/dev/sdb3','type':'part','fstype':'LVM2_member','mountpoints':[None]}]}
    rows=[{'lv_name':'root','lv_attr':'-wi-ao----','lv_device_open':'open'}]
    rows += [{'lv_name':v[0],'lv_attr':'-wi-a-----','lv_device_open':''} for v in update.di.baseline_volumes_for()]
    runner=FakeRunner(command_responses=[
        (lambda a:a[0]=='id',FakeProc(0,'0\n')),
        (lambda a:a[0]=='lsblk',FakeProc(0,json.dumps({'blockdevices':[disk]}))),
        (lambda a:a[0]=='pvs',FakeProc(0,json.dumps({'report':[{'pv':[{
            'pv_name':'/dev/sdb3','pv_uuid':'pv','vg_name':'baseline_test','vg_uuid':'vg','pv_count':'1'}]}]}))),
        (lambda a:a[0]=='lvs',FakeProc(0,json.dumps({'report':[{'lv':rows}]}))),
    ])
    with pytest.raises(update.UpdateError,match='open'):
        update.update(runner,serial='SYNTHDRIVEA00001',input_bundle=bundle,
            recovery_folder=tmp_path/'recovery',root=tmp_path/'target',pds_runner=FakePdsRunner())
    assert not any(a[0] in ('mount','chroot','lvextend','mkfs.ext4','wipefs') for a in runner.calls)


def test_update_requires_all_reviewed_inputs():
    import pytest
    with pytest.raises(ValueError, match="missing"):
        da.validate_action_params('update_installed_drive', {'device_path':'/dev/sdb'})

def test_existing_source_symlink_cannot_redirect_privileged_copy(tmp_path):
    import pytest
    import installed_drive_update as update
    destination=tmp_path/'target'; destination.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    (destination/'nested').symlink_to(outside, target_is_directory=True)
    with pytest.raises(update.UpdateError,match='symlink'):
        update._require_plain_tree(destination)


def test_recovery_inspection_checks_current_device_and_journal(tmp_path, monkeypatch):
    import json
    import installed_drive_update as update
    bundle=tmp_path/'bundle';bundle.mkdir()
    journal=tmp_path/'bundle-update.json'
    journal.write_text(json.dumps({'format':'baseline.installed-drive-update/v1',
        'serial':'SYNTHDRIVEA00001','input_bundle':str(bundle),'state':'failed',
        'stages':['captured_source_staged'],'boot_verified':False}))
    observed=[]
    monkeypatch.setattr(update,'discover_path',lambda serial:observed.append(serial) or '/dev/sdc')
    result=update.inspect_update(bundle)
    assert observed==['SYNTHDRIVEA00001']
    assert result['available'] and 'failed' in result['message']
    assert 'boot' in result['message'].lower()


def test_automatic_continuation_prepares_owned_inputs_without_manual_draft(tmp_path):
    import hashlib
    import installer_inputs
    import workload_jobs
    from test_installer_inputs import repository
    from test_baseline_web import _RealServerCase, _base_deps
    jobs=workload_jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    calls=[]
    case=_RealServerCase(_base_deps(workload_jobs=jobs,installer_bundle_root=tmp_path/'bundles',
        installer_repo_root=repository(tmp_path/'source'),
        installed_update_discovery=lambda serial:calls.append(serial) or '/dev/sdb',
        installed_update_recovery=lambda serial:tmp_path/'recovery',pds_runner=FakePdsRunner()))
    try:
        status,result=case.post_json('/install-plan/continue',{'serial':'SYNTHDRIVEA00001','request_id':'automatic-update'})
        assert status==202
        job=jobs.wait(result['job_id'],10)
        assert job['state']=='completed' and calls==['SYNTHDRIVEA00001']
        folder=tmp_path/'bundles'/hashlib.sha256(b'root').hexdigest()/job['name']
        installer_inputs.verify(folder)
        status,review=case.post_json('/install-plan/update',{'serial':'SYNTHDRIVEA00001','job_id':job['id']})
        assert status==200 and review['outcome']=='confirmation_required'
        assert all(item['action']=='prepare_inputs' for item in jobs.listing())
    finally:
        case.close()


def test_native_update_request_cannot_execute_without_policykit(tmp_path):
    import pytest
    import hitl
    from hitl_helpers import perform_with_origin
    store=hitl.ConfirmationStore(verify_secret=lambda secret:False,min_wait_s=0)
    params={'device_path':'/dev/sdb','input_bundle':str(tmp_path/'bundle'),'recovery_folder':str(tmp_path/'recovery')}
    prepared=da.prepare_action('update_installed_drive',params,pds_runner=FakePdsRunner())
    challenge=store.challenge('owner','update_installed_drive',prepared['params'],prepared['serial'],prepared['summary'])
    with pytest.raises(hitl.ConfirmationError):store.request_native_update('another-owner',challenge['id'])
    authorization=store.request_native_update('owner',challenge['id'])
    runner=FakeRunner()
    result=perform_with_origin(runner,'update_installed_drive',params,pds_runner=FakePdsRunner(),
        authorization=authorization,hitl_store=store)
    assert not result.ok and 'policykit' in result.detail.lower()
    assert not runner.calls


def test_native_policykit_confirmation_supports_only_installed_update_and_partition_unmount():
    import pytest
    import hitl
    store=hitl.ConfirmationStore(verify_secret=lambda secret:False,min_wait_s=0)
    params={'device_path':'/dev/sdb','partition_mountpoint':'/mnt/sdb2'}
    challenge=store.challenge('owner','unmount_partition',params,'SYNTHDRIVEA00001','Unmount EFI')
    authorization=store.request_native_policykit('owner',challenge['id'])
    assert authorization._kind=='native_pending'
    assert authorization.valid_for('unmount_partition',params,'SYNTHDRIVEA00001')
    repair=store.challenge('owner','repair',{'device_path':'/dev/sdb'},'SYNTHDRIVEA00001','Repair')
    with pytest.raises(hitl.ConfirmationError):
        store.request_native_policykit('owner',repair['id'])


def test_drive_admin_native_partition_route_reaches_pkexec_only_after_review():
    import subprocess
    import time
    import baseline_web as bw
    from test_baseline_web import _RealServerCase,_base_deps
    class PolicyKitExecutor:
        def __init__(self): self.calls=[]
        def __call__(self,argv,*,input,capture_output,timeout):
            self.calls.append(list(argv)); command=argv[1:]
            output={"findmnt":b"/dev/sdb2\n", "lsblk":b"sdb\n",
                    "udevadm":b"ID_SERIAL_SHORT=SYNTHDRIVEA00001\n"}.get(command[0],b"")
            return subprocess.CompletedProcess(argv,0,output,b"")
    executor=PolicyKitExecutor()
    case=_RealServerCase(_base_deps(pds_runner=FakePdsRunner(serial='SYNTHDRIVEA00001'),pkexec_executor=executor))
    try:
        status,review=case.post_json('/drive-admin/action',{'action_id':'unmount_partition',
            'params':{'device_path':'/dev/sdb','partition_mountpoint':'/mnt/sdb2'}})
        assert status==200 and review['outcome']=='confirmation_required'
        status,started=case.post_json('/drive-admin/execute-native',{'challenge_id':review['challenge']['id']})
        assert status==200 and started['outcome']=='started'
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with bw._JOBS_LOCK: job=dict(bw._JOBS[started['job_id']])
            if job['done']: break
            time.sleep(.01)
        assert job['done'] and job['outcome'] == 'applied'
        assert executor.calls[-1]==['pkexec','umount','--','/mnt/sdb2']
        status,_=case.post_json('/drive-admin/execute-native',{'challenge_id':review['challenge']['id']})
        assert status==403 and len(executor.calls)==4
    finally: case.close()


def test_automatic_execution_uses_native_authorization_once(tmp_path):
    import workload_jobs
    from test_baseline_web import _RealServerCase,_base_deps,FakeSudoExecutor
    from test_installer_inputs import repository
    jobs=workload_jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    executor=FakeSudoExecutor(stdout=b'{"state":"updated","boot_verified":false}\n')
    case=_RealServerCase(_base_deps(workload_jobs=jobs,installer_bundle_root=tmp_path/'bundles',
        installer_repo_root=repository(tmp_path/'source'),installed_update_discovery=lambda serial:'/dev/sdb',
        installed_update_recovery=lambda serial:tmp_path/'recovery',pds_runner=FakePdsRunner(),pkexec_executor=executor))
    try:
        _,prep=case.post_json('/install-plan/continue',{'serial':'SYNTHDRIVEA00001','request_id':'native-update'})
        assert jobs.wait(prep['job_id'],5)['state']=='completed'
        _,review=case.post_json('/install-plan/update',{'serial':'SYNTHDRIVEA00001','job_id':prep['job_id']})
        status,result=case.post_json('/install-plan/execute-native',{'challenge_id':review['challenge']['id']})
        assert status==200 and result['durable']
        assert jobs.wait(result['job_id'],5)['state']=='completed'
        assert len(executor.calls)==1 and executor.calls[0][0][0]=='pkexec'
        status,_=case.post_json('/install-plan/execute-native',{'challenge_id':review['challenge']['id']})
        assert status==403 and len(executor.calls)==1
    finally:case.close()


def test_disposable_volume_growth_keeps_retained_storage_and_vg_reserve():
    import pytest
    import installed_drive_update as update
    gib=1024**3
    plan=update.baseline_growth_plan(8*gib,103*gib)
    assert plan=={'grow_bytes':42*gib,'target_bytes':50*gib,'remaining_vg_bytes':61*gib}
    assert update.baseline_growth_plan(50*gib,20*gib)['grow_bytes']==0
    with pytest.raises(update.UpdateError,match='reserve'):
        update.baseline_growth_plan(8*gib,45*gib)
