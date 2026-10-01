"""The Operations page: run a backup (or a check) now, in the background, or on a schedule. Everything here goes
through the web application's own signed requests (web_gate.py); the page only offers buttons."""
from __future__ import annotations

import html


def render_operations_page(operations: dict, schedules: list) -> bytes:
    by_op = {s["op"]: s for s in schedules}
    cards = []
    for op in operations.values():
        sched = by_op.get(op.op_id)
        toggles = "".join(
            f'<label class="op-flag"><input type="checkbox" data-param="{html.escape(name)}"> {html.escape(name.replace("_", " "))}</label>'
            for name in op.params)
        schedule = ""
        if op.schedulable:
            current = (f'Scheduled every {html.escape(str(sched["every_hours"]))} h '
                       f'<button type="button" data-remove="{html.escape(op.op_id)}">Remove schedule</button>'
                       if sched else "Not scheduled")
            schedule = (f'<div class="op-schedule"><span>{current}</span> '
                        f'<label>Every <input type="number" min="1" max="8760" value="24" data-every> hours</label> '
                        f'<button type="button" data-schedule="{html.escape(op.op_id)}">Set schedule</button></div>')
        cards.append(
            f'<section class="op-card" data-op="{html.escape(op.op_id)}"><h2>{html.escape(op.op_id.replace("_", " "))}</h2>'
            f'<p>{html.escape(op.description)}</p>{toggles}'
            f'<button type="button" data-run="{html.escape(op.op_id)}">Run now</button>{schedule}</section>')
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Operations</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:56rem;padding:1rem}}
.op-card{{border:1px solid #8886;border-radius:8px;padding:1rem;margin:1rem 0}}
.op-flag{{margin-right:1rem}} button{{padding:.4rem .8rem}} .op-schedule{{margin-top:.8rem}}
#op-log{{white-space:pre-wrap;background:#1114;padding:.8rem;border-radius:6px;min-height:4rem}}
</style></head><body><h1>Operations</h1>
<p>Run now, or set a schedule. Each run is added to the log below. Backups only ever add files to the backup drive.</p>
{''.join(cards)}<h2>Log</h2><pre id="op-log">Nothing has run yet.</pre>
<script>
const log = document.getElementById('op-log');
async function post(path, body) {{
  const r = await fetch(path, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}});
  return [r.status, await r.json()];
}}
async function poll(jobId) {{
  for (;;) {{
    const r = await fetch('/drive-admin/job-log?job_id=' + encodeURIComponent(jobId));
    const j = await r.json();
    log.textContent = (j.lines || []).join('\\n') || 'Running...';
    if (j.done) {{ log.textContent += '\\n[' + j.outcome + '] ' + (j.detail || ''); return; }}
    await new Promise(res => setTimeout(res, 1500));
  }}
}}
function params(card) {{
  const p = {{}};
  card.querySelectorAll('input[data-param]').forEach(i => p[i.dataset.param] = i.checked);
  return p;
}}
document.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {{
  const card = b.closest('.op-card');
  const [s, j] = await post('/operations/run', {{op: b.dataset.run, params: params(card)}});
  if (j.job_id) {{ log.textContent = 'Started...'; poll(j.job_id); }} else log.textContent = j.detail || 'Refused';
}});
document.querySelectorAll('[data-schedule]').forEach(b => b.onclick = async () => {{
  const card = b.closest('.op-card');
  const [s, j] = await post('/operations/schedule', {{op: b.dataset.schedule, params: params(card),
      every_hours: Number(card.querySelector('[data-every]').value)}});
  if (j.outcome === 'applied') location.reload(); else log.textContent = j.detail || 'Refused';
}});
document.querySelectorAll('[data-remove]').forEach(b => b.onclick = async () => {{
  await post('/operations/schedule/remove', {{op: b.dataset.remove}}); location.reload();
}});
</script></body></html>"""
    return body.encode()


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
