"""Folders are chosen, never typed: browse to one, or paste one and have it checked on the spot.

`list_dirs` and `validate` are what the console's folder browser and its paste check call; the server checks again when a form is saved, so a pasted path is never trusted because the page said it
was fine. Only places under the allowed roots (mounted data volumes) can be browsed or chosen. A folder that does not exist yet is acceptable only inside an existing, writable folder (it will
be created there). `picker_html` is the one control every page uses for a path: the current choice, a Browse button, and a paste-only box (typing is blocked, paste is validated).
"""
from __future__ import annotations

import html
import os
from pathlib import Path

DEFAULT_ROOTS = ("/mnt", "/media", "/run/media")
MAX_ENTRIES = 300


def roots(extra=()) -> tuple:
    return tuple(r for r in (*DEFAULT_ROOTS, *extra) if r)


def _real(path: str) -> str:
    return os.path.realpath(path)


def _inside(path: str, allowed) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in (_real(a) for a in allowed))


def validate(path, allowed=None, *, exists_ok=True) -> dict:
    """{"ok", "path", "message", "creates"}: whether `path` can be used as a folder, and why not."""
    allowed = roots() if allowed is None else allowed
    if not isinstance(path, str) or not path.strip():
        return {"ok": False, "path": "", "message": "Choose a folder.", "creates": False}
    raw = path.strip()
    if "\0" in raw or "\n" in raw or "\r" in raw:
        return {"ok": False, "path": raw, "message": "That is not a folder path.", "creates": False}
    if not raw.startswith("/"):
        return {"ok": False, "path": raw, "message": "Use the full path, starting with /.", "creates": False}
    real = _real(raw)
    if not _inside(real, allowed):
        return {"ok": False, "path": raw, "message": "That folder is not on a connected drive Baseline may use.", "creates": False}
    target = Path(real)
    if target.exists():
        if not target.is_dir():
            return {"ok": False, "path": raw, "message": "That is a file, not a folder.", "creates": False}
        if not os.access(real, os.W_OK):
            return {"ok": False, "path": raw, "message": "That folder cannot be written to.", "creates": False}
        return {"ok": True, "path": real, "message": "Folder found.", "creates": False}
    parent = target.parent
    if not parent.is_dir() or not _inside(_real(str(parent)), allowed):
        return {"ok": False, "path": raw, "message": "That folder's parent does not exist.", "creates": False}
    if not os.access(str(parent), os.W_OK):
        return {"ok": False, "path": raw, "message": "That folder cannot be created there.", "creates": False}
    return {"ok": True, "path": real, "message": "Will be created.", "creates": True}


def list_dirs(path, allowed=None) -> dict:
    """The folders directly inside `path` (or the allowed places when `path` is empty), for the browser."""
    allowed = roots() if allowed is None else allowed
    if not path:
        places = sorted({str(c) for r in allowed if Path(r).is_dir() for c in Path(r).iterdir() if c.is_dir() and not c.name.startswith(".")})
        return {"path": "", "parent": None, "dirs": [{"name": Path(p).name, "path": p} for p in places[:MAX_ENTRIES]], "writable": False}
    real = _real(path)
    if not _inside(real, allowed) or not Path(real).is_dir():
        return {"path": path, "parent": None, "dirs": [], "error": "That place cannot be browsed."}
    try:
        children = sorted(c for c in Path(real).iterdir() if c.is_dir() and not c.name.startswith("."))
    except OSError as exc:
        return {"path": real, "parent": None, "dirs": [], "error": f"That folder cannot be read ({exc.strerror or exc})."}
    parent = str(Path(real).parent)
    return {"path": real, "parent": parent if _inside(_real(parent), allowed) else "", "dirs": [{"name": c.name, "path": str(c)} for c in children[:MAX_ENTRIES]],
            "writable": os.access(real, os.W_OK)}


