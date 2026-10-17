"""The Workspaces page: Kasm Workspaces (browsers and desktops in the browser, with profiles that are kept) as a VM on this machine (DR260)."""
from __future__ import annotations

import html

WORKSPACES = (
    ("Browser (temporary)", "a clean browser each time; nothing is kept"),
    ("Browser (personal)", "your own browser profile: bookmarks, sign-ins and settings are kept"),
    ("Development desktop", "a full Linux desktop; its home is kept"),
    ("VS Code", "an editor in the browser; settings and extensions are kept"),
    ("Firefox", "a second browser with its own kept profile"),
    ("Terminal", "a shell; nothing is kept"),
)


def _state(status: dict) -> tuple:
    if not status.get("present"):
        return "Not set up yet", "The Kasm VM has not been built on this machine."
    if not status.get("installed"):
        return "Setting up", "The VM exists and Kasm is being installed in it. This takes a few minutes."
    if not status.get("running"):
        return "Stopped", "Kasm is installed but its VM is not running."
    if not status.get("url"):
        return "Starting", "The VM is running; Kasm will be reachable as soon as it has an address."
    return "Running", "Kasm is ready."


def render(status: dict, notice: str = "") -> bytes:
    label, detail = _state(status)
    note = f"<p role='alert'>{html.escape(notice)}</p>" if notice else ""
    url = status.get("url")
    opener = f'<p><a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">Open Kasm</a> (sign in as the admin or the user; the passwords are in the Vault)</p>' if url else ""
    build = ('<form method="post" action="/workspaces/setup"><button type="submit">Set up Kasm now</button></form>'
             "<p>Builds the VM from the base this installer carries, then installs Kasm in it. It also happens on its own once the machine is configured.</p>"
             ) if not status.get("installed") else ""
    carried = status.get("workspaces")
    if isinstance(carried, list) and carried:        # what the base on this machine really holds (it follows your supported-OS list)
        items = "".join(f"<li><b>{html.escape(str(w.get('friendly_name', '')))}</b>: "
                        f"{'its profile is kept' if w.get('persistent') else 'nothing is kept'}</li>" for w in carried)
    else:
        items = "".join(f"<li><b>{html.escape(name)}</b>: {html.escape(what)}</li>" for name, what in WORKSPACES)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Workspaces</title></head><body><h1>Workspaces (Kasm)</h1>" + note
            + f"<p>State: <b>{html.escape(label)}</b>. {html.escape(detail)}</p>{opener}{build}"
            + f"<h2>What you can open</h2><ul>{items}</ul>"
            + "<h2>Where things are kept</h2><ul>"
              "<li>Kasm's own settings, accounts and database: <b>APPDATA_ADMIN</b>.</li>"
              "<li>Your browser and desktop profiles: <b>APPDATA_PERSONAL</b>, one folder per person and workspace.</li>"
              "<li>The operating system the VM runs on: a throwaway layer on <b>SESSION_TEMP</b> over a read-only base. Rebuilding or resetting it keeps "
              "everything above.</li>"
              "<li>The Kasm passwords: the <a href='/vault'>Vault</a>.</li></ul>"
              "<p>Kasm Workspaces Community Edition is free to use but is not fully open source; its desktop streaming and workspace images are.</p>"
              "</body></html>").encode()
