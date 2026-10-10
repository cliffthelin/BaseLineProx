"""The Operations page: run a backup (or a check) now, in the background, or on a schedule. Everything here goes
through the web application's own signed requests (web_gate.py); the page only offers buttons."""
from __future__ import annotations

import html


def render_operations_page(operations: dict, schedules: list, alerts: list | None = None,
                           history: list | None = None, history_error: str | None = None) -> bytes:
    import json
    import time
    def when(value):
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(value)) if isinstance(value, (int, float)) else 'Never run'
    banner = ''.join(f'<p role="alert"><strong>Integrity alert:</strong> {html.escape(str(a.get("detail", "")))}</p>' for a in (alerts or []))
    history_status = (f'<p role="alert">Run history unavailable: {html.escape(history_error)}</p>'
                      if history_error else '')
    choices = ''.join(f'<option value="{html.escape(op.op_id, quote=True)}">{html.escape(op.op_id.replace("_", " "))}</option>' for op in operations.values())
    records = {op.op_id: {'description': op.description, 'params': op.params, 'schedulable': op.schedulable} for op in operations.values()}
    encoded = json.dumps(records).replace('<', '\\u003c')
    rows = ''.join(f'<tr><td>{html.escape(str(s["op"]).replace("_", " "))}</td><td>{s["every_hours"]} h</td><td>{html.escape(when(s.get("last_run")))}</td><td><button type="button" data-remove="{html.escape(str(s["op"]), quote=True)}">Remove</button></td></tr>' for s in schedules)
    history_rows = ''.join(f'<tr><td>{html.escape(when(r.get("started")))}</td><td>{html.escape(str(r.get("op", "")).replace("_", " "))}</td><td>{html.escape(str(r.get("source", "unknown")))}</td><td>{html.escape(str(r.get("outcome", "completion unknown")))}</td><td>{html.escape(str(r.get("detail", "")))}</td></tr>' for r in (history or []))
    if history_error and not history_rows:
        history_rows = '<tr><td colspan="5">History unavailable.</td></tr>'
    page = """<!doctype html><html><head><meta charset="utf-8"><title>Operations</title>
<style>body{font:15px/1.5 system-ui;max-width:65rem;margin:auto;padding:1rem}.op-card{border:1px solid #33364a;border-radius:8px;padding:1rem;margin:1rem 0}label{display:inline-flex;align-items:center;gap:.5rem;margin:.4rem 1rem .4rem 0}input[type=number]{width:8ch}pre{white-space:pre-wrap;overflow-wrap:anywhere}.op-flag{margin-right:1rem}</style></head><body>
<h1>Operations</h1>__BANNER__
<section class="op-card"><label for="operation-choice">Action</label><select id="operation-choice">__CHOICES__</select>
<p id="operation-description"></p><div id="operation-params"></div>
<button type="button" id="operation-run">Run now</button>
<div id="operation-scheduling"><label>Repeat every <input id="operation-every" type="number" min="1" max="8760" value="24"> hours</label>
<button type="button" id="operation-schedule">Set schedule</button><details><summary aria-label="About schedules">ⓘ</summary><p>A schedule runs this action with these choices at the selected interval. Run now starts one immediate run. An existing schedule for this action is replaced when you set it again.</p></details></div>
<p id="operation-status" role="status" aria-live="polite"></p></section>
<h2>Schedules</h2><table id="operation-schedules"><thead><tr><th>Action</th><th>Interval</th><th>Last started</th><th></th></tr></thead><tbody>__SCHEDULES__</tbody></table>
<h2>Run history</h2>__HISTORY_STATUS__<table id="operation-history"><thead><tr><th>Started</th><th>Action</th><th>Trigger</th><th>Result</th><th>Details</th></tr></thead><tbody>__HISTORY__</tbody></table>
<h2>Current run output</h2><pre id="op-log">Select an action to run or schedule.</pre>
<script id="operation-data" type="application/json">__DATA__</script>
<script>
const specs=JSON.parse(document.getElementById('operation-data').textContent);
const choice=document.getElementById('operation-choice'),log=document.getElementById('op-log'),status=document.getElementById('operation-status');
const paramBox=document.getElementById('operation-params');
function selected(){return specs[choice.value];}
function show(){const spec=selected();if(!spec)return;
 document.getElementById('operation-description').textContent=spec.description;paramBox.replaceChildren();
 for(const [name,value] of Object.entries(spec.params)){const label=document.createElement('label'),input=document.createElement('input');
 input.type='checkbox';input.checked=value;input.dataset.param=name;label.append(input,document.createTextNode(name.replaceAll('_',' ')));paramBox.append(label);}
 document.getElementById('operation-scheduling').hidden=!spec.schedulable;
 document.getElementById('operation-run').disabled=false;status.textContent='';}
function params(){const result={};for(const input of paramBox.querySelectorAll('[data-param]'))result[input.dataset.param]=input.checked;return result;}
async function post(path,body){const response=await fetch(path,{method:'POST',credentials:'same-origin',referrerPolicy:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(!(response.headers.get('Content-Type')||'').includes('application/json'))throw Error('Log in again');
 const result=await response.json();if(!response.ok)throw Error(result.detail||result.error||'Request refused');return result;}
async function refreshHistory(){const response=await fetch('/operations/history');if(!response.ok)throw Error('Run history unavailable');
 const result=await response.json();const rows=document.querySelector('#operation-history tbody');rows.replaceChildren();
 for(const run of result.runs){const row=document.createElement('tr');for(const value of [run.started?new Date(run.started*1000).toLocaleString():'Unknown',run.op.replaceAll('_',' '),run.source,run.outcome,run.detail]){const cell=document.createElement('td');cell.textContent=value||'';row.append(cell);}rows.append(row);}}
async function poll(id){for(;;){const response=await fetch('/drive-admin/job-log?job_id='+encodeURIComponent(id));if(!response.ok)throw Error('Run output unavailable; inspect run history');
 const job=await response.json();log.textContent=(job.lines||[]).join('\\n')||'Running…';
 if(job.done){log.textContent+='\\n['+job.outcome+'] '+(job.detail||'');await refreshHistory();return;}await new Promise(resolve=>setTimeout(resolve,1500));}}
choice.onchange=show;show();
document.getElementById('operation-run').onclick=async()=>{const button=document.getElementById('operation-run');button.disabled=true;
 try{const result=await post('/operations/run',{op:choice.value,params:params()});status.textContent='Run started';await refreshHistory();await poll(result.job_id);}
 catch(error){status.textContent=error.message;}finally{button.disabled=false;}};
document.getElementById('operation-schedule').onclick=async()=>{const hours=document.getElementById('operation-every');if(!hours.reportValidity())return;
 try{await post('/operations/schedule',{op:choice.value,params:params(),every_hours:Number(hours.value)});location.reload();}catch(error){status.textContent=error.message;}};
for(const button of document.querySelectorAll('[data-remove]'))button.onclick=async()=>{try{await post('/operations/schedule/remove',{op:button.dataset.remove});location.reload();}catch(error){status.textContent=error.message;}};
setInterval(()=>refreshHistory().catch(error=>{status.textContent=error.message;}),10000);
</script></body></html>"""
    return (page.replace('__BANNER__', banner).replace('__HISTORY_STATUS__', history_status).replace('__CHOICES__', choices)
            .replace('__SCHEDULES__', rows or '<tr><td colspan="4">No schedules configured.</td></tr>')
            .replace('__HISTORY__', history_rows or '<tr><td colspan="5">No recorded runs.</td></tr>')
            .replace('__DATA__', encoded)).encode()


