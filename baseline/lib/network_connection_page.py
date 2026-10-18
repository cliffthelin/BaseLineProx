"""Console page for one network connection: what it is, its name, power and role (the TUI's connection dialog)."""
from __future__ import annotations

import html


def render(ifname: str, friendly: str, identity: list, status_line: str, alias: str, admin_up, pref: dict, lifeline: str, *, is_active: bool, notice: str = "") -> bytes:
    e = html.escape
    power_known = admin_up is not None
    role = "primary" if pref.get("primary") == ifname else ("fallback" if pref.get("fallback") == ifname else "")
    warn = ('<p class="adv-note" role="note">This connection carries your current internet access. Switching it off will disconnect this page.</p>' if is_active else "")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(friendly)}</title>
<style>body{{font:15px/1.55 system-ui,sans-serif;margin:0 auto;max-width:46rem;padding:1rem}}label{{display:block;margin:.6rem 0}}pre{{white-space:pre-wrap}}input[type=text]{{padding:.4rem;width:20rem;max-width:100%}}</style></head><body>
<h1>{e(friendly)}</h1><p><a href="/network">Back to network</a></p>{('<p role="status">' + e(notice) + '</p>') if notice else ''}
<pre class="adv">{e(chr(10).join(identity))}</pre><p>{e(status_line)}</p>
<form id="conn" data-dev="{e(ifname)}" data-active="{'1' if is_active else '0'}">
<label>Name (blank for the default) <input type="text" name="alias" value="{e(alias)}" placeholder="{e(friendly)}"></label>
<label><input type="checkbox" name="power" {'checked' if admin_up else ''} {'' if power_known else 'disabled'}> Switched on{'' if power_known else ' (state could not be read)'}</label>{warn}
<fieldset><legend>Role</legend><label><input type="radio" name="role" value="" {'checked' if not role else ''}> Leave as is</label>
<label><input type="radio" name="role" value="primary" {'checked' if role == 'primary' else ''}> Primary</label>
<label><input type="radio" name="role" value="fallback" {'checked' if role == 'fallback' else ''}> Fallback</label></fieldset>
<button type="submit">Save</button> <span id="result" role="status" aria-live="polite"></span></form>
<h2>Connection check</h2><pre class="adv">{e(lifeline)}</pre>
<script>document.getElementById('conn').addEventListener('submit',async ev=>{{ev.preventDefault();const f=ev.target,d=new FormData(f);
const body={{dev:f.dataset.dev,alias:d.get('alias')||'',power:d.get('power')==='on',role:d.get('role')||null,power_known:{'true' if power_known else 'false'}}};
if(f.dataset.active==='1'&&!body.power&&body.power_known&&!confirm('This connection carries your internet access. Switch it off?'))return;
if(f.dataset.active==='1'&&!body.power)body.confirm_power_off=true;
const r=await fetch('/network/connection',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
const j=await r.json();document.getElementById('result').textContent=j.message||(r.ok?'Saved.':'Refused.');}});</script></body></html>"""
    return page.encode()
