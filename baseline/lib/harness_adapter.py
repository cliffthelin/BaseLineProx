"""The HarnessAdapter contract - the interface every AI orchestration
CLI adapter (Claude Code, and whatever else eventually gets a real
one - OpenCode/Hermes/Pi/DeepSeek/GrokBot are listed in
providers.HARNESSES but none of them has one yet) must satisfy.

This project's own established convention (repair.py's `Runner`,
harness.py's own `Runner`) is a plain duck-typed contract with
`NotImplementedError` stubs, never `abc.ABC` - no module in this
codebase uses the `abc` module, and a harness adapter is a *module*
with free functions (matching hardware.py/network.py's own shape),
not a class instance, so there's no single object to subclass anyway.
This file is the contract stated as documentation plus one runtime
checker (`conforms`), not an enforced base class.

A conforming module exposes:

- `new_session() -> object` - a fresh, adapter-specific session value.
  Opaque to every caller outside the adapter itself: never inspected,
  only ever passed back into `ask`/`ask_streaming`/`describe_session`.
- `ask(prompt: str, *, session=None, runner=None) -> str`
- `ask_streaming(prompt: str, on_text, *, session=None, runner=None) -> str`
- `describe_session(session) -> str` - a short, human-readable status
  line (memory/access-scope state) shown in the Chat tab's status bar.

Anything beyond that - `harness.py`'s `grant_write_scope`/
`revoke_write_scope`/`is_path_within_grant` included - is an optional,
adapter-specific capability, not part of this contract. Different
harnesses' own CLIs have different (or no) permission-scoping
mechanisms; forcing every adapter to implement Claude Code's specific
`Edit(...)`+`acceptEdits` shape would be guessing at interfaces this
project has no evidence for yet. `harness_registry.supports_write_grant`
checks for these via `hasattr`, never assumes them.
"""
from __future__ import annotations

REQUIRED_ATTRS = ("new_session", "ask", "ask_streaming", "describe_session")


def conforms(adapter_module) -> bool:
    """Whether `adapter_module` exposes every required attribute as a
    callable. Used defensively by harness_registry - a module named in
    providers.HARNESSES that doesn't actually conform is treated as
    unavailable, never as a crash."""
    if adapter_module is None:
        return False
    return all(callable(getattr(adapter_module, attr, None)) for attr in REQUIRED_ATTRS)
