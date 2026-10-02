"""Read durable job state; recovery never runs a native mutation implicitly."""
import html
import json
from vm_page import _CSS


def render(jobs):
    cards=[]
    for job in jobs:
        result=job['result'] or {}
        jid=html.escape(job['id'])
        inspection=result.get('inspection',{})
        recovery=''
        if job['state'] in ('interrupted','failed'):
            recovery=f'''<button onclick="inspect('{jid}')">Inspect native state</button>
<button onclick="review('{jid}',{html.escape(json.dumps(job['name'] or job['action']),quote=True)})">Acknowledge inspected result</button>'''
        login=f'<button onclick="login(\'{jid}\')">Retrieve one-time login</button>' if result.get('login_available') else ''
        cards.append(f'''<div class="card"><strong>{html.escape(job['kind'])}: {html.escape(job['action'])} {html.escape(job['name'])}</strong>
<p>{html.escape(job['state'])} · {jid}</p><p>{html.escape(result.get('message','Native operation pending or running.'))}</p>
<p>{html.escape(inspection.get('message',''))}</p>{login}{recovery}</div>''')
    return f'''<!doctype html><html><head><title>Workload jobs</title><style>{_CSS}</style></head><body><main>
<h1>Workload jobs</h1><p>Saved progress and outcomes survive reconnects. Interrupted work is never automatically replayed.
Acknowledgement releases the job's reservation; it does not repair the workload or declare success.</p>
<p id="status" role="status"></p>{''.join(cards) or '<p>No workload jobs yet.</p>'}
<dialog id="login"><h3>Save this one-time login</h3><p id="username"></p><p id="password"></p><button onclick="location.reload()">I saved the login</button></dialog>
</main><script>
let busy=false;
async function post(path,body){{const r=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});const j=await r.json();if(!r.ok)throw new Error(j.message || j.error || j.detail);return j;}}
async function inspect(id){{busy=true;try{{await post('/workloads/inspect',{{job_id:id}});location.reload();}}catch(e){{document.getElementById('status').textContent=e.message;busy=false;}}}}
async function review(id,name){{const typed=prompt('Type '+name+' to acknowledge the inspected result. This does not retry or repair it.');if(typed===null)return;busy=true;try{{await post('/workloads/acknowledge',{{job_id:id,name:typed}});location.reload();}}catch(e){{document.getElementById('status').textContent=e.message;busy=false;}}}}
async function login(id){{busy=true;try{{const j=await post('/workloads/result',{{job_id:id}});if(!j.password)throw new Error(j.message || 'Login unavailable');document.getElementById('username').textContent=j.username;document.getElementById('password').textContent=j.password;document.getElementById('login').showModal();}}catch(e){{document.getElementById('status').textContent=e.message;busy=false;}}}}
setInterval(async()=>{{if(busy)return;try{{const r=await fetch('/workloads/jobs');const j=await r.json();if(JSON.stringify(j)!==initial)location.reload();}}catch(e){{}}}},3000);
const initial={json.dumps(json.dumps(jobs,separators=(',',':')))};
</script></body></html>'''.encode()