def render_operators_page(accounts: dict, actions: list | None = None) -> bytes:
    """`accounts`: name -> role ("operator" or "bot:<action>"). `actions`: action ids a bot may be limited to."""
    if actions is None:
        import drive_admin
        import operations
        actions = sorted(set(operations.OPERATIONS) | set(drive_admin.ACTIONS))
    options = '<option value="operator">operator (all operations)</option>' + "".join(
        f'<option value="bot:{html.escape(a)}">bot: {html.escape(a)} only</option>' for a in actions)
    rows = "".join(
        f'<li>{html.escape(n)} <em>({html.escape(str(r))})</em> '
        f'<button type="button" data-remove="{html.escape(n)}">Remove</button></li>' for n, r in sorted(accounts.items())
    ) or "<li>No operator accounts yet.</li>"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Operator accounts</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:44rem;padding:1rem}}
label{{display:block;margin:.6rem 0}} input{{padding:.4rem;width:100%;box-sizing:border-box}} button{{padding:.4rem .8rem}}
#msg{{margin-top:1rem}}</style></head><body><h1>Operator accounts</h1>
<p>A bot account may do exactly one action and nothing else. An operator can run, schedule and watch backups on the Operations page and nothing else: no settings, no recovery,
no drive actions, and never a confirmation. Adding or removing one needs this machine's root password or passphrase.
Passwords are stored only as salted one-way hashes.</p>
<ul>{rows}</ul>
<h2>Add an operator</h2>
<form id="add" autocomplete="off">
<label>Name <input name="username" required pattern="[a-z][a-z0-9_-]{{2,31}}"></label>
<label>Role <select name="role">{options}</select></label>
<label>Password for this operator (12+ characters) <input name="password" type="password" required minlength="12" autocomplete="new-password"></label>
<label>Your root password or passphrase <input name="secret" type="password" required autocomplete="off"></label>
<button type="submit">Add operator</button></form><div id="msg"></div>
<script>
const msg = document.getElementById('msg');
async function post(path, body) {{
  const r = await fetch(path, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}});
  return [r.status, await r.json()];
}}
document.getElementById('add').onsubmit = async (e) => {{
  e.preventDefault();
  const f = new FormData(e.target);
  const [s, j] = await post('/operators/add', Object.fromEntries(f));
  if (j.outcome === 'applied') location.reload(); else msg.textContent = j.detail || 'Refused';
}};
document.querySelectorAll('[data-remove]').forEach(b => b.onclick = async () => {{
  const secret = prompt('Your root password or passphrase, to remove ' + b.dataset.remove);
  if (!secret) return;
  const [s, j] = await post('/operators/remove', {{username: b.dataset.remove, secret}});
  if (j.outcome === 'applied') location.reload(); else msg.textContent = j.detail || 'Refused';
}});
</script></body></html>"""
    return page.encode()


def render_audit_page(records: list, error: str | None = None) -> bytes:
    import time
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("ts", 0))) if isinstance(r.get("ts"), (int, float)) else ""),
            html.escape(str(r.get("event", ""))),
            html.escape(", ".join(f"{k}={v}" for k, v in sorted(r.items()) if k not in ("ts", "event"))))
        for r in records) or ('<tr><td colspan="3">Audit history unavailable.</td></tr>' if error
                             else '<tr><td colspan="3">No events recorded yet.</td></tr>')
    error_notice = f'<p role="alert">Audit log unavailable: {html.escape(error)}</p>' if error else ''
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Audit</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;margin:0 auto;max-width:70rem;padding:1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border-top:1px solid #8884;padding:.35rem .5rem;text-align:left;vertical-align:top}}</style>
</head><body><h1>Audit</h1><p>The most recent events, newest first. Read-only; secrets are never recorded.</p>{error_notice}
<table><tr><th>When</th><th>Event</th><th>Details</th></tr>{rows}</table></body></html>"""
    return page.encode()


