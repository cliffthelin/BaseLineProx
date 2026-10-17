"""The Kasm settings screens: a plain-language view and an advanced view of all of them (DR260/DR263; operator 2026-10-17).

Both are over the SAME live data: Kasm's own list of its server settings, read through its admin API from inside the VM (so the titles, descriptions, types, which services a change restarts and the
current values are Kasm's, not a copy that can drift). Both write the same way: a change is validated here against the setting's type, then made through Kasm's own admin API (which does the encrypting)
and read back to check it took. Secrets are never shown or changed here (a "set" marker only). Group settings (clipboard, downloads, audio and the like) are a different part of Kasm and not covered.

`SIMPLE` is a curated start, not a claim about what matters most: each control names one setting, says in plain words what it does and what it costs, and shows it in the unit a person thinks in
(hours rather than seconds). Kasm's own description is shown with it; where Kasm's wording is the only thing known, its wording is used.
"""
from __future__ import annotations

import html
import json

import kasm_settings as ks

SettingsError = ks.SettingsError

# kind: number (stored / scale is shown), toggle, text. min and max are in the SHOWN unit.
SIMPLE = (
    {"id": "logs", "title": "How long Kasm keeps its logs", "help": "Kasm writes logs on its own disk. Keeping them longer keeps more history for finding problems and uses more space. Kasm warns to read its documentation before changing these.",
     "controls": [{"setting": "log_retention", "label": "Normal logs", "kind": "number", "unit": "days", "min": 1, "max": 365},
                  {"setting": "debug_retention", "label": "Debug logs", "kind": "number", "unit": "hours", "min": 1, "max": 720}]},
    {"id": "signin", "title": "How long a sign-in lasts", "help": "How long a person stays signed in before they must sign in again. Shorter is safer on shared screens; longer is less interruption.",
     "controls": [{"setting": "session_lifetime", "label": "Stay signed in for", "kind": "number", "unit": "hours", "scale": 3600, "min": 1, "max": 720}]},
    {"id": "lockout", "title": "Locking an account after wrong passwords", "help": "How many wrong passwords in a row lock a local account. It does not apply to accounts that sign in through another service.",
     "controls": [{"setting": "max_login_attempts", "label": "Wrong passwords allowed", "kind": "number", "unit": "attempts", "min": 1, "max": 20}]},
    {"id": "idle", "title": "How long an idle session is kept", "help": "The open workspace sends a signal while someone is using it. This is how long Kasm keeps a session after the last signal. Shorter frees memory sooner; longer lets people step away.",
     "controls": [{"setting": "keepalive_expiration", "label": "Keep an idle session for", "kind": "number", "unit": "minutes", "scale": 60, "min": 1, "max": 1440}]},
    {"id": "passwords", "title": "Password rules", "help": "What a local password must contain. Stricter rules protect accounts and make passwords harder to remember.",
     "controls": [{"setting": "password_min_length", "label": "Shortest allowed", "kind": "number", "unit": "characters", "min": 4, "max": 64},
                  {"setting": "password_require_uppercase", "label": "Needs a capital letter", "kind": "toggle"},
                  {"setting": "password_require_lowercase", "label": "Needs a small letter", "kind": "toggle"},
                  {"setting": "password_require_numbers", "label": "Needs a number", "kind": "toggle"},
                  {"setting": "password_require_special_characters", "label": "Needs a symbol", "kind": "toggle"}]},
    {"id": "notice", "title": "A notice at sign-in", "help": "A message shown to people before they sign in (for example who may use this, or that use is monitored). Leave the message empty for none.",
     "controls": [{"setting": "notice_title", "label": "Title", "kind": "text", "max": 80}, {"setting": "notice_message", "label": "Message", "kind": "text", "max": 2000, "multiline": True}]},
    {"id": "images", "title": "New workspaces and everyone's group", "help": "When a workspace is added to Kasm, whether it is also made available to the default group (everyone) straight away.",
     "controls": [{"setting": "add_images_to_default_group", "label": "Offer new workspaces to everyone", "kind": "toggle"}]},
    {"id": "agents", "title": "New machines that run workspaces", "help": "When another machine joins Kasm to run workspaces, whether it is switched on automatically. Leave off unless you add machines often and trust the network.",
     "controls": [{"setting": "auto_agent", "label": "Switch new machines on automatically", "kind": "toggle"}]},
    {"id": "updates", "title": "Checking for Kasm updates", "help": "Kasm's own description: \"This setting will stop the manager from checking for Kasm system updates.\" A machine with no internet gains nothing from checking.",
     "controls": [{"setting": "update_check", "label": "Update check", "kind": "toggle"}]},
)


