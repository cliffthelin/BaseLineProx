"""The Workspaces page: Kasm Workspaces (browsers and desktops in the browser, with profiles that are kept) as a VM on this machine (DR260)."""
from __future__ import annotations

import html
import json

WORKSPACES = (
    ("Browser (temporary)", "a clean browser each time; nothing is kept"),
    ("Browser (personal)", "your own browser profile: bookmarks, sign-ins and settings are kept"),
    ("Development desktop", "a full Linux desktop; its home is kept"),
    ("VS Code", "an editor in the browser; settings and extensions are kept"),
    ("Firefox", "a second browser with its own kept profile"),
    ("Terminal", "a shell; nothing is kept"),
)


def _state(status: dict) -> tuple:
    if not status.get("present") and status.get("dehydrated"):
        return "Removed (its data is kept)", "The VM is not defined, but everything it held is kept. Rebuild it to get it back exactly as it was."
    if not status.get("present"):
        return "Not set up yet", "The Kasm VM has not been built on this machine."
    if not status.get("installed"):
        return "Setting up", "The VM exists and Kasm is being installed in it. This takes a few minutes."
    if not status.get("running"):
        return "Stopped", "Kasm is installed but its VM is not running."
    if not status.get("url"):
        return "Starting", "The VM is running; Kasm will be reachable as soon as it has an address."
    return "Running", "Kasm is ready."


def _report(report) -> str:
    if not isinstance(report, dict):
        return ""
    out = ""
    suggestions = report.get("suggestions") or []
    if suggestions:
        items = "".join(f"<li data-severity=\"{html.escape(s['severity'])}\"><b>{html.escape(s['title'])}</b><br>Seen: {html.escape('; '.join(s.get('evidence', [])))}<br>Benefit: {html.escape(s['benefit'])}</li>" for s in suggestions)
        out += f"<h2>What the history suggests</h2><ul>{items}</ul>"
    changes = report.get("setting_changes") or []
    if changes:
        rows = "".join(f"<li><b>{html.escape(c['name'])}</b> changed {c['changes']} time(s); last: " + ("a secret (its value is not kept)" if c.get('secret') else f"{html.escape(str(c['last_old']))} to {html.escape(str(c['last_new']))}") + "</li>" for c in changes)
        out += f"<h2>Settings that changed</h2><ul>{rows}</ul>"
    return out


def _sources(carried) -> str:
    """Workspaces taken from other registries (LinuxServer.io ...): what is offered, what is not and why, and what a person must read before the next build will take a changed one."""
    if not isinstance(carried, dict):
        return ""
    rows = carried.get("workspaces") or []
    items = ""
    for row in rows:
        name = html.escape(str(row.get("name", "")))
        where = html.escape(str(row.get("source", "")))
        if row.get("status") == "included":
            caveat = []
            if row.get("unverified"):
                caveat.append("not verified on this Kasm version")
            if row.get("findings"):
                caveat.append("accepted: " + ", ".join(row["findings"]))
            if row.get("requires_network"):
                caveat.append("pulled from its own registry when first started, so it needs internet")
            items += f"<li><b>{name}</b> from {where}: offered" + (f" ({html.escape('; '.join(caveat))})" if caveat else "") + "</li>"
        else:
            detail = ""
            if row.get("definition"):
                detail = f"<details><summary>Read its definition</summary><pre>{html.escape(json.dumps(row['definition'], indent=1))}</pre></details>"
            items += f"<li><b>{name}</b> from {where}: <b>left out</b>. {html.escape(str(row.get('reason', '')))}{detail}</li>"
    return f"<h2>From other registries</h2><ul>{items}</ul>"


