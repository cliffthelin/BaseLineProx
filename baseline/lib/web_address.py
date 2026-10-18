"""The address the Baseline web console is served at: an IP on this host and a port, kept as a setting.

The console runs on the substrate (the Proxmox host) as a systemd service ordered after Proxmox's own services; its address is read from `/etc/baseline/web.env` when the service starts. This module
validates and writes that file (only when it changes) and lists the host's own addresses to choose from, so the console can be put on one given IP, or on every address (0.0.0.0).
"""
from __future__ import annotations

import ipaddress
import re
from pathlib import Path

ENV_FILE = "/etc/baseline/web.env"
DEFAULT = {"bind_host": "0.0.0.0", "port": 8100}


class AddressError(ValueError):
    pass


def validate(bind_host, port, *, local_addresses=None) -> dict:
    try:
        ip = ipaddress.IPv4Address(str(bind_host))
    except ValueError:
        raise AddressError("the address must be an IPv4 address of this host, or 0.0.0.0 for all of them") from None
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise AddressError("the port is a number from 1024 to 65535")
    if str(ip) != "0.0.0.0" and local_addresses is not None and str(ip) not in set(local_addresses):
        raise AddressError(f"{ip} is not an address of this host")
    return {"bind_host": str(ip), "port": port}


def render_env(settings: dict) -> str:
    return f"BASELINE_WEB_BIND_HOST={settings['bind_host']}\nBASELINE_WEB_PORT={settings['port']}\n"


def read(path=ENV_FILE) -> dict:
    found = dict(DEFAULT)
    try:
        for line in Path(path).read_text().splitlines():
            m = re.fullmatch(r"(BASELINE_WEB_BIND_HOST|BASELINE_WEB_PORT)=(\S+)", line.strip())
            if m and m.group(1) == "BASELINE_WEB_BIND_HOST":
                found["bind_host"] = m.group(2)
            elif m:
                found["port"] = int(m.group(2))
    except (OSError, ValueError):
        return dict(DEFAULT)
    return found


def save(bind_host, port, *, path=ENV_FILE, local_addresses=None) -> dict:
    from write_once import write_if_changed
    settings = validate(bind_host, port, local_addresses=local_addresses)
    write_if_changed(path, render_env(settings))
    return settings


def local_addresses(runner) -> list:
    """This host's IPv4 addresses (a read), for the choices on the page."""
    done = runner.run(["ip", "-4", "-o", "addr", "show"], timeout=15)
    if done.returncode:
        return []
    return sorted({m.group(1) for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)/", done.stdout or "")})
