"""Settings page: the IP address and port the Baseline console is served at."""
from __future__ import annotations

import html

PORT_PRESETS = (8100, 8443, 8080)


def render(current: dict, addresses: list, *, notice: str = "") -> bytes:
    e = html.escape
    choices = [("0.0.0.0", "Every address", "Reachable on any network this computer is on.")] + [(a, a, "Only on this address.") for a in addresses]
    if current["bind_host"] not in [c[0] for c in choices]:
        choices.append((current["bind_host"], current["bind_host"], "Saved, but not currently on this computer."))
    tiles = "".join(f'<input type="radio" name="host" id="h{i}" value="{e(v)}" {"checked" if v == current["bind_host"] else ""}><label class="tile" for="h{i}"><b>{e(t)}</b><span>{e(d)}</span></label>'
                    for i, (v, t, d) in enumerate(choices))
    ports = list(PORT_PRESETS) if current["port"] in PORT_PRESETS else [*PORT_PRESETS, current["port"]]
    chips = "".join(f'<input type="radio" name="port" id="p{p}" value="{p}" {"checked" if p == current["port"] else ""}><label for="p{p}">{p}</label>' for p in ports)
    note = f'<p class="note" role="status">{e(notice)}</p>' if notice else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Web address</title></head><body>
<header class="page-head"><div class="eyebrow">Baseline / Settings</div><h1>Where Baseline is on your network</h1>
<p class="lead">Baseline runs on the Proxmox host itself. Pick the address you will type to reach it. It is now <strong>http://{e(current['bind_host'])}:{current['port']}/</strong>.</p></header>{note}
<form id="wa"><section class="card"><h2>Address</h2><div class="tiles">{tiles}</div></section>
<section class="card"><h2>Port <small class="dim">(8100 unless something else uses it)</small></h2><div class="chips">{chips}</div></section>
<p><button type="submit" class="primary">Save</button> <span id="result" role="status" aria-live="polite"></span></p>
<p class="dim">A change applies the next time the Baseline web service starts.</p></form>
<script>document.getElementById('wa').addEventListener('submit',async ev=>{{ev.preventDefault();const f=ev.target;
const r=await fetch('/web-address',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{bind_host:f.host.value,port:Number(f.port.value)}})}});
const j=await r.json();document.getElementById('result').textContent=r.ok?'Saved. It applies when the web service restarts.':(j.message||'Refused.');}});</script></body></html>"""
    return page.encode()
