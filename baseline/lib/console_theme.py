"""The one look every console page shares: the Launcher's night-glass (violet and teal light over deep navy, frosted rounded cards, a rounded type face, soft accents).

A change here is a change to every page: the menu, headings, cards, selectors, switches, tables and buttons are all defined once, and the shared shell injects this into every page it wraps,
including pages that still carry older styling of their own (they are re-skinned by the element rules; the component classes are for pages built on them).

Components for pages: `.page-head` (`.eyebrow`, `h1`, `.lead`), `.grid` of `.card`, `.tiles` (large single-choice tiles: a radio input then a label), `.seg` (a short segmented choice),
`.switch` (an on/off toggle), `.chips` (quick presets), `.btn` / `.btn.primary`, `.note`, `.stat`. Typing into a field is the last resort: offer a choice first and reveal a field only for "Other".
"""

CSS = r"""
:root{color-scheme:dark;--ink:#eef0fb;--dim:#a3a8c7;--faint:#6d7396;--glass:rgba(24,26,46,.72);--glass-2:rgba(255,255,255,.06);--line:rgba(255,255,255,.12);
--accent:#5fd6c4;--accent-ink:#06211d;--violet:#8b87ff;--ok:#5ee2a0;--warn:#ffcf5c;--bad:#ff7d86;--r:20px;--r-sm:12px;
--font:ui-rounded,"SF Pro Rounded","Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;--mono:ui-monospace,"SF Mono","Cascadia Code",Menlo,monospace}
*{box-sizing:border-box}
html{background:#0a0c16}
body{margin:0;min-height:100vh;padding:0 clamp(1rem,3vw,2.4rem) 4rem;color:var(--ink);font-family:var(--font);font-size:15px;line-height:1.55;
background:radial-gradient(1100px 640px at 12% -8%,rgba(94,92,230,.38),transparent 60%),radial-gradient(900px 560px at 96% 4%,rgba(20,184,166,.28),transparent 60%),
radial-gradient(800px 500px at 50% 110%,rgba(236,72,153,.16),transparent 60%),#0a0c16;background-attachment:fixed}
a{color:#a9b8ff;text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:clamp(1.7rem,3vw,2.3rem);line-height:1.15;margin:.2rem 0 .4rem;letter-spacing:-.01em}h2{font-size:1.15rem;margin:1.4rem 0 .5rem}h3{font-size:1rem;margin:1rem 0 .4rem}
p{max-width:70ch}small,.dim{color:var(--dim)}
/* ---- menu ---- */
.baseline-nav{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;align-items:center;gap:.4rem .5rem;margin:0 calc(-1*clamp(1rem,3vw,2.4rem)) 1.4rem;padding:.7rem clamp(1rem,3vw,2.4rem);
background:rgba(10,12,22,.78);backdrop-filter:blur(14px);border-bottom:1px solid var(--line);font-size:.92rem}
.baseline-nav a{color:var(--dim);padding:.3rem .7rem;border-radius:999px;text-decoration:none}.baseline-nav a:hover{color:var(--ink);background:var(--glass-2)}
.baseline-nav a.active{color:var(--accent-ink);background:var(--accent);font-weight:650}
.nav-group{display:contents}.nav-group summary{cursor:pointer;list-style:none;color:var(--dim);padding:.3rem .8rem;border-radius:999px;font-weight:600;border:1px solid transparent}
.nav-group summary::-webkit-details-marker{display:none}.nav-group summary:hover{color:var(--ink);background:var(--glass-2)}
.nav-group[open] summary{color:var(--ink);border-color:var(--line);background:var(--glass-2)}
.nav-group[open] .nav-items{order:5;flex-basis:100%}.nav-items{display:none;flex-wrap:wrap;align-items:center;gap:.3rem .4rem;padding:.35rem 0 .1rem}.nav-group[open] .nav-items{display:flex}
.nav-sub{display:flex;flex-wrap:wrap;align-items:center;gap:.3rem .4rem;padding-left:.8rem;margin-left:.4rem;border-left:2px solid var(--line)}
.nav-sub-label{color:var(--faint);font-size:.72rem;text-transform:uppercase;letter-spacing:.09em}
.nav-status{order:6;flex-basis:100%;color:var(--dim);font-size:.82rem;font-variant-numeric:tabular-nums}
html[data-mode="simple"] .adv,html[data-mode="simple"] .m-adv{display:none!important}html[data-mode="advanced"] .m-simple{display:none!important}
.mode-switch{margin-left:auto;display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden}
.mode-switch button{margin:0;border:0;border-radius:0;background:transparent;color:var(--dim);padding:.3rem .85rem;cursor:pointer;font:inherit}
html[data-mode="simple"] .mode-switch [data-mode="simple"],html[data-mode="advanced"] .mode-switch [data-mode="advanced"]{background:var(--violet);color:#0b0b22;font-weight:650}
.baseline-nav form{margin:0}.baseline-nav button,.baseline-nav button[type=submit]{background:var(--glass-2);color:var(--ink);font-weight:500;border:1px solid var(--line);padding:.3rem .85rem}
.baseline-nav form button[type=submit]{border-color:rgba(255,125,134,.45);color:#ffb3b9}.baseline-nav form button[type=submit]:hover{background:rgba(255,125,134,.14)}
/* ---- page head ---- */
.page-head{margin:.4rem 0 1.4rem}.eyebrow{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);font-weight:650}.lead{color:var(--dim);font-size:1.05rem;margin:.1rem 0}
/* ---- cards ---- */
.grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(min(100%,19rem),1fr));align-items:start}
.card,fieldset,.chart,.hw-overview,.vm-usage{background:var(--glass);border:1px solid var(--line);border-radius:var(--r);padding:1.1rem 1.25rem;backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(0,0,0,.25)}
.card h2:first-child{margin-top:0}fieldset{margin:1rem 0}legend{padding:0 .5rem;color:var(--dim);font-size:.78rem;letter-spacing:.1em;text-transform:uppercase}
.note,.ra-warn{border:1px solid rgba(255,207,92,.45);background:rgba(255,207,92,.1);border-radius:var(--r-sm);padding:.6rem .9rem}
/* ---- choices ---- */
.tiles{display:grid;gap:.8rem;grid-template-columns:repeat(auto-fit,minmax(min(100%,14rem),1fr));margin:.6rem 0}
.tiles input,.seg input,.chips input{position:absolute;opacity:0;pointer-events:none}
.tiles label.tile{display:block;cursor:pointer;padding:1rem 1.1rem;border-radius:var(--r);border:1px solid var(--line);background:var(--glass-2);transition:transform .12s,border-color .12s,background .12s}
.tiles label.tile:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.28)}
.tiles label.tile b{display:block;font-size:1.02rem}.tiles label.tile span{display:block;color:var(--dim);font-size:.88rem;margin-top:.2rem}
.tiles input:checked+label.tile{border-color:var(--accent);background:rgba(95,214,196,.12);box-shadow:0 0 0 2px rgba(95,214,196,.35) inset}
.tiles input:focus-visible+label.tile,.seg input:focus-visible+label,.chips input:focus-visible+label,.switch input:focus-visible+i{outline:2px solid #9db4ff;outline-offset:2px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;background:var(--glass-2)}
.seg label{cursor:pointer;padding:.45rem 1.1rem;color:var(--dim)}.seg input:checked+label{background:var(--violet);color:#0b0b22;font-weight:650}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;margin:.4rem 0}.chips label{cursor:pointer;padding:.35rem .9rem;border-radius:999px;border:1px solid var(--line);color:var(--dim);background:var(--glass-2)}
.chips input:checked+label{border-color:var(--accent);color:var(--ink);background:rgba(95,214,196,.14)}
.switch{display:flex;align-items:center;gap:.8rem;cursor:pointer;margin:.6rem 0}.switch input{position:absolute;opacity:0}
.switch i{flex:none;width:46px;height:26px;border-radius:999px;background:rgba(255,255,255,.16);position:relative;transition:background .15s}
.switch i::after{content:"";position:absolute;left:3px;top:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:transform .15s}
.switch input:checked+i{background:var(--accent)}.switch input:checked+i::after{transform:translateX(20px)}.switch input:disabled+i{opacity:.4}
.switch span{color:var(--ink)}.switch small{display:block;color:var(--dim)}
.reveal{margin-top:.5rem}.reveal summary{cursor:pointer;color:var(--dim);font-size:.9rem}
/* ---- buttons, fields, tables ---- */
button,.btn{font:inherit;cursor:pointer;color:var(--ink);background:var(--glass-2);border:1px solid var(--line);border-radius:999px;padding:.5rem 1.1rem}
button:hover,.btn:hover{background:rgba(255,255,255,.12);text-decoration:none}button:disabled{opacity:.45;cursor:not-allowed}
button.primary,.btn.primary,button[type=submit]{background:linear-gradient(135deg,#6fe3d0,#3fb8a8);color:var(--accent-ink);border-color:transparent;font-weight:700}
input[type=text],input[type=number],input[type=password],input[type=search],input:not([type]),select,textarea{font:inherit;color:var(--ink);background:rgba(0,0,0,.28);border:1px solid var(--line);border-radius:var(--r-sm);padding:.5rem .7rem;max-width:100%}
input:focus,select:focus,textarea:focus{outline:2px solid #9db4ff;outline-offset:1px}
table{border-collapse:separate;border-spacing:0;width:100%;background:var(--glass);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;margin:.8rem 0}
th{text-align:left;font-size:.72rem;letter-spacing:.09em;text-transform:uppercase;color:var(--dim);padding:.7rem 1rem;background:rgba(255,255,255,.04)}
td{padding:.65rem 1rem;border-top:1px solid var(--line);vertical-align:top}tr:hover td{background:rgba(255,255,255,.03)}
details>summary{cursor:pointer}pre,code{font-family:var(--mono);font-size:.86em}pre{white-space:pre-wrap;background:rgba(0,0,0,.28);border-radius:var(--r-sm);padding:.7rem .9rem}
figure.chart{margin:.6rem 0;display:inline-block}figure.chart svg{color:var(--accent);display:block}figure.chart figcaption{color:var(--dim);font-size:.82rem;margin-top:.3rem}
[role=status]{color:var(--dim)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media (max-width:640px){.baseline-nav{position:static}}
"""


def style_tag() -> str:
    return f'<style id="baseline-shell-style">{CSS}</style>'