def picker_html(field_id: str, value: str = "", *, label: str = "Folder") -> str:
    """The one path control: current choice, Browse, and paste-only entry with live validation. Its value is read with `document.getElementById(field_id).dataset.value`."""
    e = html.escape
    return f"""<div class="path-picker" id="{e(field_id)}" data-value="{e(value, quote=True)}">
<div class="pp-current" aria-live="polite"><span class="pp-label">{e(label)}</span><code class="pp-value">{e(value) or "None chosen yet"}</code></div>
<div class="pp-actions"><button type="button" class="pp-browse">Browse…</button>
<input class="pp-paste" type="text" placeholder="Paste a path here" aria-label="Paste a folder path" autocomplete="off" spellcheck="false"><span class="pp-msg" role="status" aria-live="polite"></span></div>
<dialog class="pp-dialog"><div class="pp-head"><b>Choose a folder</b><button type="button" class="pp-close" aria-label="Close">×</button></div>
<div class="pp-crumbs"></div><ul class="pp-list"></ul><div class="pp-foot"><button type="button" class="pp-pick primary" disabled>Use this folder</button></div></dialog></div>"""


def picker_script() -> str:
    return r"""<script>
(function(){
function api(path,q){return fetch(path+'?path='+encodeURIComponent(q),{credentials:'same-origin'}).then(function(r){return r.json()})}
document.querySelectorAll('.path-picker').forEach(function(box){
 var val=box.querySelector('.pp-value'),msg=box.querySelector('.pp-msg'),paste=box.querySelector('.pp-paste'),dlg=box.querySelector('.pp-dialog'),
 list=box.querySelector('.pp-list'),crumbs=box.querySelector('.pp-crumbs'),pick=box.querySelector('.pp-pick'),here='';
 function choose(p,note){box.dataset.value=p;val.textContent=p||'None chosen yet';msg.textContent=note||'';msg.className='pp-msg ok';box.dispatchEvent(new Event('pathchange',{bubbles:true}));}
 paste.addEventListener('beforeinput',function(e){if(e.inputType!=='insertFromPaste'&&e.inputType!=='insertFromPasteAsQuotation'&&e.inputType!=='deleteContentBackward'&&e.inputType!=='deleteContentForward'&&e.inputType!=='deleteByCut')e.preventDefault();});
 paste.addEventListener('drop',function(e){e.preventDefault()});
 paste.addEventListener('paste',function(e){e.preventDefault();var t=((e.clipboardData||window.clipboardData).getData('text')||'').trim();paste.value=t;msg.textContent='Checking…';msg.className='pp-msg';
  api('/fs/validate',t).then(function(r){if(r.ok){choose(r.path,r.message);paste.value='';}else{msg.textContent=r.message;msg.className='pp-msg bad';paste.value='';}})
   .catch(function(){msg.textContent='Could not check that path.';msg.className='pp-msg bad'});});
 function show(p){api('/fs/browse',p).then(function(r){
   here=r.path||'';list.replaceChildren();crumbs.textContent=here||'Connected drives';pick.disabled=!here||r.error||!r.writable;
   if(r.error){var li=document.createElement('li');li.className='pp-empty';li.textContent=r.error;list.append(li);return}
   if(here){var up=document.createElement('li');var b=document.createElement('button');b.type='button';b.textContent='↑ Up';b.onclick=function(){show(r.parent||'')};up.append(b);list.append(up);}
   r.dirs.forEach(function(d){var li=document.createElement('li');var b=document.createElement('button');b.type='button';b.textContent=d.name;b.onclick=function(){show(d.path)};li.append(b);list.append(li);});
   if(!r.dirs.length){var e=document.createElement('li');e.className='pp-empty';e.textContent='No folders here.';list.append(e);}
 })}
 box.querySelector('.pp-browse').onclick=function(){dlg.showModal();show(box.dataset.value||'')};
 box.querySelector('.pp-close').onclick=function(){dlg.close()};
 pick.onclick=function(){api('/fs/validate',here).then(function(r){if(r.ok){choose(r.path,r.message);dlg.close()}else{msg.textContent=r.message;msg.className='pp-msg bad';dlg.close()}})};
});
})();
</script>"""
