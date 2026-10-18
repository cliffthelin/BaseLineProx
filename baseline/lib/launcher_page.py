"""The launcher page (DR259): a phone-OS-style home screen. One tile per VM/OS; right-click (long-press on touch, the Menu key from the
keyboard) opens its menu: Open in Console / Window / Fullscreen, power, Details, VM settings, OS settings, Applications.

`render(state)` is pure: the state (launcher_state.collect) is embedded as JSON and the page draws from it. Everything dynamic is set with
textContent, never as markup. Dark on purpose: the application shell is dark and this is a screen, not a document."""
from __future__ import annotations

import json


def _embed(state: dict) -> str:
    return json.dumps(state).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render(state: dict, error: str = "") -> bytes:
    banner = ""
    if error:
        import html
        banner = f'<p class="banner" role="alert">{html.escape(error)}</p>'
    return (_PAGE.replace("__STATE__", _embed(state)).replace("__BANNER__", banner)).encode()


_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Launcher</title>
<style>
:root{color-scheme:dark;--ink:#eef0fb;--dim:#a3a8c7;--faint:#6d7396;--glass:rgba(24,26,46,.72);--line:rgba(255,255,255,.12);
--ok:#5ee2a0;--warn:#ffcf5c;--bad:#ff7d86;--font:ui-rounded,"SF Pro Rounded","Segoe UI Variable Display","Segoe UI",system-ui,sans-serif}
*{box-sizing:border-box}
body.phone{margin:0;min-height:100vh;color:var(--ink);font-family:var(--font);
background:radial-gradient(1100px 640px at 12% -8%,rgba(94,92,230,.38),transparent 60%),radial-gradient(900px 560px at 96% 4%,rgba(20,184,166,.28),transparent 60%),
radial-gradient(800px 500px at 50% 110%,rgba(236,72,153,.16),transparent 60%),#0a0c16}
.status{display:flex;align-items:center;gap:1rem;padding:.55rem 1.4rem;font-size:.85rem;color:var(--dim);font-variant-numeric:tabular-nums}
.status .clock{font-weight:650;color:var(--ink);font-size:.95rem}.status .grow{flex:1}
.status .live::before{content:"";display:inline-block;width:.5rem;height:.5rem;border-radius:50%;background:var(--ok);margin-right:.4rem;box-shadow:0 0 .6rem var(--ok)}
.banner{margin:.5rem 1.4rem;padding:.7rem 1rem;border-radius:14px;background:rgba(255,125,134,.14);border:1px solid rgba(255,125,134,.4)}
.home{padding:1.6rem 1.4rem 8rem;max-width:1100px;margin:0 auto}
.grid{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:1.8rem 1rem}
.tile{all:unset;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;gap:.45rem;cursor:pointer;border-radius:22px;padding:.4rem;width:100%}
.tile:focus-visible{outline:3px solid #9db4ff;outline-offset:2px}
.icon{position:relative;width:76px;height:76px;border-radius:22%;display:grid;place-items:center;font-size:2.1rem;font-weight:720;color:#fff;
background:linear-gradient(145deg,hsl(var(--h) 72% 63%),hsl(var(--h) 66% 36%));text-shadow:0 2px 8px rgba(0,0,0,.35);
transition:transform .16s ease,box-shadow .16s ease}
.tile:hover .icon{transform:translateY(-2px) scale(1.04)}.tile:active .icon{transform:scale(.96)}
.tile[data-state=running] .icon{box-shadow:0 0 0 2px rgba(255,255,255,.5),0 8px 26px hsl(var(--h) 85% 58%/.55)}
.tile[data-state=stopped] .icon,.tile[data-state=unknown] .icon,.tile[data-state=preparing] .icon{filter:saturate(.5) brightness(.78)}
.tile .pip{position:absolute;right:-3px;top:-3px;width:15px;height:15px;border-radius:50%;border:2px solid #0a0c16;background:var(--faint)}
.tile[data-state=running] .pip{background:var(--ok)}
.label{font-size:.86rem;font-weight:600;text-align:center;max-width:112px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sub{font-size:.72rem;color:var(--faint);margin-top:-.3rem}
.apps{display:flex;gap:3px}.apps i{font-style:normal;font-size:.55rem;font-weight:700;width:17px;height:17px;border-radius:5px;display:grid;place-items:center;
background:rgba(255,255,255,.1);color:var(--dim);opacity:.6}.apps i[data-support=helper]{outline:1px dashed var(--faint)}.apps i[data-support=none]{opacity:.25}
.empty{max-width:34rem;margin:4rem auto;text-align:center;color:var(--dim);line-height:1.5}
.hint{text-align:center;color:var(--faint);font-size:.8rem;margin-top:2.2rem}
.dock{position:fixed;left:50%;bottom:1rem;transform:translateX(-50%);display:flex;gap:.9rem;padding:.7rem 1rem;border-radius:28px;background:var(--glass);
border:1px solid var(--line);backdrop-filter:blur(18px)}
.dock a{display:flex;flex-direction:column;align-items:center;gap:.2rem;color:var(--ink);text-decoration:none;font-size:.68rem;width:62px}
.dock a b{width:46px;height:46px;border-radius:14px;display:grid;place-items:center;font-size:1.25rem;background:rgba(255,255,255,.12)}
.dock a:hover b,.dock a:focus-visible b{background:rgba(255,255,255,.24)}.dock a:focus-visible{outline:2px solid #9db4ff;border-radius:12px}
#menu{position:fixed;z-index:30;min-width:240px;padding:.4rem;border-radius:16px;background:var(--glass);border:1px solid var(--line);
backdrop-filter:blur(22px);box-shadow:0 18px 50px rgba(0,0,0,.5)}
#menu[hidden],#sheet[hidden],#veil[hidden]{display:none}
#menu .head{padding:.5rem .7rem .4rem;font-size:.75rem;color:var(--dim);border-bottom:1px solid var(--line);margin-bottom:.3rem}
#menu button{all:unset;box-sizing:border-box;display:block;width:100%;padding:.5rem .7rem;border-radius:10px;cursor:pointer;font-size:.92rem}
#menu button:hover:not([aria-disabled=true]),#menu button:focus-visible{background:rgba(255,255,255,.14);outline:none}
#menu button[aria-disabled=true]{color:var(--faint);cursor:not-allowed}#menu button small{display:block;font-size:.72rem;color:var(--faint)}
#menu button.danger{color:var(--bad)}#menu hr{border:0;border-top:1px solid var(--line);margin:.3rem 0}
#veil{position:fixed;inset:0;background:rgba(5,6,12,.55);z-index:40}
#sheet{position:fixed;z-index:41;left:50%;bottom:0;transform:translateX(-50%);width:min(680px,100%);max-height:86vh;overflow:auto;padding:1rem 1.4rem 1.6rem;
border-radius:26px 26px 0 0;background:#14162a;border:1px solid var(--line);border-bottom:0;box-shadow:0 -20px 60px rgba(0,0,0,.55);animation:rise .22s ease}
@keyframes rise{from{transform:translate(-50%,24px);opacity:0}}
@media (prefers-reduced-motion:reduce){#sheet{animation:none}.icon{transition:none}}
#sheet .grab{width:42px;height:5px;border-radius:3px;background:var(--line);margin:0 auto .8rem}
#sheet h2{margin:.2rem 0 .2rem;font-size:1.25rem}#sheet p.note{color:var(--dim);font-size:.85rem;margin:.2rem 0 1rem;line-height:1.45}
#sheet dl{display:grid;grid-template-columns:max-content 1fr;gap:.45rem 1.2rem;margin:0}#sheet dt{color:var(--dim)}#sheet dd{margin:0;overflow-wrap:anywhere}
.row{display:grid;grid-template-columns:minmax(9.5rem,13rem) 1fr;gap:.4rem 1rem;align-items:center;padding:.65rem 0;border-top:1px solid var(--line)}
.row .name{font-weight:600}.row .src{font-size:.72rem;color:var(--faint)}
.row .ctl{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;justify-content:flex-start}
input[type=text],input[type=number],select{background:#0d0f1f;color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:.45rem .6rem;font:inherit;min-width:9rem}
input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid #9db4ff}
.btn{background:rgba(255,255,255,.12);color:var(--ink);border:0;border-radius:10px;padding:.45rem .8rem;font:inherit;cursor:pointer}
.btn.go{background:#4f5bd5}.btn:hover{filter:brightness(1.2)}
.badge{font-size:.68rem;padding:.12rem .45rem;border-radius:999px;background:rgba(255,255,255,.12);color:var(--dim)}
.badge.native{background:rgba(94,226,160,.16);color:var(--ok)}.badge.helper{background:rgba(255,207,92,.15);color:var(--warn)}
#toast{position:fixed;left:50%;top:3.2rem;transform:translateX(-50%);z-index:60;max-width:90vw;padding:.65rem 1.1rem;border-radius:14px;background:var(--glass);
border:1px solid var(--line);backdrop-filter:blur(18px)}#toast[hidden]{display:none}
.tile.ghost{opacity:.62;border-style:dashed;text-decoration:none}.tile.ghost:hover,.tile.ghost:focus-visible{opacity:1}h2.section{margin:1.4rem 0 .4rem;font-size:1rem}
</style></head>
<body class="phone">
<div class="status" role="status"><span class="clock" id="clock"></span><span id="host"></span><span class="grow"></span><span class="live" id="live"></span></div>
__BANNER__
<div id="notices"></div>
<main class="home" id="home"></main>
<nav class="dock" aria-label="Quick links">
<a id="pve" href="#" target="_blank" rel="noopener"><b aria-hidden="true">P</b>Proxmox</a>
<a href="/shell"><b aria-hidden="true">&gt;_</b>Console</a>
<a href="/hardware"><b aria-hidden="true">H</b>Hardware</a>
<a href="/audio"><b aria-hidden="true">B</b>Bluetooth</a>
<a href="/power"><b aria-hidden="true">&#x23FB;</b>Power</a>
</nav>
<div id="menu" role="menu" hidden></div>
<div id="veil" hidden></div>
<section id="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" hidden></section>
<div id="toast" role="status" aria-live="polite" hidden></div>
<script id="state" type="application/json">__STATE__</script>
<script>
"use strict";
let S = JSON.parse(document.getElementById('state').textContent);
const $ = id => document.getElementById(id);
const el = (tag, props, ...kids) => { const n = document.createElement(tag); Object.assign(n, props || {});
  for (const k of kids.flat()) n.append(k instanceof Node ? k : document.createTextNode(String(k))); return n; };
const pveBase = () => 'https://' + location.hostname + ':8006';
const APP_INITIALS = {vscode:'VS', spotify:'Sp', chrome:'Ch', chatgpt:'GP', claude:'Cl'};
let lastFocus = null;

function toast(text){ const t = $('toast'); t.textContent = text; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 5000); }
function tick(){ $('clock').textContent = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }

function draw(){
  $('host').textContent = S.host;
  const running = S.tiles.filter(t => t.state === 'running').length;
  $('live').textContent = running ? running + ' running' : '';
  $('notices').replaceChildren(...(S.notices || []).map(n => el('p', {className:'banner', role:'status'}, n)));
  const home = $('home'); home.replaceChildren();
  if (!S.tiles.length){
    home.append(el('div', {className:'empty'}, el('h2', {}, 'No virtual machines yet'),
      el('p', {}, 'Create one from '), el('a', {href:'/vms'}, 'Virtual machines'), '. Each one appears here as a tile with its own menu.'));
    return;
  }
  const grid = el('ul', {className:'grid'});
  for (const t of S.tiles){
    const b = el('button', {className:'tile', type:'button'});
    b.dataset.state = t.state; b.dataset.id = t.id || ''; b.style.setProperty('--h', t.icon.hue);
    b.setAttribute('aria-haspopup', 'menu'); b.setAttribute('aria-label', t.name + ', ' + t.state + '. Open the menu with the Menu key or a long press.');
    const icon = el('span', {className:'icon'}, t.icon.letter, el('span', {className:'pip'}));
    const apps = el('span', {className:'apps', title:'Applications (installation is not reported yet)'});
    for (const a of t.apps){ const i = el('i', {}, APP_INITIALS[a.key]); i.dataset.support = a.support; apps.append(i); }
    b.append(icon, el('span', {className:'label'}, t.name),
      el('span', {className:'sub'}, (t.kind === 'ct' ? 'container · ' : '') + (t.os.family + ' ' + t.os.release).trim() + ' · ' + t.state), apps);
    wire(b, t); grid.append(el('li', {}, b));
  }
  home.append(grid, el('p', {className:'hint'}, 'Click a running tile to open it. Right-click (or long-press) a tile for its menu.'));
  drawAvailable(home);
}

function drawAvailable(home){
  const list = S.available || [];
  if (!list.length) return;
  const row = el('ul', {className:'grid available'});
  for (const a of list){
    const b = el('button', {className:'tile ghost', type:'button'});
    b.dataset.image = a.image; b.dataset.blocked = a.blocked ? 'yes' : 'no'; b.style.setProperty('--h', (a.os.family.length * 47) % 360);
    b.title = a.blocked ? 'Cannot be created here: ' + a.blocked : (a.plan.prebuilt ? 'Ready-made: ' : '') + (a.plan.disk_gb + ' GB disk, ' + a.plan.memory_mb + ' MB, ' + a.plan.cpus + ' CPUs');
    b.append(el('span', {className:'icon'}, (a.name[0] || '?').toUpperCase()), el('span', {className:'label'}, a.name),
      el('span', {className:'sub'}, a.blocked ? 'not built · cannot be created here' : (a.plan.prebuilt ? 'ready-made · create' : 'not built · create')));
    b.addEventListener('click', () => createFromList(a));
    row.append(el('li', {}, b));
  }
  home.append(el('h2', {className:'section'}, 'Available to create'), row,
    el('p', {className:'hint'}, 'From your supported-OS list. Choose one to create it (it is created stopped; start it to begin the installer).'));
}

async function createFromList(a){
  if (a.blocked){ toast(a.name + ' cannot be created here: ' + a.blocked); return; }
  const p = a.plan;
  if (p.prebuilt){
    if (!confirm('Create ' + a.name + ' from its ready-made base?\n\nIt already has its desktop and applications; no installer runs. ' + p.memory_mb + ' MB memory, ' + p.cpus + ' CPUs, UEFI.\nIt is created stopped. When you start it you are signed in as yourself; there is no separate login.')) return;
    return power({kind:'vm'}, 'create_prebuilt', {name:p.name, os:p.os, memory_mb:p.memory_mb, cpus:p.cpus});
  }
  if (!confirm('Create ' + a.name + ' from ' + p.iso + '?\n\n' + p.disk_gb + ' GB disk, ' + p.memory_mb + ' MB memory, ' + p.cpus + ' CPUs, UEFI.\nIt is created stopped. You can change these afterwards in VM settings.')) return;
  return power({kind:'vm'}, 'create_iso', {name:p.name, iso:p.iso, disk_gb:p.disk_gb, memory_mb:p.memory_mb, cpus:p.cpus, firmware:p.firmware});
}

function wire(b, t){
  let timer = null, fired = false;
  b.addEventListener('contextmenu', e => { e.preventDefault(); openMenu(t, e.clientX, e.clientY, b); });
  b.addEventListener('keydown', e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')){ e.preventDefault();
    const r = b.getBoundingClientRect(); openMenu(t, r.left + r.width / 2, r.bottom, b); } });
  b.addEventListener('pointerdown', e => { if (e.pointerType !== 'touch') return; fired = false;
    timer = setTimeout(() => { fired = true; openMenu(t, e.clientX, e.clientY, b); }, 550); });
  for (const ev of ['pointerup', 'pointercancel', 'pointermove']) b.addEventListener(ev, () => clearTimeout(timer));
  b.addEventListener('click', e => { if (fired){ fired = false; e.preventDefault(); return; }
    if (t.state === 'running') openDefault(t); else { const r = b.getBoundingClientRect(); openMenu(t, r.left + r.width / 2, r.bottom, b); } });
}

function defaultMode(t){
  const pref = t.settings && t.settings.os.default_run_mode && t.settings.os.default_run_mode.value;
  return (pref && t.paths[pref]) ? pref : (t.paths.window ? 'window' : Object.keys(t.paths)[0]);
}
function openDefault(t){ const m = defaultMode(t); if (m) openMode(t, m); else toast(t.name + ' has nothing to open yet.'); }

function openMode(t, mode){
  const path = t.paths[mode];
  if (!path){ toast(t.name + ': ' + ((t.modes.find(m => m.id === mode) || {}).hint || 'not available')); return; }
  const url = pveBase() + path, name = 'bl-' + t.id + '-' + mode;
  let w = null;
  if (mode === 'console') w = window.open(url, '_blank');
  else if (mode === 'window') w = window.open(url, name, 'popup,width=1280,height=800');
  else w = window.open(url, name, 'popup,left=0,top=0,width=' + screen.availWidth + ',height=' + screen.availHeight);
  if (w === null && mode !== 'console') toast('The browser may have blocked the window. Allow pop-ups for this page, or open ' + url);
  sessionNote(t, mode);
}
function sessionNote(t, mode){ /* the last mode used is session-only state; it is not persisted by the page */ }

function closeMenu(){ $('menu').hidden = true; }
function openMenu(t, x, y, from){
  lastFocus = from; const m = $('menu'); m.replaceChildren();
  m.append(el('div', {className:'head'}, t.name + ' · ' + t.state));
  let group = '';
  for (const item of t.menu){
    const g = item.id.startsWith('open_') ? 'open' : (['start','shutdown','force_stop'].includes(item.id) ? 'power' : 'panel');
    if (group && g !== group) m.append(el('hr'));
    group = g;
    const b = el('button', {type:'button', role:'menuitem'}, item.label);
    if (item.id === 'force_stop') b.classList.add('danger');
    if (item.hint) b.append(el('small', {}, item.hint));
    if (!item.enabled) b.setAttribute('aria-disabled', 'true');
    b.addEventListener('click', () => { if (!item.enabled) return; closeMenu(); choose(t, item.id); });
    m.append(b);
  }
  m.hidden = false;
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.max(8, Math.min(x, innerWidth - w - 8)) + 'px';
  m.style.top = Math.max(8, Math.min(y, innerHeight - h - 8)) + 'px';
  const first = m.querySelector('button:not([aria-disabled])'); if (first) first.focus();
}
document.addEventListener('click', e => { if (!$('menu').contains(e.target)) closeMenu(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape'){ if (!$('sheet').hidden) closeSheet(); else { closeMenu(); if (lastFocus) lastFocus.focus(); } }
  const m = $('menu'); if (m.hidden || !['ArrowDown','ArrowUp'].includes(e.key)) return; e.preventDefault();
  const items = [...m.querySelectorAll('button:not([aria-disabled])')]; const i = items.indexOf(document.activeElement);
  items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
});

async function choose(t, id){
  if (id.startsWith('open_')) return openMode(t, id.slice(5));
  if (id === 'start') return power(t, 'start', {name: t.name});
  if (id === 'shutdown') return power(t, 'request_stop', {name: t.name});
  if (id === 'force_stop'){ if (!confirm('Force stop ' + t.name + '? Recent writes can be lost and its filesystems can be damaged.')) return;
    return power(t, 'force_stop', {name: t.name}); }
  return openSheet(t, id);
}

async function power(t, action, params){
  toast('Working…');
  try{
    // containers have their own action endpoint and call a clean stop 'shutdown'
    const endpoint = t.kind === 'ct' ? '/containers/action' : '/vms/action';
    const verb = (t.kind === 'ct' && action === 'request_stop') ? 'shutdown' : action;
    const r = await fetch(endpoint, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Object.assign({action: verb, request_id: crypto.randomUUID()}, params))});
    let j = await r.json();
    if (r.status === 202 && j.job_id){
      for (;;){
        await new Promise(res => setTimeout(res, 1000));
        const s = await fetch('/workloads/job?job_id=' + encodeURIComponent(j.job_id)); const job = await s.json();
        if (!s.ok) throw new Error(job.error || 'job status unavailable');
        toast(job.state + ': ' + ((job.result && job.result.message) || action));
        if (['completed','failed','interrupted','reviewed'].includes(job.state)){
          const res = await fetch('/workloads/result', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({job_id: j.job_id})});
          j = await res.json(); break; }
      }
    }
    toast(j.message || (j.ok ? 'Done' : 'Failed'));
  }catch(e){ toast('Connection lost. Check the tile before retrying.'); }
  await refresh();
}

async function refresh(){
  try{ const r = await fetch('/launcher/state'); if (r.ok){ S = await r.json(); draw(); } }catch(e){}
}

function closeSheet(){ $('sheet').hidden = true; $('veil').hidden = true; if (lastFocus && document.contains(lastFocus)) lastFocus.focus(); }
$('veil').addEventListener('click', closeSheet);

function openSheet(t, panel){
  const sh = $('sheet'); sh.replaceChildren();
  const title = {details:'Details', vm_settings:'VM settings', os_settings:'OS settings', applications:'Applications'}[panel];
  sh.append(el('div', {className:'grab'}), el('h2', {id:'sheet-title', tabIndex:-1}, t.name + ' · ' + title));
  if (panel === 'details') details(sh, t);
  else if (panel === 'vm_settings') vmSettings(sh, t);
  else if (panel === 'os_settings') osSettings(sh, t);
  else appsPanel(sh, t);
  sh.append(el('div', {className:'row'}, el('span'), el('span', {className:'ctl'}, el('button', {className:'btn', type:'button', onclick:closeSheet}, 'Close'))));
  $('veil').hidden = false; sh.hidden = false; $('sheet-title').focus();
}

function details(sh, t){
  const dl = el('dl'); for (const [k, v] of t.details) dl.append(el('dt', {}, k), el('dd', {}, v)); sh.append(dl);
}

function vmSettings(sh, t){
  sh.append(el('p', {className:'note'}, 'Applied by Proxmox the next time the VM starts. The VM must be shut down to change these.'));
  const mem = el('input', {type:'number', min:256, step:256, value:t.memory_mb, id:'f-mem'});
  const cpu = el('input', {type:'number', min:1, max:128, value:t.cpus, id:'f-cpu'});
  const save = el('button', {className:'btn go', type:'button'}, 'Save');
  save.onclick = async () => { closeSheet(); await power(t, 'configure', {name:t.name, memory_mb:Number(mem.value), cpus:Number(cpu.value)}); };
  sh.append(el('div', {className:'row'}, el('label', {htmlFor:'f-mem', className:'name'}, 'Memory (MB)'), el('span', {className:'ctl'}, mem)),
            el('div', {className:'row'}, el('label', {htmlFor:'f-cpu', className:'name'}, 'CPUs'), el('span', {className:'ctl'}, cpu)),
            el('div', {className:'row'}, el('span'), el('span', {className:'ctl'}, save)));
}

const SOURCE = {admin:'set by the administrator', user:'your setting, shared by every OS', os:'your setting for this OS only', app:'this application in this OS'};
async function writeSetting(t, layer, app, changes){
  const r = await fetch('/launcher/settings', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id:t.id, layer, app, changes})});
  const j = await r.json().catch(() => ({}));
  toast(r.ok ? 'Saved' : (j.error || 'Not saved')); await refresh();
  const fresh = S.tiles.find(x => x.id === t.id); return fresh || t;
}