def render_approvals_page(daily: list) -> bytes:
    rows = "".join(
        f'<tr><td>{html.escape(d["account"])}</td><td>{html.escape(d["action"])}</td>'
        f'<td>{html.escape(d["serial"][-6:])}</td><td>{html.escape(d["day"])}</td>'
        f'<td><button type="button" data-revoke="{html.escape(d["id"])}">Revoke</button></td></tr>' for d in daily
    ) or '<tr><td colspan="5">No daily authorizations right now.</td></tr>'
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Approvals</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:56rem;padding:1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border-top:1px solid #8884;padding:.4rem .5rem;text-align:left}}</style>
</head><body><h1>Approvals</h1>
<p>A bot account you authorized for today may run that one action on that one drive without asking again until the
day ends. Revoke one here and it must be confirmed again. Revoking needs no password.</p>
<table><tr><th>Account</th><th>Action</th><th>Drive (last 6)</th><th>Day</th><th></th></tr>{rows}</table>
<script>
document.querySelectorAll('[data-revoke]').forEach(b => b.onclick = async () => {{
  await fetch('/approvals/daily/revoke', {{method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{id: b.dataset.revoke}})}});
  location.reload();
}});
</script></body></html>"""
    return page.encode()


def render_remote_access_page(status: dict, configuration=None) -> bytes:
    import settings_web
    import structured_controls
    sections = []
    for section, key, label in (('ssh','password_auth','SSH password authentication'),
                                 ('firewall','allow_lan_only','Restrict inbound access to the LAN')):
        if configuration is None or key not in configuration.get(section, {}):
            sections.append(f'<p>{label}: configured value unavailable.</p>')
            continue
        value = configuration[section][key]
        default = settings_web._DEFAULT_SETTINGS_SECTIONS[section][key]
        help_text = ('Disabled permits key-based SSH authentication; enabling permits password authentication too.'
                     if section == 'ssh' else 'Enabled applies the established LAN-scoped firewall policy. Disabling requests a policy change; unsupported changes are refused, not saved as applied.')
        sections.append(f'<form method="post" action="/settings/{section}" data-autosave>'
            f'<label>{label} {settings_web.render_field_input(key,value)}</label>'
            f'<details class="field-info"><summary aria-label="About {label}">ⓘ</summary><p>{help_text}</p></details>'
            f'<p>Default: {"enabled" if default else "disabled"}. Configured: {"enabled" if value else "disabled"}.</p>'
            '<span role="status" data-save-status aria-live="polite"></span></form>')
    def yn(v):
        return "unknown" if v is None else ("on" if v else "off")
    listening_available = status.get("listening_available", True)
    ports = ("".join(f"<li>{html.escape(p['address'])}</li>" for p in status.get("listening", [])) or "<li>none found</li>")
    if not listening_available:
        ports = "<li>Listener inventory unavailable</li>"
    observation_errors = "".join(
        f'<p role="alert" class="ra-warn">Observation unavailable: {html.escape(error)}</p>'
        for error in status.get("observation_errors", []))
    warns = "".join(f'<p role="alert" class="ra-warn">{html.escape(w)}</p>' for w in status.get("warnings", []))
    ts = status.get("tailscale", {})
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Remote access</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:44rem;padding:1rem}}
.ra-warn{{border:2px solid #c80;padding:.6rem;border-radius:6px}}</style></head><body><h1>Remote access</h1>
<h2>Configuration</h2>
<p>These are the stored Baseline choices. Changes apply through the existing SSH and firewall mechanisms and save only on success.</p>
{''.join(sections)}
<h3>Tailscale</h3><p>Tailscale has no stored Baseline configuration policy. Its current connection is reported below; it is not inferred from the SSH or firewall choices.</p>
<details><summary>Observed results</summary>{warns}{observation_errors}
<ul><li>SSH: <strong>{yn(status.get("ssh", {}).get("active"))}</strong></li>
<li>Tailscale address: <strong>{html.escape(str(ts.get("ip") or "none"))}</strong>,
other devices on the tailnet: <strong>{html.escape(str(ts.get("peers") if ts.get("peers") is not None else "unknown"))}</strong></li></ul>
<h2>Listening on</h2><ul>{ports}</ul></details>{structured_controls.script()}</body></html>"""
    return page.encode()
