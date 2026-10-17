"""The Suggestions page: what the Wiki says to an AI, the proposals that came back, a trial in progress, and the archive of what was tried (DR263).

Everything a proposal says (its title, reasons, notes) was written by something else, so it is escaped as text and never trusted as markup."""
from __future__ import annotations

import html
import time

import kasm_settings_ui as ui

_E = html.escape
_STATUS = {"improved": "Baseline's check: it improved", "worse": "Baseline's check: it got worse", "no-clear-change": "Baseline's check: no clear change",
           "too-early": "Baseline's check: too early to tell", "no-data": "Baseline's check: not enough data"}


def _ago(ts) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def _changes(items: list) -> str:
    if not items:
        return ""
    rows = "".join(f"<tr><td>{_E(str(c['title']))}<br><span class='name'>{_E(c['name'])}</span></td><td>{_E(str(c['current'] if c['current'] is not None else ''))}</td>"
                   f"<td><b>{_E(str(c['new']))}</b></td><td>{_E(', '.join(c['restart']))}</td></tr>" for c in items)
    return f"<table><thead><tr><th>Setting</th><th>Now</th><th>Proposed</th><th>Restarts</th></tr></thead><tbody>{rows}</tbody></table>"


def _expect(e: dict) -> str:
    what = f"the measure {e['metric']}" if "metric" in e else f"the problem {e['concern']}"
    return f"Success: {what} should go {e['direction']}."


def _proposal(p: dict) -> str:
    sizes = f"<p>Size recommendation (a person applies it; the VM restarts): {_E(', '.join(f'{k} {v}' for k, v in p['sizes'].items()))}</p>" if p.get("sizes") else ""
    concerns = f"<p class='help'>About: {_E(', '.join(p['concerns']))}</p>" if p.get("concerns") else ""
    rollback = f"<p class='help'>Undo: {_E(p['rollback'])}</p>" if p.get("rollback") else ""
    buttons = ""
    if p.get("settings"):
        buttons += (f"<form method='post' action='/workspaces/suggestions/try'><input type='hidden' name='id' value='{_E(p['id'], quote=True)}'>"
                    "<label><input type='checkbox' name='confirm' value='yes' required> Make these changes in Kasm for a trial</label> <button type='submit'>Try it</button></form>")
    buttons += (f"<form method='post' action='/workspaces/suggestions/archive'><input type='hidden' name='id' value='{_E(p['id'], quote=True)}'>"
                "<input type='text' name='note' placeholder='Why (optional)' maxlength='300'> <label><input type='checkbox' name='confirm' value='yes' required> Archive it</label> <button type='submit'>Archive without trying</button></form>")
    return (f"<fieldset><legend>{_E(p['title'])}</legend><p>{_E(p['rationale'])}</p>{concerns}{_changes(p.get('changes', []))}{sizes}<p>{_E(_expect(p['expect']))}</p>{rollback}{buttons}</fieldset>")


def _trial(t: dict) -> str:
    check = t["check"]
    kept = (f"<form method='post' action='/workspaces/suggestions/finish'><input type='hidden' name='id' value='{_E(t['id'], quote=True)}'>"
            "<p>How did it go?</p><input type='text' name='note' placeholder='A note (optional)' maxlength='300'> "
            "<label><input type='radio' name='verdict' value='better' required> Better: keep it</label> <label><input type='radio' name='verdict' value='same'> The same: put it back</label> "
            "<label><input type='radio' name='verdict' value='worse'> Worse: put it back</label><br>"
            "<label><input type='checkbox' name='confirm' value='yes' required> End the trial</label> <button type='submit'>Done</button></form>")
    restart = f"<p class='restart'>Kasm needs {_E(' and '.join(t['restart']))} restarted before this takes effect.</p>" if t.get("restart") else ""
    return (f"<fieldset><legend>On trial: {_E(t['title'])}</legend><p>Started {_E(_ago(t['started']))}. The old values are kept and are put back unless you say it was better.</p>"
            f"{_changes(t.get('changes', []))}{restart}<p><b>{_E(_STATUS.get(check['status'], check['status']))}.</b> {_E(check['text'])}</p>{kept}</fieldset>")


def _archived(p: dict) -> str:
    verdict = p.get("verdict", "")
    detail = f" {_E(p['check']['text'])}" if p.get("check", {}).get("text") else ""
    note = f" Note: {_E(p['note'])}" if p.get("note") else ""
    reason = f" Reason: {_E(p['reason'])}" if p.get("reason") else ""
    recipe = ""
    if p.get("recipe_settings"):
        import json
        recipe = f"<br><span class='help'>Kept. To make the next build start with it, add to the recipe's settings: <code>{_E(json.dumps(p['recipe_settings']))}</code></span>"
    return f"<li><b>{_E(p.get('title', p['id']))}</b> ({_E(verdict)}, {_E(_ago(p.get('ended') or p.get('received')))}).{detail}{reason}{note}{recipe}</li>"


def render(overview: dict, notice: str = "") -> bytes:
    out = [ui._head("Kasm suggestions"), "<h1>Suggestions for Kasm</h1>", "<p><a href='/workspaces'>Back to Workspaces</a> | <a href='/workspaces/settings'>Settings</a></p>"]
    if notice:
        out.append(f"<p role='alert'>{_E(notice)}</p>")
    out.append("<p>Baseline keeps a Wiki of what goes wrong with Kasm, written from its history. An AI can read it and propose a setting worth changing. You decide: try it, "
               "with the old values kept, or archive it. Nothing is applied without you.</p>")
    wiki = (f"<p>The Wiki is at <code>{_E(overview['wiki_path'])}</code> (last written {_E(_ago(overview['wiki_written']))}). To ask an AI: point it at "
            f"<code>{_E(overview['brief_path'])}</code>. Proposals it writes appear here once Baseline has checked them.</p>") if overview["wiki_ready"] else "<p>The Wiki has not been written yet. Refresh it below.</p>"
    out.append("<h2>The Wiki and the AI</h2>" + wiki + (f"<p>{overview['waiting']} proposal file(s) are waiting their turn.</p>" if overview["waiting"] else "")
               + "<form method='post' action='/workspaces/suggestions/refresh'><button type='submit'>Refresh the Wiki and check for proposals</button></form>")
    if not overview["live"]:
        out.append("<p class='help'>Kasm is not answering, so proposals cannot be checked against its settings yet.</p>")
    if overview["trials"]:
        out.append("<h2>On trial</h2>" + "".join(_trial(t) for t in overview["trials"]))
    out.append("<h2>Waiting for your decision</h2>" + ("".join(_proposal(p) for p in overview["pending"]) or "<p>Nothing is waiting.</p>"))
    out.append("<h2>Archive</h2>" + ("<ul>" + "".join(_archived(p) for p in overview["archive"]) + "</ul>" if overview["archive"] else "<p>Nothing has been tried or archived yet.</p>"))
    out.append("</body></html>")
    return "".join(out).encode()
