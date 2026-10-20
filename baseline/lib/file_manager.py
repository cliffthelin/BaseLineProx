"""A file manager in the console (operator, 2026-10-19: Proxmox has no file manager, only a console). Browse the connected drives, download, upload, make a folder, rename, delete.

Only places under the allowed roots (the mounted data volumes, as in path_picker) are reachable, every path is resolved first so a link cannot lead out, a name is a plain name and never
a path, an upload never replaces a file, and a folder is deleted only when it is empty. A mounted drive itself is never renamed or deleted. Nothing is typed as a path: places are clicked.
"""
from __future__ import annotations

import html
import os
import shutil
import tempfile
import urllib.parse
from pathlib import Path

import path_picker

MAX_ENTRIES = 1000
CHUNK = 1024 * 1024


class FileManagerError(ValueError):
    pass


def _allowed(allowed):
    return path_picker.roots() if allowed is None else tuple(allowed)


def _resolve(path, allowed) -> str:
    if not isinstance(path, str) or not path.startswith("/") or "\0" in path:
        raise FileManagerError("That place cannot be used.")
    real = os.path.realpath(path)
    if not path_picker._inside(real, _allowed(allowed)):
        raise FileManagerError("That place is not on a connected drive.")
    return real


def _name(name) -> str:
    if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\0" in name or len(name.encode()) > 255:
        raise FileManagerError("A name is plain text without slashes.")
    return name


def _protected(real, allowed) -> bool:
    return real in {os.path.realpath(a) for a in _allowed(allowed)} or os.path.ismount(real)


def listing(path, allowed=None) -> dict:
    allowed = _allowed(allowed)
    if not path:
        places = sorted({str(c) for r in allowed if Path(r).is_dir() for c in Path(r).iterdir() if c.is_dir() and not c.name.startswith(".")})
        return {"path": "", "parent": None, "writable": False, "entries": [{"name": Path(p).name, "path": p, "dir": True, "size": 0} for p in places[:MAX_ENTRIES]]}
    try:
        real = _resolve(path, allowed)
    except FileManagerError as exc:
        return {"path": path, "parent": None, "entries": [], "error": str(exc)}
    if not os.path.isdir(real):
        return {"path": real, "parent": None, "entries": [], "error": "That is not a folder."}
    try:
        children = list(os.scandir(real))
    except OSError as exc:
        return {"path": real, "parent": None, "entries": [], "error": f"That folder cannot be read ({exc.strerror or exc})."}
    entries = []
    for child in children[:MAX_ENTRIES]:
        try:
            info = child.stat(follow_symlinks=False)
            is_dir = child.is_dir(follow_symlinks=False)
        except OSError:
            continue
        entries.append({"name": child.name, "path": child.path, "dir": is_dir, "size": 0 if is_dir else info.st_size, "modified": int(info.st_mtime)})
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    parent = str(Path(real).parent)
    return {"path": real, "parent": parent if path_picker._inside(os.path.realpath(parent), allowed) else "", "writable": os.access(real, os.W_OK), "entries": entries}


def open_for_download(path, allowed=None):
    real = _resolve(path, allowed)
    if not os.path.isfile(real):
        raise FileManagerError("Only a file can be downloaded.")
    return real, os.path.getsize(real)


def make_folder(parent, name, allowed=None) -> str:
    where = _resolve(parent, allowed)
    target = os.path.join(where, _name(name))
    try:
        os.mkdir(target)
    except FileExistsError:
        raise FileManagerError("Something with that name is already there.")
    except OSError as exc:
        raise FileManagerError(f"The folder could not be made ({exc.strerror or exc}).")
    return target


def rename(path, new_name, allowed=None) -> str:
    real = _resolve(path, allowed)
    if _protected(real, allowed):
        raise FileManagerError("A drive cannot be renamed here.")
    target = os.path.join(os.path.dirname(real), _name(new_name))
    if os.path.lexists(target):
        raise FileManagerError("Something with that name is already there.")
    try:
        os.rename(real, target)
    except OSError as exc:
        raise FileManagerError(f"It could not be renamed ({exc.strerror or exc}).")
    return target


def delete(path, allowed=None) -> None:
    real = _resolve(path, allowed)
    if _protected(real, allowed):
        raise FileManagerError("A drive cannot be deleted here.")
    try:
        if os.path.isdir(real) and not os.path.islink(real):
            if any(os.scandir(real)):
                raise FileManagerError("That folder is not empty. Delete what is inside it first.")
            os.rmdir(real)
        else:
            os.unlink(real)
    except OSError as exc:
        raise FileManagerError(f"It could not be deleted ({exc.strerror or exc}).")