def _index(live: list) -> dict:
    return {row["name"]: row for row in live}


def _shown(control: dict, row: dict) -> str:
    """The current value in the unit shown."""
    value = row.get("value")
    if value is None:
        return ""
    if control["kind"] == "number" and control.get("scale"):
        try:
            number = float(value) / control["scale"]
            return str(int(number)) if number == int(number) else f"{number:g}"
        except ValueError:
            return str(value)
    return str(value)


def _stored(control: dict, shown: str) -> str:
    """What Kasm stores for a value typed in the shown unit."""
    if control["kind"] == "number":
        try:
            number = float(shown)
        except ValueError:
            raise SettingsError(f"{control['label']} must be a number") from None
        low, high = control.get("min"), control.get("max")
        if (low is not None and number < low) or (high is not None and number > high):
            raise SettingsError(f"{control['label']} must be between {low} and {high} {control['unit']}".replace("  ", " ").strip())
        number *= control.get("scale", 1)
        return str(int(number)) if number == int(number) else str(number)
    if control["kind"] == "toggle":
        if shown not in ("True", "False"):
            raise SettingsError(f"{control['label']} is on or off")
        return shown
    if len(shown) > control.get("max", 2000):
        raise SettingsError(f"{control['label']} is too long")
    return shown


def plan(live: list, requested: dict) -> list:
    """Check a set of requested changes {name: value} against the live settings and return what to do: [{name, id, old, new, restart}] for those that differ. Refuses an unknown
    setting, a secret, an ill-typed value, and a setting Kasm gave no id for. A value equal to the current one is not a change."""
    rows = _index(live)
    changes = []
    for name, value in requested.items():
        row = rows.get(name)
        if row is None:
            raise SettingsError(f"{name} is not a setting this Kasm has")
        if row["secret"]:
            raise SettingsError(f"{row['title']} is a secret; it is not changed here")
        if not row.get("id"):
            raise SettingsError(f"Kasm gave no identifier for {row['title']}; it cannot be changed here")
        new = ks.normalise({"name": name, "type": row["type"]}, value)
        if new != (row["value"] if row["value"] is not None else ""):
            changes.append({"name": name, "id": row["id"], "old": row["value"], "new": new, "restart": row["restart"], "title": row["title"]})
    return changes


def default_shown() -> list:
    """The everyday view as shipped: the curated controls, in order."""
    return [c["setting"] for item in SIMPLE for c in item["controls"]]


def _generic(row: dict) -> dict:
    """A control for a setting the curated list does not know: its type decides the input, and Kasm's own title and description are all the wording there is."""
    kind = "toggle" if row["type"] == "bool" else "number" if row["type"] in ("int", "float") else "text"
    control = {"setting": row["name"], "label": row["title"], "kind": kind, "help": row["description"]}
    if kind == "number":
        control["unit"] = ""
    else:
        control["max"], control["multiline"] = 2000, row["type"] in ("multiline_string", "json")
    return control


def ordered_controls(live: list, shown=None) -> list:
    """[(group, control)] in the order the person chose (`shown`, names; the shipped list when None). A name this Kasm does not have, or a secret, is simply left out. A curated control keeps
    its plain wording, unit and bounds; any other setting gets a control made from its own type. A group is the curated group, or Kasm's own category for the others."""
    rows = _index(live)
    curated = {c["setting"]: (item, c) for item in SIMPLE for c in item["controls"]}
    out = []
    for name in (default_shown() if shown is None else shown):
        row = rows.get(name)
        if row is None or row["secret"]:
            continue
        if name in curated:
            item, control = curated[name]
            out.append(({"id": item["id"], "title": item["title"], "help": item["help"]}, control))
        else:
            category = row["category"] or "other"
            out.append(({"id": f"cat:{category}", "title": category.replace("_", " ").capitalize() + " (as Kasm describes them)", "help": ""}, _generic(row)))
    return out


