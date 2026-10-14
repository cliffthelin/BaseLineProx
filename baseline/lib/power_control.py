"""System shutdown and restart for the host, from the browser (operator, 2026-10-14).

`host_restart` asks a GNOME session to restart, which does not exist on the Proxmox host Baseline installs; this goes to systemd, which
Proxmox shuts its virtual machines and containers down through first. Two fixed commands and nothing a person types reaches one of them.
Both need an explicit confirmation on the request, so a stray click or a crawler cannot take the machine down.
"""
from __future__ import annotations

import html

ACTIONS = {
    "poweroff": ["systemctl", "poweroff"],
    "reboot": ["systemctl", "reboot"],
}


def action_argv(action) -> list:
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("unknown power action")
    return list(ACTIONS[action])


def render(notice: str = "") -> bytes:
    note = f"<p role='alert'>{html.escape(notice)}</p>" if notice else ""

    def form(action: str, label: str, warning: str) -> str:
        return (f'<form method="post" action="/power/{action}"><p>{html.escape(warning)}</p>'
                f'<label><input type="checkbox" name="confirm" value="yes" required> I want to {html.escape(label.lower())} this machine</label> '
                f'<button type="submit">{html.escape(label)}</button></form>')

    return ("<!doctype html><html><head><meta charset='utf-8'><title>Power</title></head><body><h1>Power</h1>" + note
            + "<p>Proxmox stops running virtual machines and containers first, the way it does for its own Shutdown and Reboot buttons.</p>"
            + form("poweroff", "Shut down", "The machine turns off and stays off until the power button is pressed.")
            + form("reboot", "Restart", "The machine turns off and starts again. This page is unavailable for a minute or two.")
            + "</body></html>").encode()


def render_done(action: str) -> bytes:
    text = "Shutting down" if action == "poweroff" else "Restarting"
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{text}</title></head><body><h1>{text}</h1>"
            "<p>The request was accepted. This page stops responding while the machine goes down.</p></body></html>").encode()
