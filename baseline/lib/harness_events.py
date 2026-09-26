"""Baseline's internal normalized harness-IO event types - the common
layer every HarnessAdapter (harness_adapter.py) must translate its own
wire format into, so bin/baseline never needs to know Claude Code's
NDJSON shape or OpenCode's ACP shape specifically.

Named after the real Agent Client Protocol (ACP) v1 schema's
`SessionUpdate` vocabulary (https://agentclientprotocol.com/protocol/v1/schema,
an open standard originally published by Zed Industries, now
implemented by 25+ agents including OpenCode's own `opencode acp`
server - confirmed live against the real installed binary, see
docs/design/decision-records/44) - not invented from scratch, per the
explicit ask to normalize against best standards rather than a
bespoke Baseline-only schema.

Deliberately trimmed to the two variants Baseline's harness layer
actually surfaces to the UI today. The real ACP schema defines 11
SessionUpdate variants total (user_message_chunk, agent_message_chunk,
agent_thought_chunk, tool_call, tool_call_update, plan,
available_commands_update, current_mode_update, config_option_update,
session_info_update, usage_update) - Baseline only ever needs
`agent_message_chunk` (an incremental reply) and something conceptually
mapping to ACP's `session/prompt` response `stopReason` (a turn's
conclusion), because every harness runs with zero tools by design (no
tool_call variants to show) and this project has no reasoning-trace or
plan display anywhere. More of the real taxonomy can be added later
without breaking this contract, not invented speculatively now.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentMessageChunk:
    """One increment of the agent's own reply text - named after
    ACP's real `agent_message_chunk` SessionUpdate variant."""
    text: str


@dataclass
class TurnEnd:
    """One prompt turn's conclusion: the final answer text, and
    whether it ended in error. Conceptually maps to ACP's
    `session/prompt` response (a `stopReason`), trimmed to what
    Baseline's UI actually needs."""
    text: str
    is_error: bool = False
