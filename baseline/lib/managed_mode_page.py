"""The installer / build manager's Managed server mode page: see the mode, turn it on with its parent folder, turn it off."""
from __future__ import annotations

import html

CHOICES = ("standalone", "managed")


def render(cfg: dict, *, notice: str = "") -> bytes:
    managed = cfg.get("mode") == "managed"
    vault = html.escape(str(cfg.get("parent_vault") or ""))
    checked = "checked" if cfg.get("remote_rebuild") else ""
    note = f'<p role="status">{html.escape(notice)}</p>' if notice else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Managed server mode</title>
<style>body{{font:15px/1.55 system-ui,sans-serif;margin:0 auto;max-width:46rem;padding:1rem}}
fieldset{{border:1px solid #888;border-radius:6px;margin:1rem 0;padding:.8rem 1rem}}label{{display:block;margin:.4rem 0}}
input[type=text]{{width:100%;box-sizing:border-box;padding:.4rem}}.sub{{opacity:.8;margin:.1rem 0 .5rem 1.6rem}}</style></head><body>
<h1>Managed server mode</h1>
<p>You do not have to run or maintain a parent system. Without managed server mode you only change your own build and Baseline never connects to a parent.
Turning it on makes the platform more stable and more capable: a parent keeps every child install's persistence data in git, filed by drive combination, and can rebuild children remotely.</p>
<p>Current mode: <strong>{'managed' if managed else 'standalone'}</strong></p>{note}
<form id="mm">
<fieldset><legend>Mode</legend>
<label><input type="radio" name="mode" value="standalone" {'' if managed else 'checked'}> Standalone (default)</label>
<p class="sub">Your own build only. Nothing is sent to or required from a parent.</p>
<label><input type="radio" name="mode" value="managed" {'checked' if managed else ''}> Managed</label>
<p class="sub">This machine is, or connects to, a parent that keeps backups and can rebuild children.</p></fieldset>
<fieldset><legend>Parent</legend>
<label>Folder the parent keeps its backups in <input type="text" name="parent_vault" value="{vault}" autocomplete="off"></label>
<label><input type="checkbox" name="remote_rebuild" {checked}> Allow approved remote rebuilds (needs the one-time root setup; a rebuild never wipes)</label></fieldset>
<button type="submit">Save</button> <span id="result" role="status" aria-live="polite"></span></form>
<script>
document.getElementById('mm').addEventListener('submit',async e=>{{e.preventDefault();const f=new FormData(e.target);
const body={{mode:f.get('mode'),parent_vault:f.get('parent_vault')||null,remote_rebuild:f.get('remote_rebuild')==='on'}};
const r=await fetch('/managed-mode',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
const j=await r.json();document.getElementById('result').textContent=r.ok?'Saved.':(j.message||'Refused.');if(r.ok)location.reload();}});
</script></body></html>"""
    return page.encode()
