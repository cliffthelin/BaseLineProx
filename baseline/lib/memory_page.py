"""The host's swap, as a setting the user can change from the browser (operator 2026-10-16).

Proxmox has no swap setting of its own, so the host's is here. A VM's or container's own swap is set on its tile in the Launcher (OS settings):
a container's is applied by Proxmox itself, a VM's is stored for the guest to apply when the OS is set up.
"""
from __future__ import annotations

import html

SIZES = (0, 1, 2, 4, 8, 16, 32)


def render(current: dict, recorded: dict, notice: str = "", max_gib: int = 64) -> bytes:
    kind_now = {"file": "a file in SESSION_TEMP", "reserved": "a reserved volume", "proxmox-default": "Proxmox's own swap volume", None: "none"}.get(current["kind"], "unknown")
    now = f"{current['gib']} GiB, {kind_now}" if current["gib"] else "none"
    note = f"<p role='alert'>{html.escape(notice)}</p>" if notice else ""
    saved = (f"<p>Your saved choice: {html.escape(str(recorded.get('host_swap_gib')))} GiB, {html.escape(str(recorded.get('host_swap_kind')))}. "
             "It is kept on USER_ADMIN.</p>") if recorded.get("host_swap_gib") is not None else "<p>No choice saved yet: the machine uses what setup made.</p>"
    options = "".join(f'<option value="{s}"{" selected" if s == current["gib"] else ""}>{s if s else "none"}</option>' for s in SIZES)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Memory and swap</title></head><body><h1>Memory and swap</h1>" + note
            + f"<h2>This machine</h2><p>Swap now: <b>{html.escape(now)}</b>.</p>{saved}"
            + '<form method="post" action="/memory/swap">'
              f'<label>Size in GiB (0 to {max_gib}) <input name="gib" type="number" min="0" max="{max_gib}" value="{current["gib"]}" list="sizes" required></label>'
              f"<datalist id='sizes'>{options}</datalist>"
              '<fieldset><legend>How it is made</legend>'
              '<label><input type="radio" name="kind" value="file" checked> <b>A file in SESSION_TEMP</b> (the default). Written once at this size, so '
              'swap can never find a missing block when the scratch pool is full.</label><br>'
              '<label><input type="radio" name="kind" value="reserved"> <b>A reserved volume.</b> The space is reserved and nothing is written. It is taken '
              'out of what your other volumes can grow into.</label></fieldset>'
              '<label><input type="checkbox" name="confirm" value="yes" required> Change the swap on this machine now</label> '
              '<button type="submit">Apply</button></form>'
              "<p>The new swap is switched on before the old one is released. If the old one is in use and cannot be released, it is kept until the next restart.</p>"
              "<h2>Virtual machines and containers</h2><p>Each has its own swap setting: open the <a href='/launcher'>Launcher</a>, right-click the tile, "
              "choose OS settings. A container's is applied by Proxmox at once; a virtual machine's is saved for the guest to apply when the OS is set up "
              "(that step is not built yet).</p></body></html>").encode()
