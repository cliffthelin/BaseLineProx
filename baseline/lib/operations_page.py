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
