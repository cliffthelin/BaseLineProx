import threading

import workload_jobs as jobs


def test_started_job_returns_immediately_deduplicates_and_keeps_result_after_reopen(tmp_path):
    started, release = threading.Event(), threading.Event()
    store = jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    def operation():
        started.set()
        assert release.wait(3)
        return {'ok': True, 'message': 'native operation finished', 'password': 'fresh-private-login'}
    job = store.submit('vm', 'create_iso', {'name': 'work'}, operation, request_id='same-request')
    assert started.wait(1)
    assert store.get(job['id'])['state'] == 'running'
    assert store.submit('vm', 'create_iso', {'name': 'work'}, operation, request_id='same-request')['id'] == job['id']
    release.set()
    store.wait(job['id'], 3)
    assert store.result(job['id']).get('password') == 'fresh-private-login'
    assert 'password' not in store.result(job['id'])
    store.close()
    reopened = jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    assert reopened.get(job['id'])['state'] == 'completed'
    assert b'fresh-private-login' not in (tmp_path/'jobs.sqlite').read_bytes()


def test_restart_records_interruption_blocks_replay_and_keeps_deduplication(tmp_path):
    import sqlite3
    path = tmp_path/'jobs.sqlite'
    store = jobs.WorkloadJobs(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO jobs VALUES ('lost','original','container','rebuild','{\"name\":\"work\"}','running',NULL,1,1)")
    store.close()
    restarted = jobs.WorkloadJobs(path)
    assert restarted.get('lost')['state'] == 'interrupted'
    assert restarted.submit('container','rebuild',{'name':'work'},lambda: {'ok':True},request_id='original')['id']=='lost'
    import pytest
    with pytest.raises(jobs.JobError, match='inspection'):
        restarted.submit('vm','create_iso',{'name':'other'},lambda: {'ok':True})


def test_arbitrary_secrets_cannot_be_persisted_as_job_parameters(tmp_path):
    import pytest
    store = jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    with pytest.raises(jobs.JobError, match='parameter'):
        store.submit('vm','create_iso',{'name':'work','password':'private'},lambda:{'ok':True})
    assert store.listing()==[]


def test_interrupted_inspection_and_acknowledgement_never_rerun_native_operation(tmp_path):
    import sqlite3
    import pytest
    path = tmp_path/'jobs.sqlite'
    store = jobs.WorkloadJobs(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO jobs VALUES ('lost','original','container','rebuild','{\"name\":\"work\"}','running',NULL,1,1)")
    store.close()
    store=jobs.WorkloadJobs(path)
    with pytest.raises(jobs.JobError,match='inspect'):
        store.acknowledge('lost','work')
    store.inspect('lost',{'available':True,'message':'native container stopped; phase ready'})
    store.acknowledge('lost','work')
    assert store.get('lost')['state']=='reviewed'
    assert not store.get('lost')['result']['ok']
    assert not store.threads


def test_actual_reported_stage_is_durable_and_secondary_secret_fields_are_excluded(tmp_path):
    store=jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    seen=[]
    def operation(report):
        report('Native command: pct clone')
        seen.append(store.listing()[0]['result']['message'])
        return {'ok':True,'message':'finished','password_hash':'must-not-store'}
    job=store.submit('container','create',{'name':'work'},operation,with_progress=True)
    store.wait(job['id'],3)
    assert seen==['Native command: pct clone']
    assert b'must-not-store' not in (tmp_path/'jobs.sqlite').read_bytes()


def test_backend_context_survives_restart_for_inspection_of_original_storage(tmp_path):
    path=tmp_path/'jobs.sqlite'
    store=jobs.WorkloadJobs(path)
    context={'backend':'ProxmoxVmHost','store':'/external/os','persistence_store':'/external/users'}
    job=store.submit('vm','start',{'name':'work'},lambda:{'ok':True},context=context)
    store.wait(job['id'],3)
    store.close()
    restarted=jobs.WorkloadJobs(path)
    assert restarted.get(job['id'])['context']==context


def test_restart_keeps_last_observed_native_stage_and_second_service_cannot_take_over(tmp_path):
    import sqlite3
    import pytest
    path=tmp_path/'jobs.sqlite'
    store=jobs.WorkloadJobs(path)
    with pytest.raises(jobs.JobError,match='another service'):
        jobs.WorkloadJobs(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO jobs VALUES ('lost','original','container','rebuild','{\"name\":\"work\"}','running','{\"message\":\"Native command: pct clone\"}',1,1)")
    store.close()
    restarted=jobs.WorkloadJobs(path)
    assert restarted.get('lost')['result']['last_observed_stage']=='Native command: pct clone'


def test_ubuntu_locale_and_configuration_verification_report_survive_job_restart(tmp_path):
    path=tmp_path/'jobs.sqlite'
    store=jobs.WorkloadJobs(path)
    report={'checks':{'locale':True},'configuration_applied':True,'browser_page_loaded':False}
    job=store.submit('vm','verify_ubuntu',{'name':'desktop','locale':'en_GB.UTF-8'},
        lambda:{'ok':True,'message':'Configuration checked','configuration_report':report})
    assert store.wait(job['id'],3)['result']['configuration_report']==report
    store.close()
    restarted=jobs.WorkloadJobs(path)
    try:assert restarted.get(job['id'])['result']['configuration_report']==report
    finally:restarted.close()


def test_the_parameters_the_launcher_sends_for_a_ready_made_vm_are_accepted_by_the_job_store(tmp_path):
    """Found on the rehearsal's real web service: the launcher posts name, os, memory_mb and cpus; the store refused `os`."""
    store = jobs.WorkloadJobs(tmp_path/'jobs.sqlite')
    job = store.submit('vm', 'create_prebuilt', {'name': 'ready-debian', 'os': 'debian', 'memory_mb': 4096, 'cpus': 2}, lambda: {'ok': True, 'message': 'made'})
    store.wait(job['id'], 3)
    assert store.result(job['id'])['ok'] is True
    store.close()
