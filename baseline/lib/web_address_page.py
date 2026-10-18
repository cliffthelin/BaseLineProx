"""Settings page: the IP address and port the Baseline console is served at."""
from __future__ import annotations

import html


def render(current: dict, addresses: list, *, notice: str = "") -> bytes:
    options = "".join(
        f'<option value="{html.escape(a)}"{" selected" if a == current["bind_host"] else ""}>{html.escape(label)}</option>'
        for a, label in [("0.0.0.0", "Every address on this host (0.0.0.0)"), *[(a, a) for a in addresses]])
    if current["bind_host"] not in ["0.0.0.0", *addresses]:
        options += f'<option value="{html.escape(current["bind_host"])}" selected>{html.escape(current["bind_host"])} (not currently on this host)</option>'
    note = f'<p role="status">{html.escape(notice)}</p>' if notice else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Web address</title>
<style>body{{font:15px/1.55 system-ui,sans-serif;margin:0 auto;max-width:42rem;padding:1rem}}label{{display:block;margin:.6rem 0}}select,input{{padding:.4rem;min-width:14rem}}</style></head><body>
<h1>Web address</h1>
<p>Baseline runs on the Proxmox host itself, as a system service started after Proxmox's own. This is the address it answers on.
Choose one IP of this host, or every address. The change applies the next time the Baseline web service starts.</p>
<p>Now: <strong>http://{html.escape(current['bind_host'])}:{current['port']}/</strong></p>{note}
<form id="wa"><label>Address <select name="bind_host">{options}</select></label>
<label>Port <input type="number" name="port" min="1024" max="65535" value="{current['port']}"></label>
<button type="submit">Save</button> <span id="result" role="status" aria-live="polite"></span></form>
<script>document.getElementById('wa').addEventListener('submit',async e=>{{e.preventDefault();const f=new FormData(e.target);
const r=await fetch('/web-address',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{bind_host:f.get('bind_host'),port:Number(f.get('port'))}})}});
const j=await r.json();document.getElementById('result').textContent=r.ok?'Saved. It applies when the web service restarts.':(j.message||'Refused.');}});</script></body></html>"""
    return page.encode()