def simple_requested(live: list, form: dict, shown=None) -> dict:
    """The change set a plain-language form asks for: {setting name: stored value}, converted from the shown units and limited by each control's own bounds. Only what is in the view counts."""
    return {control["setting"]: _stored(control, str(form[f"c:{control['setting']}"]))
            for _group, control in ordered_controls(live, shown) if f"c:{control['setting']}" in form}


def advanced_requested(live: list, form: dict) -> dict:
    return {key[2:]: str(value) for key, value in form.items() if key.startswith("s:")}


# ---- pages -------------------------------------------------------------------------------------------------------------------------------
_CSS = ("<style>body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:1rem auto;padding:0 1rem}fieldset{margin:1rem 0;padding:.8rem 1rem;border:1px solid #8884}"
        "legend{font-weight:600}.help{color:#9aa4b8;margin:.2rem 0 .6rem}.row{display:flex;gap:.8rem;align-items:center;margin:.35rem 0;flex-wrap:wrap}.row label{min-width:16rem}"
        ".restart{font-size:.85em;color:#e0a458}.secret{color:#9aa4b8;font-style:italic}input[type=number]{width:7rem}textarea{width:100%;min-height:4rem;font-family:monospace}"
        "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #8883;padding:.35rem .5rem;text-align:left;vertical-align:top}.name{font-family:monospace;font-size:.85em;color:#9aa4b8}"
        "details{margin:.6rem 0}summary{cursor:pointer;font-weight:600}</style>")


