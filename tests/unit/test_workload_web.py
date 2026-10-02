import json
from test_vm_web import _case


def test_admin_has_persistent_workload_job_page_and_submit_poll_result_routes(tmp_path):
    case, fake, _ = _case(tmp_path,wait_jobs=False)
    try:
        assert case.get('/workloads')[0] == 200
        status, job = case.post_json('/vms/action', {'action':'create_iso','name':'durable','iso':'ubuntu.iso',
                                                    'disk_gb':10,'memory_mb':2048,'cpus':2,'request_id':'first'})
        assert status == 202 and job['job_id']
        store = case.server.deps['workload_jobs']
        store.wait(job['job_id'],3)
        status, body = case.get('/workloads/job?job_id='+job['job_id'])
        assert status == 200 and json.loads(body)['state']=='completed'
        assert case.post_json('/workloads/result',{'job_id':job['job_id']})[1]['ok']
        assert case.post_json('/vms/action', {'action':'create_iso','name':'durable','iso':'ubuntu.iso',
                            'disk_gb':10,'memory_mb':2048,'cpus':2,'request_id':'first'})[1]['job_id']==job['job_id']
    finally:
        case.close()


def test_slow_native_operation_does_not_block_web_and_conflicting_work_is_refused(tmp_path):
    import threading
    case,fake,_=_case(tmp_path,wait_jobs=False)
    started,release=threading.Event(),threading.Event()
    original=fake.host.create_from_iso
    def slow(*args,**kwargs):
        started.set()
        assert release.wait(3)
        return original(*args,**kwargs)
    fake.host.create_from_iso=slow
    try:
        status,result=case.post_json('/vms/action',{'action':'create_iso','name':'slow','iso':'ubuntu.iso',
                    'disk_gb':10,'memory_mb':2048,'cpus':2,'request_id':'slow-request'})
        assert status==202 and started.wait(1)
        assert case.get('/workloads')[0]==200
        assert case.get('/workloads/jobs')[0]==200
        assert case.post_json('/vms/action',{'action':'start','name':'other'})[0]==409
        assert case.post_json('/vms/action',{'action':'set_store','store':str(tmp_path/'different')})[0]==409
    finally:
        release.set()
        case.close()


def test_job_pages_and_secret_results_are_admin_only(tmp_path):
    case,_,_=_case(tmp_path,role='operator',wait_jobs=False)
    try:
        for path in ('/workloads','/workloads/jobs','/workloads/job?job_id=x'):
            assert case.get(path)[0]==403
        assert case.post_json('/workloads/result',{'job_id':'x'})[0]==403
    finally:
        case.close()
