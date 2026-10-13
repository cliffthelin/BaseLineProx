"""Switch this machine's own screen between the browser and the Baseline text console, from a page in the browser.

The browser window (Proxmox's GUI and Baseline's web pages) runs on virtual terminal 3 and the Baseline text console on virtual terminal 1.
Ctrl+Alt+F1 / Ctrl+Alt+F3 do the same thing, but nobody should have to know that: `/console` is a page with one button. It changes what
the physical screen shows, so it is honoured only for a request from this machine itself (loopback); from anywhere else it is refused.
In the Baseline console the `p` key comes back to the browser.
"""
from __future__ import annotations

import ipaddress
import subprocess

TEXT_CONSOLE_VT = 1
BROWSER_VT = 3


def is_local(address: str) -> bool:
    """True only for the machine's own loopback addresses (an IPv4-mapped IPv6 loopback included)."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def page() -> bytes:
    return b"""<!doctype html><html><head><meta charset="utf-8"><title>Baseline console</title><style>
:root{color-scheme:dark}html,body{background:#0d0e13}
body{font-family:system-ui,sans-serif;max-width:640px;margin:4rem auto;padding:0 1rem;color:#e7e9f0}
h1{font-size:1.4rem}p{color:#9aa0ba;line-height:1.5}
button{font:inherit;font-size:1.1rem;padding:.9rem 1.4rem;border:0;border-radius:.5rem;background:#3b6cf6;color:#fff;cursor:pointer}
button:hover{background:#557ff8}button:focus-visible{outline:3px solid #9db6ff;outline-offset:2px}kbd{background:#1d2030;padding:.1rem .4rem;border-radius:.25rem}
</style></head><body><h1>Baseline text console</h1>
<p>The Baseline console (hardware, network, tether, VMs) is on this machine's own screen, behind this browser.</p>
<form method="post" action="/console/switch"><button type="submit" autofocus>Show the Baseline console</button></form>
<p>To come back to this browser, press <kbd>p</kbd> in the console. The keyboard does the same without this page:
<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>F1</kbd> for the console, <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>F3</kbd> for the browser.</p>
</body></html>"""


def refused_page() -> bytes:
    return (b"<!doctype html><html><body><h1>Baseline console</h1><p>The console is on the machine's own screen; "
            b"it can only be switched from that machine.</p></body></html>")


def switch(vt: int = TEXT_CONSOLE_VT, *, run=subprocess.run) -> bool:
    if vt not in (TEXT_CONSOLE_VT, BROWSER_VT):
        raise ValueError("only the text console and the browser can be shown")
    return run(["chvt", str(vt)], capture_output=True, timeout=10).returncode == 0
