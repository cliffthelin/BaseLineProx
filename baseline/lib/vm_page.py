"""The VM library page: create, configure and run VMs and overlays from the browser.

`perform` turns one JSON action from the page into a VmHost call and a plain message; it never raises for a
bad request. `render_vms_page` draws the page; every dynamic value is escaped. The store location is a setting
kept in a small JSON file next to the app's other state.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

import vm_host as vh
import ubuntu_environment as ubuntu

_FORBIDDEN_PREFIXES = ("/dev", "/proc", "/sys", "/etc", "/boot", "/run/user", "/usr", "/bin", "/sbin", "/lib", "/var/lib/dpkg")
_NEEDS_CONFIRM = {"delete_vm", "delete_base", "rollback", "freeze"}


def _int(params: dict, key: str, label: str) -> int:
    try:
        return int(str(params.get(key, "")).strip())
    except ValueError:
        raise vh.VmError(f"{label} must be a whole number") from None


def perform(host: vh.VmHost, action: str, params: dict, *, iso_dir) -> dict:
    name = str(params.get("name", ""))
    try:
        if action in _NEEDS_CONFIRM and params.get("confirm") != "yes":
            raise vh.VmError("this needs confirmation")
        if action == "prepare_ubuntu":
            path = ubuntu.acquire_base(host, cache_dir=Path(iso_dir).parent / "images")
            return _ok(f"Ubuntu base ready: {path.name}. Choose Desktop or Server below.")
        if action == "create_ubuntu":
            recipe = params.get("recipe", "ubuntu-desktop")
            if recipe not in ("ubuntu-desktop", "ubuntu-server"):
                raise vh.VmError("choose Ubuntu Desktop or Ubuntu Server")
            created = ubuntu.create(host, name, desktop=recipe == "ubuntu-desktop",
                                     homepage=str(params.get("homepage", "")),
                                     memory_mb=_int(params, "memory_mb", "memory"), cpus=_int(params, "cpus", "cpus"),
                                     disk_gb=_int(params, "disk_gb", "OS disk size"),
                                     persistence_gb=_int(params, "persistence_gb", "user disk size"))
            return dict(created, ok=True)
        if action == "create_iso":
            iso = {i["name"]: i["path"] for i in available_isos(host, iso_dir)}.get(str(params.get("iso", "")))
            if iso is None:
                raise vh.VmError("choose an ISO from the installer cache folder")
            firmware = params.get("firmware", "bios")
            if firmware not in ("bios", "uefi"):
                raise vh.VmError("choose BIOS or UEFI firmware")
            host.create_from_iso(name, iso=iso, disk_gb=_int(params, "disk_gb", "disk size"),
                                 memory_mb=_int(params, "memory_mb", "memory"), cpus=_int(params, "cpus", "cpus"))
            if firmware == "uefi":
                host.configure_uefi(name)
            return _ok(f"Created {name}. Start it to boot the installer.")
        if action == "create_overlay":
            host.create_overlay(name, base=str(params.get("base", "")), memory_mb=_int(params, "memory_mb", "memory"),
                                cpus=_int(params, "cpus", "cpus"),
                                persistence_gb=_int(dict({"persistence_gb": 32}, **params), "persistence_gb", "user disk size"))
            return _ok(f"Created overlay {name}; the base image is never written.")
        if action == "start":
            display = params.get("display") or vh.default_display(os.environ)
            if display not in ("gtk", "vnc"):
                raise vh.VmError("display must be a window or VNC")
            st = host.start(name, display=display)
            where = f" Connect a VNC viewer to {st['vnc']}." if st.get("vnc") else ""
            return _ok(f"Started {name}.{where}")
        if action == "request_stop":
            host.request_stop(name)
            return _ok(f"Asked {name} to shut down. If it does not stop, use Force stop.")
        if action == "force_stop":
            host.force_stop(name)
            return _ok(f"Stopped {name}.")
        if action == "configure":
            host.configure(name, memory_mb=_int(params, "memory_mb", "memory"), cpus=_int(params, "cpus", "cpus"))
            return _ok(f"Updated {name}.")
        if action == "eject_iso":
            host.eject_iso(name)
            return _ok(f"Ejected the installer ISO from {name}.")
        if action == "rollback":
            if host._spec(name).get("recipe"):
                ubuntu.rebuild(host, name)
            else:
                host.rollback(name)
            return _ok(f"Rebuilt {name}'s OS. Its retained user disk was kept.")
        if action == "freeze":
            host.freeze_as_base(name, str(params.get("base_name", "")))
            return _ok(f"{name} is now the read-only base image {params.get('base_name')}.")
        if action == "delete_vm":
            host.delete_vm(name)
            return _ok(f"Deleted {name}.")
        if action == "delete_base":
            host.delete_base(name)
            return _ok(f"Deleted base image {name}.")
    except vh.VmError as exc:
        return {"ok": False, "message": str(exc)}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "message": f"invalid request: {exc}"}
    except OSError as exc:
        return {"ok": False, "message": f"{exc.strerror or exc}"}
    return {"ok": False, "message": f"unknown action: {action}"}


def available_isos(host, iso_dir):
    return host.available_isos() if hasattr(host, "available_isos") else vh.list_isos(iso_dir)


def _ok(message: str) -> dict:
    return {"ok": True, "message": message}


def load_store(config_path, *, default: str) -> str:
    return _load_path(config_path, "store", default)


def load_persistence_store(config_path, *, default: str) -> str:
    return _load_path(config_path, "persistence_store", default)


def _load_path(config_path, key, default):
    try:
        value = json.loads(Path(config_path).read_text()).get(key)
    except (OSError, ValueError, AttributeError):
        return default
    return value if isinstance(value, str) and value.startswith("/") else default


def save_store(config_path, store: str, *, persistence_store=None) -> dict:
    changes = {"store": store}
    if persistence_store is not None:
        changes["persistence_store"] = persistence_store
    for value in changes.values():
        p = Path(value) if isinstance(value, str) else Path("")
        if (not isinstance(value, str) or not value.startswith("/") or ".." in p.parts or str(p) == "/"
                or "INSTALLER_CACHE" in p.parts
                or any(str(p) == f or str(p).startswith(f + "/") for f in _FORBIDDEN_PREFIXES)):
            return {"ok": False, "message": "VM disks need a plain absolute folder outside system paths and installer cache"}
    try:
        current = json.loads(Path(config_path).read_text())
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current.update(changes)
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    Path(config_path).write_text(json.dumps(current))
    return {"ok": True, "message": "VM storage locations saved. Existing files were not moved."}


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _gb(n: int) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"


_CSS = """
:root{--bg:#0f1316;--panel:#171d22;--line:#27313a;--ink:#e6ecef;--mute:#8a98a3;--acc:#5fd3a5;--warn:#f0b35c;--bad:#ef6f6f}
@media (prefers-color-scheme: light){:root{--bg:#f4f1ea;--panel:#fffdf8;--line:#ddd6c8;--ink:#1d2327;--mute:#68737b;--acc:#0b7a5a;--warn:#a2650b;--bad:#b3261e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:26px;margin:6px 0 2px}h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:30px 0 10px}
.sub{color:var(--mute);margin:0 0 18px}.notice{padding:10px 14px;border-left:4px solid var(--acc);background:var(--panel);margin:12px 0}
.notice.bad{border-color:var(--bad)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.vm{display:grid;grid-template-columns:1fr auto;gap:10px 18px;align-items:center}
.vm .name{font-size:18px;font-weight:600}.vm .meta{color:var(--mute);font-size:13px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--mute);margin-right:8px}.dot.on{background:var(--acc);box-shadow:0 0 8px var(--acc)}
.tag{font-size:11px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin-left:8px;color:var(--mute)}
.btns{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}
button,.btn{font:inherit;font-size:13px;padding:6px 12px;border-radius:7px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer}
button:hover{border-color:var(--acc)}button.go{background:var(--acc);color:#07140f;border-color:var(--acc);font-weight:600}
button.danger{color:var(--bad)}button.danger:hover{border-color:var(--bad)}
form.row{display:flex;flex-wrap:wrap;gap:10px;align-items:end}form.row label{display:flex;flex-direction:column;font-size:12px;color:var(--mute);gap:3px}
input,select{font:inherit;padding:6px 8px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--ink);min-width:90px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:760px){.two,.vm{grid-template-columns:1fr}.btns{justify-content:flex-start}}
.baseline-nav{display:flex;flex-wrap:wrap;gap:4px 16px;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
.baseline-nav a{color:var(--mute);text-decoration:none;font-size:14px}.baseline-nav a:hover{color:var(--ink)}.baseline-nav a.active{color:var(--acc);font-weight:600}
.warn{color:var(--warn)}.empty{color:var(--mute);padding:6px 2px}
"""

_JS = """
window.__vmBusy = false;
window.__loginVisible = false;
async function act(action, params, ask){
  if (ask && !confirm(ask)) return;
  if (window.__vmBusy) return;
  window.__vmBusy = true;
  document.getElementById('action-status').textContent = 'Working…';
  const body = Object.assign({action: action, request_id: crypto.randomUUID()}, params || {});
  if (ask) body.confirm = "yes";
  let j;
  try {
    const r = await fetch("/vms/action", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    j = await r.json();
    if (r.status === 202 && j.job_id) {
      document.getElementById('action-status').textContent = 'Job recorded. You can close this page and return to Workload jobs.';
      while (true) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const status = await fetch('/workloads/job?job_id=' + encodeURIComponent(j.job_id));
        const job = await status.json();
        if (!status.ok) throw new Error(job.error || 'Job status unavailable');
        document.getElementById('action-status').textContent = job.state + ': ' + (job.result?.message || action);
        if (['completed','failed','interrupted','reviewed'].includes(job.state)) {
          const result = await fetch('/workloads/result', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:j.job_id})});
          j = await result.json(); break;
        }
      }
    }
  } catch (e) {
    window.__vmBusy = false;
    document.getElementById('action-status').textContent = 'Connection lost. Check the machine list before retrying.';
    return;
  }
  if (j.ok && j.password) {
    window.__loginVisible = true;
    document.getElementById('login-name').textContent = j.username;
    document.getElementById('login-password').textContent = j.password;
    document.getElementById('one-time-login').showModal();
    return;
  }
  location.href = "/vms?ok=" + (j.ok ? 1 : 0) + "&notice=" + encodeURIComponent(j.message || "");
}
function submitForm(ev, action){
  ev.preventDefault();
  const f = ev.target, p = {};
  for (const el of f.elements) if (el.name) p[el.name] = el.value;
  act(action, p);
}
setInterval(function(){
  if (window.__vmBusy || window.__loginVisible) return;
  const a = document.activeElement;
  if (a && (a.tagName === "INPUT" || a.tagName === "SELECT")) return;
  fetch("/vms/status").then(r => r.json()).then(function(s){
    if (JSON.stringify(s) !== window.__vmState) location.reload();
  }).catch(function(){});
}, 4000);
const homeField = document.querySelector('input[name="homepage"]');
if (homeField && !homeField.value && !['localhost','127.0.0.1','[::1]'].includes(location.hostname))
  homeField.value = 'https://' + location.hostname + ':8006';
for (const link of document.querySelectorAll('.proxmox-link')) link.href = 'https://' + location.hostname + ':8006';
"""


def status_snapshot(vms: list, bases: list) -> dict:
    """What the page polls to know it is stale; the page embeds the same compact JSON."""
    return {"vms": [[v["name"], v["running"]] for v in vms], "bases": [b["name"] for b in bases]}


def _vm_card(v: dict, display_default: str, backend: str = "Local QEMU") -> str:
    n = _e(v["name"])
    on = v["running"]
    kind = "overlay on " + _e(v["base"]) if v["kind"] == "overlay" else "standalone disk"
    meta = f'{v["cpus"]} CPU · {v["memory_mb"]} MB · {kind}'
    if v.get("iso"):
        meta += f' · installer ISO attached'
    if v.get("vnc"):
        meta += f' · VNC {_e(v["vnc"])}'
    btns = []
    if on:
        btns.append(f'<button onclick="act(\'request_stop\',{{name:\'{n}\'}})">Shut down</button>')
        btns.append(f'<button class="danger" onclick="act(\'force_stop\',{{name:\'{n}\'}},\'Force stop {n}? Recent writes can be lost and its filesystems can be damaged.\')">Force stop</button>')
    else:
        btns.append(f'<button class="go" onclick="act(\'start\',{{name:\'{n}\',display:\'{display_default}\'}})">Start</button>')
        if backend != "Proxmox":
            btns.append(f'<button onclick="act(\'start\',{{name:\'{n}\',display:\'vnc\'}})">Start (VNC)</button>')
        if v.get("iso"):
            btns.append(f'<button onclick="act(\'eject_iso\',{{name:\'{n}\'}})">Installed - eject ISO</button>')
        if v["kind"] == "overlay":
            btns.append(f'<button class="danger" onclick="act(\'rollback\',{{name:\'{n}\'}},\'Rebuild the OS of {n}? OS changes are lost; the separate user disk is retained.\')">Rebuild OS</button>')
        elif not v.get("iso"):
            btns.append(f'<button onclick="var b=prompt(\'Name for the new read-only base image\');if(b)act(\'freeze\',{{name:\'{n}\',base_name:b}},\'Turn {n} into a base image? {n} is consumed; clone new VMs from the base.\')">Freeze as base</button>')
        btns.append(f'<button class="danger" onclick="act(\'delete_vm\',{{name:\'{n}\'}},\'Delete {n} and its disk?\')">Delete</button>')
    cfg = ""
    if backend == "Proxmox":
        btns.append('<a class="btn proxmox-link" href="#" target="_blank" rel="noopener">Open Proxmox</a>')
    if not on:
        cfg = (f'<form class="row" onsubmit="submitForm(event,\'configure\')" style="grid-column:1/-1">'
               f'<input type="hidden" name="name" value="{n}">'
               f'<label>Memory MB<input name="memory_mb" type="number" min="256" value="{_e(v["memory_mb"])}"></label>'
               f'<label>CPUs<input name="cpus" type="number" min="1" max="128" value="{_e(v["cpus"])}"></label>'
               f'<button>Save settings</button></form>')
    return (f'<div class="card vm"><div><div class="name"><span class="dot {"on" if on else ""}"></span>{n}'
            f'<span class="tag">{"running" if on else "stopped"}</span></div><div class="meta">{meta}</div></div>'
            f'<div class="btns">{"".join(btns)}</div>{cfg}</div>')


def render_vms_page(*, store: str, free_gb, kvm_ok: bool, isos: list, bases: list, vms: list, notice: str,
                    notice_ok, default_display: str, backend: str = "Local QEMU",
                    persistence_store: str = str(vh.DEFAULT_PERSISTENCE_STORE), homepage: str = "") -> bytes:
    iso_opts = "".join(f'<option value="{_e(i["name"])}">{_e(i["name"])} ({_gb(i["size"])})</option>' for i in isos)
    base_opts = "".join(f'<option value="{_e(b["name"])}">{_e(b["name"])}</option>' for b in bases)
    kvm = "" if kvm_ok else ('<div class="notice bad">KVM is not available to this account (check /dev/kvm and the kvm group), '
                             'so VMs cannot be started here.</div>')
    note = f'<div class="notice {"" if notice_ok in (True, None) else "bad"}">{_e(notice)}</div>' if notice else ""
    vm_html = "".join(_vm_card(v, default_display, backend) for v in vms) or '<div class="empty">No VMs yet. Create one below.</div>'
    base_html = "".join(
        f'<div class="card vm"><div><div class="name">{_e(b["name"])}<span class="tag">read-only base</span></div>'
        f'<div class="meta">{_gb(b["size"])} on disk · used by {_e(", ".join(b["used_by"]) or "nothing yet")}</div></div>'
        f'<div class="btns"><button class="danger" onclick="act(\'delete_base\',{{name:\'{_e(b["name"])}\'}},'
        f'\'Delete base image {_e(b["name"])}?\')">Delete</button></div></div>' for b in bases) \
        or '<div class="empty">No base images yet. Install an OS in a VM, then Freeze it as a base.</div>'
    state = json.dumps(status_snapshot(vms, bases), separators=(",", ":"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Virtual Machines</title><style>{_CSS}</style></head><body>
<main>
<h1>Virtual machines</h1>
<p class="sub">{_e(backend)} · OS library <code>{_e(store)}</code> · {_e(free_gb)} GB free<br>Retained user disks <code>{_e(persistence_store)}</code></p>
<a class="btn proxmox-link" href="#" target="_blank" rel="noopener">Open Proxmox</a>
<p id="action-status" role="status"></p>
<dialog id="one-time-login"><h3>Save your environment login</h3><p>This fresh admin login is shown once. Save it before continuing.</p>
<p>Username: <code id="login-name"></code></p><p>Password: <code id="login-password"></code></p>
<button onclick="location.href='/vms'">I saved the login</button></dialog>
{kvm}{note}
<h2>Ubuntu environment</h2><div class="card">
<p>Ubuntu 24.04 with a rebuildable OS and a separate retained /home. First boot installs the selected desktop and browser and requires package-download access.</p>
<button onclick="act('prepare_ubuntu',{{}})">Download verified Ubuntu base</button>
<form class="row" onsubmit="submitForm(event,'create_ubuntu')">
<label>Name<input name="name" required pattern="[a-z0-9][a-z0-9-]{{0,31}}" placeholder="ubuntu"></label>
<label>Environment<select name="recipe"><option value="ubuntu-desktop">Ubuntu Desktop + Firefox</option><option value="ubuntu-server">Ubuntu Server</option></select></label>
<label>Proxmox homepage<input name="homepage" required type="url" value="{_e(homepage)}"></label>
<label>OS GB<input name="disk_gb" type="number" min="8" value="40"></label>
<label>User GB<input name="persistence_gb" type="number" min="1" value="32"></label>
<label>Memory MB<input name="memory_mb" type="number" min="2048" value="4096"></label>
<label>CPUs<input name="cpus" type="number" min="1" value="2"></label>
<button class="go">Create Ubuntu</button></form></div>
{_requested_distros()}
<h2>Machines</h2>{vm_html}
<h2>Base images</h2>{base_html}
<div class="two">
<div><h2>New VM from an installer ISO</h2><div class="card"><form class="row" onsubmit="submitForm(event,'create_iso')">
<label>Name<input name="name" required pattern="[a-z0-9][a-z0-9-]{{0,31}}" placeholder="dev-box"></label>
<label>Installer ISO<select name="iso">{iso_opts}</select></label>
<label>Firmware<select name="firmware"><option value="bios">BIOS</option><option value="uefi">UEFI</option></select></label>
<label>Disk GB<input name="disk_gb" type="number" min="1" value="40"></label>
<label>Memory MB<input name="memory_mb" type="number" min="256" value="4096"></label>
<label>CPUs<input name="cpus" type="number" min="1" value="4"></label>
<button class="go">Create</button></form></div></div>
<div><h2>New overlay from a base</h2><div class="card"><form class="row" onsubmit="submitForm(event,'create_overlay')">
<label>Name<input name="name" required pattern="[a-z0-9][a-z0-9-]{{0,31}}" placeholder="scratch"></label>
<label>Base image<select name="base">{base_opts}</select></label>
<label>Retained data GB<input name="persistence_gb" type="number" min="1" max="4096" value="32"></label>
<label>Memory MB<input name="memory_mb" type="number" min="256" value="4096"></label>
<label>CPUs<input name="cpus" type="number" min="1" value="4"></label>
<button class="go">Create overlay</button></form></div></div>
</div>
<h2>Where the library lives</h2><div class="card"><form class="row" onsubmit="submitForm(event,'set_store')">
<label style="flex:1">Folder for templates and disposable OS disks<input name="store" value="{_e(store)}" style="width:100%"></label>
<label style="flex:1">Folder for protected VM and home disks<input name="persistence_store" value="{_e(persistence_store)}" style="width:100%"></label>
<button>Change location</button></form>
<p class="sub warn">Existing VMs stay where they are; the new folder starts as an empty library.</p></div>
</main><script>window.__vmState = {json.dumps(state)};{_JS}</script></body></html>""".encode()


def _requested_distros():
    """Vendor installer sources and current limits, never fabricated LXC variants."""
    entries = (
        ("SparkyLinux", "https://sparkylinux.org/download/", "Desktop ISO → VM; installed OS and retained-home recipe unverified."),
        ("MX Linux", "https://mxlinux.org/download-links/", "Desktop ISO → VM; installed OS and retained-home recipe unverified."),
        ("Zorin OS", "https://zorin.com/os/download/", "Desktop ISO → VM; choose the vendor edition; retained-home recipe unverified."),
        ("Bazzite", "https://bazzite.gg/#image-picker", "OS installer → VM; its OCI build image is not a ready LXC desktop. Graphics/gaming and retained /var/home need validation."),
        ("CachyOS", "https://cachyos.org/download/", "Desktop ISO → VM; its kernel and graphics need VM validation."),
        ("Omarchy", "https://omarchy.org/", "Official ISO → UEFI VM; desktop graphics, encrypted install and retained-home recipe need validation."),
        ("OpenMediaVault", "https://www.openmediavault.org/download.html", "NAS ISO → VM; NAS data disks must be separately retained. Disk attachment, ownership and recovery workflow not implemented here."),
        ("ChromeOS", "https://support.google.com/chromeosflex/answer/11542901", "Google ChromeOS is hardware-specific. ChromeOS Flex is a different product; no ChromeOS guest recipe implemented."),
        ("GrapheneOS", "https://grapheneos.org/build#emulator", "Supported-device releases or a source-built development emulator; not an LXC template. Emulator build/run integration remains open."),
    )
    rows = ''.join(f'<tr><td><a href="{_e(url)}" target="_blank" rel="noopener">{_e(name)}</a></td><td>{_e(note)}</td></tr>'
                   for name, url, note in entries)
    return ('<h2>Requested systems</h2><div class="card"><p><strong>Not installed or boot-verified by Baseline</strong> in this increment. '
            'These vendor links lead to real installer sources, not container substitutes.</p><table>' + rows + '</table>'
            '<p>For an ISO: download and verify the vendor image into the selected installer cache, create an ISO VM below, '
            'install using its console, shut down, eject the ISO, and freeze the clean installation as a base. '
            'New overlays get a separate blank retained disk; it is <strong>not automatically mounted</strong> by these distros. '
            'Configure and verify its filesystem and mount before trusting an OS reset. Ubuntu is the automated retained-home recipe.</p></div>')
