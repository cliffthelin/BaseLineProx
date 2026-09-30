"""Gateway routes stored in the registry (hardened-appliance-prd.md, R3.2).

Routes are GLOBAL-scope entries of the `gateway_route` type, so the gateway
config survives a broken persona volume. Values are validated with
gateway_config's own checks when written, so a bad route never reaches the
registry. `manifest_entries` is what measured_boot hashes for this layer.
"""
from __future__ import annotations

import gateway_config
import registry

TYPE_ID = "gateway_route"
_SCOPE = registry.GLOBAL


def _ensure_type() -> None:
    registry.register_type(TYPE_ID, "Reverse-proxy route: URL path to upstream host:port", default_scope=_SCOPE)


def set_route(route_id: str, path: str, upstream: str) -> None:
    gateway_config._check_path(path)
    gateway_config._check_hostport(upstream, "upstream")
    _ensure_type()
    registry.upsert_entry(TYPE_ID, route_id, attributes={"path": path, "upstream": upstream}, scope=_SCOPE)


def remove_route(route_id: str) -> None:
    registry.delete_entry(TYPE_ID, route_id, scope=_SCOPE)


def manifest_entries() -> dict:
    _ensure_type()
    return {rid: e["attributes"] for rid, e in sorted(registry.list_entries(TYPE_ID, scope=_SCOPE).items())}


def list_routes() -> list[dict]:
    return [dict(a) for a in manifest_entries().values()]


def render(site: str, forward_auth: str | None = None) -> str:
    return gateway_config.render_caddyfile(site, list_routes(), forward_auth)
