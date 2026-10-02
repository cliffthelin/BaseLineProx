"""Durable workload outcomes. Interrupted mutations are never automatically replayed.

Native operations execute in a worker; SQLite records survive web restarts.
Passwords are held only in memory for one authenticated retrieval, never SQLite.
One workload mutation runs at a time to protect shared VMID/storage allocation.
"""
import fcntl
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class JobError(ValueError):
    pass


class WorkloadJobs:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lease = open(str(self.path) + '.lock', 'a')
        os.chmod(str(self.path) + '.lock', 0o600)
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close()
            raise JobError('workload jobs are already owned by another service') from None
        self.lock = threading.RLock()
        self.threads = {}
        self.secrets = {}
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request TEXT UNIQUE, kind TEXT, action TEXT, params TEXT, state TEXT, result TEXT, created REAL, updated REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS contexts (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
            interrupted=list(db.execute("SELECT id,result FROM jobs WHERE state IN ('queued','running')"))
            for row in interrupted:
                prior=json.loads(row['result']) if row['result'] else {}
                result={'ok':False,'message':'Service restarted during this operation. Inspect native state; nothing was replayed.',
                        'last_observed_stage':prior.get('message','Queued; no native stage recorded')}
                db.execute("UPDATE jobs SET state='interrupted',result=?,updated=? WHERE id=?",
                           (json.dumps(result),time.time(),row['id']))
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def submit(self, kind, action, params, operation, *, request_id=None, with_progress=False, context=None):
        context=context or {}
        if set(context)-{'backend','store','persistence_store','data_store'} or any(not isinstance(v,str) for v in context.values()):
            raise JobError('unsupported backend context')
        allowed = {'name','template','cache_storage','os_storage','disk_gb','memory_mb','cpus','recipe','homepage',
                   'persistence_gb','iso','base','base_name','display','firmware','confirm'}
        if not isinstance(params, dict) or set(params) - allowed or any(not isinstance(v, (str,int,float,bool)) for v in params.values()):
            raise JobError('unsupported workload job parameter')
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id,str) or not 1 <= len(request_id) <= 128:
            raise JobError('invalid request ID')
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM jobs WHERE request=?', (request_id,)).fetchone()
            if old:
                if (old['kind'], old['action'], json.loads(old['params'])) != (kind, action, params):
                    raise JobError('request ID already belongs to a different operation')
                return self._public(old)
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','interrupted')").fetchone():
                raise JobError('another workload job needs completion or inspection first')
            job_id = uuid.uuid4().hex
            now = time.time()
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                       (job_id, request_id, kind, action, json.dumps(params), 'queued', None, now, now))
            db.execute('INSERT INTO contexts VALUES (?,?)',(job_id,json.dumps(context)))
        thread = threading.Thread(target=self._run, args=(job_id, operation, with_progress), daemon=True)
        self.threads[job_id] = thread
        thread.start()
        return self.get(job_id)

    def _run(self, job_id, operation, with_progress):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?", (time.time(), job_id))
        try:
            def report(message):
                with self.connect() as db:
                    db.execute('UPDATE jobs SET result=?,updated=? WHERE id=?',
                               (json.dumps({'ok':False,'message':message}),time.time(),job_id))
            result = operation(report) if with_progress else operation()
            password = result.pop('password', None)
            if password:
                with self.lock:
                    self.secrets[job_id] = {'password': password, 'username': result.get('username')}
                result['login_available'] = True
            result = {k:v for k,v in result.items() if k in ('ok','message','username','name','login_available')}
            state = 'completed' if result.get('ok') else 'failed'
        except Exception:
            # Native exceptions can contain sensitive command output. Never persist it.
            result = {'ok': False, 'message': 'Operation raised an error; inspect workload state before retrying.'}
            state = 'failed'
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE id=?',
                       (state, json.dumps(result), time.time(), job_id))

    def _public(self, row):
        with self.connect() as db:
            context=db.execute('SELECT value FROM contexts WHERE id=?',(row['id'],)).fetchone()
        return {'id': row['id'], 'kind': row['kind'], 'action': row['action'],
                'name': json.loads(row['params']).get('name', ''), 'state': row['state'],
                'created': row['created'], 'updated': row['updated'], 'context':json.loads(context['value']) if context else {},
                'result': json.loads(row['result']) if row['result'] else None}

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise JobError('unknown workload job')
        return self._public(row)

    def listing(self):
        with self.connect() as db:
            return [self._public(row) for row in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100')]

    def result(self, job_id):
        job = self.get(job_id)
        result = dict(job['result'] or {})
        with self.lock:
            secret = self.secrets.pop(job_id, None)
        if secret:
            result.update(secret)
        elif result.get('login_available'):
            result['message'] = result.get('message', '') + ' Login was already retrieved or lost on service restart; credential recovery is required.'
        return result

    def wait(self, job_id, timeout):
        thread = self.threads.get(job_id)
        if thread:
            thread.join(timeout)
        return self.get(job_id)


    def close(self):
        for thread in self.threads.values():
            thread.join(10)
        if any(thread.is_alive() for thread in self.threads.values()):
            raise JobError('cannot release ownership while a workload job is running')
        self.lease.close()

    def inspect(self, job_id, observation):
        with self.lock, self.connect() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row is None or row['state'] not in ('interrupted','failed'):
                raise JobError('only interrupted or failed jobs need inspection')
            result=json.loads(row['result'])
            result['inspection']=observation
            db.execute('UPDATE jobs SET result=?,updated=? WHERE id=?',(json.dumps(result),time.time(),job_id))
        return self.get(job_id)

    def acknowledge(self, job_id, name):
        with self.lock, self.connect() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row is None or row['state'] not in ('interrupted','failed'):
                raise JobError('only interrupted or failed jobs can be reviewed')
            result=json.loads(row['result'])
            if not result.get('inspection',{}).get('available'):
                raise JobError('inspect native state before acknowledging')
            expected=json.loads(row['params']).get('name','') or row['action']
            if name != expected:
                raise JobError('type the exact workload name or action to acknowledge')
            db.execute("UPDATE jobs SET state='reviewed',updated=? WHERE id=?",(time.time(),job_id))
        return self.get(job_id)
