"""Caddyfile rendering for the single-gateway overlay (hardened-appliance-prd.md,
R3.1 / R3.2).

Pure: takes validated route data and returns Caddyfile text. It never runs
caddy, never writes /etc, and never opens a socket. Every value that lands in
the file is checked against a strict pattern first, because a newline or brace
in a path or upstream would inject arbitrary Caddyfile directives.
"""
from __future__ import annotations

import re

_SITE_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*$")
_HOSTPORT_RE = re.compile(r"^([A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?):([0-9]{1,5})$")
_STRIPPED_HEADERS = ("Server", "X-Powered-By")
# Authelia's current forward-auth endpoint and the identity headers it sets
# (hardened-appliance-prd.md, R-4). Needs Caddy >= 2.5.1.
_FORWARD_AUTH_URI = "/api/authz/forward-auth"
_FORWARD_AUTH_HEADERS = ("Remote-User", "Remote-Groups", "Remote-Email", "Remote-Name")


def _check_site(site: str) -> str:
    if not isinstance(site, str) or not _SITE_RE.match(site):
        raise ValueError(f"invalid site address: {site!r}")
    return site


def _check_hostport(value: str, what: str) -> str:
    m = _HOSTPORT_RE.match(value) if isinstance(value, str) else None
    if not m or not 1 <= int(m.group(3)) <= 65535:
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def _check_path(path: str) -> str:
    if not isinstance(path, str) or not _PATH_RE.match(path):
        raise ValueError(f"invalid route path: {path!r}")
    return path


def _validated_routes(routes) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out = []
    for route in routes:
        path = _check_path(route.get("path"))
        upstream = _check_hostport(route.get("upstream"), "upstream")
        if path in seen:
            raise ValueError(f"duplicate route path: {path}")
        seen.add(path)
        out.append((path, upstream))
    return sorted(out)


def render_caddyfile(site: str, routes, forward_auth: str | None = None) -> str:
    """Render one site block. Routes are sorted, so output is independent of
    input order. Anything not matching a route gets a 404, never a backend."""
    site = _check_site(site)
    ordered = _validated_routes(routes)
    lines = [f"{site} {{", "\ttls internal", "\theader {"]
    lines += [f"\t\t-{name}" for name in _STRIPPED_HEADERS]
    lines.append("\t}")
    if forward_auth is not None:
        lines.append(f"\tforward_auth {_check_hostport(forward_auth, 'forward_auth')} {{")
        lines.append(f"\t\turi {_FORWARD_AUTH_URI}")
        lines.append("\t\tcopy_headers " + " ".join(_FORWARD_AUTH_HEADERS))
        lines.append("\t}")
    for path, upstream in ordered:
        lines += [f"\thandle_path {path}/* {{", f"\t\treverse_proxy {upstream}", "\t}"]
    lines += ["\thandle {", "\t\trespond 404", "\t}", "}"]
    return "\n".join(lines) + "\n"