def save_upload(folder, name, stream, length, allowed=None) -> str:
    """Writes exactly `length` bytes from `stream` as a new file, through a temporary file in the same folder; never replaces one, and a short transfer leaves nothing behind."""
    where = _resolve(folder, allowed)
    target = os.path.join(where, _name(name))
    if os.path.lexists(target):
        raise FileManagerError("A file with that name is already there.")
    if not isinstance(length, int) or length < 0:
        raise FileManagerError("The upload has no size.")
    try:
        fd, temp = tempfile.mkstemp(prefix=".upload-", dir=where)
    except OSError as exc:
        raise FileManagerError(f"That folder cannot be written to ({exc.strerror or exc}).")
    try:
        with os.fdopen(fd, "wb") as out:
            left = length
            while left:
                chunk = stream.read(min(CHUNK, left))
                if not chunk:
                    raise FileManagerError("The upload ended early; nothing was kept.")
                out.write(chunk)
                left -= len(chunk)
        os.chmod(temp, 0o644)
        os.link(temp, target)                  # a link fails when the name appeared meanwhile, so nothing is replaced
    except FileExistsError:
        raise FileManagerError("A file with that name is already there.")
    except OSError as exc:
        raise FileManagerError(f"The upload could not be saved ({exc.strerror or exc}).")
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass
    return target


def _size(n) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def render(view, allowed=None, notice="") -> bytes:
    e = html.escape
    q = lambda p: urllib.parse.quote(p, safe="")
    here = view.get("path", "")
    rows = ""
    if view.get("parent") is not None and here:
        rows += f"<tr><td><a href='/files?path={q(view['parent'])}'>⬑ Up</a></td><td></td><td></td><td></td></tr>"
    elif here:
        rows += "<tr><td><a href='/files'>⬑ All drives</a></td><td></td><td></td><td></td></tr>"
    for entry in view.get("entries", []):
        name = e(entry["name"])
        if entry["dir"]:
            first = f"<a href='/files?path={q(entry['path'])}'>📁 {name}</a>"
            size = ""
        else:
            first = f"<a href='/files/download?path={q(entry['path'])}'>{name}</a>"
            size = _size(entry["size"])
        acts = ("" if not here else f"<button type='button' data-act='rename' data-path='{e(entry['path'], quote=True)}' data-name='{e(entry['name'], quote=True)}'>Rename</button> "
                f"<button type='button' data-act='delete' data-path='{e(entry['path'], quote=True)}' data-name='{e(entry['name'], quote=True)}'>Delete</button>")
        rows += f"<tr><td>{first}</td><td>{size}</td><td></td><td>{acts}</td></tr>"
    error = f"<p class='bad'>{e(view['error'])}</p>" if view.get("error") else ""
    note = f"<p role='status'>{e(notice)}</p>" if notice else ""
    tools = ""
    if here and view.get("writable"):
        tools = ("<p><button type='button' id='fm-new'>New folder</button> <label>Upload <input type='file' id='fm-up' multiple></label></p>")
    crumb = e(here) if here else "Connected drives"
    script = """<script>
const here=%s;
async function op(body){const r=await fetch('/files/op',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();
  if(!j.ok){alert(j.message||'That did not work');}location.reload();}
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  if(b.id==='fm-new'){const n=prompt('Name of the new folder');if(n)op({op:'mkdir',path:here,name:n});}
  else if(b.dataset.act==='rename'){const n=prompt('New name',b.dataset.name);if(n&&n!==b.dataset.name)op({op:'rename',path:b.dataset.path,name:n});}
  else if(b.dataset.act==='delete'){if(confirm('Delete '+b.dataset.name+'? This cannot be undone.'))op({op:'delete',path:b.dataset.path});}});
const up=document.getElementById('fm-up');
if(up)up.addEventListener('change',async()=>{for(const f of up.files){const r=await fetch('/files/upload?path='+encodeURIComponent(here)+'&name='+encodeURIComponent(f.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:f});
  const j=await r.json();if(!j.ok){alert(f.name+': '+(j.message||'upload failed'));break;}}location.reload();});
</script>""" % __import__("json").dumps(here)
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Files</title></head><body><h1>Files</h1><p><code>{crumb}</code></p>{note}{error}{tools}"
            f"<table><thead><tr><th>Name</th><th>Size</th><th></th><th></th></tr></thead><tbody>{rows}</tbody></table>{script}</body></html>").encode()
