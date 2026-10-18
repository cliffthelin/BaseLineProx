"""The installer / build manager's Managed server mode page: choose the mode, pick where a parent keeps its backups, and say whether it may rebuild children."""
from __future__ import annotations

import html


def render(cfg: dict, folders: list | None = None, *, notice: str = "") -> bytes:
    e = html.escape
    managed = cfg.get("mode") == "managed"
    current = cfg.get("parent_vault") or ""
    folders = folders or []
    options = [(f["folder"], f"{f['volume']}") for f in folders]
    if current and current not in [o[0] for o in options]:
        options.insert(0, (current, current))
    folder_tiles = "".join(
        f'<input type="radio" name="vault" id="v{i}" value="{e(path)}" {"checked" if path == current else ""}>'
        f'<label class="tile" for="v{i}"><b>{e(label)}</b><span>Backups go in <code>{e(path)}</code></span></label>' for i, (path, label) in enumerate(options))
    other_checked = "" if (not current or current in [o[0] for o in options]) else "checked"
    note = f'<p class="note" role="status">{e(notice)}</p>' if notice else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Managed server mode</title></head><body>
<header class="page-head"><div class="eyebrow">Baseline / Set up and build / Parent server</div><h1>Managed server mode</h1>
<p class="lead">Optional. A parent keeps your computers' data and can rebuild them for you. Without it you only change your own build and nothing ever connects to a parent.</p></header>{note}
<form id="mm">
<section class="card"><h2>How should this machine run?</h2><div class="tiles">
<input type="radio" name="mode" id="m-s" value="standalone" {"" if managed else "checked"}><label class="tile" for="m-s"><b>On its own</b><span>Your build only. Nothing is sent to a parent, and none is needed.</span></label>
<input type="radio" name="mode" id="m-m" value="managed" {"checked" if managed else ""}><label class="tile" for="m-m"><b>With a parent server</b><span>Backups of your data are kept on the parent, and it can rebuild your computers.</span></label></div></section>
<section class="card" id="parent"><h2>Where the parent keeps its backups</h2>
<div class="tiles">{folder_tiles or '<p class="dim">No other drive is connected. Connect one, or choose Another place below.</p>'}
<input type="radio" name="vault" id="v-other" value="__other" {other_checked}><label class="tile" for="v-other"><b>Another place</b><span>Type a folder. Use this only if the drive you want is not listed.</span></label></div>
<details class="reveal" {"open" if other_checked else ""}><summary>Folder to use</summary><input type="text" id="other" value="{e(current if other_checked else "")}" placeholder="/path/to/folder" autocomplete="off"></details>
<label class="switch"><input type="checkbox" id="remote" {"checked" if cfg.get("remote_rebuild") else ""}><i></i><span>Allow remote rebuilds<small>You approve each one with a one-time code. A rebuild never wipes anything.</small></span></label></section>
<p><button type="submit" class="primary">Save</button> <span id="result" role="status" aria-live="polite"></span></p></form>
<script>
const f=document.getElementById('mm'),parent=document.getElementById('parent');
function sync(){{parent.style.opacity=f.mode.value==='managed'?1:.45}}f.addEventListener('change',sync);sync();
f.addEventListener('submit',async ev=>{{ev.preventDefault();
let v=f.vault?f.vault.value:'';if(v==='__other')v=document.getElementById('other').value.trim();
const body={{mode:f.mode.value,parent_vault:f.mode.value==='managed'?(v||null):(v||null),remote_rebuild:document.getElementById('remote').checked&&f.mode.value==='managed'}};
const r=await fetch('/managed-mode',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
const j=await r.json();document.getElementById('result').textContent=r.ok?'Saved.':(j.message||'Refused.');if(r.ok)setTimeout(()=>location.reload(),600);}});
</script></body></html>"""
    return page.encode()
