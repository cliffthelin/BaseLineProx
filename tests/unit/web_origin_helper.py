"""Test helper: a real, signed web origin from a test gate (never a bypass: production code still verifies it)."""
import web_gate
from settings_web import SessionStore

NOW = 1_800_000_000.0


def configured_gate(clock=lambda: NOW, audit=None):
    gate = web_gate.WebGate(b"t" * 32, clock=clock, audit=audit)
    web_gate.configure(gate)
    return gate


def origin_for(op, params, gate=None, sessions=None, now=NOW):
    gate = gate or configured_gate()
    sessions = sessions or SessionStore()
    token = sessions.create("root", now).token
    return gate.origin_for_session(sessions, token, op, params, now)