def render(status: dict, notice: str = "", report=None) -> bytes:
    label, detail = _state(status)
    note = f"<p role='alert'>{html.escape(notice)}</p>" if notice else ""
    url = status.get("url")
    opener = f'<p><a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">Open Kasm</a> (sign in as the admin or the user; the passwords are in the Vault)</p>' if url else ""
    rebuild = bool(status.get("dehydrated") and not status.get("present"))
    build = ('<form method="post" action="/workspaces/setup"><button type="submit">' + ("Rebuild the VM" if rebuild else "Set up Kasm now") + "</button></form>"
             + ("<p>Builds the VM again from its kept layers: same address, same settings, same data.</p>" if rebuild else
                "<p>Builds the VM from the base this installer carries, then installs Kasm in it. It also happens on its own once the machine is configured.</p>")
             ) if (not status.get("installed") or rebuild) else ""
    mode = status.get("mode")
    controls = ""
    if status.get("present") and mode:
        controls = ("<h2>How it runs</h2><form method=\"post\" action=\"/workspaces/mode\">"
                    f"<label><input type=\"radio\" name=\"mode\" value=\"persist\"{' checked' if mode == 'persist' else ''}> <b>Keep everything.</b> All configuration and data, including what the VM's own system holds, "
                    "is kept in layers over a read-only base, so the VM can be removed and rebuilt exactly as it was.</label><br>"
                    f"<label><input type=\"radio\" name=\"mode\" value=\"reset\"{' checked' if mode == 'reset' else ''}> <b>Reset at every start.</b> Everything done during a run, including new profiles "
                    "and settings, is discarded; the VM starts again from where it was when it was started.</label><br>"
                    "<label><input type=\"checkbox\" name=\"confirm\" value=\"yes\" required> Restart the Kasm VM to change this</label> <button type=\"submit\">Apply</button></form>"
                    "<h2>Remove the VM, keep its data</h2><form method=\"post\" action=\"/workspaces/dehydrate\">"
                    "<p>Removes the VM from Proxmox and leaves every layer in place. Nothing is deleted; rebuilding it brings it back as it was.</p>"
                    "<label><input type=\"checkbox\" name=\"confirm\" value=\"yes\" required> Shut the VM down and remove it</label> <button type=\"submit\">Remove</button></form>")
    carried = status.get("workspaces")
    if isinstance(carried, list) and carried:        # what the base on this machine really holds (it follows your supported-OS list)
        items = "".join(f"<li><b>{html.escape(str(w.get('friendly_name', '')))}</b>: "
                        f"{'its profile is kept' if w.get('persistent') else 'nothing is kept'}</li>" for w in carried)
    else:
        items = "".join(f"<li><b>{html.escape(name)}</b>: {html.escape(what)}</li>" for name, what in WORKSPACES)
    recipe = status.get("recipe")
    parts = ""
    if isinstance(recipe, dict):
        label_of = {"required": "required", "used": "used", "unused": "carried, not used"}
        rows = "".join(f"<li><b>{html.escape(str(c.get('id', '')))}</b> ({html.escape(label_of.get(c.get('state'), str(c.get('state'))))}): {html.escape(str(c.get('note', '')))}</li>"
                       for c in recipe.get("components", []))
        plugins = "".join(f"<li><b>{html.escape(str(p.get('id', '')))}</b> plugin ({html.escape(label_of.get(p.get('state'), str(p.get('state'))))})</li>" for p in recipe.get("plugins", []))
        parts = f"<h2>What this Kasm is built from</h2><ul>{rows}{plugins}</ul>"
    others = _sources(status.get("registry_sources"))
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Workspaces</title></head><body><h1>Workspaces (Kasm)</h1>" + note
            + f"<p>State: <b>{html.escape(label)}</b>. {html.escape(detail)}</p>{opener}{build}"
            + ("<p><a href='/workspaces/settings'>Kasm settings</a> (everyday choices, or all of them) | <a href='/workspaces/suggestions'>Suggestions</a> (what the history says, and what an AI proposes)</p>" if status.get("running") else "") + controls
            + f"<h2>What you can open</h2><ul>{items}</ul>" + others + parts + _report(report)
            + "<h2>Where things are kept</h2><ul>"
              "<li>Kasm's own settings, accounts and database: <b>APPDATA_ADMIN</b>.</li>"
              "<li>Your browser and desktop profiles: <b>APPDATA_PERSONAL</b>, one folder per person and workspace.</li>"
              "<li>The VM's own system: a layer on <b>APPDATA_ADMIN</b> over a read-only base, so it is kept too. In reset mode a layer on <b>SESSION_TEMP</b> "
              "sits over all of these for the run and is discarded.</li>"
              "<li>The Kasm passwords: the <a href='/vault'>Vault</a>.</li></ul>"
              "<p>Kasm Workspaces Community Edition is free to use but is not fully open source; its desktop streaming and workspace images are.</p>"
              "</body></html>").encode()
