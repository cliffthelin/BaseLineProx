"""Tests for gateway_config.py (hardened-appliance-prd.md, R3.1 / R3.2).
Pure: renders text only, never runs caddy or touches /etc."""
import pytest

import gateway_config as gc

ROUTES = [
    {"path": "/media", "upstream": "10.10.0.12:8188"},
    {"path": "/chat", "upstream": "10.10.0.11:8080"},
]


def test_renders_site_with_internal_tls_and_routes():
    out = gc.render_caddyfile("baseline.local", ROUTES)
    assert out.startswith("baseline.local {")
    assert "tls internal" in out
    assert "handle_path /chat/* {\n\t\treverse_proxy 10.10.0.11:8080" in out
    assert "handle_path /media/* {\n\t\treverse_proxy 10.10.0.12:8188" in out


def test_output_is_deterministic_and_independent_of_route_order():
    assert gc.render_caddyfile("baseline.local", ROUTES) == gc.render_caddyfile(
        "baseline.local", list(reversed(ROUTES))
    )


def test_strips_dangerous_response_headers():
    out = gc.render_caddyfile("baseline.local", ROUTES)
    assert "-Server" in out
    assert "-X-Powered-By" in out


def test_unmatched_paths_get_404_not_a_backend():
    out = gc.render_caddyfile("baseline.local", ROUTES)
    assert "handle {\n\t\trespond 404" in out


def test_forward_auth_is_emitted_before_routes_when_configured():
    out = gc.render_caddyfile("baseline.local", ROUTES, forward_auth="127.0.0.1:9091")
    assert out.index("forward_auth 127.0.0.1:9091") < out.index("handle_path")


def test_no_forward_auth_block_by_default():
    assert "forward_auth" not in gc.render_caddyfile("baseline.local", ROUTES)


@pytest.mark.parametrize(
    "path",
    ["chat", "/chat/", "/a b", "/a{b", "/a\nb", "/a}", "/", "", "/a\tb", "/a*"],
)
def test_rejects_unsafe_or_malformed_paths(path):
    with pytest.raises(ValueError):
        gc.render_caddyfile("baseline.local", [{"path": path, "upstream": "10.0.0.1:80"}])


@pytest.mark.parametrize(
    "upstream",
    ["10.0.0.1", "10.0.0.1:0", "10.0.0.1:99999", "host name:80", "a:80\nrespond 200", "http://a:80", ""],
)
def test_rejects_unsafe_or_malformed_upstreams(upstream):
    with pytest.raises(ValueError):
        gc.render_caddyfile("baseline.local", [{"path": "/x", "upstream": upstream}])


@pytest.mark.parametrize("site", ["", "a b", "a{", "a\nb", "https://x", "x/y"])
def test_rejects_unsafe_site_address(site):
    with pytest.raises(ValueError):
        gc.render_caddyfile(site, ROUTES)


def test_rejects_duplicate_paths():
    dup = ROUTES + [{"path": "/chat", "upstream": "10.10.0.13:1"}]
    with pytest.raises(ValueError):
        gc.render_caddyfile("baseline.local", dup)


def test_rejects_unsafe_forward_auth():
    with pytest.raises(ValueError):
        gc.render_caddyfile("baseline.local", ROUTES, forward_auth="x\nrespond 200")


def test_empty_routes_render_a_closed_gateway():
    out = gc.render_caddyfile("baseline.local", [])
    assert "respond 404" in out
    assert "reverse_proxy" not in out


def test_forward_auth_uses_current_authelia_endpoint_and_copies_identity_headers():
    out = gc.render_caddyfile("baseline.local", ROUTES, forward_auth="127.0.0.1:9091")
    assert "uri /api/authz/forward-auth" in out
    assert "/api/verify" not in out
    assert "copy_headers Remote-User Remote-Groups Remote-Email Remote-Name" in out