function settingsGuard(sh, t){
  if (t.settings) return false;
  sh.append(el('p', {className:'note', role:'alert'}, 'Settings are not available: ' + (t.settings_error || 'unknown reason') +
    '. Nothing is saved while they are unavailable.')); return true;
}

function osSettings(sh, t){
  if (settingsGuard(sh, t)) return;
  sh.append(el('p', {className:'note'}, 'Saved on your own volume, never on the disposable system. "All my OSes" is shared with every OS; "Only this OS" is a difference for ' + t.name +
    '. Applying them inside the OS happens when the OS is set up; that step is not built yet.'));
  for (const [key, f] of Object.entries(S.schema.os)){
    const cur = t.settings.os[key];
    const input = f.type === 'choice' ? el('select', {id:'f-' + key}, f.choices.map(c => el('option', {value:String(c), selected: cur && String(cur.value) === String(c)}, String(c))))
      : el('input', {type:'text', id:'f-' + key, value: cur ? cur.value : '', placeholder:f.example || '', pattern:f.pattern, size:16});
    if (f.type === 'choice' && !cur) input.insertBefore(el('option', {value:'', selected:true}, 'not set'), input.firstChild);
    const scope = el('select', {'aria-label':'Where to save ' + f.label}, el('option', {value:'user'}, 'All my OSes'), el('option', {value:'os'}, 'Only this OS'));
    if (cur && cur.source === 'os') scope.value = 'os';
    const save = el('button', {className:'btn go', type:'button'}, 'Save');
    save.onclick = async () => { if (input.value === '') return toast('Choose a value, or use "Use inherited".');
      const v = f.numeric ? Number(input.value) : input.value;
      const fresh = await writeSetting(t, scope.value, null, {[key]: v}); openSheet(fresh, 'os_settings'); };
    const reset = el('button', {className:'btn', type:'button'}, 'Use inherited');
    reset.onclick = async () => { const fresh = await writeSetting(t, scope.value, null, {[key]: null}); openSheet(fresh, 'os_settings'); };
    sh.append(el('div', {className:'row'}, el('div', {}, el('label', {htmlFor:'f-' + key, className:'name'}, f.label),
      el('div', {className:'src'}, cur ? SOURCE[cur.source] : 'not set')), el('span', {className:'ctl'}, input, scope, save, reset)));
  }
}

