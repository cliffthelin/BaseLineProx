# Decision record: OpenCode as the second HarnessAdapter, normalized through real ACP - not a bespoke wire format

> **Note, 2026-09-30 (docs-vs-code audit, v0.2 row 30):** There is no `opencode.py`; the adapter is `opencode_adapter.py`, with the protocol in `acp_protocol.py` and `acp_transport.py`. The record below is left as written.

Status: **implemented, unit-tested (39 new tests across 4 new modules,
740/740 suite passing), a full real round trip confirmed live against
the actual `opencode acp` binary** (initialize, session creation, a
real prompt, real streaming notifications, and turn completion all
observed with real bytes) - the deepest live verification of any
harness-layer work this session. `bin/baseline`'s UI itself is not
verified live (no real hardware access this session, same standing
blocker as every other UI item).

## The actual request, and why it changed the design

Asked to add OpenCode as the second harness, the request added a real
constraint: adapters should be "channeled through a common [layer]
whose aim is to normalize harness IO," built "based on best standards"
rather than invented, only inventing one "if needed." That ruled out
the simplest path (an `opencode.py` with its own `ask`/`ask_streaming`
parsing OpenCode's bespoke `--format json` mode, independent of how
Claude's adapter parses its own NDJSON) and required two things
instead: (1) a real internal normalization layer both adapters
translate into, and (2) checking whether an actual standard already
exists before inventing Baseline's own.

## The standard exists, and OpenCode already speaks it

**Agent Client Protocol (ACP)** - an open, JSON-RPC 2.0-based standard
originally published by Zed Industries, now implemented by 25+ agents
(with JetBrains as a co-developing partner) - is real, adopted, and
directly relevant: `opencode --help` lists `opencode acp` ("start ACP
(Agent Client Protocol) server") as a first-class subcommand. This is
the "best standard" the request asked to check for - LLM-Rosetta
(arXiv:2604.09360), an academic normalization IR, was considered too
but ACP is the more concretely real, adopted choice: a production
protocol already implemented by the exact tool being adapted, not a
paper's proposed taxonomy.

**Checked directly, Claude Code's installed CLI (2.1.226) does not
support ACP** - no `acp` subcommand, no ACP-related flags in `--help`.
So Baseline cannot make ACP the universal transport for every harness
today. The resolution: Baseline's own internal event schema
(`harness_events.py`) is named after ACP's real vocabulary and is what
every adapter - regardless of its own wire protocol - normalizes into.
Where a harness genuinely speaks ACP (OpenCode), the adapter is a thin
translation of an already-standard protocol. Where it doesn't (Claude
Code), the adapter still normalizes into the exact same two internal
event types, via its own NDJSON parser (stream_json.py, already built
in decision record 41, now feeding the shared schema instead of its
own bespoke callback shape).

## What was built

- **`baseline/lib/harness_events.py`** - `AgentMessageChunk(text)` /
  `TurnEnd(text, is_error=False)`, named after ACP's real
  `SessionUpdate` vocabulary (https://agentclientprotocol.com/protocol/v1/schema),
  deliberately trimmed to the two variants Baseline's harness layer
  actually surfaces (no tool_call/plan/thought_chunk variants - every
  harness runs with zero tools by design).
- **`harness_adapter.py`'s contract updated**: `ask_streaming`'s
  `on_event` callback now receives these normalized objects, never a
  bare string and never an adapter-specific shape - this is the actual
  normalization boundary the request asked for.
- **`stream_json.py` gained `to_normalized(event)`** - Claude's NDJSON
  events mapped into the same two types.
- **`harness.py`'s `ask_streaming` and `bin/baseline`'s `ask_harness`
  updated** to the `on_event` contract (a real, tested, breaking
  change to decision record 41's own shape - corrected in place with
  updated tests, the same "fix the test because the assumption
  changed" pattern decision record 40 already used once this session).
- **`baseline/lib/acp_protocol.py`** - pure ACP message building/
  parsing: `build_initialize_request`/`build_session_new_request`/
  `build_session_prompt_request`, `parse_message`, `is_response_for`,
  `extract_session_id`, `extract_stop_reason`, `extract_message_chunk`.
  Every test fixture is a **real captured line** from the live round
  trip below - not a guessed shape.
- **`baseline/lib/acp_transport.py`** - `AcpConnection`, the real
  bidirectional subprocess transport (`subprocess.Popen`, newline-
  delimited JSON-RPC over stdin/stdout) - confirmed live, not unit-
  tested directly (a thin real-IO wrapper, same as `RealRunner`
  elsewhere in this codebase - exercised through the adapter's
  injected fakes instead).
- **`baseline/lib/opencode_adapter.py`** - `OpencodeSession`,
  `new_session`, `describe_session`, `ask_streaming`, `ask`. Reuses a
  warm connection + session id across turns (the same "always
  available, not always running" shape as `HarnessSession`, decision
  record 31, for a different transport). `ask()` is a thin wrapper
  around `ask_streaming()` with a no-op callback - ACP's completion
  response carries no text (unlike Claude's `result` event), so even
  the non-streaming path must read the event stream to accumulate the
  final answer.
- **`providers.py`**: `opencode`'s entry set to `implemented: True,
  adapter_module: "opencode_adapter"`.

## The real, live round trip - and what it caught

Four real JSON-RPC calls were made directly against a live `opencode
acp` process spawned in this session (not simulated, not guessed):

1. `initialize` -> a real response with `agentCapabilities`,
   `authMethods`, `agentInfo` (`OpenCode 1.18.11`).
2. `session/new` -> a real `sessionId` and `configOptions` (available
   models).
3. `session/prompt` ("Say exactly: hello world") -> real streaming
   `session/update` notifications, including one genuinely
   unanticipated variant (`available_commands_update`, safely ignored
   by `extract_message_chunk`) and the real `agent_message_chunk`
   notification.
4. The real completion response: `{"stopReason":"end_turn", ...}`.

**This caught a real discrepancy between ACP's own documentation and
its actual wire bytes**: the live `session/update` notification's
discriminator key is `"sessionUpdate"` inside `update`, not `"type"`
as the protocol's own docs page (fetched during this work) implied.
`acp_protocol.py` follows the real bytes. This is the second time this
session that live verification against a real binary caught something
docs alone would have gotten wrong (the first: decision record 40's
`Write(...)` vs. `Edit(...)`).

## What this deliberately does not do

- **No write-grant capability for OpenCode.** ACP defines a real
  `session/request_permission` flow, but whether it can express
  decision record 32's specific session-only/scope-asked/path-bounded
  shape has not been checked. `opencode_adapter.py` simply has no
  `grant_write_scope`/`revoke_write_scope` - `harness_registry
  .supports_write_grant` already handles this via `hasattr`, never an
  assumption, so the Console tab's `grant write` command correctly
  reports "not supported by this harness" rather than crashing or
  faking one.
- **No streaming-optimization beyond what ACP already gives for
  free.** Unlike Claude (which needed `--include-partial-messages`,
  untested, for real token deltas), OpenCode's `agent_message_chunk`
  notifications may already arrive incrementally in real use - not
  independently re-tested for genuine token-level granularity in this
  pass, only confirmed to arrive as at least one usable chunk.
- **No live `bin/baseline` UI verification.** The registry dispatch
  and both adapters are real and tested; whether the Chat tab actually
  renders correctly when a real operator selects "OpenCode" from the
  dropdown has not been checked on a real boot - no real hardware
  access this session, unchanged from every other UI item in this
  pass.

## Verification performed before this commit

- RED confirmed first for every new module: `harness_events`,
  `stream_json.to_normalized`, `acp_protocol`, `opencode_adapter` all
  failed with the expected `ModuleNotFoundError`/`AttributeError`
  before their implementations existed.
- 39 new tests across `test_harness_events.py` (3),
  `test_stream_json.py`'s new `to_normalized` cases (5),
  `test_harness_streaming.py`'s corrected cases (6, updated not just
  added), `test_acp_protocol.py` (14), `test_opencode_adapter.py` (8),
  and `test_harness_registry.py`'s new generic-dispatch cases (3).
- One real test-fixture bug caught and fixed during this same pass:
  a reused hardcoded real response line (`"id":3`) didn't match the
  correctly-incrementing real request-id counter on a second call -
  fixed by deriving the second fixture's id explicitly, not by
  changing the implementation (the counter was correct).
- Full suite: 740/740 passing (707 before this change), no
  regressions.
- All seven new/changed Python files byte-compile clean.
- All scratch probe scripts (`/tmp/acp_probe*.py`) deleted after use;
  no ACP session artifacts retained.