def _head(title: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>{_CSS}</head><body>"


def _tabs(active: str) -> str:
    def tab(path, label, key):
        return f"<b>{label}</b>" if key == active else f"<a href='{path}'>{label}</a>"
    return "<p>" + tab("/workspaces/settings", "Everyday settings", "simple") + " | " + tab("/workspaces/settings/advanced", "All settings", "advanced") + " | " + tab("/workspaces/settings/customize", "Choose what appears", "customize") + " | <a href='/workspaces'>Back to Workspaces</a></p>"


def _control(control: dict, row: dict) -> str:
    name = f"c:{control['setting']}"
    value = _shown(control, row)
    restart = f"<span class='restart'>Changing this restarts {html.escape(', '.join(row['restart']))}.</span>" if row["restart"] else ""
    if control["kind"] == "toggle":
        on = value.lower() == "true"
        field = (f"<select name='{html.escape(name)}'><option value='True'{' selected' if on else ''}>On</option><option value='False'{'' if on else ' selected'}>Off</option></select>")
    elif control["kind"] == "number":
        bounds = "".join(f" {k}='{control[k]}'" for k in ("min", "max") if control.get(k) is not None)
        field = f"<input type='number' step='any' name='{html.escape(name)}' value='{html.escape(value)}'{bounds}> {html.escape(control['unit'])}"
    elif control.get("multiline"):
        field = f"<textarea name='{html.escape(name)}' maxlength='{control.get('max', 2000)}'>{html.escape(value)}</textarea>"
    else:
        field = f"<input type='text' name='{html.escape(name)}' value='{html.escape(value)}' maxlength='{control.get('max', 200)}'>"
    note = f"<div class='help'>{html.escape(control['help'])}</div>" if control.get("help") else ""
    return f"<div class='row'><label>{html.escape(control['label'])}</label>{field} {restart}</div>{note}"


def render_simple(live: list, notice: str = "", shown=None) -> bytes:
    rows = _index(live)
    out = [_head("Kasm settings"), "<h1>Kasm settings</h1>", _tabs("simple")]
    if notice:
        out.append(f"<p role='alert'>{html.escape(notice)}</p>")
    out.append("<p>The everyday choices, in plain words. <a href='/workspaces/settings/customize'>Choose which settings appear here</a>; every setting Kasm has is under "
               "<a href='/workspaces/settings/advanced'>All settings</a>. Changes are made in Kasm itself and checked afterwards.</p>")
    out.append("<form method='post' action='/workspaces/settings/apply'><input type='hidden' name='mode' value='simple'>")
    previous, open_ = None, False
    for group, control in ordered_controls(live, shown):
        if group["id"] != previous:                                  # settings next to each other that belong together share one box
            out.append("</fieldset>" if open_ else "")
            out.append(f"<fieldset><legend>{html.escape(group['title'])}</legend>" + (f"<p class='help'>{html.escape(group['help'])}</p>" if group["help"] else ""))
            previous, open_ = group["id"], True
        out.append(_control(control, rows[control["setting"]]))
    out.append("</fieldset>" if open_ else "<p>Nothing is chosen to appear here yet. <a href='/workspaces/settings/customize'>Choose some</a>.</p>")
    if open_:
        out.append("<p><label><input type='checkbox' name='confirm' value='yes' required> Make these changes in Kasm now</label> <button type='submit'>Apply</button></p>")
    out.append("</form></body></html>")
    return "".join(out).encode()


def _advanced_field(row: dict) -> str:
    name, value, kind = html.escape(f"s:{row['name']}"), row["value"] or "", row["type"]
    if row["secret"]:
        return "<span class='secret'>a secret: shown only as set or not set, and not changed here</span>"
    if kind == "bool":
        on = value.lower() == "true"
        return f"<select name='{name}'><option value='True'{' selected' if on else ''}>True</option><option value='False'{'' if on else ' selected'}>False</option></select>"
    if kind in ("multiline_string", "json"):
        return f"<textarea name='{name}'>{html.escape(value)}</textarea>"
    if kind in ("int", "float"):
        return f"<input type='number' step='any' name='{name}' value='{html.escape(value)}'>"
    return f"<input type='text' name='{name}' value='{html.escape(value)}'>"


def render_advanced(live: list, notice: str = "", query: str = "") -> bytes:
    needle = query.strip().lower()
    out = [_head("All Kasm settings"), "<h1>All Kasm settings</h1>", _tabs("advanced")]
    if notice:
        out.append(f"<p role='alert'>{html.escape(notice)}</p>")
    out.append(f"<form method='get' action='/workspaces/settings/advanced'><input type='search' name='q' value='{html.escape(query)}' placeholder='Search by name or words'> <button type='submit'>Search</button></form>")
    out.append("<form method='post' action='/workspaces/settings/apply'><input type='hidden' name='mode' value='advanced'>")
    categories: dict = {}
    for row in sorted(live, key=lambda r: (r["category"], r["title"])):
        if needle and needle not in f"{row['name']} {row['title']} {row['description']} {row['category']}".lower():
            continue
        categories.setdefault(row["category"] or "other", []).append(row)
    shown = sum(len(v) for v in categories.values())
    out.append(f"<p>{shown} of {len(live)} settings. Only a setting you change is sent. Secrets are not shown.</p>")
    for category, rows in categories.items():
        out.append(f"<details{' open' if needle else ''}><summary>{html.escape(category.replace('_', ' '))} ({len(rows)})</summary><table><tbody>")
        for row in rows:
            restart = f"<br><span class='restart'>A change restarts {html.escape(', '.join(row['restart']))}.</span>" if row["restart"] else ""
            current = "<span class='secret'>set</span>" if row["secret"] else ""
            out.append(f"<tr><td><b>{html.escape(row['title'])}</b><br><span class='name'>{html.escape(row['name'])} ({html.escape(row['type'])})</span>{restart}</td>"
                       f"<td>{html.escape(row['description'])}</td><td>{_advanced_field(row) if not current else current + '<br>' + _advanced_field(row)}</td></tr>")
        out.append("</tbody></table></details>")
    out.append("<p><label><input type='checkbox' name='confirm' value='yes' required> Make the changed settings in Kasm now</label> <button type='submit'>Apply</button></p></form></body></html>")
    return "".join(out).encode()


def render_result(result: dict) -> bytes:
    out = [_head("Kasm settings changed"), "<h1>Kasm settings</h1>", _tabs("")]
    if not result["applied"] and not result["failed"]:
        out.append("<p>Nothing was different from what Kasm already has, so nothing was changed.</p>")
    for item in result["applied"]:
        out.append(f"<p>Changed <b>{html.escape(item['title'])}</b>: {html.escape(str(item['old']))} to {html.escape(str(item['new']))}"
                   + ("" if item.get("verified", True) else " <b>(Kasm did not report the new value afterwards; check it)</b>") + ".</p>")
    for item in result["failed"]:
        out.append(f"<p role='alert'>Could not change <b>{html.escape(item['title'])}</b>: {html.escape(item['reason'])}</p>")
    if result.get("restart"):
        out.append(f"<p class='restart'>Kasm needs {html.escape(' and '.join(result['restart']))} restarted before {'these changes take' if len(result['applied']) > 1 else 'this change takes'} effect. "
                   "Restart the Kasm VM from the Workspaces page when it suits you.</p>")
    out.append("<p><a href='/workspaces/settings'>Everyday settings</a> | <a href='/workspaces/settings/advanced'>All settings</a></p></body></html>")
    return "".join(out).encode()


def render_unavailable(reason: str) -> bytes:
    return (_head("Kasm settings") + "<h1>Kasm settings</h1>" + _tabs("") + f"<p role='alert'>{html.escape(reason)}</p>"
            "<p>The settings are read from the running Kasm itself, so the VM must be running.</p></body></html>").encode()


# ---- choosing what the everyday screen shows (a toggle for every setting and an ordered list, like choosing what goes on a toolbar) -------
_CUSTOMIZE_CSS = ("<style>.pick{display:grid;grid-template-columns:minmax(16rem,1fr) minmax(20rem,2fr);gap:1.2rem;align-items:start}@media(max-width:46rem){.pick{grid-template-columns:1fr}}"
                  ".panel{border:1px solid #8884;border-radius:6px;padding:.6rem .8rem}.panel h2{margin:.1rem 0 .5rem;font-size:1rem}"
                  "#order{list-style:none;margin:0;padding:0}#order li{display:flex;align-items:center;gap:.4rem;padding:.3rem .2rem;border-bottom:1px solid #8883}"
                  "#order li span.t{flex:1}#order button{padding:.1rem .45rem}.sw{display:flex;align-items:flex-start;gap:.7rem;padding:.35rem 0;border-bottom:1px solid #8883}"
                  ".sw input{position:absolute;opacity:0}.sw .track{flex:none;width:2.4rem;height:1.3rem;border-radius:1rem;background:#555a6e;position:relative;transition:background .15s;margin-top:.15rem}"
                  ".sw .track::after{content:'';position:absolute;top:.15rem;left:.15rem;width:1rem;height:1rem;border-radius:50%;background:#fff;transition:transform .15s}"
                  ".sw input:checked+.track{background:#3f8f5f}.sw input:checked+.track::after{transform:translateX(1.1rem)}"
                  ".sw input:focus-visible+.track{outline:2px solid #7fa4ec;outline-offset:2px}.sw .d{color:#9aa4b8;font-size:.85em}"
                  "@media(prefers-reduced-motion:reduce){.sw .track,.sw .track::after{transition:none}}</style>")

_CUSTOMIZE_JS = """<script>
(function(){
  var order=document.getElementById('order'),field=document.getElementById('orderfield'),empty=document.getElementById('empty');
  var titles={};document.querySelectorAll('.sw input[data-name]').forEach(function(b){titles[b.dataset.name]=b.dataset.title;});
  function sync(){var names=[];order.querySelectorAll('li').forEach(function(li){names.push(li.dataset.name);});field.value=names.join(',');empty.hidden=names.length>0;}
  function add(name){if(order.querySelector('li[data-name="'+name+'"]'))return;var li=document.createElement('li');li.dataset.name=name;
    li.innerHTML='<span class="t"></span><button type="button" data-act="up" aria-label="Move up">&#9650;</button><button type="button" data-act="down" aria-label="Move down">&#9660;</button><button type="button" data-act="off" aria-label="Remove">&#10005;</button>';
    li.querySelector('.t').textContent=titles[name]||name;order.appendChild(li);}
  function remove(name){var li=order.querySelector('li[data-name="'+name+'"]');if(li)li.remove();var b=document.querySelector('.sw input[data-name="'+name+'"]');if(b)b.checked=false;}
  order.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var li=b.closest('li'),act=b.dataset.act;
    if(act==='up'&&li.previousElementSibling)order.insertBefore(li,li.previousElementSibling);
    if(act==='down'&&li.nextElementSibling)order.insertBefore(li.nextElementSibling,li);
    if(act==='off')remove(li.dataset.name);sync();});
  document.querySelectorAll('.sw input[data-name]').forEach(function(b){b.addEventListener('change',function(){if(b.checked)add(b.dataset.name);else remove(b.dataset.name);sync();});});
  var q=document.getElementById('find');q.addEventListener('input',function(){var n=q.value.toLowerCase();
    document.querySelectorAll('.sw').forEach(function(r){r.hidden=n&&r.dataset.text.indexOf(n)<0;});
    document.querySelectorAll('details.cat').forEach(function(d){d.hidden=!d.querySelector('.sw:not([hidden])');if(n&&!d.hidden)d.open=true;});});
  sync();
})();
</script>"""


def shown_from_form(live: list, form: dict) -> list:
    """The everyday list a customise form asks for: the names ticked, in the order the page's list gave (a tick with no place in the list goes last). Unknown names and secrets are left out."""
    rows = _index(live)
    ticked = {k[5:] for k, v in form.items() if k.startswith("show:") and v == "on"}
    listed = [n for n in str(form.get("order", "")).split(",") if n]
    ordered = [n for n in dict.fromkeys(listed) if n in ticked] + sorted(n for n in ticked if n not in listed)
    return [n for n in ordered if n in rows and not rows[n]["secret"]]


def render_customize(live: list, shown: list, notice: str = "") -> bytes:
    rows = _index(live)
    chosen = [n for n in shown if n in rows and not rows[n]["secret"]]
    titles = {n: rows[n]["title"] or n for n in chosen}
    out = [_head("Choose what appears"), _CUSTOMIZE_CSS, "<h1>Choose what appears in everyday settings</h1>", _tabs("customize")]
    if notice:
        out.append(f"<p role='alert'>{html.escape(notice)}</p>")
    out.append("<p>Switch a setting on to put it on the everyday screen; switch it off to take it away. The list on the left is the order they appear in. "
               "Secrets are not offered. Nothing here changes Kasm itself, only what you see.</p>")
    out.append("<form method='post' action='/workspaces/settings/customize'><div class='pick'>")
    out.append("<div class='panel'><h2>On the everyday screen</h2><ol id='order'>" + "".join(
        f"<li data-name='{html.escape(n)}'><span class='t'>{html.escape(titles[n])}</span>"
        "<button type='button' data-act='up' aria-label='Move up'>&#9650;</button><button type='button' data-act='down' aria-label='Move down'>&#9660;</button>"
        "<button type='button' data-act='off' aria-label='Remove'>&#10005;</button></li>" for n in chosen) + "</ol>"
        f"<p id='empty' class='help'{' hidden' if chosen else ''}>Nothing is switched on yet.</p>"
        f"<input type='hidden' id='orderfield' name='order' value='{html.escape(','.join(chosen))}'></div>")
    out.append("<div class='panel'><h2>All settings</h2><p><input type='search' id='find' placeholder='Search settings' autocomplete='off'></p>")
    categories: dict = {}
    for row in sorted(live, key=lambda r: (r["category"], r["title"])):
        if not row["secret"]:
            categories.setdefault(row["category"] or "other", []).append(row)
    for category, items in categories.items():
        out.append(f"<details class='cat'><summary>{html.escape(category.replace('_', ' '))} ({len(items)})</summary>")
        for row in items:
            text = f"{row['name']} {row['title']} {row['description']}".lower()
            out.append(f"<label class='sw' data-text='{html.escape(text, quote=True)}'><input type='checkbox' name='show:{html.escape(row['name'])}' value='on' data-name='{html.escape(row['name'])}' "
                       f"data-title='{html.escape(row['title'] or row['name'], quote=True)}'{' checked' if row['name'] in chosen else ''}><span class='track'></span>"
                       f"<span><b>{html.escape(row['title'] or row['name'])}</b><br><span class='d'>{html.escape(row['description'])}</span></span></label>")
        out.append("</details>")
    out.append("</div></div><p><button type='submit'>Save</button> <button type='submit' name='reset' value='yes' formnovalidate>Back to the shipped list</button></p></form>")
    out.append(_CUSTOMIZE_JS + "</body></html>")
    return "".join(out).encode()
