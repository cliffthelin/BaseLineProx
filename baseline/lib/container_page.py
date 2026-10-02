"""Authenticated distro-container controls; no fabricated catalog or boot status."""
import html
import json
from pathlib import Path

import distro_containers as dc
import vm_host as vh
from vm_page import _CSS


def perform(host, action, params):
    try:
        name = str(params.get('name', ''))
        if action == 'create':
            return dict(host.create(name, template=params.get('template'), cache_storage=params.get('cache_storage'),
                                    os_storage=params.get('os_storage'), disk_gb=int(params.get('disk_gb', 8)),
                                    memory_mb=int(params.get('memory_mb', 512)), cpus=int(params.get('cpus', 1))), ok=True)
        if action == 'recover':
            if params.get('confirm') != 'yes':
                raise vh.VmError('confirm explicit rebuild recovery; retained data will be kept')
            return host.recover(name)
        if action == 'reset_login':
            if params.get('confirm') != 'yes':
                raise vh.VmError('confirm login reset; the old password will stop working')
            return host.reset_login(name)
        if action == 'rebuild':
            if params.get('confirm') != 'yes':
                raise vh.VmError('confirm OS rebuild; data directories will be kept')
            host.rebuild(name)
            return {'ok': True, 'message': 'OS clone rebuilt and started; retained data kept.'}
        if action == 'start':
            host.start(name)
        elif action == 'shutdown':
            host.shutdown(name)
        elif action == 'refresh':
            host.command(['pveam', 'update'])
        else:
            raise vh.VmError('unknown container action')
        return {'ok': True, 'message': 'Container action completed.'}
    except (vh.VmError, OSError, ValueError, TypeError) as exc:
        return {'ok': False, 'message': str(exc)}


def load_data(config):
    try:
        value = json.loads(Path(config).read_text()).get('container_data_store')
        return value if isinstance(value, str) and value.startswith('/') else dc.DEFAULT_DATA
    except (OSError, TypeError, ValueError, AttributeError):
        return dc.DEFAULT_DATA


def save_data(config, path):
    from vm_page import _FORBIDDEN_PREFIXES
    try:
        folder = Path(path)
        if '..' in folder.parts or any(str(folder) == p or str(folder).startswith(p+'/') for p in _FORBIDDEN_PREFIXES):
            raise vh.VmError('choose a separate protected data folder outside system paths')
        dc.DistroContainers(folder)._check_data()
        try:
            value = json.loads(Path(config).read_text())
        except (OSError, ValueError):
            value = {}
        value['container_data_store'] = str(folder)
        Path(config).parent.mkdir(parents=True, exist_ok=True)
        Path(config).write_text(json.dumps(value))
        return {'ok': True, 'message': 'Folder saved; existing containers and data were not moved.'}
    except (vh.VmError, OSError, TypeError, ValueError) as exc:
        return {'ok': False, 'message': str(exc)}


