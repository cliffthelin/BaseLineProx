"""Minimal Agent Client Protocol (ACP) message building/parsing - the
shared client any future ACP-compliant adapter can reuse, not only
OpenCode's. ACP is a real, open, JSON-RPC 2.0 standard
(https://agentclientprotocol.com, originally published by Zed
Industries, now implemented by 25+ agents including OpenCode's own
`opencode acp` server) - Baseline speaks it rather than inventing a
bespoke wire format, per the explicit request (decision record 44) to
normalize harness IO against best standards instead of a
Baseline-only schema.

Verification status: every shape in this module's own tests is a
REAL line captured from a live `opencode acp` process spawned directly
during this work - `initialize`, `session/new`, `session/prompt`, and
an `agent_message_chunk` `session/update` notification all completed a
full, real round trip. This caught one real discrepancy between the
protocol's own documentation and its actual wire bytes: the live
`session/update` notification's discriminator key is `"sessionUpdate"`
inside `update`, not `"type"` as the docs page implied - this module
follows the real bytes, not the docs, wherever they disagreed.
"""
from __future__ import annotations

import json

import harness_events


def build_initialize_request(request_id, *, protocol_version: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_version,
            "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False},
                "terminal": False,
            },
        },
    }


def build_session_new_request(request_id, *, cwd: str, mcp_servers: list = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "session/new",
        "params": {"cwd": cwd, "mcpServers": mcp_servers or []},
    }


def build_session_prompt_request(request_id, *, session_id: str, text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "session/prompt",
        "params": {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
    }


def encode_message(message: dict) -> str:
    """One JSON-RPC message as a newline-delimited line - confirmed
    live: the real opencode acp process accepts exactly this framing."""
    return json.dumps(message) + "\n"


def parse_message(line: str):
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except ValueError:
        return None


def is_response_for(message, request_id) -> bool:
    if not message or message.get("id") != request_id:
        return False
    return "result" in message or "error" in message


def extract_session_id(session_new_response):
    if not session_new_response:
        return None
    result = session_new_response.get("result") or {}
    return result.get("sessionId")


def extract_stop_reason(prompt_response, request_id):
    if not is_response_for(prompt_response, request_id):
        return None
    result = prompt_response.get("result") or {}
    return result.get("stopReason")


def extract_message_chunk(notification):
    """The normalized chunk from a real `session/update` notification's
    `agent_message_chunk` variant - None for every other SessionUpdate
    variant (usage_update, available_commands_update, tool_call, ...)
    or a non-notification message. Baseline's trimmed schema
    (harness_events.py) only ever needs this one variant, since every
    harness runs with zero tools by design."""
    if not notification or notification.get("method") != "session/update":
        return None
    update = (notification.get("params") or {}).get("update") or {}
    if update.get("sessionUpdate") != "agent_message_chunk":
        return None
    content = update.get("content") or {}
    text = content.get("text")
    return harness_events.AgentMessageChunk(text=text) if text else None
