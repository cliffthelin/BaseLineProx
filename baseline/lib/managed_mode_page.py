"""The installer / build manager's Managed server mode page: one section, one description. Choose the mode; if a parent is wanted, choose where it keeps its backups (a connected drive, or browse
to a folder) and whether it may rebuild children."""
from __future__ import annotations

import html

import path_picker


def render(cfg: dict, folders: list | None = None, *, notice: str = "") -> bytes:
    e = html.escape
    managed = cfg.get("mode") == "managed"
    current = cfg.get("mirror_root") or ""
    options = [(f["folder"], f["volume"]) for f in (folders or [])]
    listed = current in [o[0] for o in options]
    folder_tiles = "".join(
        f'<input type="radio" name="mirror" id="v{i}" value="{e(path)}" {"checked" if path == current else ""}>'
        f'<label class="tile" for="v{i}"><b>{e(label)}</b><span>Keep the mirror here</span></label>' for i, (path, label) in enumerate(options))
    note = f'<p class="note" role="status">{e(notice)}</p>' if notice else ""
    picked = current if current and not listed else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Managed server mode</title></head><body>
<header class="page-head"><div class="eyebrow">Baseline / Set up and build / Parent server</div><h1>Managed server mode</h1>
<p class="lead">Optional. A parent keeps a mirror of your computers and can rebuild them. Without one you only change your own build, and nothing ever connects to a parent.</p></header>{note}
<form id="mm"><section class="card">
<div class="tiles"><input type="radio" name="mode" id="m-s" value="standalone" {"" if managed else "checked"}><label class="tile" for="m-s"><b>On its own</b><span>No parent</span></label>
<input type="radio" name="mode" id="m-m" value="managed" {"checked" if managed else ""}><label class="tile" for="m-m"><b>With a parent server</b><span>Backups and remote rebuilds</span></label></div>
<div id="parent"><h2>Keep the mirror on</h2><div class="tiles">{folder_tiles}</div>
{path_picker.picker_html("mirror-pick", picked, label="Another place")}
<label class="switch"><input type="checkbox" id="remote" {"checked" if cfg.get("remote_rebuild") else ""}><i></i><span>Allow remote rebuilds</span></label></div>
</section>
<p><button type="submit" class="primary">Save</button> <span id="result" role="status" aria-live="polite"></span></p></form>
{path_picker.picker_script()}
<script>
const f=document.getElementById('mm'),parent=document.getElementById('parent'),pick=document.getElementById('mirror-pick');
function sync(){{parent.style.display=f.mode.value==='managed'?'block':'none'}}f.addEventListener('change',sync);sync();
pick.addEventListener('pathchange',()=>{{document.querySelectorAll('input[name=mirror]').forEach(r=>r.checked=false)}});
f.addEventListener('submit',async ev=>{{ev.preventDefault();
const chosen=f.mirror&&f.mirror.value?f.mirror.value:(pick.dataset.value||'');
const body={{mode:f.mode.value,mirror_root:f.mode.value==='managed'?(chosen||null):null,remote_rebuild:document.getElementById('remote').checked&&f.mode.value==='managed'}};
const r=await fetch('/managed-mode',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
const j=await r.json();document.getElementById('result').textContent=r.ok?'Saved.':(j.message||'Refused.');if(r.ok)setTimeout(()=>location.reload(),600);}});
</script></body></html>"""
    return page.encode()