def render(host=None, unavailable=''):
    e = lambda value: html.escape(str(value), quote=True)
    if host is None:
        content = f'<p>{e(unavailable or "Proxmox LXC tools are unavailable on this host.")}</p>'
    else:
        templates = host.catalog()
        templates = [t for t in templates if not t['name'].startswith('openeuler-25.03-default_')]
        stores = host.storages()
        options = lambda items: ''.join(f'<option value="{e(x)}">{e(x)}</option>' for x in items)
        cards = []
        for ct in host.list_containers():
            name = ct['name']
            args = e(json.dumps({'name': name}))
            button = 'shutdown' if ct['running'] else 'start'
            rebuild = '' if ct['running'] else f'<button class="danger" onclick="act(\'rebuild\',{args},true)">Rebuild OS</button>'
            reset = f'<button onclick="act(\'reset_login\',{args},true)">Reset login</button>' if ct['running'] and ct['phase']=='ready' else ''
            recovery = ct.get('recovery')
            if recovery is not None:
                button = ''
                rebuild = (f'<button onclick="act(\'recover\',{args},true)">Recover rebuild</button>'
                           if recovery.get('recoverable') else '')
                state_label = recovery.get('native_state','unverified')
                controls = rebuild
                details = f'<p>{e(recovery.get("message",""))}</p>'
            else:
                state_label = 'running' if ct['running'] else 'stopped'
                controls = f'<button onclick="act(\'{button}\',{args})">{button.title()}</button> {rebuild} {reset}'
                details = ''
            cards.append(f'<div class="card"><strong>{e(name)}</strong> · CT {ct["vmid"]} · '
                         f'{e(state_label)} · {e(ct["phase"])}'
                         f'<p>{e(ct["template"])}<br>Retained data: {e(ct["data_path"])}</p>'
                         f'{details}{controls}</div>')
        missing = '<p class="warn">No active LVM-thin/ZFS container storage supports this linked-clone recipe.</p>' if not stores['overlay'] else ''
        content = f'''<p>LXC distributions share the host kernel. Their OS is a native linked clone of an immutable template.</p>
<p>Separate <code>/home</code>, <code>/root</code> and <code>/data</code> directories survive an OS rebuild.
Packages and system settings on the root filesystem reset. These bind directories are <strong>not included in vzdump</strong>;
separate backup/restore verification is still required. This is a Linux environment, not a preinstalled GUI/browser.</p>
<p><a href="/vms">Requested desktop, NAS and mobile systems: installer sources and VM status</a></p>
<p>openEuler 25.03 is disabled: its native Proxmox setup failed; a verified fix is pending.</p>
<button onclick="act('refresh',{{}})">Refresh Proxmox template catalog</button>
<p>{len(templates)} system templates available from this host. Availability does not mean every version has been boot-tested.</p>
{missing}<div class="card"><form class="row" onsubmit="submit(event,'create')">
<label>Name<input name="name" required pattern="[a-z0-9][a-z0-9-]{{0,31}}"></label>
<label>Distro template<select name="template">{options([t['name'] for t in templates])}</select></label>
<label>Vanilla template cache<select name="cache_storage">{options(stores['cache'])}</select></label>
<label>Disposable OS storage<select name="os_storage">{options(stores['overlay'])}</select></label>
<label>OS GiB<input name="disk_gb" type="number" min="2" max="128" value="8"></label>
<label>Memory MiB<input name="memory_mb" type="number" min="128" value="512"></label>
<label>CPUs<input name="cpus" type="number" min="1" value="1"></label>
<button class="go" {'disabled' if not templates or not stores['overlay'] or not stores['cache'] else ''}>Create linked container</button>
</form></div>{''.join(cards) or '<p>No Baseline distro containers yet.</p>'}
<h2>Protected data folder</h2><form class="row" onsubmit="submit(event,'set_data')">
<label>Folder<input name="data_store" value="{e(host.data_store)}" required></label><button>Save folder</button></form>
<p>Changing folders does not migrate data. Default unprivileged UID mapping is used; custom mappings are refused.</p>'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>Distro containers</title><style>{_CSS}</style></head>
<body><main><h1>Distro containers</h1><p><a href="/workloads">Workload jobs: return here after a disconnect</a></p><p id="status" role="status"></p>{content}
<dialog id="login"><h3>Save this one-time container login</h3><p id="username"></p><p id="password"></p>
<button onclick="location.reload()">I saved the login</button></dialog></main>
<script>
let busy=false;
async function act(action,params,confirmReset){{
 if(busy)return;
 if(confirmReset && !confirm(action==='recover'?'Finish the interrupted OS rebuild after ownership checks? Retained data is kept.':action==='reset_login'?'Replace the container login? The old password stops working; data is kept.':'Rebuild the stopped OS? Packages and system settings reset; /home, /root and /data are kept.'))return;
 busy=true;document.getElementById('status').textContent='Working… template preparation can take several minutes.';
 try{{
 const body=Object.assign({{action,request_id:crypto.randomUUID()}},params);if(confirmReset)body.confirm='yes';
 const r=await fetch('/containers/action',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
 let result=await r.json();
 if(r.status===202 && result.job_id){{
 const id=result.job_id;
 while(true){{await new Promise(resolve=>setTimeout(resolve,1000));
 const response=await fetch('/workloads/job?job_id='+encodeURIComponent(id));const job=await response.json();
 if(!response.ok)throw new Error(job.error || 'Job status unavailable');
 document.getElementById('status').textContent=job.state+': '+(job.result?.message || action);
 if(['completed','failed','interrupted','reviewed'].includes(job.state)){{
 const response=await fetch('/workloads/result',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{job_id:id}})}});
 result=await response.json();break;
 }}
 }}
 }}
 if(!r.ok || !result.ok)throw new Error(result.message || result.detail || 'Request failed');
 if(result.password){{document.getElementById('username').textContent='Username: '+result.username;
 document.getElementById('password').textContent='Password: '+result.password;document.getElementById('login').showModal();}}
 else location.reload();
 }}catch(error){{document.getElementById('status').textContent=error.message;busy=false;}}
}}
function submit(event,action){{event.preventDefault();act(action,Object.fromEntries(new FormData(event.target)));}}
</script></body></html>'''.encode()