function appsPanel(sh, t){
  if (settingsGuard(sh, t)) return;
  sh.append(el('p', {className:'note'}, 'Which applications this OS should have, from your settings. Whether each is installed is not reported yet, so nothing here claims it. ' +
    '"native" means the application supports this OS; "helper" means it needs an adapter that is not built.'));
  for (const a of S.apps){
    const meta = t.apps.find(x => x.key === a.key), cur = t.settings.apps[a.key];
    const box = (key, label) => { const c = el('input', {type:'checkbox', checked: !!(cur[key] && cur[key].value)});
      c.onchange = async () => { const fresh = await writeSetting(t, 'app', a.key, {[key]: c.checked}); openSheet(fresh, 'applications'); };
      return el('label', {}, c, ' ' + label); };
    sh.append(el('div', {className:'row'}, el('div', {}, el('span', {className:'name'}, a.label + ' '),
      el('span', {className:'badge ' + meta.support}, meta.support), el('div', {className:'src'}, 'installed: not reported')),
      el('span', {className:'ctl'}, box('enabled', 'Wanted'), box('autostart', 'Start with the OS'))));
  }
}

$('pve').href = pveBase() + '/';
tick(); setInterval(tick, 30000); draw();
setInterval(() => { if ($('sheet').hidden && $('menu').hidden) refresh(); }, 15000);
</script>
</body></html>
"""
