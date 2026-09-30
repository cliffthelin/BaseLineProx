"""Tests for gateway_routes.py (hardened-appliance-prd.md, R3.2): gateway
routes live in the registry, not in a hand-edited Caddyfile. conftest's
autouse fixtures redirect both registry databases to temp files."""
import pytest

import gateway_routes as gr
import measured_boot as mb


def test_registered_routes_render_into_the_caddyfile():
    gr.set_route("chat", "/chat", "10.10.0.11:8080")
    gr.set_route("media", "/media", "10.10.0.12:8188")
    out = gr.render("baseline.local")
    assert "reverse_proxy 10.10.0.11:8080" in out and "reverse_proxy 10.10.0.12:8188" in out


def test_invalid_route_is_rejected_at_write_time_and_not_stored():
    with pytest.raises(ValueError):
        gr.set_route("bad", "/x\nrespond 200", "10.0.0.1:80")
    assert gr.list_routes() == []


def test_set_route_again_updates_in_place():
    gr.set_route("chat", "/chat", "10.10.0.11:8080")
    gr.set_route("chat", "/chat", "10.10.0.99:9000")
    assert gr.list_routes() == [{"path": "/chat", "upstream": "10.10.0.99:9000"}]


def test_remove_route_drops_it():
    gr.set_route("chat", "/chat", "10.10.0.11:8080")
    gr.remove_route("chat")
    assert gr.list_routes() == []


def test_two_ids_with_the_same_path_is_rejected_at_render():
    gr.set_route("a", "/chat", "10.0.0.1:80")
    gr.set_route("b", "/chat", "10.0.0.2:80")
    with pytest.raises(ValueError):
        gr.render("baseline.local")


def test_manifest_entries_feed_a_stable_layer_digest():
    gr.set_route("chat", "/chat", "10.10.0.11:8080")
    d1 = mb.layer_digest("gateway_layer", gr.manifest_entries())
    d2 = mb.layer_digest("gateway_layer", gr.manifest_entries())
    assert d1 == d2
    gr.set_route("chat", "/chat", "10.10.0.11:8081")
    assert mb.layer_digest("gateway_layer", gr.manifest_entries()) != d1
