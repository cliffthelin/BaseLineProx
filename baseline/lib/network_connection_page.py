"""Console page for one network connection: what it is, its name, power and role (the TUI's connection dialog)."""
from __future__ import annotations

import html


def render(ifname: str, friendly: str, identity: list, status_line: str, alias: str, admin_up, pref: dict, lifeline: str, *, is_active: bool, notice: str = "") -> bytes:
    e = html.escape
    power_known = admin_up is not None
    role = "primary" if pref.get("primary") == ifname else ("fallback" if pref.get("fallback") == ifname else "")
    warn = ('<p class="note" role="note">This connection carries your current internet access. Switching it off will disconnect this page.</p>' if is_active else "")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(friendly)}</title></head><body>
<header class="page-head"><div class="eyebrow">Baseline / This computer / Internet and network</div><h1>{e(friendly)}</h1><p class="lead">{e(status_line) or 'A network connection on this computer.'} <a href="/network">Back to network</a></p></header>
{('<p class="note" role="status">' + e(notice) + '</p>') if notice else ''}
<form id="conn" data-dev="{e(ifname)}" data-active="{'1' if is_active else '0'}">
<div class="grid"><section class="card"><h2>Power</h2>
<label class="switch"><input type="checkbox" name="power" {'checked' if admin_up else ''} {'' if power_known else 'disabled'}><i></i><span>Switched on{'' if power_known else ' (state could not be read)'}<small>Turning it off disconnects anything using it.</small></span></label>{warn}</section>
<section class="card"><h2>Role</h2><div class="seg" role="radiogroup" aria-label="Role">
<input type="radio" name="role" id="r0" value="" {'checked' if not role else ''}><label for="r0">Leave as is</label>
<input type="radio" name="role" id="r1" value="primary" {'checked' if role == 'primary' else ''}><label for="r1">Main</label>
<input type="radio" name="role" id="r2" value="fallback" {'checked' if role == 'fallback' else ''}><label for="r2">Backup</label></div>
<p class="dim">Main is used first. Backup takes over if the main connection fails.</p></section>
<section class="card"><h2>Name</h2><details class="reveal" {'open' if alias else ''}><summary>Rename this connection</summary>
<input type="text" name="alias" value="{e(alias)}" placeholder="{e(friendly)}" autocomplete="off"></details></section></div>
<section class="card adv"><h2>Details</h2><pre>{e(chr(10).join(identity))}</pre><h3>Connection check</h3><pre>{e(lifeline)}</pre></section>
<p><button type="submit" class="primary">Save</button> <span id="result" role="status" aria-live="polite"></span></p></form>
<script>document.getElementById('conn').addEventListener('submit',async ev=>{{ev.preventDefault();const f=ev.target,d=new FormData(f);
const body={{dev:f.dataset.dev,alias:d.get('alias')||'',power:d.get('power')==='on',role:d.get('role')||null,power_known:{'true' if power_known else 'false'}}};
if(f.dataset.active==='1'&&!body.power&&body.power_known&&!confirm('This connection carries your internet access. Switch it off?'))return;
if(f.dataset.active==='1'&&!body.power)body.confirm_power_off=true;
const r=await fetch('/network/connection',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
const j=await r.json();document.getElementById('result').textContent=j.message||(r.ok?'Saved.':'Refused.');}});</script></body></html>"""
    return page.encode()
